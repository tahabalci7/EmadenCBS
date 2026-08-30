import argparse
import csv
import hashlib
import json
import math
import os
import statistics
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from src.batch.ced_batch_processor import CEDBatchProcessor
from src.batch.corpus_benchmark import (
    _append_jsonl,
    _distribution,
    _has_identity,
    _identity,
    _load_jsonl,
    _load_results_file,
    _run_lock,
    _selected_latest_results,
    _write_summary_atomic,
    discover_pdfs,
    load_input_manifest,
)
from src.batch.heavy_refinement_queue import (
    HeavyRefinementQueue,
)
from src.batch.refinement_pipeline import (
    RefinementPipeline,
)
from src.batch.corpus_preflight import CLASSIFICATIONS


DEFAULT_SAMPLE_SIZE = 100
DEFAULT_SEED = "primary-production-v1"

QUICK_USABLE = "QUICK_USABLE"
HEAVY_INLINE_USABLE = "HEAVY_INLINE_USABLE"
NO_USABLE_RESULT = "NO_USABLE_RESULT"
AMBIGUOUS = "AMBIGUOUS"

SPEED_CLASSES = (
    QUICK_USABLE,
    HEAVY_INLINE_USABLE,
    NO_USABLE_RESULT,
    AMBIGUOUS,
)

RESULT_FIELDS = (
    "relative_path",
    "province",
    "project_type",
    "preflight_class",
    "file_size",
    "modified_time",
    "modified_time_ns",
    "elapsed_seconds",
    "status",
    "result_completeness",
    "extraction_strategy",
    "coordinate_count",
    "table_count",
    "polygon_count",
    "transformed_coordinate_count",
    "ocr_page_count",
    "ocr_page_numbers",
    "general_fallback_used",
    "heavy_fallback_deferred",
    "has_useful_result",
    "primary_speed_class",
    "refinement_eligible",
    "refinement_enqueued",
    "refinement_job_id",
    "refinement_enqueue_reason",
    "refinement_queue_error",
    "strong_unique_projected_count",
    "crs_conflicted_record_count",
    "strong_comparable_polygon_count",
    "error",
    "benchmark_completed",
    "benchmarked_at",
)


def representative_allocation(
    preflight_results,
    sample_size=DEFAULT_SAMPLE_SIZE,
):
    preflight_results = _latest_preflight_results(
        preflight_results
    )
    populations = Counter(
        (
            item.get("classification", ""),
            item.get("project_type", ""),
        )
        for item in preflight_results
        if item.get("classification") in CLASSIFICATIONS
        and item.get("project_type") in {"EK-1", "EK-2"}
    )
    class_populations = {
        classification: sum(
            populations[(classification, project_type)]
            for project_type in ("EK-1", "EK-2")
        )
        for classification in CLASSIFICATIONS
    }
    class_quotas = _nearest_proportional_allocation(
        class_populations,
        sample_size,
        minimum_one=True,
    )

    allocation = {}
    for classification in CLASSIFICATIONS:
        project_populations = {
            project_type: populations[
                (classification, project_type)
            ]
            for project_type in ("EK-1", "EK-2")
        }
        project_quotas = _largest_remainder_allocation(
            project_populations,
            class_quotas.get(classification, 0),
            minimum_one=True,
        )
        for project_type, count in project_quotas.items():
            allocation[(classification, project_type)] = count

    if sum(allocation.values()) != sample_size:
        raise RuntimeError("Representative allocation toplamı geçersiz.")
    return allocation


