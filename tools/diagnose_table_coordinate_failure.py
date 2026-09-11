"""Diagnose detected tables that do not produce coordinate points.

This command is intentionally read-only.  It runs the production text
extraction, table detection, classification, provenance matching, and
coordinate parser, then reports observable parser inputs and candidates.
The failure observations are diagnostics only; they are not production
classification rules.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import fitz


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.coordinate.coordinate_engine import CoordinateEngine
from src.coordinate.state_machine import (
    is_label,
    is_number,
    is_valid_coordinate_block,
    parse_coordinate_blocks,
    parse_row_coordinate,
    recover_row_coordinate_from_values,
    to_float,
)
from src.coordinate.table_classifier import TableClassifier
from src.coordinate.table_detector import TableDetector
from src.core.pdf_text_extraction_service import PDFTextExtractionService


TOKEN_RE = re.compile(r"\S+")
COMMA_DECIMAL_RE = re.compile(r"(?<!\d)[+-]?\d+,\d+(?!\d)")
THOUSANDS_RE = re.compile(
    r"(?<!\d)[+-]?\d{1,3}(?:[.\s]\d{3})+(?:,\d+)?(?!\d)"
)
SPLIT_NUMBER_RE = re.compile(
    r"(?<!\d)\d{2,6}\s+(?:[.,]\s*)?\d{2,6}(?!\d)"
)


def _configure_console_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, OSError, ValueError):
                pass


def _parse_page_selection(value: str) -> list[int]:
    pages = []

    for part in value.split(","):
        part = part.strip()
        match = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if match is None:
            raise argparse.ArgumentTypeError(
                "Sayfalar 48, 48-53 veya 48,50,53 biçiminde olmalıdır."
            )

        start = int(match.group(1))
        end = int(match.group(2) or start)
        if start < 1 or end < 1:
            raise argparse.ArgumentTypeError(
                "Sayfa numaraları 1 veya daha büyük olmalıdır."
            )
        if start > end:
            raise argparse.ArgumentTypeError(
                "Sayfa aralığı başlangıcı bitişten büyük olamaz."
            )
        pages.extend(range(start, end + 1))

    return sorted(set(pages))


def _format_page_selection(pages: list[int]) -> str:
    parts = []
    start = pages[0]
    end = start

    for page in pages[1:]:
        if page == end + 1:
            end = page
            continue
        parts.append(str(start) if start == end else f"{start}-{end}")
        start = end = page

    parts.append(str(start) if start == end else f"{start}-{end}")
    return ",".join(parts)


def _validate_pages_within_document(
    pages: list[int],
    page_count: int,
) -> None:
    outside = [page for page in pages if page > page_count]
    if outside:
        raise ValueError(
            "İstenen sayfa PDF sınırı dışında: "
            f"{','.join(map(str, outside))}; PDF page count: {page_count}"
        )


def _nonempty_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _allow_numeric_labels(text: str) -> bool:
    upper_text = text.upper()
    return "KOORDİNAT" in upper_text or "KOORDINAT" in upper_text


def _number_candidates(lines: list[str]) -> list[dict]:
    candidates = []
    for line_index, line in enumerate(lines):
        for match in TableDetector.NUMBER_PATTERN.finditer(line):
            token = match.group(0)
            try:
                value = to_float(token)
            except ValueError:
                value = None
            candidates.append(
                {
                    "line": line_index,
                    "token": token,
                    "value": value,
                }
            )
    return candidates


def _label_candidates(
    lines: list[str],
    allow_numeric_labels: bool,
) -> list[dict]:
    candidates = []
    seen = set()

    def add(line_index: int, value: str, source: str) -> None:
        key = (line_index, value, source)
        if key not in seen:
            seen.add(key)
            candidates.append(
                {
                    "line": line_index,
                    "value": value,
                    "source": source,
                }
            )

    for line_index, line in enumerate(lines):
        if is_label(line, allow_numeric_labels):
            add(line_index, line, "whole_line")

        tokens = TOKEN_RE.findall(line)
        if not tokens:
            continue

        leading = []
        for token in tokens:
            if is_number(token):
                break
            leading.append(token)

        if leading:
            value = " ".join(leading)
            if is_label(value, allow_numeric_labels):
                add(line_index, value, "row_prefix")
        elif allow_numeric_labels and tokens[0].isdigit():
            add(line_index, tokens[0], "numeric_row_prefix")

    return candidates


def _range_candidates(numbers: list[dict]) -> dict[str, list[dict]]:
    ranges = {
        "utm_y": [],
        "utm_x": [],
        "latitude": [],
        "longitude": [],
    }
    for candidate in numbers:
        value = candidate["value"]
        if value is None:
            continue
        if 100000 <= value <= 999999:
            ranges["utm_y"].append(candidate)
        if 3000000 <= value <= 5000000:
            ranges["utm_x"].append(candidate)
        if 35 <= value <= 43:
            ranges["latitude"].append(candidate)
        if 25 <= value <= 46:
            ranges["longitude"].append(candidate)
    return ranges


def _row_parser_matches(
    lines: list[str],
    allow_numeric_labels: bool,
) -> list[dict]:
    matches = []
    for line_index, line in enumerate(lines):
        point = parse_row_coordinate(line, allow_numeric_labels)
        method = "parse_row_coordinate"
        if point is None:
            point = recover_row_coordinate_from_values(line)
            method = "recover_row_coordinate_from_values"
        if point is not None:
            matches.append(
                {
                    "line": line_index,
                    "method": method,
                    "point": point,
                }
            )
    return matches


def _five_line_matches(
    lines: list[str],
    allow_numeric_labels: bool,
) -> list[dict]:
    matches = []
    for index in range(max(0, len(lines) - 4)):
        block = lines[index : index + 5]
        if not is_label(block[0], allow_numeric_labels):
            continue
        if not all(is_number(value) for value in block[1:]):
            continue
        values = [to_float(value) for value in block[1:]]
        if is_valid_coordinate_block(*values):
            matches.append(
                {
                    "start_line": index,
                    "label": block[0],
                    "values": values,
                }
            )
    return matches


def _looks_row_based(lines: list[str]) -> bool:
    for line in lines:
        values = TableDetector.NUMBER_PATTERN.findall(line)
        if len(values) >= 3:
            return True
    return False


def _looks_column_based(lines: list[str]) -> bool:
    single_token_lines = sum(
        1 for line in lines if len(TOKEN_RE.findall(line)) == 1
    )
    return len(lines) >= 5 and single_token_lines >= max(5, len(lines) // 2)


def _failure_observations(
    table: str,
    lines: list[str],
    labels: list[dict],
    numbers: list[dict],
    ranges: dict[str, list[dict]],
    parsed_points: list[dict],
    row_matches: list[dict],
    five_line_matches: list[dict],
) -> list[tuple[str, str]]:
    if parsed_points:
        return [
            (
                "PARSER_ACCEPTED",
                f"Mevcut parser {len(parsed_points)} nokta üretti.",
            )
        ]

    observations = []
    if not labels:
        observations.append(
            ("NO_LABEL_PATTERN", "Mevcut label kuralları aday bulamadı.")
        )
    if len(numbers) < 4:
        observations.append(
            (
                "INSUFFICIENT_NUMERIC_VALUES",
                f"Yalnız {len(numbers)} production numeric token bulundu.",
            )
        )

    has_y = bool(ranges["utm_y"])
    has_x = bool(ranges["utm_x"])
    has_lat = bool(ranges["latitude"])
    has_lon = bool(ranges["longitude"])
    if has_y and has_x and not (has_lat and has_lon):
        observations.append(
            ("ONLY_UTM", "UTM aralıkları var; tam coğrafi çift yok.")
        )
    if has_lat and has_lon and not (has_y and has_x):
        observations.append(
            (
                "ONLY_GEOGRAPHIC",
                "Coğrafi aralıklar var; tam UTM çifti yok.",
            )
        )
    if has_y and has_x and has_lat and has_lon and not row_matches:
        observations.append(
            (
                "NUMBERS_PRESENT_WRONG_ORDER",
                "Dört koordinat aralığı da var fakat satır parser eşleşmedi.",
            )
        )
    if _looks_row_based(lines) and not row_matches:
        observations.append(
            (
                "ROW_LAYOUT",
                "Aynı satırda çoklu sayılar var fakat production row parser eşleşmedi.",
            )
        )
    if _looks_column_based(lines) and not five_line_matches:
        observations.append(
            (
                "COLUMN_LAYOUT",
                "Tek-token satırlar baskın fakat geçerli 5-line blok bulunmadı.",
            )
        )
    if COMMA_DECIMAL_RE.search(table):
        observations.append(
            ("DECIMAL_FORMAT", "Virgüllü ondalık token gözlendi.")
        )
    if THOUSANDS_RE.search(table):
        observations.append(
            ("THOUSANDS_SEPARATOR", "Binlik ayırıcı biçimi gözlendi.")
        )
    if SPLIT_NUMBER_RE.search(table):
        observations.append(
            ("OCR_TOKEN_SPLIT", "Boşlukla bölünmüş olası sayısal token gözlendi.")
        )
    if not (has_y or has_x or has_lat or has_lon):
        observations.append(
            (
                "TABLE_FALSE_POSITIVE",
                "Koordinat aralıklarına giren numeric aday bulunmadı.",
            )
        )
    if not observations:
        observations.append(
            ("UNKNOWN", "Mevcut gözlemler tek bir neden ayırmaya yetmedi.")
        )
    return observations


def _format_candidates(candidates: list[dict]) -> str:
    if not candidates:
        return "[]"
    return "[" + ", ".join(
        f"L{item['line']:03d}:{item['token']}={item['value']}"
        for item in candidates
    ) + "]"


def _page_summary(line_sources: list[dict]) -> str:
    pages = sorted(
        {
            source.get("source_page")
            for source in line_sources
            if isinstance(source, dict)
            and isinstance(source.get("source_page"), int)
        }
    )
    if not pages:
        return "UNKNOWN"
    if len(pages) == 1:
        return str(pages[0])
    return f"{pages[0]}-{pages[-1]} ({','.join(map(str, pages))})"


def _print_table(
    pdf_path: Path,
    table_index: int,
    table: str,
    line_sources: list[dict],
    preview_lines: int,
) -> None:
    lines = _nonempty_lines(table)
    allow_numeric = _allow_numeric_labels(table)
    numbers = _number_candidates(lines)
    labels = _label_candidates(lines, allow_numeric)
    ranges = _range_candidates(numbers)
    parsed_points = parse_coordinate_blocks(table, line_sources=line_sources)
    row_matches = _row_parser_matches(lines, allow_numeric)
    five_line_matches = _five_line_matches(lines, allow_numeric)
    observations = _failure_observations(
        table,
        lines,
        labels,
        numbers,
        ranges,
        parsed_points,
        row_matches,
        five_line_matches,
    )

    print("\n" + "=" * 88)
    print(f"PDF: {pdf_path}")
    print(f"PAGE: {_page_summary(line_sources)}")
    print(f"TABLE INDEX: {table_index}")
    print(f"TABLE TYPE: {TableClassifier.classify(table)}")
    print(f"TABLE TITLE / CONTEXT: {TableClassifier._extract_heading(table)}")
    print(f"NUMBER OF LINES: {len(lines)}")
    print(f"NUMBER OF NUMERIC TOKENS: {len(numbers)}")
    print(f"NUMBER OF LABEL-LIKE TOKENS: {len(labels)}")
    print("RAW TABLE TEXT PREVIEW:")
    for index, line in enumerate(lines[:preview_lines]):
        print(f"  RAW[{index:03d}] {line}")
    if len(lines) > preview_lines:
        print(f"  ... {len(lines) - preview_lines} satır daha")

    print("NORMALIZED LINES / PARSER INPUT:")
    for index, line in enumerate(lines):
        print(f"  LINE[{index:03d}] {line}")

    print("LABEL CANDIDATES:")
    if labels:
        for item in labels:
            print(
                f"  L{item['line']:03d} {item['source']}: {item['value']}"
            )
    else:
        print("  []")
    print(f"NUMERIC CANDIDATES: {_format_candidates(numbers)}")
    print(f"UTM Y RANGE: {_format_candidates(ranges['utm_y'])}")
    print(f"UTM X RANGE: {_format_candidates(ranges['utm_x'])}")
    print(f"LATITUDE RANGE: {_format_candidates(ranges['latitude'])}")
    print(f"LONGITUDE RANGE: {_format_candidates(ranges['longitude'])}")
    print(f"ROW PARSER MATCHES: {row_matches}")
    print(f"5-LINE PARSER MATCHES: {five_line_matches}")
    print(f"FINAL PARSED POINT COUNT: {len(parsed_points)}")
    print("REJECTION / FAILURE OBSERVATION:")
    for category, evidence in observations:
        print(f"  {category}: {evidence}")


def diagnose_pdf(pdf_path: Path, preview_lines: int = 15) -> int:
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF bulunamadı: {pdf_path}")

    extraction = PDFTextExtractionService.extract(
        str(pdf_path),
        defer_heavy_fallback_if_useful=True,
    )
    text = extraction.get("text", "")
    print(f"PDF: {pdf_path}")
    print(f"EXTRACTION SUCCESS: {extraction.get('success', False)}")
    print(f"EXTRACTION METHOD: {extraction.get('method', '')}")
    print(f"EXTRACTION STRATEGY: {extraction.get('strategy', '')}")
    print(f"TEXT LENGTH: {len(text)}")
    print(f"TEXT LAYER PAGES: {extraction.get('text_layer_pages', 0)}")
    print(f"OCR PAGES: {extraction.get('ocr_pages', 0)}")
    print(f"OCR PAGE NUMBERS: {extraction.get('ocr_page_numbers', [])}")
    if extraction.get("error"):
        print(f"EXTRACTION ERROR: {extraction['error']}")

    tables = TableDetector.find_tables(text)
    table_sources = CoordinateEngine._match_table_line_sources(text, tables)
    print(f"DETECTED TABLE COUNT: {len(tables)}")

    for table_index, table in enumerate(tables, start=1):
        _print_table(
            pdf_path,
            table_index,
            table,
            table_sources[table_index - 1],
            preview_lines,
        )
    return 0


def diagnose_pdf_pages(
    pdf_path: Path,
    pages: list[int],
    preview_lines: int = 15,
) -> int:
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF bulunamadı: {pdf_path}")

    with fitz.open(pdf_path) as document:
        page_count = document.page_count
        _validate_pages_within_document(pages, page_count)

        print(f"PDF: {pdf_path}")
        print(f"Requested pages: {_format_page_selection(pages)}")
        print(f"PDF page count: {page_count}")
        print(f"Pages actually inspected: {','.join(map(str, pages))}")

        for page_number in pages:
            print(f"\n=== PAGE {page_number} ===")
            page = document.load_page(page_number - 1)
            text = page.get_text("text") or ""
            print(f"TEXT LENGTH: {len(text)}")

            if not text.strip():
                print("TABLE COUNT: 0")
                print("TEXT_LAYER_EMPTY")
                continue

            page_text = (
                f"--- Sayfa {page_number} [PDF METİN KATMANI] ---\n{text}"
            )
            tables = TableDetector.find_tables(page_text)
            table_sources = CoordinateEngine._match_table_line_sources(
                page_text,
                tables,
            )
            print(f"TABLE COUNT: {len(tables)}")

            if not tables:
                print("NO_TABLE_ON_PAGE")
                continue

            for table_index, table in enumerate(tables, start=1):
                _print_table(
                    pdf_path,
                    table_index,
                    table,
                    table_sources[table_index - 1],
                    preview_lines,
                )

    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Production extraction sonucundaki tabloların coordinate parser "
            "girdilerini salt-okunur olarak teşhis eder."
        )
    )
    parser.add_argument("pdf_path", type=Path)
    parser.add_argument(
        "--pages",
        type=_parse_page_selection,
        help=(
            "Yalnız seçilen 1-based PDF sayfalarının text layer'ını "
            "incele (örnek: 48, 48-53 veya 48,50,53)."
        ),
    )
    parser.add_argument(
        "--preview-lines",
        type=int,
        default=15,
        help="Her tablo için raw preview satır sayısı (varsayılan: 15).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_console_encoding()
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.preview_lines < 1:
        parser.error("--preview-lines en az 1 olmalıdır.")
    try:
        if args.pages:
            return diagnose_pdf_pages(
                args.pdf_path.resolve(),
                args.pages,
                args.preview_lines,
            )
        return diagnose_pdf(args.pdf_path.resolve(), args.preview_lines)
    except (FileNotFoundError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
