"""Tablolar Dizini → fiziksel sayfa. OCR yok; yalnız metin katmanı."""

from __future__ import annotations

import re
import unicodedata

import fitz


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

TOC_HEADING_CANONICAL = {
    "ICINDEKILER",
    "ICINDEKILER TABLOSU",
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
APPENDIX_PAGE_TAIL_RE = re.compile(
    r"(?P<title>.*?)"
    r"(?:[\.·…]{2,}|\s+)"
    r"(?P<page>\d+(?:\s*[-–/]\s*\d+)?)\s*$"
)
INDEX_STOP_RE = re.compile(
    r"^(SEKILLER|SEKIL DIZINI|ICINDEKILER|"
    r"KISALTMALAR|KAYNAKLAR)\b"
)

TOC_LEAVE_RE = re.compile(
    r"^(SEKILLER|SEKIL DIZINI|TABLOLAR DIZINI|"
    r"TABLOLAR LISTESI|TABLO DIZINI|TABLO LISTESI|"
    r"CIZELGELER DIZINI|CIZELGELER LISTESI|"
    r"KISALTMALAR|KAYNAKLAR)\b"
)

# Appendix label EK-1 / Ek 1- is not folder EK-2 (PTD project type).
APPENDIX_EK1_RE = re.compile(r"\bEK\s*[-.]?\s*1\b")
APPENDIX_OTHER_EK_RE = re.compile(r"\bEK\s*[-.]?\s*([2-9]|[1-9]\d)\b")
APPENDIX_BARE_ONE_RE = re.compile(r"^1\s*[-.)]")
EK1_APPENDIX_NUMBER = "EK-1"
PAGE_MARKER_RE = re.compile(
    r"^--- Sayfa (?P<page>\d+) \[[^\]\r\n]+\] ---$"
)
TOC_LEADER_RE = re.compile(r"[\.·…]{3,}\s*\d+(?:\s*[-–/]\s*\d+)?\s*$")

MAJOR_UNRELATED_SECTION_CANONICAL = {
    "KAYNAKLAR",
    "KAYNAKCA",
    "KAYNAKCA LISTESI",
    "SEKILLER",
    "SEKIL DIZINI",
    "SEKILLER DIZINI",
    "SEKILLER LISTESI",
}

INDEX_WINDOW_PAGES = 40
CONTINUATION_BEFORE = 1
CONTINUATION_AFTER = 3
APPENDIX_CONTINUATION_BEFORE = 1
APPENDIX_CONTINUATION_AFTER = 10
APPENDIX_SECTION_MAX_PAGES = 40
APPENDIX_BODY_SEARCH_PAGES = 80
APPENDIX_PEEK_BEFORE = 5
APPENDIX_PEEK_AFTER = 15


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


def fold_heading(value):
    """Turkish fold plus punctuation/OCR noise for appendix headings."""

    text = normalize_tr(value)
    if not text:
        return ""
    text = re.sub(r"(?<=[A-Z])0(?=[A-Z])", "O", text)
    text = re.sub(r"[^A-Z0-9]+", " ", text)
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


def is_toc_heading(line):
    normalized = normalize_tr(line)
    if not normalized:
        return False
    if normalized in TOC_HEADING_CANONICAL:
        return True
    return any(
        normalized.startswith(heading + " ")
        for heading in TOC_HEADING_CANONICAL
    )


def is_coordinate_appendix_title(title):
    """Selected-site coordinate appendix, not folder EK-1/EK-2."""

    folded = fold_heading(title)
    if not folded:
        return False

    has_coord = "KOORDINAT" in folded
    has_selected_yer = "SECILEN YER" in folded
    has_selected_alan = "SECILEN ALAN" in folded
    has_proje_icin = "PROJE ICIN" in folded
    has_ek1 = bool(APPENDIX_EK1_RE.search(folded))
    has_bare_one = bool(APPENDIX_BARE_ONE_RE.match(folded))
    has_other_ek = bool(APPENDIX_OTHER_EK_RE.search(folded))

    if has_other_ek and not has_ek1:
        return False
    if has_selected_yer and has_coord:
        return True
    if has_selected_alan and has_coord and (has_ek1 or has_proje_icin):
        return True
    if has_ek1 and has_coord:
        return True
    if has_ek1 and has_selected_yer:
        return True
    if has_bare_one and has_selected_yer and has_coord:
        return True
    return False


def is_toc_style_line(line):
    """İÇİNDEKİLER dotted leader + page number, not the body heading."""

    text = str(line or "").strip()
    if not text:
        return False
    if TOC_LEADER_RE.search(text):
        return True
    normalized = normalize_tr(text)
    match = APPENDIX_PAGE_TAIL_RE.match(normalized)
    if match is None:
        return False
    title = match.group("title") or ""
    page = match.group("page") or ""
    if not page or not is_coordinate_appendix_title(title):
        return False
    return bool(re.search(r"[\.·…]{2,}", text))


def is_major_unrelated_section(line):
    """Next appendix/bibliography heading; not EK-1 itself."""

    folded = fold_heading(line)
    if not folded:
        return False
    if is_coordinate_appendix_title(line):
        return False
    if APPENDIX_OTHER_EK_RE.search(folded):
        return True
    if folded in MAJOR_UNRELATED_SECTION_CANONICAL:
        return True
    return any(
        folded.startswith(heading + " ")
        for heading in MAJOR_UNRELATED_SECTION_CANONICAL
    )


def is_selected_site_body_heading(line, previous_line=None):
    """Body heading for the selected-site coordinate appendix."""

    if is_toc_style_line(line):
        return False
    if is_coordinate_appendix_title(line):
        return True
    previous = str(previous_line or "").strip()
    if not previous or is_toc_style_line(previous):
        return False
    joined = previous + " " + str(line or "")
    if is_toc_style_line(joined):
        return False
    return is_coordinate_appendix_title(joined)


def is_coordinate_appendix_body(text):
    if page_has_selected_site_body_heading(text):
        return True
    normalized = normalize_tr(text)
    if not normalized:
        return False
    if is_toc_style_line(normalized) and "\n" not in str(text or ""):
        return False
    if "SECILEN YERIN KOORDINAT" in normalized:
        return True
    if (
        "PROJE ICIN SECILEN YER" in normalized
        and "KOORDINAT" in normalized
    ):
        return True
    if (
        "PROJE ICIN SECILEN ALAN" in normalized
        and "KOORDINAT" in normalized
    ):
        return True
    return False


def page_has_selected_site_body_heading(text):
    lines = [
        line.strip()
        for line in str(text or "").splitlines()
        if line.strip()
    ]
    previous = None
    for line in lines:
        if PAGE_MARKER_RE.fullmatch(line):
            previous = None
            continue
        if is_selected_site_body_heading(line, previous):
            return True
        previous = line
    return False


def page_starts_major_unrelated_section(text):
    lines = [
        line.strip()
        for line in str(text or "").splitlines()
        if line.strip() and not PAGE_MARKER_RE.fullmatch(line.strip())
    ]
    if not lines:
        return False
    window = lines[:8]
    for index, line in enumerate(window):
        previous = window[index - 1] if index else None
        if is_selected_site_body_heading(line, previous):
            return False
        if is_major_unrelated_section(line):
            return True
        if previous and is_major_unrelated_section(
            previous + " " + line
        ):
            return True
    return False


def find_selected_site_section_span(lines):
    """Line span from the body heading until the next major section."""

    cleaned = [
        str(line).strip()
        for line in lines
        if str(line).strip()
    ]
    start = None
    previous = None
    for index, line in enumerate(cleaned):
        if PAGE_MARKER_RE.fullmatch(line):
            previous = None
            continue
        if is_selected_site_body_heading(line, previous):
            start = index
            if previous and is_coordinate_appendix_title(
                previous + " " + line
            ):
                start = index - 1
            break
        previous = line

    if start is None:
        return None

    for index in range(start, -1, -1):
        if PAGE_MARKER_RE.fullmatch(cleaned[index]):
            start = index
            break

    end = len(cleaned)
    previous = None
    for index in range(start + 1, len(cleaned)):
        line = cleaned[index]
        if PAGE_MARKER_RE.fullmatch(line):
            previous = None
            continue
        if is_major_unrelated_section(line) or (
            previous
            and is_major_unrelated_section(previous + " " + line)
        ):
            end = index
            break
        previous = line
    return start, end


def scope_selected_site_coordinate_text(text):
    """Slice extracted text to the selected-site appendix block."""

    if not str(text or "").strip():
        return None
    lines = [
        line.strip()
        for line in str(text).splitlines()
        if line.strip()
    ]
    span = find_selected_site_section_span(lines)
    if span is None:
        return None
    start, end = span
    scoped = "\n".join(lines[start:end]).strip()
    if not scoped:
        return None
    return scoped


def extend_appendix_section_pages(
    start_page,
    page_count,
    page_text_lookup,
    before=APPENDIX_CONTINUATION_BEFORE,
    max_pages=APPENDIX_SECTION_MAX_PAGES,
):
    """Pages from the heading until the next unrelated major section."""

    if not isinstance(start_page, int) or start_page < 1:
        return []
    count = int(page_count or 0)
    start = max(1, start_page - int(before or 0))
    if count:
        start = min(start, count)
    pages = list(range(start, start_page + 1))
    limit = start_page + int(max_pages or 0)
    if count:
        limit = min(limit, count)
    for physical_page in range(start_page + 1, limit + 1):
        text = ""
        if page_text_lookup is not None:
            text = page_text_lookup(physical_page) or ""
        if page_starts_major_unrelated_section(text):
            break
        pages.append(physical_page)
    return pages


def locate_selected_site_heading_page(
    page_count,
    page_text_lookup,
    skip_pages=None,
):
    """Find the body heading, late pages first — not a full-table scan."""

    skip = set(skip_pages or [])
    count = int(page_count or 0)
    if count < 1:
        return []

    search_start = max(
        INDEX_WINDOW_PAGES + 1,
        count - APPENDIX_BODY_SEARCH_PAGES + 1,
    )
    for physical_page in range(count, search_start - 1, -1):
        if physical_page in skip:
            continue
        text = ""
        if page_text_lookup is not None:
            text = page_text_lookup(physical_page) or ""
        if page_has_selected_site_body_heading(text):
            return [physical_page]
    return []


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


def split_toc_appendix_line(line):
    normalized = normalize_tr(line)
    if not normalized:
        return None

    page_match = APPENDIX_PAGE_TAIL_RE.match(normalized)
    if page_match:
        title = page_match.group("title").strip(" .-:")
        page = page_match.group("page")
    else:
        title = normalized.strip(" .-:")
        page = ""

    if not is_coordinate_appendix_title(title):
        return None

    return {
        "table_no": EK1_APPENDIX_NUMBER,
        "table_title": title,
        "printed_page_raw": page,
        "raw_text": line.strip(),
    }


def extract_toc_appendix_entries(pages_data):
    """İÇİNDEKİLER lines for the selected-site coordinate appendix.

    TOC often starts on one early page and lists EK-1 on the next.
    Stay in-TOC across the index window until a leave heading.
    """

    entries = []
    in_toc = False
    pending = None

    for page in pages_data:
        physical_page = page.get("physical_page")
        lines = str(page.get("text") or "").splitlines()
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            if is_toc_heading(stripped):
                in_toc = True
                pending = None
                continue

            if not in_toc:
                continue

            normalized = normalize_tr(stripped)
            if TOC_LEAVE_RE.match(normalized):
                if pending is not None:
                    entries.append(pending)
                    pending = None
                in_toc = False
                continue

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

            parsed = split_toc_appendix_line(stripped)
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


def resolve_appendix_entry(entry, pages, skip_pages=None):
    skip = set(skip_pages or [])
    printed_raw, printed_first = parse_printed_page(
        entry.get("printed_page_raw", "")
    )
    body_pages = []

    for page in pages:
        physical_page = page["physical_page"]
        if physical_page in skip:
            continue
        if is_coordinate_appendix_body(page.get("text") or ""):
            body_pages.append(physical_page)

    physical_page = None
    resolve_kind = "UNRESOLVED"
    if body_pages:
        if printed_first is None:
            physical_page = body_pages[0]
        else:
            physical_page = min(
                body_pages,
                key=lambda page: abs(page - printed_first),
            )
        resolve_kind = "APPENDIX_BODY_RESOLVED"
    elif printed_first is not None:
        physical_page = printed_first
        resolve_kind = "APPENDIX_PRINTED_PAGE"

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


def peek_appendix_physical_page(
    document,
    printed_first,
    page_count,
    offset=0,
):
    if printed_first is None:
        return None

    guess = printed_first + int(offset or 0)
    start = max(1, guess - APPENDIX_PEEK_BEFORE)
    end = min(page_count, guess + APPENDIX_PEEK_AFTER)
    for physical_page in range(start, end + 1):
        try:
            text = document[physical_page - 1].get_text("text") or ""
        except Exception:
            text = ""
        if is_coordinate_appendix_body(text):
            return physical_page

    if 1 <= guess <= page_count:
        return guess
    return None


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


def expand_pages(
    page_numbers,
    page_count,
    before=CONTINUATION_BEFORE,
    after=CONTINUATION_AFTER,
):
    expanded = set()
    for page_number in page_numbers:
        if not isinstance(page_number, int) or page_number < 1:
            continue
        start = max(1, page_number - before)
        end = page_number + after
        if page_count:
            end = min(page_count, end)
        for candidate in range(start, end + 1):
            expanded.add(candidate)
    return sorted(expanded)


def planned_read_pages(page_count, max_pages, target_pages):
    """First max_pages plus index/appendix targets, including pages > 150."""

    pages = set()
    count = int(page_count or 0)
    limit = int(max_pages or 0)
    if count > 0 and limit > 0:
        pages.update(range(1, min(limit, count) + 1))
    for page_number in target_pages or []:
        if not isinstance(page_number, int) or page_number < 1:
            continue
        if count and page_number > count:
            continue
        pages.add(page_number)
    return sorted(pages)


class TableIndexLocator:
    @classmethod
    def plan(cls, pdf_path):
        empty = {
            "index_found": False,
            "index_pages": [],
            "geometry_entries": [],
            "appendix_entries": [],
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
            appendix_entries = extract_toc_appendix_entries(
                index_pages_data
            )
            toc_pages = sorted(
                {
                    entry.get("physical_index_page")
                    for entry in appendix_entries
                    if isinstance(entry.get("physical_index_page"), int)
                }
            )
            skip_pages = sorted(set(index_page_numbers) | set(toc_pages))

            body_pages = []
            if geometry_entries:
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

            resolved = []
            if geometry_entries:
                resolved = [
                    resolve_entry(
                        entry,
                        body_pages,
                        skip_pages=skip_pages,
                    )
                    for entry in geometry_entries
                ]
                resolved = apply_printed_page_offset(resolved)

            offsets = [
                entry["page_offset"]
                for entry in resolved
                if entry.get("page_offset") is not None
            ]
            median_offset = 0
            if offsets:
                offsets.sort()
                median_offset = offsets[len(offsets) // 2]

            resolved_appendix = []
            if appendix_entries and body_pages:
                resolved_appendix = [
                    resolve_appendix_entry(
                        entry,
                        body_pages,
                        skip_pages=skip_pages,
                    )
                    for entry in appendix_entries
                ]
                resolved_appendix = apply_printed_page_offset(
                    resolved_appendix
                )
            elif appendix_entries:
                for entry in appendix_entries:
                    printed_raw, printed_first = parse_printed_page(
                        entry.get("printed_page_raw", "")
                    )
                    physical_page = peek_appendix_physical_page(
                        document,
                        printed_first,
                        page_count,
                        offset=median_offset,
                    )
                    clone = dict(entry)
                    clone["printed_page"] = printed_raw
                    clone["printed_page_first"] = printed_first
                    clone["physical_page"] = physical_page
                    if (
                        physical_page is not None
                        and printed_first is not None
                    ):
                        clone["page_offset"] = (
                            physical_page - printed_first
                        )
                        clone["resolve_kind"] = (
                            "APPENDIX_BODY_RESOLVED"
                            if clone["page_offset"]
                            else "APPENDIX_PRINTED_PAGE"
                        )
                    else:
                        clone["page_offset"] = None
                        clone["resolve_kind"] = "UNRESOLVED"
                    resolved_appendix.append(clone)

            physical_pages = [
                entry["physical_page"]
                for entry in resolved
                if entry.get("physical_page") is not None
            ]
            appendix_pages = [
                entry["physical_page"]
                for entry in resolved_appendix
                if entry.get("physical_page") is not None
            ]
            page_text_cache = {
                page["physical_page"]: page.get("text") or ""
                for page in body_pages
            }

            def page_text_lookup(physical_page):
                if physical_page in page_text_cache:
                    return page_text_cache[physical_page]
                try:
                    text = document[physical_page - 1].get_text(
                        "text"
                    ) or ""
                except Exception:
                    text = ""
                page_text_cache[physical_page] = text
                return text

            if not appendix_pages:
                appendix_pages = locate_selected_site_heading_page(
                    page_count,
                    page_text_lookup,
                    skip_pages=skip_pages,
                )

            appendix_section_pages = []
            for start_page in appendix_pages:
                appendix_section_pages.extend(
                    extend_appendix_section_pages(
                        start_page,
                        page_count,
                        page_text_lookup,
                    )
                )

            target_pages = sorted(
                set(expand_pages(physical_pages, page_count))
                | set(appendix_section_pages)
            )
        finally:
            document.close()

        return {
            "index_found": bool(
                index_page_numbers
                or appendix_entries
                or appendix_section_pages
            ),
            "index_pages": index_page_numbers,
            "geometry_entries": resolved,
            "appendix_entries": resolved_appendix,
            "target_pages": target_pages,
            "page_count": page_count,
        }