def select_representative_sample(
    records,
    preflight_results,
    sample_size=DEFAULT_SAMPLE_SIZE,
    seed=DEFAULT_SEED,
):
    preflight_results = _latest_preflight_results(
        preflight_results
    )
    preflight_by_identity = {
        _identity(item): item
        for item in preflight_results
        if _has_identity(item)
    }
    annotated = []
    for record in records:
        preflight = preflight_by_identity.get(_identity(record))
        if preflight is None:
            continue
        classification = preflight.get("classification", "")
        if classification not in CLASSIFICATIONS:
            continue
        item = dict(record)
        item["preflight_class"] = classification
        annotated.append(item)

    allocation = representative_allocation(
        preflight_results,
        sample_size=sample_size,
    )
    grouped = defaultdict(list)
    for record in annotated:
        grouped[
            (
                record["preflight_class"],
                record["project_type"],
            )
        ].append(record)

    selected = []
    for cell in sorted(allocation):
        quota = allocation[cell]
        candidates = sorted(
            grouped[cell],
            key=lambda item: _seeded_sample_key(
                item["relative_path"],
                seed,
            ),
        )
        if quota > len(candidates):
            raise RuntimeError(
                f"Representative cell yetersiz: {cell}"
            )
        selected.extend(candidates[:quota])

    selected.sort(key=lambda item: item["relative_path"].casefold())
    if len(selected) != sample_size:
        raise RuntimeError("Representative sample boyutu geçersiz.")
    if len({item["relative_path"] for item in selected}) != sample_size:
        raise RuntimeError("Representative sample duplicate içeriyor.")
    return selected, allocation


def write_exact_manifest(path, records):
    path = Path(path)
    paths = [item["relative_path"] for item in records]
    if len(paths) != len(set(paths)):
        raise ValueError("Manifest duplicate path içeriyor.")
    manifest_text = "\n".join(paths)
    digest = hashlib.sha256(
        manifest_text.encode("utf-8")
    ).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        with temp_path.open(
            "w",
            encoding="utf-8",
            newline="\n",
        ) as file:
            file.write(manifest_text)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)
    return digest


def prepare_representative_manifest(
    root,
    output,
    preflight_results_path,
    manifest_path,
    sample_size=DEFAULT_SAMPLE_SIZE,
    seed=DEFAULT_SEED,
):
    records = discover_pdfs(root, output)
    preflight_results = _load_results_file(
        Path(preflight_results_path)
    )
    preflight_results = _latest_preflight_results(
        preflight_results
    )
    selected, allocation = select_representative_sample(
        records,
        preflight_results,
        sample_size=sample_size,
        seed=seed,
    )
    digest = write_exact_manifest(manifest_path, selected)
    return {
        "corpus_count": len(records),
        "preflight_count": len(preflight_results),
        "sample_count": len(selected),
        "manifest_sha256": digest,
        "allocation": _serialize_allocation(allocation),
        "project_type_distribution": dict(
            sorted(Counter(
                item["project_type"] for item in selected
            ).items())
        ),
    }


def classify_primary_result(result):
    try:
        polygon_count = int(result.get("polygon_count", 0) or 0)
    except (TypeError, ValueError):
        return AMBIGUOUS
    if result.get("status") == "HATA" or polygon_count <= 0:
        return NO_USABLE_RESULT
    general_fallback = result.get("general_fallback_used")
    if general_fallback is True:
        return HEAVY_INLINE_USABLE
    if general_fallback is False:
        return QUICK_USABLE
    return AMBIGUOUS


def run_primary_benchmark(
    root,
    output,
    preflight_results_path,
    input_manifest_path,
    run_id,
    resume=False,
    processor_factory=CEDBatchProcessor,
):
    root = Path(root).resolve()
    output = Path(output).resolve()
    manifest_records, manifest_metadata = load_input_manifest(
        input_manifest_path,
        root,
    )
    preflight_results = _load_results_file(
        Path(preflight_results_path)
    )
    preflight_results = _latest_preflight_results(
        preflight_results
    )
    _annotate_preflight(manifest_records, preflight_results)

    run_dir = output / "runs" / str(run_id)
    if run_dir.exists() and not resume:
        raise RuntimeError(f"Benchmark run zaten mevcut: {run_id}")
    run_dir.mkdir(parents=True, exist_ok=True)

    with _run_lock(run_dir):
        run_metadata = _prepare_run_metadata(
            run_dir,
            run_id,
            manifest_metadata,
            resume,
        )
        return _run_primary_locked(
            root=root,
            run_dir=run_dir,
            records=manifest_records,
            preflight_results=preflight_results,
            run_metadata=run_metadata,
            processor_factory=processor_factory,
        )


