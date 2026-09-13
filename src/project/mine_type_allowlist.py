"""MAPEG-style maden cinsi vocabulary and post-filter.

Title/label extraction often scrapes nearby nouns (İŞLETME, RUHSAT,
MADEN). After extraction, keep only tokens that are real mineral /
commodity names. Do not invent a cinsi when nothing valid remains.

``TAŞ`` is rejected: in this ÇED corpus it is usually a leftover
(taş ocağı, doğal taş) rather than a MAPEG class. Named stones
(MERMER, TRAVERTEN, OLTU TAŞI, LÜLETAŞI, KİREÇTAŞI) stay allowlisted.

To add a mineral later, append one entry to ``MINE_TYPE_ENTRIES``.
Matching folds İ/I and Turkish diacritics; aliases are optional.
"""

from __future__ import annotations

import re
import unicodedata


UNKNOWN = "Bilinmiyor"

# (canonical display, *aliases that do not fold to the same key)
# Matching uses fold_mine_token, so ÇİNKO and CINKO need no extra alias.
MINE_TYPE_ENTRIES = (
    # IV. grup — metalik
    ("KROM", "KROMIT"),
    ("KALAY",),
    ("ÇİNKO",),
    ("KURŞUN",),
    ("DEMİR",),
    ("BAKIR",),
    ("ALTIN",),
    ("GÜMÜŞ",),
    ("NİKEL",),
    ("MANGANEZ",),
    ("MOLİBDEN",),
    ("VOLFRAM", "WOLFRAM", "TUNGSTEN"),
    ("ANTİMON",),
    ("CIVA",),
    ("KOBALT",),
    ("VANADYUM",),
    ("TİTANYUM",),
    ("ALÜMİNYUM",),
    ("BOKSİT", "BOKSIT"),
    ("KADMİYUM",),
    ("BİZMUT",),
    ("PLATİN",),
    ("MANYETİT",),
    ("HEMATİT",),
    ("PİRİT",),
    ("GALEN",),
    ("SFALERİT",),
    ("KALKOPİRİT",),
    # IV. grup — endüstriyel
    ("KUVARSİT",),
    ("KUVARS",),
    ("BARİT",),
    ("MANYEZİT", "MAGNEZIT", "MANEZIT"),
    ("PERLİT",),
    ("FELDİSPAT", "FELDSPAT"),
    ("BENTONİT",),
    ("KAOLİN", "KAOLEN"),
    ("TALK",),
    ("GRAFİT",),
    ("FLUORİT",),
    ("FOSFAT",),
    ("FOSFORİT",),
    ("TRONA",),
    ("BOR",),
    ("KOLEMANİT",),
    ("TİNKAL",),
    ("ÜLEKSİT",),
    ("ZEOLİT",),
    ("POMZA",),
    ("DİYATOMİT", "DIATOMIT"),
    ("SÖLESTİN",),
    ("SEPİYOLİT",),
    ("VERMİKÜLİT",),
    ("DOLOMİT",),
    ("MİKA",),
    ("OLİVİN",),
    ("WOLLASTONİT",),
    ("SİYANİT",),
    ("ANDALUZİT",),
    ("KORUND",),
    ("ZIMPARA",),
    ("KÜKÜRT",),
    ("KALSİT",),
    ("ALÇITAŞI", "JİPS", "JIPS"),
    ("SİLİS KUMU", "SILIS KUMU"),
    ("PİROFİLLİT",),
    ("HALLOYSİT",),
    ("ALÜNİT",),
    ("KRİYOLİT",),
    ("APATİT",),
    ("LİTYUM",),
    ("STRONSİYUM",),
    # III. grup
    ("TUZ",),
    ("KAYA TUZU",),
    ("SODYUM",),
    ("POTASYUM",),
    # IV. grup — enerji
    ("LİNYİT",),
    ("KÖMÜR",),
    ("TAŞKÖMÜRÜ", "TAS KOMURU"),
    ("ANTRASİT",),
    ("ASFALTİT",),
    ("BİTÜMLÜ ŞEYL",),
    ("ŞEYL",),
    ("TURBA",),
    ("URANYUM",),
    ("TORYUM",),
    # I–II. grup — yapı / doğal taş (named classes only; not bare TAŞ)
    ("KİL",),
    ("MERMER",),
    ("TRAVERTEN",),
    ("KALKER",),
    ("KİREÇTAŞI",),
    ("KİREÇ",),
    ("GRANİT",),
    ("ANDEZİT",),
    ("BAZALT",),
    ("TÜF",),
    ("DİYABAZ",),
    ("GABRO",),
    ("DİYORİT",),
    ("SERPANTİN",),
    ("ONİKS", "ONYX"),
    ("ARDUVAZ",),
    ("KUMTAŞI",),
    ("KUM",),
    ("ÇAKIL",),
    ("MARN",),
    ("TRAS",),
    ("RİYOLİT",),
    ("SİYENİT",),
    ("DUNİT",),
    ("OBSİDİYEN",),
    ("LÜLETAŞI",),
    ("OLTU TAŞI",),
    # V. grup — kıymetli taş ( sparingly; named gems only )
    ("ELMAS",),
    ("YAKUT",),
    ("ZÜMRÜT",),
    ("SAFİR",),
    ("OPAL",),
)

