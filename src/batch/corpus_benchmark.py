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


def run_benchmark(
    root,
    output,
    sample_size=None,
    resume=True,
):
    root = Path(root).resolve()
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)

    all_records = discover_pdfs(root, output)
    selected_records = select_pilot(
        all_records,
        sample_size=sample_size,
    )

    jsonl_path = output / "benchmark_results.jsonl"
    csv_path = output / "benchmark_results.csv"
    summary_path = output / "benchmark_summary.json"
    prior_results = _load_jsonl(jsonl_path)
    latest_results = {
        _identity(result): result
        for result in prior_results
        if _has_identity(result)
    }

    selected_identities = {
        _identity(record) for record in selected_records
    }

    try:
        for index, record in enumerate(selected_records, start=1):
            identity = _identity(record)
            previous = latest_results.get(identity)

            if (
                resume
                and previous
                and previous.get("benchmark_completed")
                and previous.get("status") != "HATA"
            ):
                print(
                    f"[{index}/{len(selected_records)}] "
                    f"RESUME SKIP | {record['relative_path']}"
                )
                continue

            print(
                f"[{index}/{len(selected_records)}] "
                f"PROCESS | {record['relative_path']}"
            )
            result = benchmark_pdf(record, root)
            _append_jsonl(jsonl_path, result)
            latest_results[identity] = result
            current_results = _selected_latest_results(
                latest_results,
                selected_identities,
            )
            _write_csv_atomic(csv_path, current_results)
            _write_summary_atomic(
                summary_path,
                build_summary(
                    current_results,
                    total_discovered=len(all_records),
                    total_selected=len(selected_records),
                ),
            )

    except KeyboardInterrupt:
        print("Benchmark kullanıcı tarafından durduruldu; sonuçlar korundu.")

    current_results = _selected_latest_results(
        latest_results,
        selected_identities,
    )
    summary = build_summary(
        current_results,
        total_discovered=len(all_records),
        total_selected=len(selected_records),
    )
    _write_csv_atomic(csv_path, current_results)
    _write_summary_atomic(summary_path, summary)
    return summary


def benchmark_pdf(record, root):
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
    return summary


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
    parser.set_defaults(resume=True)
    return parser


def main(argv=None):
    args = build_argument_parser().parse_args(argv)
    summary = run_benchmark(
        root=args.root,
        output=args.output,
        sample_size=args.sample_size,
        resume=args.resume,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    main()