def _run_primary_locked(
    root,
    run_dir,
    records,
    preflight_results,
    run_metadata,
    processor_factory,
):
    jsonl_path = run_dir / "benchmark_results.jsonl"
    csv_path = run_dir / "benchmark_results.csv"
    summary_path = run_dir / "benchmark_summary.json"
    queue_path = run_dir / "heavy_refinement_queue.json"
    queue = HeavyRefinementQueue(queue_path, pdf_root=root)
    pipeline = RefinementPipeline(
        queue,
        processor_factory=processor_factory,
    )

    prior_results = _load_jsonl(jsonl_path)
    latest_results = {
        _identity(item): item
        for item in prior_results
        if _has_identity(item)
    }
    selected_identities = {_identity(item) for item in records}
    run_started = time.perf_counter()
    new_processed = 0

    try:
        for index, record in enumerate(records, start=1):
            previous = latest_results.get(_identity(record))
            if previous and previous.get("benchmark_completed"):
                print(
                    f"[{index}/{len(records)}] RESUME SKIP | "
                    f"{record['relative_path']}"
                )
                continue

            print(
                f"[{index}/{len(records)}] PRIMARY | "
                f"{record['relative_path']}"
            )
            result = benchmark_primary_pdf(
                record,
                pipeline,
            )
            _append_jsonl(jsonl_path, result)
            latest_results[_identity(record)] = result
            new_processed += 1
            current = _selected_latest_results(
                latest_results,
                selected_identities,
            )
            _write_csv_atomic(csv_path, current)
            _write_summary_atomic(
                summary_path,
                build_primary_summary(
                    current,
                    preflight_results,
                    total_selected=len(records),
                    run_wall_seconds=(
                        time.perf_counter() - run_started
                    ),
                    new_processed=new_processed,
                    run_metadata=run_metadata,
                    queue=queue,
                ),
            )
    except KeyboardInterrupt:
        print("Primary benchmark durduruldu; sonuçlar korundu.")

    current = _selected_latest_results(
        latest_results,
        selected_identities,
    )
    summary = build_primary_summary(
        current,
        preflight_results,
        total_selected=len(records),
        run_wall_seconds=time.perf_counter() - run_started,
        new_processed=new_processed,
        run_metadata=run_metadata,
        queue=queue,
    )
    _write_csv_atomic(csv_path, current)
    _write_summary_atomic(summary_path, summary)
    return summary


def benchmark_primary_pdf(record, pipeline):
    started = time.perf_counter()
    try:
        processor_result = pipeline.process_pdf(
            record["path"],
            record["project_type"] or "BILINMIYOR",
        )
    except Exception as error:
        processor_result = {
            "status": "HATA",
            "error": str(error),
        }

    geometry = processor_result.get("geometry_snapshot")
    geometry = geometry if isinstance(geometry, dict) else {}
    refinement = processor_result.get("refinement")
    refinement = refinement if isinstance(refinement, dict) else {}
    ocr_page_numbers = list(
        processor_result.get("ocr_page_numbers", []) or []
    )
    ocr_page_count = len(ocr_page_numbers)
    if not ocr_page_numbers:
        ocr_page_count = int(
            processor_result.get("ocr_pages", 0) or 0
        )

    return {
        "relative_path": record["relative_path"],
        "province": record["province"],
        "project_type": record["project_type"],
        "preflight_class": record.get("preflight_class", ""),
        "file_size": record["file_size"],
        "modified_time": record["modified_time"],
        "modified_time_ns": record["modified_time_ns"],
        "elapsed_seconds": round(
            time.perf_counter() - started,
            6,
        ),
        "status": processor_result.get("status", "HATA"),
        "result_completeness": processor_result.get(
            "result_completeness",
            "",
        ),
        "extraction_strategy": processor_result.get(
            "extraction_strategy",
            "",
        ),
        "coordinate_count": int(
            processor_result.get("coordinate_count", 0) or 0
        ),
        "table_count": int(
            processor_result.get("table_count", 0) or 0
        ),
        "polygon_count": int(
            processor_result.get("polygon_count", 0) or 0
        ),
        "transformed_coordinate_count": int(
            processor_result.get(
                "transformed_coordinate_count",
                0,
            )
            or 0
        ),
        "ocr_page_count": ocr_page_count,
        "ocr_page_numbers": ocr_page_numbers,
        "general_fallback_used": processor_result.get(
            "general_fallback_used"
        ),
        "heavy_fallback_deferred": bool(
            processor_result.get("heavy_fallback_deferred", False)
        ),
        "has_useful_result": bool(
            processor_result.get("has_useful_result", False)
        ),
        "primary_speed_class": classify_primary_result(
            processor_result
        ),
        "refinement_eligible": bool(
            refinement.get("eligible", False)
        ),
        "refinement_enqueued": bool(
            refinement.get("enqueued", False)
        ),
        "refinement_job_id": refinement.get("job_id"),
        "refinement_enqueue_reason": refinement.get(
            "enqueue_reason"
        ),
        "refinement_queue_error": refinement.get("queue_error"),
        "strong_unique_projected_count": geometry.get(
            "strong_unique_projected_count"
        ),
        "crs_conflicted_record_count": geometry.get(
            "crs_conflicted_record_count"
        ),
        "strong_comparable_polygon_count": geometry.get(
            "strong_comparable_polygon_count"
        ),
        "error": processor_result.get("error", ""),
        "benchmark_completed": True,
        "benchmarked_at": datetime.now(
            timezone.utc
        ).isoformat(),
    }


