"""Table-declared area vs computed polygon area (export QA).

ÇED/PTD coordinate tables often state an area next to the heading
(``183.081 m² (18,30 ha)``, ``1916,11 ha``, ``1 No.lu ÇED (12,4 ha)``).
After PolygonBuilder computes geodesic/projected shoelace area, compare
the two. A large mismatch is the Destekci class where a merged or
wrong-CRS ring is exported as one huge ÇED.

Tolerance (documented contract):

- Relative: 15% of the **declared** hectares.
- Absolute floor: 0.10 ha (1000 m²).

A ring matches when
``abs(computed - declared) <= max(0.15 * declared, 0.10)``.

15% covers rounding, shoelace vs geodesic, and a few metres of vertex
noise on hectare-scale ÇED/ruhsat rings. The 0.10 ha floor keeps tiny
tesisi/ünite/stok parcels (0.05–0.2 ha) from failing on a few hundred
square metres of CRS or vertex jitter. The ORT witness (18.3 ha
declared vs ~1509 ha computed) fails by two orders of magnitude.

When no declared area is associated with the ring, QA is a no-op.
POINT groups (Galeri pins) are not area rings and are not compared.
"""

import re

from src.coordinate.state_machine import parse_localized_number


RELATIVE_TOLERANCE = 0.15
ABSOLUTE_FLOOR_HA = 0.10
SQUARE_METRES_PER_HECTARE = 10000.0

# Integer-looking thousands: 183.081 m² → 183081, not 183.081.
_DOT_THOUSANDS = re.compile(
    r"^[+-]?\d{1,3}(?:\.\d{3})+$"
)

_HA_UNIT = r"(?:ha|hektar(?:lar)?)"
_M2_UNIT = r"(?:m(?:2|²|\^2))"

_HA_VALUE = re.compile(
    r"([\d.\s]+(?:,\d+)?|\d+,\d+)\s*" + _HA_UNIT + r"\b",
    re.IGNORECASE,
)
_M2_VALUE = re.compile(
    r"([\d.\s]+(?:,\d+)?|\d+,\d+)\s*" + _M2_UNIT + r"\b",
    re.IGNORECASE,
)
_TOTAL_HINT = re.compile(
    r"\btoplam\b",
    re.IGNORECASE,
)


def parse_declared_area_ha(text):
    """Return hectares declared in a heading/caption, or None.

    Prefers an explicit ha / hektar figure when both m² and ha appear
    (``183.081 m² (18,30 ha)`` → 18.30). Standalone m² is converted.
    ``TOPLAM ALAN`` lines are ignored so a file-level sum is not
    attached to every ring.
    """

    if text is None:
        return None

    raw = str(text).strip()
    if not raw:
        return None

    if _TOTAL_HINT.search(raw):
        return None

    hectares = _first_unit_value(raw, _HA_VALUE, as_square_metres=False)
    if hectares is not None and hectares > 0:
        return hectares

    square_metres = _first_unit_value(
        raw,
        _M2_VALUE,
        as_square_metres=True,
    )
    if square_metres is not None and square_metres > 0:
        return square_metres / SQUARE_METRES_PER_HECTARE

    return None


def extract_declared_areas(text):
    """Collect non-total ha declarations from a table slice."""

    found = []
    seen = set()
    for line in str(text or "").splitlines():
        value = parse_declared_area_ha(line)
        if value is None:
            continue
        key = round(value, 4)
        if key in seen:
            continue
        seen.add(key)
        found.append(value)
    return found


def attach_declared_area(points, table_text=None):
    """Copy heading/table declared ha onto points that lack one."""

    if not points:
        return points

    groups = {}
    for point in points:
        key = point.get("polygon_group", "DEFAULT")
        groups.setdefault(key, []).append(point)

    for group_points in groups.values():
        declared = _group_declared_ha(group_points)
        if declared is None:
            continue
        for point in group_points:
            if point.get("declared_ha") in (None, ""):
                point["declared_ha"] = declared

    missing = [
        point
        for point in points
        if point.get("declared_ha") in (None, "")
    ]
    if not missing:
        return points

    table_values = extract_declared_areas(table_text)
    if len(table_values) == 1 and len(groups) == 1:
        declared = table_values[0]
        for point in missing:
            point["declared_ha"] = declared

    return points


def compare_declared_vs_computed(declared_ha, computed_ha):
    """Return a comparison record. ``match`` is True when within tolerance."""

    try:
        declared = float(declared_ha)
        computed = float(computed_ha)
    except (TypeError, ValueError):
        return None

    if declared <= 0:
        return None

    delta = abs(computed - declared)
    allowed = max(RELATIVE_TOLERANCE * declared, ABSOLUTE_FLOOR_HA)
    ratio = computed / declared if declared else None
    return {
        "declared_ha": round(declared, 4),
        "computed_ha": round(computed, 4),
        "ratio": None if ratio is None else round(ratio, 4),
        "delta_ha": round(delta, 4),
        "allowed_ha": round(allowed, 4),
        "match": delta <= allowed,
    }


def apply_polygon_area_qa(polygon):
    """Annotate one built polygon. Returns the comparison or None."""

    if polygon.get("geometry_type") == "POINT":
        return None

    declared = polygon.get("declared_ha")
    if declared in (None, ""):
        declared = _polygon_declared_ha(polygon)
        if declared is not None:
            polygon["declared_ha"] = declared

    if declared in (None, ""):
        return None

    computed = polygon.get("area_ha")
    comparison = compare_declared_vs_computed(declared, computed)
    if comparison is None:
        return None

    polygon["declared_ha"] = comparison["declared_ha"]
    polygon["computed_ha"] = comparison["computed_ha"]
    polygon["area_ratio"] = comparison["ratio"]
    polygon["area_mismatch"] = not comparison["match"]
    return comparison


def export_should_skip_polygon(polygon):
    """True when a mismatch must not become a KML placemark."""

    return bool(polygon.get("area_mismatch"))


def _group_declared_ha(points):
    for point in points:
        existing = point.get("declared_ha")
        if existing not in (None, ""):
            try:
                value = float(existing)
            except (TypeError, ValueError):
                value = None
            if value is not None and value > 0:
                return value

    for field in ("polygon_heading", "section"):
        for point in points:
            value = parse_declared_area_ha(point.get(field))
            if value is not None:
                return value
    return None


def _polygon_declared_ha(polygon):
    existing = polygon.get("declared_ha")
    if existing not in (None, ""):
        try:
            value = float(existing)
        except (TypeError, ValueError):
            value = None
        if value is not None and value > 0:
            return value

    for field in ("polygon_heading", "section"):
        value = parse_declared_area_ha(polygon.get(field))
        if value is not None:
            return value

    return _group_declared_ha(polygon.get("points") or [])


def _first_unit_value(text, pattern, *, as_square_metres):
    match = pattern.search(text)
    if match is None:
        return None
    return _parse_area_number(
        match.group(1),
        as_square_metres=as_square_metres,
    )


def _parse_area_number(token, *, as_square_metres):
    text = str(token).strip()
    if not text:
        return None

    if as_square_metres and _DOT_THOUSANDS.fullmatch(text.replace(" ", "")):
        compact = text.replace(" ", "").replace(".", "")
        try:
            return float(compact)
        except ValueError:
            return None

    try:
        return parse_localized_number(text)
    except (TypeError, ValueError):
        return None
