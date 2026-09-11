"""Read-only Tablolar Dizini diagnostic for the CED PDF corpus.

Text layer only. Does not run OCR. Does not change production parsers.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import fitz

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.batch.corpus_preflight import discover_preflight_pdfs
from src.batch.corpus_benchmark import load_input_manifest


INDEX_HEADING_CANONICAL = {
    "TABLOLAR DIZINI",
    "TABLOLAR LISTESI",
    "TABLO DIZINI",
    "TABLO LISTESI",
    "CIZELGELER DIZINI",
    "CIZELGELER LISTESI",
    "CIZELGE DIZINI",
    "CIZELGE LISTESI",
}

COORDINATE_TITLE_HINTS = (
    "KOORDINAT",
    "KOSE NOKT",
    "SINIR NOKT",
    "SINIR KOORDINAT",
    "ALAN VE KOORDINAT",
    "RUHSAT ALAN",
    "CED ALAN",
    "PROJE ALAN",
    "FAALIYET ALAN",
    "OCAK ALAN",
    "PASA ALAN",
)

ENTRY_START_RE = re.compile(
    r"^(?:TABLO|CIZELGE)\s*[-.]?\s*"
    r"(?P<no>\d+(?:[.,]\d+)*)"
    r"(?P<rest>.*)$"
)
PAGE_TAIL_RE = re.compile(
    r"(?P<title>.*?)"
    r"(?:[\.·…\s]{3,}|\s{2,})"
    r"(?P<page>\d+(?:\s*[-–/]\s*\d+)?)\s*$"
)
PAGE_ONLY_RE = re.compile(
    r"^[\.·…\s]*"
    r"(?P<page>\d+(?:\s*[-–/]\s*\d+)?)\s*$"
)
INDEX_STOP_RE = re.compile(
    r"^(SEKILLER|SEKIL DIZINI|ICINDEKILER|"
    r"KISALTMALAR|KAYNAKLAR)\b"
)


def _configure_console_encoding():
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass


def normalize_tr(value):
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.replace("İ", "I").replace("ı", "I")
    text = text.upper()
    replacements = {
        "Ç": "C",
        "Ğ": "G",
        "Ö": "O",
        "Ş": "S",
        "Ü": "U",
        "Â": "A",
        "Î": "I",
        "Û": "U",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = "".join(
        char
        for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    )
    text = text.replace("…", "...")
    text = re.sub(r"[\t\r\n]+", " ", text)
    text = re.sub(r" +", " ", text)
    return text.strip()


def is_index_heading(line):
    normalized = normalize_tr(line)
    if not normalized:
        return False
    if normalized in INDEX_HEADING_CANONICAL:
        return True
    for heading in INDEX_HEADING_CANONICAL:
        if normalized.startswith(heading + " "):
            return True
    return False


def is_coordinate_title(title):
    normalized = normalize_tr(title)
    if not normalized:
        return False
    return any(hint in normalized for hint in COORDINATE_TITLE_HINTS)


def parse_printed_page(page_text):
    if not page_text:
        return "", None
    compact = re.sub(r"\s+", "", str(page_text))
    compact = compact.replace("–", "-")
    match = re.match(r"(\d+)(?:[-/](\d+))?$", compact)
    if match is None:
        return str(page_text).strip(), None
    first = int(match.group(1))
    return compact, first


def split_entry(line):
    normalized = normalize_tr(line)
    start = ENTRY_START_RE.match(normalized)
    if start is None:
        return None

    rest = start.group("rest").strip(" .-:")
    page_match = PAGE_TAIL_RE.match(rest)
    if page_match:
        title = page_match.group("title").strip(" .-:")
        page = page_match.group("page")
    else:
        title = rest.strip(" .-:")
        page = ""

    return {
        "table_no": start.group("no").replace(",", "."),
        "table_title": title,
        "printed_page_raw": page,
        "raw_text": line.strip(),
    }


def extract_index_entries(page_lines, physical_page):
    entries = []
    pending = None
    in_index = False

    for line in page_lines:
        stripped = line.strip()
        if not stripped:
            continue

        if is_index_heading(stripped):
            in_index = True
            pending = None
            continue

        if not in_index:
            continue

        normalized = normalize_tr(stripped)
        if INDEX_STOP_RE.match(normalized):
            break

        if pending is not None:
            page_only = PAGE_ONLY_RE.match(normalized)
            if page_only:
                pending["printed_page_raw"] = page_only.group("page")
                pending["raw_text"] = (
                    pending["raw_text"] + " " + stripped
                ).strip()
                entries.append(pending)
                pending = None
                continue
            entries.append(pending)
            pending = None

        parsed = split_entry(stripped)
        if parsed is None:
            continue

        parsed["physical_index_page"] = physical_page
        if parsed["printed_page_raw"]:
            entries.append(parsed)
        else:
            pending = parsed

    if pending is not None:
        entries.append(pending)

    return entries


def read_text_pages(pdf_path, max_pages):
    pages = []
    readable = False
    page_count = 0

    try:
        document = fitz.open(pdf_path)
    except Exception as error:
        return {
            "page_count": 0,
            "scanned_pages": 0,
            "readable": False,
            "error": str(error),
            "pages": [],
        }

    try:
        page_count = len(document)
        scan_limit = min(page_count, max_pages)
        for index in range(scan_limit):
            try:
                text = document[index].get_text("text") or ""
            except Exception:
                text = ""
            if text.strip():
                readable = True
            pages.append(
                {
                    "physical_page": index + 1,
                    "text": text,
                }
            )
    finally:
        document.close()

    return {
        "page_count": page_count,
        "scanned_pages": len(pages),
        "readable": readable,
        "error": "",
        "pages": pages,
    }


def analyze_index_window(pages):
    all_entries = []
    index_pages = []

    for page in pages:
        lines = page["text"].splitlines()
        if any(is_index_heading(line) for line in lines):
            index_pages.append(page["physical_page"])
        all_entries.extend(
            extract_index_entries(
                lines,
                page["physical_page"],
            )
        )

    unique_entries = []
    seen = set()
    for entry in all_entries:
        key = (
            entry.get("table_no", ""),
            normalize_tr(entry.get("table_title", "")),
            entry.get("printed_page_raw", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        unique_entries.append(entry)

    coordinate_entries = [
        entry
        for entry in unique_entries
        if is_coordinate_title(entry.get("table_title", ""))
    ]

    return {
        "index_found": bool(index_pages),
        "index_pages": index_pages,
        "entries": unique_entries,
        "coordinate_entries": coordinate_entries,
    }


def find_body_matches(pages, entry):
    table_no = str(entry.get("table_no") or "").strip()
    title = normalize_tr(entry.get("table_title") or "")
    number_pages = []
    title_pages = []

    number_patterns = []
    if table_no:
        escaped = re.escape(table_no)
        number_patterns = [
            re.compile(
                rf"\b(?:TABLO|CIZELGE)\s*[-.]?\s*{escaped}\b"
            ),
        ]

    for page in pages:
        normalized = normalize_tr(page["text"])
        if not normalized:
            continue
        if any(pattern.search(normalized) for pattern in number_patterns):
            number_pages.append(page["physical_page"])
        if title and len(title) >= 12 and title in normalized:
            title_pages.append(page["physical_page"])

    both = [page for page in number_pages if page in set(title_pages)]
    physical_page = None
    resolve_kind = "UNRESOLVED"
    if both:
        physical_page = both[0]
        resolve_kind = "BODY_RESOLVED_BY_TITLE_AND_NUMBER"
    elif title_pages:
        physical_page = title_pages[0]
        resolve_kind = "ONLY_TITLE_RESOLVED"
    elif number_pages:
        physical_page = number_pages[0]
        resolve_kind = "ONLY_NUMBER_RESOLVED"

    printed_raw, printed_first = parse_printed_page(
        entry.get("printed_page_raw", "")
    )
    page_offset = None
    if physical_page is not None and printed_first is not None:
        page_offset = physical_page - printed_first

    return {
        "index_entry_found": True,
        "body_title_resolved": bool(title_pages),
        "table_no_match": bool(number_pages),
        "title_match": bool(title_pages),
        "physical_page": physical_page,
        "printed_page": printed_raw,
        "page_offset": page_offset,
        "resolve_kind": resolve_kind,
        "number_match_pages": number_pages[:8],
        "title_match_pages": title_pages[:8],
    }


def select_resolve_sample(pdf_results, sample_size):
    candidates = [
        result
        for result in pdf_results
        if result.get("coordinate_entry_count", 0) > 0
        and result.get("error") == ""
    ]
    candidates.sort(key=lambda item: item["relative_path"].casefold())
    if sample_size <= 0 or len(candidates) <= sample_size:
        return candidates
    step = max(1, len(candidates) // sample_size)
    sampled = candidates[::step][:sample_size]
    return sampled


def project_bucket(project_type):
    value = str(project_type or "").upper()
    if value in {"EK-1", "EK-2"}:
        return value
    return "OTHER"


def empty_metrics():
    return {
        "total_pdf": 0,
        "text_layer_readable": 0,
        "index_found": 0,
        "index_with_coordinate_entry": 0,
        "total_coordinate_index_entries": 0,
        "read_errors": 0,
    }


def analyze_pdf(record, max_index_pages):
    started = time.perf_counter()
    text_result = read_text_pages(record["path"], max_index_pages)
    index_result = analyze_index_window(text_result["pages"])
    elapsed = round(time.perf_counter() - started, 4)

    return {
        "relative_path": record["relative_path"],
        "province": record["province"],
        "project_type": record["project_type"],
        "page_count": text_result["page_count"],
        "scanned_pages": text_result["scanned_pages"],
        "text_layer_readable": text_result["readable"],
        "index_found": index_result["index_found"],
        "index_pages": index_result["index_pages"],
        "entry_count": len(index_result["entries"]),
        "coordinate_entry_count": len(index_result["coordinate_entries"]),
        "entries": index_result["entries"],
        "coordinate_entries": index_result["coordinate_entries"],
        "error": text_result["error"],
        "elapsed_seconds": elapsed,
    }


def title_vocabulary(coordinate_entries):
    counts = Counter()
    for entry in coordinate_entries:
        title = normalize_tr(entry.get("table_title", ""))
        title = re.sub(r"^[\d.]+\s*", "", title)
        title = re.sub(r"\s+", " ", title).strip(" .-")
        if title:
            counts[title] += 1
    return counts.most_common(30)


def build_summary(pdf_results, resolve_results):
    metrics = empty_metrics()
    by_type = defaultdict(empty_metrics)

    all_coordinate_entries = []
    for result in pdf_results:
        bucket = project_bucket(result.get("project_type"))
        for target in (metrics, by_type[bucket]):
            target["total_pdf"] += 1
            if result.get("text_layer_readable"):
                target["text_layer_readable"] += 1
            if result.get("error"):
                target["read_errors"] += 1
            if result.get("index_found"):
                target["index_found"] += 1
            if result.get("coordinate_entry_count", 0) > 0:
                target["index_with_coordinate_entry"] += 1
            target["total_coordinate_index_entries"] += int(
                result.get("coordinate_entry_count", 0) or 0
            )
        all_coordinate_entries.extend(result.get("coordinate_entries") or [])

    resolve_counter = Counter(
        item.get("resolve_kind") for item in resolve_results
    )
    resolve_total = len(resolve_results)
    both = resolve_counter.get("BODY_RESOLVED_BY_TITLE_AND_NUMBER", 0)

    def rate(count, total):
        if not total:
            return 0.0
        return round(100.0 * count / total, 2)

    def attach_rates(block):
        total = block["total_pdf"]
        block["index_found_rate"] = rate(block["index_found"], total)
        block["index_with_coordinate_entry_rate"] = rate(
            block["index_with_coordinate_entry"],
            total,
        )
        return block

    attach_rates(metrics)
    typed = {
        key: attach_rates(value)
        for key, value in sorted(by_type.items())
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ocr_used": False,
        "source": "text_layer_only",
        "metrics": {
            **metrics,
            "body_resolved_by_title_and_number": both,
            "body_resolve_rate": rate(both, resolve_total),
            "only_title_resolved": resolve_counter.get(
                "ONLY_TITLE_RESOLVED",
                0,
            ),
            "only_number_resolved": resolve_counter.get(
                "ONLY_NUMBER_RESOLVED",
                0,
            ),
            "unresolved": resolve_counter.get("UNRESOLVED", 0),
            "resolve_sample_entries": resolve_total,
        },
        "by_project_type": typed,
        "title_vocabulary_top30": [
            {"title": title, "count": count}
            for title, count in title_vocabulary(all_coordinate_entries)
        ],
        "resolve_kind_counts": dict(resolve_counter),
    }


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_csv(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {key: row.get(key, "") for key in fieldnames}
            )


def write_markdown(path, summary, resolve_sample_size):
    metrics = summary["metrics"]
    lines = [
        "# Tablolar Dizini text-layer analizi",
        "",
        f"Olusturulma: {summary['generated_at']}",
        "OCR: kullanilmadi",
        "",
        "## Metrics",
        "",
        f"- TOTAL_PDF: {metrics['total_pdf']}",
        f"- TEXT_LAYER_READABLE: {metrics['text_layer_readable']}",
        f"- INDEX_FOUND: {metrics['index_found']} ({metrics['index_found_rate']}%)",
        (
            "- INDEX_WITH_COORDINATE_ENTRY: "
            f"{metrics['index_with_coordinate_entry']} "
            f"({metrics['index_with_coordinate_entry_rate']}%)"
        ),
        (
            "- TOTAL_COORDINATE_INDEX_ENTRIES: "
            f"{metrics['total_coordinate_index_entries']}"
        ),
        (
            "- BODY_RESOLVED_BY_TITLE_AND_NUMBER: "
            f"{metrics['body_resolved_by_title_and_number']} "
            f"({metrics['body_resolve_rate']}%)"
        ),
        f"- ONLY_TITLE_RESOLVED: {metrics['only_title_resolved']}",
        f"- ONLY_NUMBER_RESOLVED: {metrics['only_number_resolved']}",
        f"- UNRESOLVED: {metrics['unresolved']}",
        f"- RESOLVE_SAMPLE_ENTRIES: {metrics['resolve_sample_entries']}",
        f"- Resolve sample PDF cap: {resolve_sample_size}",
        "",
        "## EK-1 / EK-2",
        "",
    ]
    for project_type, block in summary["by_project_type"].items():
        lines.append(f"### {project_type}")
        lines.append(f"- TOTAL_PDF: {block['total_pdf']}")
        lines.append(
            f"- INDEX_FOUND: {block['index_found']} "
            f"({block['index_found_rate']}%)"
        )
        lines.append(
            "- INDEX_WITH_COORDINATE_ENTRY: "
            f"{block['index_with_coordinate_entry']} "
            f"({block['index_with_coordinate_entry_rate']}%)"
        )
        lines.append(
            "- TOTAL_COORDINATE_INDEX_ENTRIES: "
            f"{block['total_coordinate_index_entries']}"
        )
        lines.append("")

    lines.extend(["## Title vocabulary (top 30)", ""])
    for index, item in enumerate(summary["title_vocabulary_top30"], start=1):
        lines.append(f"{index}. {item['title']} — {item['count']}")

    lines.extend(
        [
            "",
            "## Architectural note",
            "",
            "Bu dosya yalniz sayimdir. STAGE onerisi ozet JSON icindedir.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def architectural_recommendation(summary):
    metrics = summary["metrics"]
    index_rate = metrics["index_found_rate"]
    coord_rate = metrics["index_with_coordinate_entry_rate"]
    body_rate = metrics["body_resolve_rate"]

    if index_rate >= 50 and coord_rate >= 30 and body_rate >= 40:
        verdict = (
            "Index-first sira corpus verisine gore denemeye deger. "
            "STAGE 1-3 on yol, mevcut discovery yedek kalmali."
        )
        suitable = True
    elif index_rate >= 25:
        verdict = (
            "Index yardimci sinyal olabilir ama tek basina on yol olmamali. "
            "Mevcut text-layer discovery birincil kalsin; index ile "
            "hedef sayfa kisitlamasi deneysel tutulmali."
        )
        suitable = False
    else:
        verdict = (
            "Index-first sira bu corpus ornegine gore zayif. "
            "Mevcut fast/selective text-layer discovery birincil kalmali."
        )
        suitable = False

    return {
        "index_first_suitable_as_primary": suitable,
        "verdict": verdict,
        "proposed_order": [
            "STAGE 1 Table Index Discovery",
            "STAGE 2 Index entry -> physical body table resolution",
            "STAGE 3 target text-layer extraction",
            "STAGE 4 multi-page table continuation",
            "STAGE 5 logical sub-area grouping",
            "STAGE 6 coordinate parser",
            "STAGE 7 existing fast/selective/wider discovery if index route fails",
            "STAGE 8 selective OCR only if target page text is unusable",
        ],
    }


def load_records(root, output, manifest):
    root = Path(root)
    output = Path(output)
    if manifest:
        records, metadata = load_input_manifest(manifest, root)
        return records, metadata
    records = discover_preflight_pdfs(root, output)
    return records, {
        "input_manifest_used": False,
        "discovery": "discover_preflight_pdfs",
    }


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "CED PDF corpusunda Tablolar Dizini text-layer analizi. OCR yok."
        )
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(r"E:\eMadenCBS_Downloads"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            r"E:\eMadenCBS_Downloads\benchmark\table_index_analysis"
        ),
    )
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--max-index-pages", type=int, default=40)
    parser.add_argument("--max-body-pages", type=int, default=250)
    parser.add_argument("--resolve-sample", type=int, default=40)
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def main():
    _configure_console_encoding()
    args = parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    records, discovery_meta = load_records(
        args.root,
        output,
        args.manifest,
    )
    if args.limit:
        records = records[: args.limit]

    jsonl_path = output / "table_index_pdfs.jsonl"
    prior = {}
    if args.resume and jsonl_path.exists():
        for line in jsonl_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            prior[row.get("relative_path")] = row

    pdf_results = []
    for index, record in enumerate(records, start=1):
        relative = record["relative_path"]
        previous = prior.get(relative)
        if args.resume and previous and not previous.get("error"):
            print(f"[{index}/{len(records)}] RESUME {relative}")
            pdf_results.append(previous)
            continue

        print(f"[{index}/{len(records)}] INDEX {relative}")
        result = analyze_pdf(record, args.max_index_pages)
        pdf_results.append(result)

    compact_rows = []
    for result in pdf_results:
        compact_rows.append(
            {
                "relative_path": result["relative_path"],
                "province": result["province"],
                "project_type": result["project_type"],
                "page_count": result["page_count"],
                "scanned_pages": result["scanned_pages"],
                "text_layer_readable": result["text_layer_readable"],
                "index_found": result["index_found"],
                "index_pages": "|".join(
                    str(page) for page in result.get("index_pages", [])
                ),
                "entry_count": result["entry_count"],
                "coordinate_entry_count": result["coordinate_entry_count"],
                "error": result["error"],
                "elapsed_seconds": result["elapsed_seconds"],
            }
        )

    resolve_pdfs = select_resolve_sample(
        pdf_results,
        args.resolve_sample,
    )
    resolve_results = []
    for pdf_result in resolve_pdfs:
        record = next(
            item
            for item in records
            if item["relative_path"] == pdf_result["relative_path"]
        )
        print(f"[RESOLVE] {record['relative_path']}")
        body = read_text_pages(record["path"], args.max_body_pages)
        for entry in pdf_result.get("coordinate_entries") or []:
            match = find_body_matches(body["pages"], entry)
            resolve_results.append(
                {
                    "relative_path": pdf_result["relative_path"],
                    "project_type": pdf_result["project_type"],
                    "table_no": entry.get("table_no"),
                    "table_title": entry.get("table_title"),
                    "physical_index_page": entry.get("physical_index_page"),
                    "raw_text": entry.get("raw_text"),
                    **match,
                }
            )

    summary = build_summary(pdf_results, resolve_results)
    summary["discovery"] = discovery_meta
    summary["limits"] = {
        "max_index_pages": args.max_index_pages,
        "max_body_pages": args.max_body_pages,
        "resolve_sample_pdfs": len(resolve_pdfs),
        "pdf_limit": args.limit,
    }
    summary["architectural_recommendation"] = architectural_recommendation(
        summary
    )

    write_jsonl(jsonl_path, pdf_results)
    write_json(output / "table_index_summary.json", summary)
    write_json(output / "table_index_resolve.json", resolve_results)
    write_csv(
        output / "table_index_pdfs.csv",
        compact_rows,
        [
            "relative_path",
            "province",
            "project_type",
            "page_count",
            "scanned_pages",
            "text_layer_readable",
            "index_found",
            "index_pages",
            "entry_count",
            "coordinate_entry_count",
            "error",
            "elapsed_seconds",
        ],
    )
    write_markdown(
        output / "table_index_report.md",
        summary,
        len(resolve_pdfs),
    )

    metrics = summary["metrics"]
    print("")
    print("TOTAL_PDF", metrics["total_pdf"])
    print("TEXT_LAYER_READABLE", metrics["text_layer_readable"])
    print(
        "INDEX_FOUND",
        metrics["index_found"],
        metrics["index_found_rate"],
    )
    print(
        "INDEX_WITH_COORDINATE_ENTRY",
        metrics["index_with_coordinate_entry"],
        metrics["index_with_coordinate_entry_rate"],
    )
    print(
        "TOTAL_COORDINATE_INDEX_ENTRIES",
        metrics["total_coordinate_index_entries"],
    )
    print(
        "BODY_RESOLVE_RATE",
        metrics["body_resolve_rate"],
    )
    print("OUTPUT", output)


if __name__ == "__main__":
    main()
