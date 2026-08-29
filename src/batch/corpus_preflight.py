import argparse
import csv
import io
import json
import math
import os
import re
import statistics
import sys
import time
from collections import Counter
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from src.batch.corpus_benchmark import discover_pdfs, select_pilot
from src.core.pdf_text_extraction_service import (
    PDFTextExtractionService,
)
from src.ocr.ocr_engine import OCREngine


FAST_TEXT_LIKELY = "FAST_TEXT_LIKELY"
SELECTIVE_OCR_CANDIDATE = "SELECTIVE_OCR_CANDIDATE"
WIDER_DISCOVERY_NEEDED = "WIDER_DISCOVERY_NEEDED"
SCAN_OR_HEAVY_FALLBACK_RISK = "SCAN_OR_HEAVY_FALLBACK_RISK"
UNCERTAIN = "UNCERTAIN"
PREFLIGHT_SCHEMA_VERSION = 2

CLASSIFICATIONS = (
    FAST_TEXT_LIKELY,
    SELECTIVE_OCR_CANDIDATE,
    WIDER_DISCOVERY_NEEDED,
    SCAN_OR_HEAVY_FALLBACK_RISK,
    UNCERTAIN,
)

EXCLUDED_DIRECTORY_NAMES = {
    "benchmark",
    "output",
    "preflight",
}

RESULT_FIELDS = (
    "schema_version",
    "relative_path",
    "province",
    "project_type",
    "file_size",
    "modified_time",
    "modified_time_ns",
    "page_count",
    "elapsed_seconds",
    "fast_window_pages_scanned",
    "fast_text_layer_pages",
    "fast_text_chars",
    "coordinate_keyword_hits",
    "table_keyword_hits",
    "area_keyword_hits",
    "projected_number_count",
    "candidate_page_count",
    "candidate_page_numbers",
    "candidate_score_max",
    "license_coordinate_page_numbers",
    "project_coordinate_page_numbers",
    "classification",
    "error",
    "preflight_completed",
    "preflight_at",
)


def _configure_console_encoding():
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass


def discover_preflight_pdfs(root, output):
    records = discover_pdfs(root, output)
    return [
        record
        for record in records
        if not _has_excluded_directory(record["relative_path"])
    ]


def preflight_pdf(record):
    started = time.perf_counter()

    try:
        fast_result = OCREngine.extract_text_layer(
            record["path"],
            max_pages=PDFTextExtractionService.FAST_SCAN_MAX_PAGES,
        )
        observation = observe_fast_text(fast_result)
        error = ""
    except Exception as exc:
        observation = _empty_observation()
        error = str(exc)

    return {
        "schema_version": PREFLIGHT_SCHEMA_VERSION,
        "relative_path": record["relative_path"],
        "province": record["province"],
        "project_type": record["project_type"],
        "file_size": record["file_size"],
        "modified_time": record["modified_time"],
        "modified_time_ns": record["modified_time_ns"],
        **observation,
        "elapsed_seconds": round(time.perf_counter() - started, 6),
        "error": error,
        "preflight_completed": True,
        "preflight_at": datetime.now(timezone.utc).isoformat(),
    }


def observe_fast_text(fast_result):
    text = fast_result.get("text", "") or ""
    upper_text = text.upper()
    page_count = int(fast_result.get("page_count", 0) or 0)
    scanned_pages = int(fast_result.get("scanned_pages", 0) or 0)
    text_layer_pages = int(
        fast_result.get("text_layer_pages", 0) or 0
    )

    candidate_scores = _candidate_scores(text)
    candidate_pages = sorted(candidate_scores)
    score_max = max(candidate_scores.values(), default=0)
    page_signals = _page_signal_summary(text)

    signals = {
        "coordinate_keyword_hits": _keyword_hits(
            upper_text,
            PDFTextExtractionService.STRUCTURE_KEYWORDS,
        ),
        "table_keyword_hits": len(
            re.findall(r"\b(?:TABLO|ÇİZELGE|CIZELGE)\b", upper_text)
        ),
        "area_keyword_hits": _keyword_hits(
            upper_text,
            PDFTextExtractionService.AREA_KEYWORDS,
        ),
        "projected_number_count": len(
            re.findall(r"\b\d{6,7}(?:[.,]\d+)?\b", upper_text)
        ),
    }

    observation = {
        "page_count": page_count,
        "fast_window_pages_scanned": scanned_pages,
        "fast_text_layer_pages": text_layer_pages,
        "fast_text_chars": len(text),
        **signals,
        "candidate_page_count": len(candidate_pages),
        "candidate_page_numbers": candidate_pages,
        "candidate_score_max": score_max,
        **page_signals,
    }
    observation["classification"] = classify_observation(observation)
    return observation


