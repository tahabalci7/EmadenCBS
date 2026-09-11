"""Tablolar Dizini → fiziksel sayfa. OCR yok; yalnız metin katmanı."""

from __future__ import annotations

import re
import unicodedata

import fitz

from src.coordinate.state_machine import parse_localized_number


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

GEOMETRY_TITLE_HINTS = (
    "KOORDINAT",
    "KOSE NOKT",
    "SINIR NOKT",
    "SINIR KOORDINAT",
)

ENTRY_START_RE = re.compile(
    r"^(?:TABLO|CIZELGE)\s*[-.]?\s*"
    r"(?P<no>(?:[IVXLCDM]+|[0-9]+)(?:[.,][A-Z0-9]+)*)"
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

INDEX_WINDOW_PAGES = 40
CONTINUATION_BEFORE = 1
CONTINUATION_AFTER = 3
COORDINATE_CHAPTER_FORWARD = 20
COORDINATE_CHAPTER_GAP = 1

FRAGMENT_HEADING_HINTS = (
    "KOORDINATLARI",
    "KOORDINATLAR",
    "Y SAGA",
    "X YUKARI",
    "POLIGON NO",
    "NOKTA NO",
)

NON_AREA_FRAGMENT_HINTS = (
    "SONDAJ",
    "MODELLEME",
    "BLOK MODEL",
    "REZERV",
    "TENOR",
    "JEOLOJIK MODEL",
)


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
    return any(
        normalized.startswith(heading + " ")
        for heading in INDEX_HEADING_CANONICAL
    )


def is_geometry_title(title):
    normalized = normalize_tr(title)
    if not normalized:
        return False
    return any(hint in normalized for hint in GEOMETRY_TITLE_HINTS)


def parse_printed_page(page_text):
    if not page_text:
        return "", None
    compact = re.sub(r"\s+", "", str(page_text))
    compact = compact.replace("–", "-")
    match = re.match(r"(\d+)(?:[-/](\d+))?$", compact)
    if match is None:
        return str(page_text).strip(), None
    return compact, int(match.group(1))


def table_no_variants(table_no):
    raw = str(table_no or "").strip()
    if not raw:
        return []
    variants = [raw, raw.replace(",", ".")]
    dotted = variants[-1]
    if dotted.upper().startswith("I."):
        variants.append("1." + dotted[2:])
    elif dotted.startswith("1."):
        variants.append("I." + dotted[2:])
    unique = []
    seen = set()
    for item in variants:
        key = item.upper()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


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


def resolve_entry(entry, pages, skip_pages=None):
    table_no = str(entry.get("table_no") or "").strip()
    title = normalize_tr(entry.get("table_title") or "")
    skip = set(skip_pages or [])
    number_pages = []
    title_pages = []
    number_patterns = [
        re.compile(
            rf"\b(?:TABLO|CIZELGE)\s*[-.]?\s*{re.escape(variant)}\b",
            re.IGNORECASE,
        )
        for variant in table_no_variants(table_no)
    ]

    for page in pages:
        physical_page = page["physical_page"]
        if physical_page in skip:
            continue
        normalized = normalize_tr(page.get("text") or "")
        if not normalized:
            continue
        if any(pattern.search(normalized) for pattern in number_patterns):
            number_pages.append(physical_page)
        if title and len(title) >= 12 and title in normalized:
            title_pages.append(physical_page)

    printed_raw, printed_first = parse_printed_page(
        entry.get("printed_page_raw", "")
    )
    both = [page for page in number_pages if page in set(title_pages)]

    def pick(candidates):
        if not candidates:
            return None
        if printed_first is None:
            return candidates[0]
        return min(
            candidates,
            key=lambda page: abs(page - printed_first),
        )

    physical_page = None
    resolve_kind = "UNRESOLVED"
    if both:
        physical_page = pick(both)
        resolve_kind = "BODY_RESOLVED_BY_TITLE_AND_NUMBER"
    elif title_pages:
        physical_page = pick(title_pages)
        resolve_kind = "ONLY_TITLE_RESOLVED"
    elif number_pages:
        physical_page = pick(number_pages)
        resolve_kind = "ONLY_NUMBER_RESOLVED"
    page_offset = None
    if physical_page is not None and printed_first is not None:
        page_offset = physical_page - printed_first

    return {
        **entry,
        "printed_page": printed_raw,
        "printed_page_first": printed_first,
        "physical_page": physical_page,
        "page_offset": page_offset,
        "resolve_kind": resolve_kind,
    }


def apply_printed_page_offset(entries):
    offsets = [
        entry["page_offset"]
        for entry in entries
        if entry.get("page_offset") is not None
    ]
    if not offsets:
        return entries

    offsets.sort()
    median = offsets[len(offsets) // 2]
    updated = []
    for entry in entries:
        if entry.get("physical_page") is not None:
            updated.append(entry)
            continue
        printed_first = entry.get("printed_page_first")
        if printed_first is None:
            updated.append(entry)
            continue
        guessed = printed_first + median
        if guessed < 1:
            updated.append(entry)
            continue
        clone = dict(entry)
        clone["physical_page"] = guessed
        clone["resolve_kind"] = "PRINTED_PAGE_OFFSET"
        clone["page_offset"] = median
        updated.append(clone)
    return updated


def expand_pages(page_numbers, page_count):
    expanded = set()
    for page_number in page_numbers:
        if not isinstance(page_number, int) or page_number < 1:
            continue
        start = max(1, page_number - CONTINUATION_BEFORE)
        end = page_number + CONTINUATION_AFTER
        if page_count:
            end = min(page_count, end)
        for candidate in range(start, end + 1):
            expanded.add(candidate)
    return sorted(expanded)


def _count_utm_yx_in_text(text):
    utm_y_count = 0
    utm_x_count = 0
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        values = []
        try:
            values.append(parse_localized_number(stripped))
        except ValueError:
            for token in re.findall(r"[+-]?\d+(?:[.,]\d+)?", stripped):
                try:
                    values.append(parse_localized_number(token))
                except ValueError:
                    continue
        for value in values:
            if 100000 <= value <= 999999:
                utm_y_count += 1
            elif 3000000 <= value <= 5000000:
                utm_x_count += 1
    return utm_y_count, utm_x_count


def looks_like_non_area_coordinates(text):
    normalized = normalize_tr(text)
    if not normalized:
        return False
    return any(hint in normalized for hint in NON_AREA_FRAGMENT_HINTS)


def looks_like_coordinate_fragment(text):
    """Mid-document UTM/Y-X leftover pages, not only early index hits."""

    if looks_like_non_area_coordinates(text):
        return False

    utm_y_count, utm_x_count = _count_utm_yx_in_text(text)
    if utm_y_count >= 2 and utm_x_count >= 2:
        return True

    compact = re.sub(r"[^A-Z0-9]+", " ", normalize_tr(text))
    compact = re.sub(r" +", " ", compact).strip()
    heading = any(hint in compact for hint in FRAGMENT_HEADING_HINTS)
    return heading and utm_y_count >= 1 and utm_x_count >= 1


def extend_coordinate_chapter_pages(target_pages, body_pages, page_count):
    """Walk forward from index hits across prose gaps and page-split tables."""

    page_text = {}
    if isinstance(body_pages, dict):
        for key, value in body_pages.items():
            try:
                page_text[int(key)] = value or ""
            except (TypeError, ValueError):
                continue
    else:
        for page in body_pages or []:
            physical_page = page.get("physical_page")
            if isinstance(physical_page, int):
                page_text[physical_page] = page.get("text") or ""

    expanded = {
        page_number
        for page_number in (target_pages or [])
        if isinstance(page_number, int) and page_number >= 1
    }
    limit = int(page_count or 0)
    seeds = sorted(expanded)
    for seed in seeds:
        end = seed + COORDINATE_CHAPTER_FORWARD
        if limit:
            end = min(limit, end)
        gap = 0
        for page_number in range(seed + 1, end + 1):
            text = page_text.get(page_number, "")
            if looks_like_non_area_coordinates(text):
                break
            if looks_like_coordinate_fragment(text):
                expanded.add(page_number)
                gap = 0
                continue
            gap += 1
            if gap > COORDINATE_CHAPTER_GAP:
                break
    return sorted(expanded)


class TableIndexLocator:
    @classmethod
    def plan(cls, pdf_path):
        empty = {
            "index_found": False,
            "index_pages": [],
            "geometry_entries": [],
            "target_pages": [],
            "page_count": 0,
        }
        try:
            document = fitz.open(pdf_path)
        except Exception:
            return empty

        try:
            page_count = len(document)
            index_limit = min(page_count, INDEX_WINDOW_PAGES)
            index_pages_data = []
            for index in range(index_limit):
                try:
                    text = document[index].get_text("text") or ""
                except Exception:
                    text = ""
                index_pages_data.append(
                    {
                        "physical_page": index + 1,
                        "text": text,
                    }
                )

            index_page_numbers = []
            entries = []
            for page in index_pages_data:
                lines = page["text"].splitlines()
                if any(is_index_heading(line) for line in lines):
                    index_page_numbers.append(page["physical_page"])
                entries.extend(
                    extract_index_entries(
                        lines,
                        page["physical_page"],
                    )
                )

            geometry_entries = [
                entry
                for entry in entries
                if is_geometry_title(entry.get("table_title", ""))
            ]
            if not geometry_entries:
                return {
                    **empty,
                    "index_found": bool(index_page_numbers),
                    "index_pages": index_page_numbers,
                    "page_count": page_count,
                }

            body_pages = []
            for index in range(page_count):
                try:
                    text = document[index].get_text("text") or ""
                except Exception:
                    text = ""
                body_pages.append(
                    {
                        "physical_page": index + 1,
                        "text": text,
                    }
                )
        finally:
            document.close()

        resolved = [
            resolve_entry(
                entry,
                body_pages,
                skip_pages=index_page_numbers,
            )
            for entry in geometry_entries
        ]
        resolved = apply_printed_page_offset(resolved)
        physical_pages = [
            entry["physical_page"]
            for entry in resolved
            if entry.get("physical_page") is not None
        ]
        target_pages = expand_pages(physical_pages, page_count)
        target_pages = extend_coordinate_chapter_pages(
            target_pages,
            body_pages,
            page_count,
        )
        return {
            "index_found": bool(index_page_numbers),
            "index_pages": index_page_numbers,
            "geometry_entries": resolved,
            "target_pages": target_pages,
            "page_count": page_count,
        }