def build_primary_summary(
    results,
    preflight_results,
    total_selected,
    run_wall_seconds=0,
    new_processed=0,
    run_metadata=None,
    queue=None,
):
    results = list(results)
    total = len(results)
    speed_counts = Counter(
        item.get("primary_speed_class", AMBIGUOUS)
        for item in results
    )
    completeness_counts = Counter(
        item.get("result_completeness", "")
        for item in results
    )
    status_counts = Counter(
        item.get("status", "") for item in results
    )
    elapsed = [
        float(item.get("elapsed_seconds", 0) or 0)
        for item in results
    ]
    ocr_counts = [
        int(item.get("ocr_page_count", 0) or 0)
        for item in results
    ]
    queue_jobs = queue.list_jobs() if queue is not None else []

    summary = {
        "total_selected": total_selected,
        "processed": total,
        "completed": total == total_selected,
        "new_processed": new_processed,
        "run_wall_seconds": round(run_wall_seconds, 6),
        "primary_speed_class": {
            name: _count_and_percent(speed_counts[name], total)
            for name in SPEED_CLASSES
        },
        "result_completeness": {
            name: _count_and_percent(
                completeness_counts[name],
                total,
            )
            for name in (
                "COMPLETE",
                "USEFUL_PARTIAL",
                "INSUFFICIENT",
            )
        },
        "status_hata": _count_and_percent(
            status_counts["HATA"],
            total,
        ),
        "queue": {
            "eligible": sum(
                bool(item.get("refinement_eligible"))
                for item in results
            ),
            "enqueued": sum(
                bool(item.get("refinement_enqueued"))
                for item in results
            ),
            "job_count": len(queue_jobs),
            "pending": sum(
                item.get("status") == "PENDING"
                for item in queue_jobs
            ),
            "in_progress": sum(
                item.get("status") == "IN_PROGRESS"
                for item in queue_jobs
            ),
            "completed": sum(
                item.get("status") == "COMPLETED"
                for item in queue_jobs
            ),
            "attempts_nonzero": sum(
                int(item.get("attempts", 0) or 0) != 0
                for item in queue_jobs
            ),
        },
        "elapsed_seconds": _distribution(elapsed),
        "ocr_page_count": _distribution(ocr_counts),
        "general_fallback_count": sum(
            item.get("general_fallback_used") is True
            for item in results
        ),
        "coordinate_yield": sum(
            int(item.get("coordinate_count", 0) or 0) > 0
            for item in results
        ),
        "polygon_yield": sum(
            int(item.get("polygon_count", 0) or 0) > 0
            for item in results
        ),
        "preflight_class_breakdown": _group_summary(
            results,
            "preflight_class",
        ),
        "project_type_breakdown": _group_summary(
            results,
            "project_type",
        ),
        "weighted_projection": weighted_projection(
            results,
            preflight_results,
        ),
    }
    if run_metadata:
        summary.update(run_metadata)
    return summary