# Explicit non-commodities. Not required for rejection (absence from
# the allowlist is enough) but documents the Adana-class junk tokens.
REJECTED_MINE_TYPE_TOKENS = frozenset(
    {
        "MADEN",
        "MADENI",
        "MADENLER",
        "MADENCILIK",
        "ISLETME",
        "RUHSAT",
        "ACIK",
        "ATIK",
        "CEVHER",
        "CEVHERI",
        "CEVHERLER",
        "CEVHERLERI",
        "TAS",
        "COZELTI",
        "PROJE",
        "OCAK",
        "OCAGI",
        "ALAN",
        "SAHA",
        "HAMMADDE",
        "CINS",
        "CINSI",
        "KAPASITE",
        "FAALIYET",
        "GRUP",
        "NUMARALI",
        "YENI",
        "MEVCUT",
        "YERALTI",
        "AGREGA",
        "METAL",
    }
)

_PART_SPLIT = re.compile(
    r"\s*(?:/+|\||(?:\bVE\b)|&|\s+-\s+)\s*",
    flags=re.IGNORECASE,
)
_TOKEN_SPLIT = re.compile(r"[\s\-_,;:]+")
_JUNK_PREFIX = re.compile(
    r"\b(?:"
    r"NUMARALI|"
    r"RUHSAT|"
    r"S[Iİ]C[Iİ]L"
    r")\b",
    flags=re.IGNORECASE,
)
_DIGIT_RUN = re.compile(r"\d+")

_LOOKUP = {}
_MAX_PHRASE_LEN = 1


def fold_mine_token(value):
    """Uppercase and fold Turkish İ/I plus diacritics for matching."""

    text = unicodedata.normalize("NFKC", str(value or "")).upper()
    text = (
        text.replace("İ", "I")
        .replace("I\u0307", "I")
        .replace("Ş", "S")
        .replace("Ğ", "G")
        .replace("Ü", "U")
        .replace("Ö", "O")
        .replace("Ç", "C")
    )
    return text


def _register(canonical, *aliases):
    global _MAX_PHRASE_LEN
    for alias in (canonical,) + aliases:
        folded = fold_mine_token(alias)
        folded = re.sub(r"[\s\-_/]+", " ", folded).strip()
        if not folded:
            continue
        _LOOKUP[folded] = canonical
        compact = folded.replace(" ", "")
        _LOOKUP[compact] = canonical
        _MAX_PHRASE_LEN = max(
            _MAX_PHRASE_LEN,
            len(folded.split()),
        )


for _entry in MINE_TYPE_ENTRIES:
    _register(*_entry)


def allowlisted_canonical(token):
    """Return canonical cinsi or '' if the token is not a mineral."""

    folded = fold_mine_token(token)
    folded = re.sub(r"[\s\-_/]+", " ", folded).strip()
    if not folded:
        return ""
    if folded in REJECTED_MINE_TYPE_TOKENS:
        return ""
    compact = folded.replace(" ", "")
    if compact in REJECTED_MINE_TYPE_TOKENS:
        return ""
    return _LOOKUP.get(folded) or _LOOKUP.get(compact) or ""


def _extract_allowlisted(part):
    tokens = [
        token
        for token in _TOKEN_SPLIT.split(part)
        if token
    ]
    kept = []
    seen = set()
    index = 0
    while index < len(tokens):
        matched = ""
        consumed = 0
        max_len = min(_MAX_PHRASE_LEN, len(tokens) - index)
        for length in range(max_len, 0, -1):
            phrase = " ".join(tokens[index : index + length])
            canonical = allowlisted_canonical(phrase)
            if canonical:
                matched = canonical
                consumed = length
                break
        if matched:
            folded = fold_mine_token(matched)
            if folded not in seen:
                seen.add(folded)
                kept.append(matched)
            index += consumed
        else:
            index += 1
    return kept


def _joiner_for(raw, kept):
    if len(kept) <= 1:
        return ""
    if re.search(r"/", raw):
        return " / "
    if re.search(r"(?<!\s)-(?!\s)", raw):
        return "-"
    return " / "


def filter_mine_type(value, unknown=UNKNOWN):
    """Keep allowlisted minerals; return *unknown* if none remain.

    Slash-joined leftovers drop junk tokens (``KROM / İŞLETME`` →
    ``KROM``). Hyphen compounds stay hyphenated when both sides are
    valid (``KURŞUN-ÇİNKO``). Bare generic words become missing.
    """

    if value is None:
        return unknown

    raw = unicodedata.normalize("NFKC", str(value)).strip()
    if not raw or raw == unknown:
        return unknown

    cleaned = _JUNK_PREFIX.sub(" ", raw)
    cleaned = _DIGIT_RUN.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" \t\r\n:;,.-/|_")
    if not cleaned:
        return unknown

    parts = [
        part.strip()
        for part in _PART_SPLIT.split(cleaned)
        if part and part.strip()
    ]
    if not parts:
        parts = [cleaned]

    kept = []
    seen = set()
    for part in parts:
        for mineral in _extract_allowlisted(part):
            folded = fold_mine_token(mineral)
            if folded in seen:
                continue
            seen.add(folded)
            kept.append(mineral)

    if not kept:
        return unknown

    joiner = _joiner_for(raw, kept)
    if not joiner:
        return kept[0]
    return joiner.join(kept)


def is_missing_mine_type(value, unknown=UNKNOWN):
    return filter_mine_type(value, unknown=unknown) == unknown