def classify_observation(observation):
    text_chars = int(observation.get("fast_text_chars", 0) or 0)
    scanned_pages = int(
        observation.get("fast_window_pages_scanned", 0) or 0
    )
    text_layer_pages = int(
        observation.get("fast_text_layer_pages", 0) or 0
    )
    page_count = int(observation.get("page_count", 0) or 0)
    candidate_count = int(
        observation.get("candidate_page_count", 0) or 0
    )
    candidate_score_max = int(
        observation.get("candidate_score_max", 0) or 0
    )
    strong_direct_text = (
        text_chars > 0
        and bool(observation.get("license_coordinate_page_numbers"))
        and bool(observation.get("project_coordinate_page_numbers"))
    )
    if strong_direct_text:
        return FAST_TEXT_LIKELY

    if (
        candidate_count > 0
        and candidate_score_max
        >= PDFTextExtractionService.STRONG_TARGET_SCORE
    ):
        return SELECTIVE_OCR_CANDIDATE

    average_chars_per_scanned_page = (
        text_chars / scanned_pages if scanned_pages else 0
    )
    weak_text_layer = (
        text_chars == 0
        or text_layer_pages == 0
        or average_chars_per_scanned_page
        < OCREngine.MIN_TEXT_CHARACTERS
    )
    if weak_text_layer:
        return SCAN_OR_HEAVY_FALLBACK_RISK

    if scanned_pages < page_count:
        return WIDER_DISCOVERY_NEEDED

    return UNCERTAIN


def run_preflight(root, output, sample_size=None, resume=True):
    root = Path(root).resolve()
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)

    all_records = discover_preflight_pdfs(root, output)
    selected_records = select_pilot(all_records, sample_size=sample_size)

    jsonl_path = output / "preflight_results.jsonl"
    csv_path = output / "preflight_results.csv"
    summary_path = output / "preflight_summary.json"
    prior_results = _load_jsonl(jsonl_path)
    latest_results = {
        _identity(result): result
        for result in prior_results
        if result.get("relative_path")
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
                and previous.get("preflight_completed")
                and previous.get("schema_version")
                == PREFLIGHT_SCHEMA_VERSION
            ):
                print(
                    f"[{index}/{len(selected_records)}] RESUME SKIP | "
                    f"{record['relative_path']}"
                )
                continue

            print(
                f"[{index}/{len(selected_records)}] PREFLIGHT | "
                f"{record['relative_path']}"
            )
            result = preflight_pdf(record)
            _append_jsonl(jsonl_path, result)
            latest_results[identity] = result
            current = _selected_latest_results(
                latest_results,
                selected_identities,
            )
            _write_csv_atomic(csv_path, current)
            _write_summary_atomic(
                summary_path,
                build_summary(
                    current,
                    total_discovered=len(all_records),
                    total_selected=len(selected_records),
                ),
            )
    except KeyboardInterrupt:
        print("Preflight durduruldu; tamamlanan sonuçlar korundu.")

    current = _selected_latest_results(
        latest_results,
        selected_identities,
    )
    summary = build_summary(
        current,
        total_discovered=len(all_records),
        total_selected=len(selected_records),
    )
    _write_csv_atomic(csv_path, current)
    _write_summary_atomic(summary_path, summary)
    return summary


def build_summary(results, total_discovered, total_selected):
    results = list(results)
    class_counts = Counter(
        item.get("classification", UNCERTAIN) for item in results
    )
    processed = len(results)
    elapsed = [
        float(item.get("elapsed_seconds", 0) or 0) for item in results
    ]
    page_counts = [
        int(item.get("page_count", 0) or 0) for item in results
    ]
    file_sizes = [
        int(item.get("file_size", 0) or 0) for item in results
    ]
    average_elapsed = statistics.fmean(elapsed) if elapsed else 0

    return {
        "total_discovered": total_discovered,
        "total_selected": total_selected,
        "processed": processed,
        "province_count": len(
            {item.get("province", "") for item in results}
            - {""}
        ),
        "classification_distribution": {
            classification: {
                "count": class_counts.get(classification, 0),
                "percent": round(
                    100 * class_counts.get(classification, 0) / processed,
                    2,
                )
                if processed
                else 0,
            }
            for classification in CLASSIFICATIONS
        },
        "project_type_breakdown": _project_type_breakdown(results),
        "page_count": _distribution(page_counts),
        "file_size_bytes": _distribution(file_sizes),
        "elapsed_seconds": _distribution(elapsed),
        "projected_full_corpus_seconds": round(
            average_elapsed * total_discovered,
            3,
        ),
        "errors": sum(bool(item.get("error")) for item in results),
    }