def weighted_projection(results, preflight_results):
    preflight_results = _latest_preflight_results(
        preflight_results
    )
    population = Counter(
        (
            item.get("classification", ""),
            item.get("project_type", ""),
        )
        for item in preflight_results
        if item.get("classification") in CLASSIFICATIONS
        and item.get("project_type") in {"EK-1", "EK-2"}
    )
    samples = defaultdict(list)
    for item in results:
        samples[
            (
                item.get("preflight_class", ""),
                item.get("project_type", ""),
            )
        ].append(item)

    projected = Counter()
    covered_population = 0
    cells = {}
    for cell, population_count in sorted(population.items()):
        cell_results = samples.get(cell, [])
        sample_count = len(cell_results)
        cell_key = f"{cell[0]}|{cell[1]}"
        cell_data = {
            "corpus_population": population_count,
            "sample_count": sample_count,
        }
        if sample_count == 0:
            cell_data["projection_available"] = False
            cells[cell_key] = cell_data
            continue

        covered_population += population_count
        cell_data["projection_available"] = True
        for speed_class in (
            QUICK_USABLE,
            HEAVY_INLINE_USABLE,
            NO_USABLE_RESULT,
        ):
            observed = sum(
                item.get("primary_speed_class") == speed_class
                for item in cell_results
            )
            rate = observed / sample_count
            estimate = rate * population_count
            projected[speed_class] += estimate
            cell_data[f"{speed_class.lower()}_rate"] = round(
                rate,
                6,
            )
        cells[cell_key] = cell_data

    total_population = sum(population.values())
    return {
        "corpus_population": total_population,
        "covered_population": covered_population,
        "coverage_percent": round(
            100 * covered_population / total_population,
            2,
        )
        if total_population
        else 0,
        "partial_coverage": covered_population != total_population,
        "estimated_quick_usable": round(projected[QUICK_USABLE]),
        "estimated_heavy_inline_usable": round(
            projected[HEAVY_INLINE_USABLE]
        ),
        "estimated_no_usable_result": round(
            projected[NO_USABLE_RESULT]
        ),
        "cells": cells,
    }


def _group_summary(results, field):
    groups = {}
    values = sorted(
        {
            item.get(field, "")
            for item in results
            if item.get(field, "")
        }
    )
    for value in values:
        items = [
            item for item in results if item.get(field) == value
        ]
        speed = Counter(
            item.get("primary_speed_class", AMBIGUOUS)
            for item in items
        )
        completeness = Counter(
            item.get("result_completeness", "")
            for item in items
        )
        groups[value] = {
            "sample": len(items),
            "quick_usable": speed[QUICK_USABLE],
            "heavy_inline_usable": speed[HEAVY_INLINE_USABLE],
            "no_usable_result": speed[NO_USABLE_RESULT],
            "complete": completeness["COMPLETE"],
            "useful_partial": completeness["USEFUL_PARTIAL"],
            "median_elapsed_seconds": round(
                statistics.median(
                    float(item.get("elapsed_seconds", 0) or 0)
                    for item in items
                ),
                6,
            ),
        }
    return groups


def _nearest_proportional_allocation(
    populations,
    total,
    minimum_one=False,
):
    active = {
        key: value
        for key, value in populations.items()
        if value > 0
    }
    population_total = sum(active.values())
    if total < 0 or total > population_total:
        raise ValueError("Allocation total geçersiz.")
    quotas = {
        key: int(math.floor(
            (value * total / population_total) + 0.5
        ))
        for key, value in active.items()
    }
    if minimum_one and total >= len(active):
        quotas = {key: max(1, value) for key, value in quotas.items()}
    ideals = {
        key: value * total / population_total
        for key, value in active.items()
    }
    _rebalance_quotas(quotas, ideals, active, total, minimum_one)
    return {key: quotas.get(key, 0) for key in populations}


def _largest_remainder_allocation(
    populations,
    total,
    minimum_one=False,
):
    active = {
        key: value
        for key, value in populations.items()
        if value > 0
    }
    if not active:
        return {key: 0 for key in populations}
    minimums = {
        key: 1
        for key in active
    } if minimum_one and total >= len(active) else {
        key: 0 for key in active
    }
    remaining = total - sum(minimums.values())
    population_total = sum(active.values())
    ideals = {
        key: active[key] * remaining / population_total
        for key in active
    }
    quotas = {
        key: minimums[key] + int(math.floor(ideals[key]))
        for key in active
    }
    for key in sorted(
        active,
        key=lambda item: (
            -(ideals[item] - math.floor(ideals[item])),
            str(item),
        ),
    )[: total - sum(quotas.values())]:
        quotas[key] += 1
    return {key: quotas.get(key, 0) for key in populations}


