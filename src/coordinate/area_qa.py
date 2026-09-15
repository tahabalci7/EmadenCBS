"""Table-declared area vs computed polygon area (export QA).

ÇED/PTD coordinate tables often state an area next to the heading
(``183.081 m² (18,30 ha)``, ``1916,11 ha``, ``1 No.lu ÇED (12,4 ha)``).
After PolygonBuilder computes projected/geodesic shoelace area, compare
the two. A large mismatch is the Destekci class where a merged, wrong-CRS,
or axis-swapped ring would otherwise be written as KML.

This module is also the **blocking pre-export gate**: KML is not written
when a compared ring diverges, CRS/lon is insane, or required layers are
missing. DIGER copies of a typed ring are omitted, not treated as success.

Tolerance (documented contract, previously tuned):

- Relative: 15% of the **declared** hectares.
- Absolute floor: 0.10 ha (1000 m²).

A ring matches when
``abs(computed - declared) <= max(0.15 * declared, 0.10)``.

15% covers rounding, shoelace vs geodesic, and a few metres of vertex
noise on hectare-scale ÇED/ruhsat rings. The 0.10 ha floor keeps tiny
tesisi/ünite/stok parcels (0.05–0.2 ha) from failing on a few hundred
square metres of CRS or vertex jitter. The ORT-style witness (18.3 ha
declared vs ~1509 ha computed) fails by two orders of magnitude.

When no declared area is associated with the ring, area comparison is a
no-op (CRS / layer checks still apply). POINT groups (Galeri pins) are
not area rings and are not compared.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.coordinate.state_machine import parse_localized_number


RELATIVE_TOLERANCE = 0.15
ABSOLUTE_FLOOR_HA = 0.10
SQUARE_METRES_PER_HECTARE = 10000.0

# Site layers without a justifying declared area. Wrong zone / axis swap
# produces million-hectare rings; ruhsat of a few thousand ha is real.
TYPICAL_LAYER_MAX_HA = 5000.0

TURKEY_LON_RANGE = (25.0, 45.5)
TURKEY_LAT_RANGE = (35.5, 42.5)
PROVINCE_LON_TOLERANCE = 2.5
PROVINCE_LAT_TOLERANCE = 1.8

# Approximate centroids (lon, lat). Used only to reject impossible
# project locations (Adana ~35–36° vs ~30° or ~41°).
PROVINCE_CENTROIDS = {
    "ADANA": (35.32, 37.00),
    "ADIYAMAN": (38.28, 37.76),
    "AFYON": (30.54, 38.76),
    "AFYONKARAHISAR": (30.54, 38.76),
    "ANKARA": (32.85, 39.93),
    "ANTALYA": (30.71, 36.90),
    "ARTVIN": (41.82, 41.18),
    "AYDIN": (27.84, 37.84),
    "BALIKESIR": (27.89, 39.65),
    "BILECIK": (29.98, 40.14),
    "BOLU": (31.61, 40.74),
    "BURDUR": (30.29, 37.72),
    "CANAKKALE": (26.41, 40.16),
    "CORUM": (34.95, 40.55),
    "DENIZLI": (29.09, 37.77),
    "DIYARBAKIR": (40.23, 37.91),
    "ELAZIG": (39.23, 38.67),
    "ERZINCAN": (39.49, 39.75),
    "ERZURUM": (41.27, 39.91),
    "ESKISEHIR": (30.52, 39.78),
    "GAZIANTEP": (37.38, 37.07),
    "GIRESUN": (38.39, 40.91),
    "GUMUSHANE": (39.48, 40.46),
    "HATAY": (36.16, 36.20),
    "ICEL": (34.64, 36.81),
    "KASTAMONU": (33.78, 41.38),
    "KAYSERI": (35.49, 38.73),
    "KIRKLARELI": (27.23, 41.74),
    "KOCAELI": (29.92, 40.77),
    "KONYA": (32.49, 37.87),
    "KUTAHYA": (29.98, 39.42),
    "MALATYA": (38.31, 38.35),
    "MANISA": (27.43, 38.61),
    "KAHRAMANMARAS": (36.94, 37.59),
    "MARAS": (36.94, 37.59),
    "MERSIN": (34.64, 36.81),
    "MUGLA": (28.37, 37.22),
    "NIGDE": (34.68, 37.97),
    "ORDU": (37.88, 40.98),
    "RIZE": (40.52, 41.02),
    "SAKARYA": (30.40, 40.76),
    "SAMSUN": (36.33, 41.29),
    "SIIRT": (41.95, 37.93),
    "SIVAS": (37.02, 39.75),
    "TRABZON": (39.72, 41.00),
    "TUNCELI": (39.54, 39.11),
    "VAN": (43.38, 38.50),
    "YOZGAT": (34.80, 39.82),
    "ZONGULDAK": (31.79, 41.46),
}

CED_LAYER_TYPES = frozenset(
    {
        "CED_ALANI",
        "MEVCUT_CED_ALANI",
        "YENI_CED_ALANI",
    }
)
RUHSAT_LAYER_TYPES = frozenset({"RUHSAT_ALANI"})
TYPED_EXPORT_TYPES = frozenset(
    {
        "RUHSAT_ALANI",
        "CED_ALANI",
        "MEVCUT_CED_ALANI",
        "YENI_CED_ALANI",
        "PROJE_ALANI",
        "ISLETME_IZIN_ALANI",
        "TESIS_ALANI",
        "DEPOLAMA_ALANI",
        "GALERI_ALANI",
        "SANTIYE_ALANI",
        "BITKISEL_TOPRAK_ALANI",
        "PASA_ALANI",
        "STOK_ALANI",
        "OCAK_ALANI",
        "KIRMA_ELEME_ALANI",
        "CEVHER_HAZIRLAMA_ALANI",
        "ATIK_ALANI",
        "HAVUZ_ALANI",
        "CALISILMAYACAK_ALAN",
    }
)

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
_COMBINED_RUHSAT_CED = re.compile(
    r"ruhsat.{0,64}(?:\bve\b|&|/|,).{0,24}(?:ced|proje\s+alan)"
    r"|(?:ced|proje\s+alan).{0,64}(?:\bve\b|&|/|,).{0,24}ruhsat",
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
        key = (
            point.get("table_index", 0),
            point.get("polygon_group", "DEFAULT"),
        )
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
    table_groups = {
        (point.get("table_index", 0), point.get("polygon_group", "DEFAULT"))
        for point in missing
    }
    if len(table_values) == 1 and len(table_groups) == 1:
        declared = table_values[0]
        for point in missing:
            point["declared_ha"] = declared

    return points


def compare_declared_vs_computed(
    declared_ha,
    computed_ha,
    *,
    relative_tolerance=None,
    absolute_floor_ha=None,
):
    """Return a comparison record. ``match`` is True when within tolerance."""

    try:
        declared = float(declared_ha)
        computed = float(computed_ha)
    except (TypeError, ValueError):
        return None

    if declared <= 0:
        return None

    relative = (
        RELATIVE_TOLERANCE
        if relative_tolerance is None
        else float(relative_tolerance)
    )
    floor = (
        ABSOLUTE_FLOOR_HA
        if absolute_floor_ha is None
        else float(absolute_floor_ha)
    )
    delta = abs(computed - declared)
    allowed = max(relative * declared, floor)
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
        comparison = None
    else:
        computed = polygon.get("area_ha")
        comparison = compare_declared_vs_computed(declared, computed)
        if comparison is not None:
            polygon["declared_ha"] = comparison["declared_ha"]
            polygon["computed_ha"] = comparison["computed_ha"]
            polygon["area_ratio"] = comparison["ratio"]
            polygon["area_mismatch"] = not comparison["match"]

    _apply_crs_sanity(polygon)
    return comparison


def export_should_skip_polygon(polygon):
    """True when a ring must not become a KML placemark."""

    return bool(
        polygon.get("area_mismatch")
        or polygon.get("crs_insane")
        or polygon.get("export_suppressed")
    )


def heading_is_combined_ruhsat_ced(*texts):
    """True when a caption explicitly names both Ruhsat and ÇED."""

    for text in texts:
        if not text:
            continue
        normalized = _normalize_tr(text)
        if _COMBINED_RUHSAT_CED.search(normalized):
            return True
    return False


def evaluate_export_gate(project_model):
    """Blocking pre-export checks. Never writes files.

    Fail-closed: any compared-area mismatch, insane CRS, missing
    Ruhsat/ÇED, or silent identical Ruhsat+ÇED copy blocks the write.
    """

    polygons = list(getattr(project_model, "polygons", None) or [])
    project_info = getattr(project_model, "project_info", None) or {}

    for polygon in polygons:
        apply_polygon_area_qa(polygon)

    _apply_identical_ring_rules(polygons)

    reasons = []
    for polygon in polygons:
        if polygon.get("geometry_type") == "POINT":
            continue
        if polygon.get("export_suppressed"):
            continue
        table_title = _polygon_title(polygon)
        table_type = polygon.get("table_type", "DIGER")
        if polygon.get("area_mismatch"):
            reasons.append(
                {
                    "code": "AREA_MISMATCH",
                    "table_title": table_title,
                    "table_type": table_type,
                    "declared_ha": polygon.get("declared_ha"),
                    "computed_ha": polygon.get(
                        "computed_ha",
                        polygon.get("area_ha"),
                    ),
                    "ratio": polygon.get("area_ratio"),
                }
            )
        if polygon.get("crs_insane"):
            reasons.append(
                {
                    "code": polygon.get("crs_insane_code")
                    or "CRS_AREA_INSANE",
                    "table_title": table_title,
                    "table_type": table_type,
                    "declared_ha": polygon.get("declared_ha"),
                    "computed_ha": polygon.get("area_ha"),
                    "ratio": polygon.get("area_ratio"),
                    "longitude": polygon.get("crs_check_longitude"),
                    "latitude": polygon.get("crs_check_latitude"),
                    "detail": polygon.get("crs_insane_detail"),
                }
            )

    reasons.extend(_layer_gate_reasons(polygons, project_info))
    reasons.extend(
        _province_lonlat_reasons(polygons, project_info)
    )

    codes = []
    seen = set()
    for reason in reasons:
        code = reason.get("code")
        if not code or code in seen:
            continue
        seen.add(code)
        codes.append(code)

    blocked = bool(reasons)
    if blocked and "EXPORT_BLOCKED" not in seen:
        codes.append("EXPORT_BLOCKED")

    exportable = [
        polygon
        for polygon in polygons
        if not export_should_skip_polygon(polygon)
    ]
    skipped = [
        polygon
        for polygon in polygons
        if export_should_skip_polygon(polygon)
    ]

    return {
        "ok": not blocked,
        "written": False,
        "path": None,
        "quarantine_path": None,
        "codes": codes,
        "reasons": reasons,
        "exportable_polygons": exportable,
        "skipped_polygons": skipped,
        "skipped_count": len(skipped),
    }


def write_quarantine_reason(file_path, gate, extra=None):
    """Write a structured fail reason under ``_Duzeltme``. Returns path."""

    target = Path(file_path)
    quarantine_dir = target.parent / "_Duzeltme"
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "ok": False,
        "intended_kml": str(target),
        "codes": list(gate.get("codes") or []),
        "reasons": list(gate.get("reasons") or []),
    }
    if extra:
        payload.update(extra)
    quarantine_path = quarantine_dir / f"{target.stem}.json"
    quarantine_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return str(quarantine_path)


def format_gate_message(gate):
    """Short Turkish summary for UI / batch logs."""

    if gate.get("ok"):
        return "KML dışa aktarma kapısı geçti."

    lines = ["KML yazılmadı (dışa aktarma kapısı)."]
    for reason in gate.get("reasons") or []:
        code = reason.get("code")
        title = reason.get("table_title") or reason.get("table_type") or ""
        if code == "AREA_MISMATCH":
            lines.append(
                f"- {title}: tablo {reason.get('declared_ha')} ha, "
                f"poligon {reason.get('computed_ha')} ha "
                f"(oran {reason.get('ratio')})."
            )
        elif code == "MISSING_RUHSAT_OR_CED":
            lines.append(
                "- Ruhsat Alanı ve en az bir ÇED katmanı zorunludur."
            )
        elif code == "DUPLICATE_LAYER_GEOMETRY":
            lines.append(
                "- Aynı halka Ruhsat ve ÇED olarak işaretli; başlık "
                "'Ruhsat ve ÇED' demedikçe kopya kabul edilmez."
            )
        elif code in {"CRS_AREA_INSANE", "CRS_LONLAT_OUT_OF_RANGE"}:
            detail = reason.get("detail") or ""
            lines.append(f"- {title}: {detail}".rstrip())
        else:
            detail = reason.get("detail") or code
            lines.append(f"- {detail}")
    return "\n".join(lines)


def _apply_crs_sanity(polygon):
    if polygon.get("geometry_type") == "POINT":
        return

    computed = _as_float(polygon.get("area_ha"))
    declared = _as_float(polygon.get("declared_ha"))
    if computed is not None and computed > TYPICAL_LAYER_MAX_HA:
        justified = (
            declared is not None
            and computed
            <= max(
                TYPICAL_LAYER_MAX_HA,
                declared * (1.0 + RELATIVE_TOLERANCE),
                declared + ABSOLUTE_FLOOR_HA,
            )
        )
        if not justified:
            polygon["crs_insane"] = True
            polygon["crs_insane_code"] = "CRS_AREA_INSANE"
            polygon["crs_insane_detail"] = (
                f"Computed area {round(computed, 4)} ha exceeds "
                f"{TYPICAL_LAYER_MAX_HA:.0f} ha without a matching "
                "declared table area (wrong CRS / axis)."
            )

    lon, lat = _polygon_lonlat(polygon)
    if lon is None or lat is None:
        return
    polygon["crs_check_longitude"] = lon
    polygon["crs_check_latitude"] = lat
    if not _in_range(lon, TURKEY_LON_RANGE) or not _in_range(
        lat,
        TURKEY_LAT_RANGE,
    ):
        polygon["crs_insane"] = True
        polygon["crs_insane_code"] = "CRS_LONLAT_OUT_OF_RANGE"
        polygon["crs_insane_detail"] = (
            f"Ring lon/lat ({lon:.4f}, {lat:.4f}) is outside Turkey."
        )


def _apply_identical_ring_rules(polygons):
    """Prefer typed rings over DIGER; flag silent Ruhsat=ÇED copies."""

    area_polygons = [
        polygon
        for polygon in polygons
        if polygon.get("geometry_type") != "POINT"
    ]
    from src.coordinate.polygon_builder import PolygonBuilder

    by_geometry = {}
    for polygon in area_polygons:
        key = PolygonBuilder._geometry_key(polygon.get("points") or [])
        if not key:
            continue
        by_geometry.setdefault(key, []).append(polygon)

    for group in by_geometry.values():
        if len(group) < 2:
            continue
        typed = [
            polygon
            for polygon in group
            if polygon.get("table_type", "DIGER") in TYPED_EXPORT_TYPES
        ]
        diger = [
            polygon
            for polygon in group
            if polygon.get("table_type", "DIGER") == "DIGER"
        ]
        if typed and diger:
            for polygon in diger:
                polygon["export_suppressed"] = True
                polygon["export_suppress_reason"] = "prefer_typed"

        ruhsat = [
            polygon
            for polygon in group
            if polygon.get("table_type") in RUHSAT_LAYER_TYPES
            and not polygon.get("export_suppressed")
        ]
        ced = [
            polygon
            for polygon in group
            if polygon.get("table_type") in CED_LAYER_TYPES
            and not polygon.get("export_suppressed")
        ]
        if ruhsat and ced:
            combined = any(
                heading_is_combined_ruhsat_ced(
                    polygon.get("polygon_heading"),
                    polygon.get("section"),
                    *[
                        point.get("polygon_heading")
                        for point in (polygon.get("points") or [])
                    ],
                )
                for polygon in ruhsat + ced
            )
            if not combined:
                for polygon in ruhsat + ced:
                    polygon["silent_layer_duplicate"] = True


def _layer_gate_reasons(polygons, project_info):
    area_polygons = [
        polygon
        for polygon in polygons
        if polygon.get("geometry_type") != "POINT"
        and not polygon.get("export_suppressed")
    ]
    has_ruhsat = any(
        polygon.get("table_type") in RUHSAT_LAYER_TYPES
        for polygon in area_polygons
    )
    has_ced = any(
        polygon.get("table_type") in CED_LAYER_TYPES
        for polygon in area_polygons
    )
    combined = any(
        heading_is_combined_ruhsat_ced(
            polygon.get("polygon_heading"),
            polygon.get("section"),
        )
        for polygon in area_polygons
    )
    if combined:
        has_ruhsat = True
        has_ced = True

    reasons = []
    if not has_ruhsat or not has_ced:
        reasons.append(
            {
                "code": "MISSING_RUHSAT_OR_CED",
                "table_title": "",
                "table_type": "",
                "detail": (
                    "Export requires Ruhsat Alanı and at least one "
                    "ÇED layer (CED_ALANI / MEVCUT_CED / YENI_CED)."
                ),
                "has_ruhsat": has_ruhsat,
                "has_ced": has_ced,
            }
        )

    if any(polygon.get("silent_layer_duplicate") for polygon in area_polygons):
        reasons.append(
            {
                "code": "DUPLICATE_LAYER_GEOMETRY",
                "table_title": "",
                "table_type": "",
                "detail": (
                    "Identical ring typed as both Ruhsat and ÇED "
                    "without an explicit combined heading."
                ),
            }
        )
    return reasons


def _province_lonlat_reasons(polygons, project_info):
    centroid = _province_centroid(project_info.get("province"))
    if centroid is None:
        return []

    center_lon, center_lat = centroid
    reasons = []
    for polygon in polygons:
        if polygon.get("geometry_type") == "POINT":
            continue
        if polygon.get("export_suppressed"):
            continue
        if polygon.get("crs_insane"):
            continue
        lon, lat = _polygon_lonlat(polygon)
        if lon is None or lat is None:
            continue
        if (
            abs(lon - center_lon) <= PROVINCE_LON_TOLERANCE
            and abs(lat - center_lat) <= PROVINCE_LAT_TOLERANCE
        ):
            continue
        if _in_range(lon, TURKEY_LON_RANGE) and abs(
            lon - center_lon
        ) <= PROVINCE_LON_TOLERANCE:
            continue
        polygon["crs_insane"] = True
        polygon["crs_insane_code"] = "CRS_LONLAT_OUT_OF_RANGE"
        polygon["crs_check_longitude"] = lon
        polygon["crs_check_latitude"] = lat
        detail = (
            f"Ring lon/lat ({lon:.4f}, {lat:.4f}) is not plausible "
            f"for province {project_info.get('province')} "
            f"(expected lon ~{center_lon:.1f}°)."
        )
        polygon["crs_insane_detail"] = detail
        reasons.append(
            {
                "code": "CRS_LONLAT_OUT_OF_RANGE",
                "table_title": _polygon_title(polygon),
                "table_type": polygon.get("table_type", "DIGER"),
                "longitude": lon,
                "latitude": lat,
                "detail": detail,
            }
        )
    return reasons


def _province_centroid(province):
    key = _normalize_tr(province).replace(" ", "")
    if not key or key == "BILINMIYOR":
        return None
    return PROVINCE_CENTROIDS.get(key)


def _polygon_lonlat(polygon):
    points = polygon.get("points") or []
    pairs = []
    for point in points:
        lon = point.get("transformed_longitude")
        lat = point.get("transformed_latitude")
        if lon in (None, "") or lat in (None, ""):
            lon = point.get("longitude")
            lat = point.get("latitude")
        lon = _as_float(lon)
        lat = _as_float(lat)
        if lon is None or lat is None:
            continue
        pairs.append((lon, lat))
    if not pairs:
        return None, None
    lon = sum(item[0] for item in pairs) / len(pairs)
    lat = sum(item[1] for item in pairs) / len(pairs)
    return lon, lat


def _polygon_title(polygon):
    heading = str(polygon.get("polygon_heading") or "").strip()
    if heading:
        return heading
    section = str(polygon.get("section") or "").strip()
    if section:
        return section
    return str(polygon.get("table_type") or "DIGER")


def _group_declared_ha(points):
    for point in points:
        existing = _as_float(point.get("declared_ha"))
        if existing is not None and existing > 0:
            return existing

    for field in ("polygon_heading", "section"):
        for point in points:
            value = parse_declared_area_ha(point.get(field))
            if value is not None:
                return value
    return None


def _polygon_declared_ha(polygon):
    existing = _as_float(polygon.get("declared_ha"))
    if existing is not None and existing > 0:
        return existing

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

    compact = text.replace(" ", "")
    if as_square_metres and _DOT_THOUSANDS.fullmatch(compact):
        try:
            return float(compact.replace(".", ""))
        except ValueError:
            return None

    try:
        return parse_localized_number(text)
    except (TypeError, ValueError):
        return None


def _as_float(value):
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _in_range(value, bounds):
    low, high = bounds
    return low <= value <= high


def _normalize_tr(text):
    return (
        str(text or "")
        .upper()
        .replace("İ", "I")
        .replace("İ", "I")
        .replace("Ş", "S")
        .replace("Ğ", "G")
        .replace("Ü", "U")
        .replace("Ö", "O")
        .replace("Ç", "C")
    )