def _candidate_scores(text):
    if not text.strip():
        return {}
    with redirect_stdout(io.StringIO()):
        _, scores = PDFTextExtractionService._target_groups(text)
    return scores


def _page_signal_summary(text):
    page_matches = list(PDFTextExtractionService.PAGE_PATTERN.finditer(text))
    license_pages = []
    project_pages = []

    for index, match in enumerate(page_matches):
        page_number = int(match.group(1))
        start = match.end()
        end = (
            page_matches[index + 1].start()
            if index + 1 < len(page_matches)
            else len(text)
        )
        page_text = text[start:end].upper()
        has_coordinate_word = (
            "KOORDİNAT" in page_text or "KOORDINAT" in page_text
        )
        projected_numbers = len(
            re.findall(r"\b\d{6,7}(?:[.,]\d+)?\b", page_text)
        )
        if not has_coordinate_word or projected_numbers < 4:
            continue

        if any(
            keyword in page_text
            for keyword in ("RUHSAT ALANI", "RUHSAT SAHASI")
        ):
            license_pages.append(page_number)
        if any(
            keyword in page_text
            for keyword in (
                "ÇED ALANI",
                "CED ALANI",
                "ÇED İZİN",
                "CED IZIN",
                "YENİ ÇED",
                "YENI CED",
                "PROJE ALANI",
                "PROJEYE KONU",
                "TALEP EDİLEN",
                "TALEP EDILEN",
                "İŞLETME İZİN ALANI",
                "ISLETME IZIN ALANI",
            )
        ):
            project_pages.append(page_number)

    return {
        "license_coordinate_page_numbers": sorted(set(license_pages)),
        "project_coordinate_page_numbers": sorted(set(project_pages)),
    }


def _keyword_hits(text, keywords):
    return sum(text.count(keyword) for keyword in set(keywords))


def _empty_observation():
    return {
        "page_count": 0,
        "fast_window_pages_scanned": 0,
        "fast_text_layer_pages": 0,
        "fast_text_chars": 0,
        "coordinate_keyword_hits": 0,
        "table_keyword_hits": 0,
        "area_keyword_hits": 0,
        "projected_number_count": 0,
        "candidate_page_count": 0,
        "candidate_page_numbers": [],
        "candidate_score_max": 0,
        "license_coordinate_page_numbers": [],
        "project_coordinate_page_numbers": [],
        "classification": UNCERTAIN,
    }


def _has_excluded_directory(relative_path):
    parts = Path(relative_path).parts[:-1]
    return any(
        part.casefold() in EXCLUDED_DIRECTORY_NAMES for part in parts
    )


def _identity(item):
    return (
        item.get("relative_path", ""),
        int(item.get("file_size", 0) or 0),
        int(item.get("modified_time_ns", 0) or 0),
    )


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
            row["candidate_page_numbers"] = json.dumps(
                row.get("candidate_page_numbers", []),
                ensure_ascii=False,
            )
            for field in (
                "license_coordinate_page_numbers",
                "project_coordinate_page_numbers",
            ):
                row[field] = json.dumps(
                    row.get(field, []),
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
    return sorted(
        (
            result
            for identity, result in latest_results.items()
            if identity in identities
        ),
        key=lambda item: item["relative_path"].casefold(),
    )


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
        counts = Counter(
            item.get("classification", UNCERTAIN) for item in items
        )
        breakdown[project_type] = {
            "processed": len(items),
            "classifications": {
                classification: counts.get(classification, 0)
                for classification in CLASSIFICATIONS
            },
        }
    return breakdown


def build_argument_parser():
    parser = argparse.ArgumentParser(
        description=(
            "e-ÇED PDF corpusunu OCR çalıştırmadan hızlı text-layer "
            "sinyalleriyle sınıflandırır."
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
    _configure_console_encoding()
    args = build_argument_parser().parse_args(argv)
    summary = run_preflight(
        root=args.root,
        output=args.output,
        sample_size=args.sample_size,
        resume=args.resume,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    main()
