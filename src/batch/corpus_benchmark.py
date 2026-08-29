import argparse
import csv
import hashlib
import json
import math
import os
import statistics
import time
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from src.batch.ced_batch_processor import CEDBatchProcessor
from src.coordinate.coordinate_engine import CoordinateEngine


RESULT_FIELDS = (
    "relative_path",
    "province",
    "project_type",
    "preflight_class",
    "file_size",
    "modified_time",
    "modified_time_ns",
    "status",
    "processing_status",
    "extraction_yield",
    "elapsed_seconds",
    "page_count",
    "text_layer_pages",
    "ocr_pages",
    "ocr_page_numbers",
    "extraction_strategy",
    "defer_heavy_fallback_if_useful",
    "result_completeness",
    "has_useful_result",
    "heavy_fallback_deferred",
    "general_fallback_used",
    "final_result_source",
    "pre_fallback_coordinate_count",
    "pre_fallback_polygon_count",
    "pre_fallback_table_count",
    "fallback_coordinate_count",
    "fallback_polygon_count",
    "fallback_table_count",
    "table_count",
    "coordinate_count",
    "polygon_count",
    "transformed_coordinate_count",
    "table_but_no_coordinates",
    "coordinates_but_no_polygon",
    "coordinates_with_unresolved_crs",
    "error",
    "benchmark_completed",
    "benchmarked_at",
)


def discover_pdfs(root, output):
    root = Path(root).resolve()
    output = Path(output).resolve()
    records = []

    for pdf_path in root.rglob("*.pdf"):
        resolved_path = pdf_path.resolve()
        if _is_within(resolved_path, output):
            continue

        stat = resolved_path.stat()
        relative_path = resolved_path.relative_to(root)
        province, project_type = _path_context(relative_path)
        records.append(
            {
                "path": resolved_path,
                "relative_path": relative_path.as_posix(),
                "province": province,
                "project_type": project_type,
                "file_size": stat.st_size,
                "modified_time_ns": stat.st_mtime_ns,
                "modified_time": datetime.fromtimestamp(
                    stat.st_mtime,
                    tz=timezone.utc,
                ).isoformat(),
            }
        )

    return sorted(
        records,
        key=lambda item: item["relative_path"].casefold(),
    )