def _rebalance_quotas(
    quotas,
    ideals,
    populations,
    total,
    minimum_one,
):
    minimum = 1 if minimum_one and total >= len(quotas) else 0
    while sum(quotas.values()) < total:
        candidates = [
            key for key in quotas if quotas[key] < populations[key]
        ]
        key = max(
            candidates,
            key=lambda item: (ideals[item] - quotas[item], str(item)),
        )
        quotas[key] += 1
    while sum(quotas.values()) > total:
        candidates = [
            key for key in quotas if quotas[key] > minimum
        ]
        key = max(
            candidates,
            key=lambda item: (quotas[item] - ideals[item], str(item)),
        )
        quotas[key] -= 1


def _seeded_sample_key(relative_path, seed):
    return hashlib.sha256(
        f"{seed}|{relative_path}".encode("utf-8")
    ).hexdigest()


def _serialize_allocation(allocation):
    return {
        f"{classification}|{project_type}": count
        for (classification, project_type), count
        in sorted(allocation.items())
    }


def _annotate_preflight(records, preflight_results):
    by_identity = {
        _identity(item): item
        for item in preflight_results
        if _has_identity(item)
    }
    for record in records:
        preflight = by_identity.get(_identity(record))
        if preflight is None:
            raise RuntimeError(
                "Manifest kaydı için preflight sonucu bulunamadı: "
                f"{record['relative_path']}"
            )
        record["preflight_class"] = preflight.get(
            "classification",
            "",
        )


def _latest_preflight_results(results):
    latest = {}
    anonymous = []
    for item in results:
        if _has_identity(item):
            latest[_identity(item)] = item
        else:
            anonymous.append(item)
    return list(latest.values()) + anonymous


def _prepare_run_metadata(
    run_dir,
    run_id,
    manifest_metadata,
    resume,
):
    path = Path(run_dir) / "run_metadata.json"
    expected = {
        "run_id": str(run_id),
        "benchmark_mode": "primary_refinement_pipeline",
        **manifest_metadata,
    }
    if resume:
        if not path.exists():
            raise RuntimeError(f"Resume metadata bulunamadı: {path}")
        metadata = json.loads(path.read_text(encoding="utf-8"))
        for field, value in expected.items():
            if metadata.get(field) != value:
                raise RuntimeError(
                    f"Resume metadata uyuşmuyor: {field}"
                )
        return metadata
    metadata = {
        **expected,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_summary_atomic(path, metadata)
    return metadata


def _write_csv_atomic(path, results):
    temp_path = Path(path).with_suffix(Path(path).suffix + ".tmp")
    try:
        with temp_path.open(
            "w",
            encoding="utf-8-sig",
            newline="",
        ) as file:
            writer = csv.DictWriter(file, fieldnames=RESULT_FIELDS)
            writer.writeheader()
            for result in results:
                row = dict(result)
                row["ocr_page_numbers"] = json.dumps(
                    row.get("ocr_page_numbers", []),
                    ensure_ascii=False,
                )
                writer.writerow({
                    field: row.get(field, "")
                    for field in RESULT_FIELDS
                })
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def _count_and_percent(count, total):
    return {
        "count": count,
        "percent": round(100 * count / total, 2) if total else 0,
    }


def build_argument_parser():
    parser = argparse.ArgumentParser(
        description="Temsili primary production PDF benchmark"
    )
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--preflight-results",
        required=True,
        type=Path,
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--sample-size",
        type=int,
        default=DEFAULT_SAMPLE_SIZE,
    )
    parser.add_argument("--seed", default=DEFAULT_SEED)
    parser.add_argument(
        "--prepare-manifest",
        action="store_true",
    )
    parser.add_argument("--resume", action="store_true")
    return parser


def main(argv=None):
    args = build_argument_parser().parse_args(argv)
    if args.prepare_manifest:
        manifest = prepare_representative_manifest(
            root=args.root,
            output=args.output,
            preflight_results_path=args.preflight_results,
            manifest_path=args.manifest,
            sample_size=args.sample_size,
            seed=args.seed,
        )
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return manifest
    summary = run_primary_benchmark(
        root=args.root,
        output=args.output,
        preflight_results_path=args.preflight_results,
        input_manifest_path=args.manifest,
        run_id=args.run_id,
        resume=args.resume,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    main()