def select_pilot(records, sample_size=None):
    if sample_size is None or sample_size >= len(records):
        return list(records)
    if sample_size <= 0:
        return []

    grouped = {
        "EK-1": defaultdict(list),
        "EK-2": defaultdict(list),
    }
    remaining = []

    for record in records:
        project_type = record["project_type"]
        if project_type in grouped:
            grouped[project_type][record["province"]].append(record)
        else:
            remaining.append(record)

    selected = []
    selected_paths = set()
    quotas = {
        "EK-1": sample_size // 2,
        "EK-2": sample_size - (sample_size // 2),
    }

    for project_type in ("EK-1", "EK-2"):
        chosen = _round_robin_provinces(
            grouped[project_type],
            quotas[project_type],
        )
        selected.extend(chosen)
        selected_paths.update(
            item["relative_path"] for item in chosen
        )

    if len(selected) < sample_size:
        leftovers = [
            record
            for record in records
            if record["relative_path"] not in selected_paths
        ]
        leftovers.sort(key=_stable_sample_key)
        selected.extend(
            leftovers[: sample_size - len(selected)]
        )

    return selected[:sample_size]


def select_stratified_pilot(
    records,
    preflight_results,
    prior_results,
    class_quotas,
):
    preflight_by_identity = {
        _identity(result): result
        for result in preflight_results
        if _has_identity(result)
    }
    prior_by_identity = {
        _identity(result): result
        for result in prior_results
        if _has_identity(result)
        and result.get("benchmark_completed")
    }
    annotated = []
    for record in records:
        preflight = preflight_by_identity.get(_identity(record))
        if preflight is None:
            continue
        item = dict(record)
        item["preflight_class"] = preflight.get(
            "classification",
            "",
        )
        annotated.append(item)

    selected = []
    selected_identities = set()
    completed_identities = set(prior_by_identity)

    for classification, quota in class_quotas.items():
        class_records = [
            record
            for record in annotated
            if record.get("preflight_class") == classification
        ]
        completed = [
            record
            for record in class_records
            if _identity(record) in completed_identities
        ]
        chosen = select_pilot(completed, sample_size=quota)

        if len(chosen) < quota:
            candidates = [
                record
                for record in class_records
                if _identity(record) not in completed_identities
            ]
            chosen.extend(
                _fill_balanced_sample(
                    candidates,
                    quota - len(chosen),
                    chosen,
                    quota,
                )
            )

        for record in chosen[:quota]:
            identity = _identity(record)
            if identity in selected_identities:
                continue
            selected.append(record)
            selected_identities.add(identity)

    return selected


def _fill_balanced_sample(records, count, selected, final_size):
    if count <= 0:
        return []

    desired = {
        "EK-1": final_size // 2,
        "EK-2": final_size - (final_size // 2),
    }
    current = Counter(
        record.get("project_type", "") for record in selected
    )
    picked = []
    picked_paths = set()

    for project_type in ("EK-1", "EK-2"):
        needed = max(0, desired[project_type] - current[project_type])
        grouped = defaultdict(list)
        for record in records:
            if record.get("project_type") == project_type:
                grouped[record.get("province", "")].append(record)
        chosen = _round_robin_provinces(
            grouped,
            min(needed, count - len(picked)),
        )
        picked.extend(chosen)
        picked_paths.update(item["relative_path"] for item in chosen)

    if len(picked) < count:
        leftovers = [
            record
            for record in records
            if record["relative_path"] not in picked_paths
        ]
        leftovers.sort(key=_stable_sample_key)
        picked.extend(leftovers[: count - len(picked)])

    return picked[:count]


def run_benchmark(
    root,
    output,
    sample_size=None,
    resume=False,
    preflight_results_path=None,
    class_quotas=None,
    time_budget_minutes=None,
    run_id=None,
    defer_heavy_fallback_if_useful=False,
):
    root = Path(root).resolve()
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)

    if resume and not run_id:
        raise ValueError("Resume için run_id zorunludur.")

    resolved_run_id = _resolve_run_id(run_id)
    run_dir = output / "runs" / resolved_run_id
    run_dir_existed = run_dir.exists()
    if run_dir_existed and not resume:
        raise RuntimeError(
            f"Benchmark run zaten mevcut: {resolved_run_id}"
        )
    run_dir.mkdir(parents=True, exist_ok=True)

    with _run_lock(run_dir):
        run_metadata = _prepare_run_metadata(
            run_dir=run_dir,
            run_id=resolved_run_id,
            defer_heavy_fallback_if_useful=(
                defer_heavy_fallback_if_useful
            ),
            resume=resume,
        )
        return _run_benchmark_locked(
            root=root,
            output_root=output,
            run_dir=run_dir,
            sample_size=sample_size,
            resume=resume,
            preflight_results_path=preflight_results_path,
            class_quotas=class_quotas,
            time_budget_minutes=time_budget_minutes,
            defer_heavy_fallback_if_useful=(
                defer_heavy_fallback_if_useful
            ),
            run_metadata=run_metadata,
        )


def _run_benchmark_locked(
    root,
    output_root,
    run_dir,
    sample_size,
    resume,
    preflight_results_path,
    class_quotas,
    time_budget_minutes,
    defer_heavy_fallback_if_useful,
    run_metadata,
):
    all_records = discover_pdfs(root, output_root)
    jsonl_path = run_dir / "benchmark_results.jsonl"
    csv_path = run_dir / "benchmark_results.csv"
    summary_path = run_dir / "benchmark_summary.json"

    prior_results = _load_jsonl(jsonl_path)
    latest_results = {
        _identity(result): result
        for result in prior_results
        if _has_identity(result)
    }

    if class_quotas:
        preflight_results = _load_results_file(
            Path(preflight_results_path)
        )
        selected_records = select_stratified_pilot(
            all_records,
            preflight_results,
            prior_results,
            class_quotas,
        )
    else:
        selected_records = select_pilot(
            all_records,
            sample_size=sample_size,
        )

    selected_identities = {
        _identity(record) for record in selected_records
    }

    run_started = time.perf_counter()
    new_processed = 0
    stopped_by_time_budget = False
    time_budget_seconds = (
        time_budget_minutes * 60
        if time_budget_minutes is not None
        else None
    )

    try:
        for index, record in enumerate(selected_records, start=1):
            identity = _identity(record)
            previous = latest_results.get(identity)

            if previous and record.get("preflight_class"):
                previous = dict(previous)
                previous["preflight_class"] = record[
                    "preflight_class"
                ]
                latest_results[identity] = previous

            if (
                resume
                and previous
                and previous.get("benchmark_completed")
                and (
                    class_quotas
                    or previous.get("status") != "HATA"
                )
            ):
                print(
                    f"[{index}/{len(selected_records)}] "
                    f"RESUME SKIP | {record['relative_path']}"
                )
                continue

            if (
                time_budget_seconds is not None
                and new_processed > 0
                and time.perf_counter() - run_started
                >= time_budget_seconds
            ):
                stopped_by_time_budget = True
                print(
                    "Benchmark süre bütçesine ulaştı; "
                    "yeni PDF başlatılmadı."
                )
                break

            print(
                f"[{index}/{len(selected_records)}] "
                f"PROCESS | {record['relative_path']}"
            )
            result = benchmark_pdf(
                record,
                root,
                defer_heavy_fallback_if_useful=(
                    defer_heavy_fallback_if_useful
                ),
            )
            new_processed += 1
            _append_jsonl(jsonl_path, result)
            latest_results[identity] = result
            current_results = _selected_latest_results(
                latest_results,
                selected_identities,
            )
            _write_csv_atomic(csv_path, current_results)
            _write_summary_atomic(
                summary_path,
                _build_run_summary(
                    current_results,
                    total_discovered=len(all_records),
                    total_selected=len(selected_records),
                    class_quotas=class_quotas,
                    new_processed=new_processed,
                    stopped_by_time_budget=False,
                    run_wall_seconds=(
                        time.perf_counter() - run_started
                    ),
                    run_metadata=run_metadata,
                ),
            )

    except KeyboardInterrupt:
        print("Benchmark kullanıcı tarafından durduruldu; sonuçlar korundu.")

    current_results = _selected_latest_results(
        latest_results,
        selected_identities,
    )
    summary = _build_run_summary(
        current_results,
        total_discovered=len(all_records),
        total_selected=len(selected_records),
        class_quotas=class_quotas,
        new_processed=new_processed,
        stopped_by_time_budget=stopped_by_time_budget,
        run_wall_seconds=time.perf_counter() - run_started,
        run_metadata=run_metadata,
    )
    _write_csv_atomic(csv_path, current_results)
    _write_summary_atomic(summary_path, summary)
    return summary


def benchmark_pdf(
    record,
    root,
    defer_heavy_fallback_if_useful=False,
):
    started = time.perf_counter()
    coordinates = []
    processor_result = None

    try:
        processor = CEDBatchProcessor(
            province=record["province"] or "BILINMIYOR",
            downloads_root=root,
        )
        with _capture_final_coordinates() as captured:
            processor_result = processor.process_pdf(
                pdf_path=record["path"],
                project_type=(
                    record["project_type"] or "BILINMIYOR"
                ),
                defer_heavy_fallback_if_useful=(
                    defer_heavy_fallback_if_useful
                ),
            )
        if captured:
            coordinates = captured[-1]
    except Exception as error:
        processor_result = {
            "status": "HATA",
            "error": str(error),
        }

    processor_result = processor_result or {}
    coordinate_count = int(
        processor_result.get("coordinate_count", 0) or 0
    )
    table_count = int(
        processor_result.get("table_count", 0) or 0
    )
    polygon_count = int(
        processor_result.get("polygon_count", 0) or 0
    )
    transformed_count = sum(
        point.get("transformed_longitude") is not None
        and point.get("transformed_latitude") is not None
        for point in coordinates
    )

    result = {
        "relative_path": record["relative_path"],
        "province": record["province"],
        "project_type": record["project_type"],
        "preflight_class": record.get("preflight_class", ""),
        "file_size": record["file_size"],
        "modified_time": record["modified_time"],
        "modified_time_ns": record["modified_time_ns"],
        "status": processor_result.get("status", "HATA"),
        "processing_status": processor_result.get(
            "status",
            "HATA",
        ),
        "extraction_yield": _extraction_yield(
            table_count,
            coordinate_count,
            polygon_count,
        ),
        "elapsed_seconds": round(
            time.perf_counter() - started,
            6,
        ),
        "page_count": int(
            processor_result.get("page_count", 0) or 0
        ),
        "text_layer_pages": int(
            processor_result.get("text_layer_pages", 0) or 0
        ),
        "ocr_pages": int(
            processor_result.get("ocr_pages", 0) or 0
        ),
        "ocr_page_numbers": list(
            processor_result.get("ocr_page_numbers", []) or []
        ),
        "extraction_strategy": processor_result.get(
            "extraction_strategy",
            "",
        ),
        "defer_heavy_fallback_if_useful": bool(
            defer_heavy_fallback_if_useful
        ),
        "result_completeness": processor_result.get(
            "result_completeness",
            "",
        ),
        "has_useful_result": bool(
            processor_result.get("has_useful_result", False)
        ),
        "heavy_fallback_deferred": bool(
            processor_result.get("heavy_fallback_deferred", False)
        ),
        "general_fallback_used": bool(
            processor_result.get("general_fallback_used", False)
        ),
        "final_result_source": processor_result.get(
            "final_result_source",
            "",
        ),
        "pre_fallback_coordinate_count": processor_result.get(
            "pre_fallback_coordinate_count"
        ),
        "pre_fallback_polygon_count": processor_result.get(
            "pre_fallback_polygon_count"
        ),
        "pre_fallback_table_count": processor_result.get(
            "pre_fallback_table_count"
        ),
        "fallback_coordinate_count": processor_result.get(
            "fallback_coordinate_count"
        ),
        "fallback_polygon_count": processor_result.get(
            "fallback_polygon_count"
        ),
        "fallback_table_count": processor_result.get(
            "fallback_table_count"
        ),
        "table_count": table_count,
        "coordinate_count": coordinate_count,
        "polygon_count": polygon_count,
        "transformed_coordinate_count": transformed_count,
        "table_but_no_coordinates": (
            table_count > 0 and coordinate_count == 0
        ),
        "coordinates_but_no_polygon": (
            coordinate_count > 0 and polygon_count == 0
        ),
        "coordinates_with_unresolved_crs": (
            coordinate_count > transformed_count
        ),
        "error": processor_result.get("error", ""),
        "benchmark_completed": True,
        "benchmarked_at": datetime.now(
            timezone.utc
        ).isoformat(),
    }
    return result


def build_summary(results, total_discovered, total_selected):
    results = list(results)
    elapsed = [
        float(item.get("elapsed_seconds", 0) or 0)
        for item in results
    ]
    coordinate_counts = [
        int(item.get("coordinate_count", 0) or 0)
        for item in results
    ]
    statuses = Counter(
        item.get("status", "") for item in results
    )
    strategies = Counter(
        item.get("extraction_strategy", "") or "unknown"
        for item in results
    )
    completeness = Counter(
        item.get("result_completeness", "")
        for item in results
    )

    summary = {
        "total_discovered": total_discovered,
        "total_selected": total_selected,
        "processed": len(results),
        "processing_status": dict(sorted(statuses.items())),
        "successful": statuses.get("BASARILI", 0),
        "metin_yok": statuses.get("METIN_YOK", 0),
        "errors": statuses.get("HATA", 0),
        "extraction_yield": {
            "with_coordinates": _count(results, "coordinate_count"),
            "without_coordinates": sum(
                not item.get("coordinate_count", 0)
                for item in results
            ),
            "with_tables": _count(results, "table_count"),
            "table_but_no_coordinates": _count_flag(
                results,
                "table_but_no_coordinates",
            ),
            "with_polygons": _count(results, "polygon_count"),
            "coordinates_but_no_polygon": _count_flag(
                results,
                "coordinates_but_no_polygon",
            ),
            "all_coordinates_transformed": sum(
                item.get("coordinate_count", 0) > 0
                and item.get("coordinate_count", 0)
                == item.get("transformed_coordinate_count", 0)
                for item in results
            ),
            "partially_or_unresolved_crs": _count_flag(
                results,
                "coordinates_with_unresolved_crs",
            ),
        },
        "ocr_usage": {
            "used_ocr": _count(results, "ocr_pages"),
            "no_ocr": sum(
                not item.get("ocr_pages", 0)
                for item in results
            ),
        },
        "strategy_distribution": dict(
            sorted(strategies.items())
        ),
        "result_completeness": {
            status: completeness.get(status, 0)
            for status in (
                "COMPLETE",
                "USEFUL_PARTIAL",
                "INSUFFICIENT",
            )
        },
        "heavy_fallback_deferred": _count_flag(
            results,
            "heavy_fallback_deferred",
        ),
        "general_fallback_used": _count_flag(
            results,
            "general_fallback_used",
        ),
        "project_type_breakdown": _project_type_breakdown(
            results
        ),
        "elapsed_seconds": _distribution(elapsed),
        "coordinate_count_distribution": _distribution(
            coordinate_counts
        ),
    }
    summary["failure_classes"] = {
        "HATA": summary["errors"],
        "METIN_YOK": summary["metin_yok"],
        "table_but_no_coordinates": summary[
            "extraction_yield"
        ]["table_but_no_coordinates"],
        "coordinates_but_no_polygon": summary[
            "extraction_yield"
        ]["coordinates_but_no_polygon"],
        "coordinates_with_unresolved_crs": summary[
            "extraction_yield"
        ]["partially_or_unresolved_crs"],
    }
    summary["preflight_class_breakdown"] = (
        _preflight_class_breakdown(results)
    )
    return summary


def _build_run_summary(
    results,
    total_discovered,
    total_selected,
    class_quotas,
    new_processed,
    stopped_by_time_budget,
    run_wall_seconds,
    run_metadata=None,
):
    summary = build_summary(
        results,
        total_discovered=total_discovered,
        total_selected=total_selected,
    )
    summary.update(
        {
            "class_quotas": class_quotas or {},
            "new_processed": new_processed,
            "stopped_by_time_budget": stopped_by_time_budget,
            "run_wall_seconds": round(run_wall_seconds, 6),
        }
    )
    if run_metadata:
        summary.update(run_metadata)
    return summary


def _preflight_class_breakdown(results):
    breakdown = {}
    classifications = sorted(
        {
            item.get("preflight_class", "")
            for item in results
            if item.get("preflight_class")
        }
    )

    for classification in classifications:
        items = [
            item
            for item in results
            if item.get("preflight_class") == classification
        ]
        statuses = Counter(item.get("status", "") for item in items)
        strategies = Counter(
            item.get("extraction_strategy", "") or "unknown"
            for item in items
        )
        coordinate_counts = [
            int(item.get("coordinate_count", 0) or 0)
            for item in items
        ]
        polygon_counts = [
            int(item.get("polygon_count", 0) or 0)
            for item in items
        ]
        elapsed = [
            float(item.get("elapsed_seconds", 0) or 0)
            for item in items
        ]
        ocr_counts = [
            int(item.get("ocr_pages", 0) or 0)
            for item in items
            if item.get("ocr_pages", 0)
        ]

        breakdown[classification] = {
            "processed": len(items),
            "status": dict(sorted(statuses.items())),
            "with_coordinates": _count(items, "coordinate_count"),
            "with_polygons": _count(items, "polygon_count"),
            "all_coordinates_transformed": sum(
                item.get("coordinate_count", 0) > 0
                and item.get("coordinate_count", 0)
                == item.get("transformed_coordinate_count", 0)
                for item in items
            ),
            "unresolved_crs": _count_flag(
                items,
                "coordinates_with_unresolved_crs",
            ),
            "coordinate_count": _distribution(coordinate_counts),
            "polygon_count": _distribution(polygon_counts),
            "elapsed_seconds": _distribution(elapsed),
            "strategy_distribution": dict(sorted(strategies.items())),
            "ocr_used": len(ocr_counts),
            "ocr_page_count": _distribution(ocr_counts),
        }

    return breakdown


@contextmanager
def _capture_final_coordinates():
    original_descriptor = CoordinateEngine.__dict__[
        "extract_coordinates"
    ]
    original_function = original_descriptor.__func__
    captured = []

    def wrapped(cls, text, pdf_path=None):
        result = original_function(
            cls,
            text,
            pdf_path=pdf_path,
        )
        if pdf_path is not None:
            captured.append(result)
        return result

    CoordinateEngine.extract_coordinates = classmethod(wrapped)
    try:
        yield captured
    finally:
        CoordinateEngine.extract_coordinates = original_descriptor


def _round_robin_provinces(province_groups, limit):
    queues = {}
    for province, records in province_groups.items():
        queues[province] = sorted(
            records,
            key=_stable_sample_key,
        )

    provinces = sorted(queues, key=str.casefold)
    selected = []
    while len(selected) < limit:
        added = False
        for province in provinces:
            if queues[province]:
                selected.append(queues[province].pop(0))
                added = True
                if len(selected) >= limit:
                    break
        if not added:
            break
    return selected


def _stable_sample_key(record):
    relative_path = record["relative_path"].encode("utf-8")
    return hashlib.sha256(relative_path).hexdigest()


def _path_context(relative_path):
    parts = relative_path.parts
    for index, part in enumerate(parts):
        project_type = part.upper()
        if project_type in {"EK-1", "EK-2"}:
            province = parts[index - 1] if index > 0 else ""
            return province, project_type
    return "", ""


def _identity(item):
    return (
        item.get("relative_path", ""),
        int(item.get("file_size", 0) or 0),
        int(item.get("modified_time_ns", 0) or 0),
    )


def _has_identity(item):
    return bool(item.get("relative_path"))


def _resolve_run_id(run_id):
    if run_id is None:
        timestamp = datetime.now(timezone.utc).strftime(
            "%Y%m%dT%H%M%S%fZ"
        )
        return f"{timestamp}-{os.getpid()}"

    run_id = str(run_id)
    if (
        not run_id
        or run_id in {".", ".."}
        or not all(
            character.isalnum() or character in "-_."
            for character in run_id
        )
    ):
        raise ValueError(f"Geçersiz run_id: {run_id}")
    return run_id


@contextmanager
def _run_lock(run_dir):
    lock_path = Path(run_dir) / ".benchmark.lock"
    try:
        descriptor = os.open(
            lock_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        )
    except FileExistsError as error:
        raise RuntimeError(
            f"Benchmark run şu anda kilitli: {run_dir}"
        ) from error

    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(
                {
                    "pid": os.getpid(),
                    "started_at": datetime.now(
                        timezone.utc
                    ).isoformat(),
                },
                file,
                ensure_ascii=False,
                indent=2,
            )
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        yield lock_path
    finally:
        lock_path.unlink(missing_ok=True)


def _prepare_run_metadata(
    run_dir,
    run_id,
    defer_heavy_fallback_if_useful,
    resume,
):
    metadata_path = Path(run_dir) / "run_metadata.json"
    if resume:
        if not metadata_path.exists():
            raise RuntimeError(
                f"Resume metadata bulunamadı: {metadata_path}"
            )
        with metadata_path.open("r", encoding="utf-8") as file:
            metadata = json.load(file)
        if metadata.get("run_id") != run_id:
            raise RuntimeError("Run metadata run_id ile uyuşmuyor.")
        if bool(
            metadata.get("defer_heavy_fallback_if_useful", False)
        ) != bool(defer_heavy_fallback_if_useful):
            raise RuntimeError(
                "Resume deferred-mode ayarı mevcut run ile "
                "uyuşmuyor."
            )
        return metadata

    metadata = {
        "run_id": run_id,
        "defer_heavy_fallback_if_useful": bool(
            defer_heavy_fallback_if_useful
        ),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_summary_atomic(metadata_path, metadata)
    return metadata


def _load_jsonl(path):
    if not path.exists():
        return []
    results = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return results


def _load_results_file(path):
    if path.suffix.casefold() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            return list(csv.DictReader(file))
    return _load_jsonl(path)


def _append_jsonl(path, result):
    with path.open("a", encoding="utf-8", newline="\n") as file:
        file.write(json.dumps(result, ensure_ascii=False) + "\n")
        file.flush()
        os.fsync(file.fileno())


def _write_csv_atomic(path, results):
    temp_path = path.with_suffix(path.suffix + ".tmp")
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
            writer.writerow(
                {field: row.get(field, "") for field in RESULT_FIELDS}
            )
        file.flush()
        os.fsync(file.fileno())
    os.replace(temp_path, path)


def _write_summary_atomic(path, summary):
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())
    os.replace(temp_path, path)


def _selected_latest_results(latest_results, identities):
    results = [
        result
        for identity, result in latest_results.items()
        if identity in identities
    ]
    return sorted(
        results,
        key=lambda item: item["relative_path"].casefold(),
    )


def _extraction_yield(table_count, coordinate_count, polygon_count):
    if polygon_count > 0:
        return "WITH_POLYGONS"
    if coordinate_count > 0:
        return "COORDINATES_NO_POLYGON"
    if table_count > 0:
        return "TABLE_NO_COORDINATES"
    return "NO_COORDINATE_YIELD"


def _count(results, field):
    return sum(bool(item.get(field, 0)) for item in results)


def _count_flag(results, field):
    return sum(bool(item.get(field, False)) for item in results)


def _distribution(values):
    if not values:
        return {
            "total": 0,
            "average": 0,
            "median": 0,
            "p90": 0,
            "max": 0,
        }
    ordered = sorted(values)
    return {
        "total": round(sum(ordered), 6),
        "average": round(statistics.fmean(ordered), 6),
        "median": round(statistics.median(ordered), 6),
        "p90": round(
            ordered[max(0, math.ceil(len(ordered) * 0.9) - 1)],
            6,
        ),
        "max": round(max(ordered), 6),
    }


def _project_type_breakdown(results):
    breakdown = {}
    for project_type in ("EK-1", "EK-2", "BILINMIYOR"):
        items = [
            item
            for item in results
            if (item.get("project_type") or "BILINMIYOR")
            == project_type
        ]
        if not items:
            continue
        breakdown[project_type] = {
            "processed": len(items),
            "with_coordinates": _count(items, "coordinate_count"),
            "with_polygons": _count(items, "polygon_count"),
            "used_ocr": _count(items, "ocr_pages"),
            "errors": sum(
                item.get("status") == "HATA" for item in items
            ),
            "metin_yok": sum(
                item.get("status") == "METIN_YOK" for item in items
            ),
        }
    return breakdown


def _is_within(path, directory):
    try:
        path.relative_to(directory)
        return True
    except ValueError:
        return False


def build_argument_parser():
    parser = argparse.ArgumentParser(
        description=(
            "İndirilmiş e-ÇED PDF corpusunu production pipeline ile "
            "sequential benchmark eder."
        )
    )
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--sample-size", type=int, default=None)
    parser.add_argument(
        "--run-id",
        help="İzole benchmark run kimliği",
    )
    parser.add_argument(
        "--defer-heavy-if-useful",
        action="store_true",
        help=(
            "Useful partial sonuçta heavy OCR fallback'i erteler"
        ),
    )
    parser.add_argument(
        "--preflight-results",
        type=Path,
        help="Stratified seçim için preflight CSV veya JSONL dosyası",
    )
    parser.add_argument(
        "--class-sample",
        action="append",
        default=[],
        metavar="CLASS=COUNT",
        help="Tekrarlanabilir preflight sınıf kotası",
    )
    parser.add_argument(
        "--time-budget-minutes",
        type=float,
        default=None,
        help="Tamamlanan PDF sonrasında yeni PDF başlatmama bütçesi",
    )
    resume_group = parser.add_mutually_exclusive_group()
    resume_group.add_argument(
        "--resume",
        dest="resume",
        action="store_true",
    )
    resume_group.add_argument(
        "--no-resume",
        dest="resume",
        action="store_false",
    )
    parser.set_defaults(resume=None)
    return parser


def main(argv=None):
    args = build_argument_parser().parse_args(argv)
    class_quotas = _parse_class_quotas(args.class_sample)
    if class_quotas and args.preflight_results is None:
        raise SystemExit(
            "--class-sample için --preflight-results gereklidir"
        )
    if args.resume is True and not args.run_id:
        raise SystemExit("--resume için --run-id zorunludur")
    summary = run_benchmark(
        root=args.root,
        output=args.output,
        sample_size=args.sample_size,
        resume=(args.resume is True),
        preflight_results_path=args.preflight_results,
        class_quotas=class_quotas,
        time_budget_minutes=args.time_budget_minutes,
        run_id=args.run_id,
        defer_heavy_fallback_if_useful=(
            args.defer_heavy_if_useful
        ),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def _parse_class_quotas(values):
    quotas = {}
    for value in values:
        try:
            classification, count_text = value.rsplit("=", 1)
            count = int(count_text)
        except (TypeError, ValueError) as exc:
            raise SystemExit(
                f"Geçersiz --class-sample değeri: {value}"
            ) from exc
        if not classification or count < 0:
            raise SystemExit(
                f"Geçersiz --class-sample değeri: {value}"
            )
        quotas[classification] = count
    return quotas


if __name__ == "__main__":
    main()
