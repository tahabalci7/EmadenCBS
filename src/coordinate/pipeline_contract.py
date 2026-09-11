"""Structured pipeline diagnostics for coordinate extraction.

Reason codes are stable identifiers for GUI and batch. They describe
stage-contract misses (accepted table but no points, UTM without WGS84,
groups below polygon size). They are not per-PDF classifications.
"""

from collections import OrderedDict

from src.coordinate.layout_capabilities import LAYOUT_CLASS_IDS
from src.coordinate.ring_geometry import count_lonlat_crossings


NO_COORDINATE_TABLE = "NO_COORDINATE_TABLE"
DETECTED_TABLE_NO_POINTS = "DETECTED_TABLE_NO_POINTS"
POINTS_NO_POLYGON = "POINTS_NO_POLYGON"
GROUP_BELOW_POLYGON_SIZE = "GROUP_BELOW_POLYGON_SIZE"
CRS_INHERITED = "CRS_INHERITED"
CRS_UNRESOLVED_NO_TRANSFORM = "CRS_UNRESOLVED_NO_TRANSFORM"
KML_NO_WGS84 = "KML_NO_WGS84"
KML_RING_STILL_CROSSED = "KML_RING_STILL_CROSSED"

REASON_CODES = (
    NO_COORDINATE_TABLE,
    DETECTED_TABLE_NO_POINTS,
    POINTS_NO_POLYGON,
    GROUP_BELOW_POLYGON_SIZE,
    CRS_INHERITED,
    CRS_UNRESOLVED_NO_TRANSFORM,
    KML_NO_WGS84,
    KML_RING_STILL_CROSSED,
)


def make_diagnostic(
    code,
    *,
    severity,
    stage,
    class_id,
    **fields,
):
    if code not in REASON_CODES:
        raise ValueError(f"unknown reason code: {code}")
    if class_id not in LAYOUT_CLASS_IDS:
        raise ValueError(f"unknown layout class: {class_id}")

    record = {
        "code": code,
        "severity": severity,
        "stage": stage,
        "class_id": class_id,
    }
    for key, value in fields.items():
        if value is not None:
            record[key] = value
    return record


def reason_codes(diagnostics):
    codes = []
    seen = set()
    for item in diagnostics or []:
        code = item.get("code")
        if not code or code in seen:
            continue
        seen.add(code)
        codes.append(code)
    return codes


def merge_diagnostics(*groups):
    merged = []
    seen = set()
    for group in groups:
        for item in group or []:
            key = (
                item.get("code"),
                item.get("table_index"),
                item.get("polygon_group"),
                item.get("table_type"),
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
    return merged


def collect_pipeline_diagnostics(
    tables,
    coordinates,
    polygons,
    extra=None,
):
    """Post-hoc contract checks usable by GUI and batch.

    Does not change geometry. Empty accepted tables, UTM without WGS84,
    and dropped <3-vertex groups become reason codes.
    """

    diagnostics = list(extra or [])

    if not tables:
        if not any(
            item.get("code") == NO_COORDINATE_TABLE
            for item in diagnostics
        ):
            diagnostics.append(
                make_diagnostic(
                    NO_COORDINATE_TABLE,
                    severity="info",
                    stage="detector",
                    class_id="detector_parser_contract",
                    detail="No coordinate table was accepted.",
                )
            )
    else:
        pointed_tables = {
            item.get("table_index")
            for item in coordinates or []
            if item.get("table_index") is not None
        }
        already_reported = {
            item.get("table_index")
            for item in diagnostics
            if item.get("code") == DETECTED_TABLE_NO_POINTS
        }
        for table_index in range(1, len(tables) + 1):
            if table_index in pointed_tables:
                continue
            if table_index in already_reported:
                continue
            diagnostics.append(
                make_diagnostic(
                    DETECTED_TABLE_NO_POINTS,
                    severity="error",
                    stage="parser",
                    class_id="detector_parser_contract",
                    table_index=table_index,
                    detail=(
                        "TableDetector accepted a coordinate table; "
                        "parser emitted 0 points."
                    ),
                )
            )

    if coordinates and not polygons:
        diagnostics.append(
            make_diagnostic(
                POINTS_NO_POLYGON,
                severity="error",
                stage="polygon_builder",
                class_id="grouping_typing",
                point_count=len(coordinates),
                detail="Coordinates exist but PolygonBuilder emitted 0 polygons.",
            )
        )

    diagnostics.extend(
        _group_size_diagnostics(coordinates, polygons)
    )
    diagnostics.extend(
        _crs_export_diagnostics(coordinates, extra)
    )
    diagnostics.extend(
        inspect_kml_polygons(polygons or [])
    )
    return merge_diagnostics(diagnostics)


def inspect_kml_polygons(polygons):
    """KML export contract: UTM rings must become WGS84 or report a miss."""

    from src.export.kml_exporter import KMLExporter

    diagnostics = []
    for polygon in polygons or []:
        texts = KMLExporter._build_coordinate_texts(polygon)
        table_type = polygon.get("table_type", "DIGER")
        polygon_group = polygon.get("polygon_group", "DEFAULT")
        if not texts:
            points = polygon.get("points") or []
            has_utm = any(
                point.get("y") not in (None, "")
                and point.get("x") not in (None, "")
                for point in points
            )
            if has_utm:
                diagnostics.append(
                    make_diagnostic(
                        KML_NO_WGS84,
                        severity="error",
                        stage="kml_exporter",
                        class_id="crs_inheritance",
                        table_type=table_type,
                        polygon_group=polygon_group,
                        point_count=len(points),
                        detail=(
                            "Polygon has UTM vertices but KML received "
                            "no WGS84 coordinates."
                        ),
                    )
                )
            continue

        for text in texts:
            pairs = _kml_text_pairs(text)
            if count_lonlat_crossings(pairs):
                diagnostics.append(
                    make_diagnostic(
                        KML_RING_STILL_CROSSED,
                        severity="warning",
                        stage="kml_exporter",
                        class_id="ring_geometry",
                        table_type=table_type,
                        polygon_group=polygon_group,
                        detail="KML ring still self-intersects after repair.",
                    )
                )
    return diagnostics


def _kml_text_pairs(coordinate_text):
    pairs = []
    for line in str(coordinate_text).splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(",")
        if len(parts) < 2:
            continue
        pairs.append((float(parts[0]), float(parts[1])))
    if (
        len(pairs) >= 2
        and pairs[0][0] == pairs[-1][0]
        and pairs[0][1] == pairs[-1][1]
    ):
        pairs = pairs[:-1]
    return pairs


def _group_size_diagnostics(coordinates, polygons):
    if not coordinates:
        return []

    grouped = {}
    for item in coordinates:
        key = (
            item.get("table_type", "DIGER"),
            item.get("section", "Bilinmeyen Alan"),
            item.get("table_index", 0),
            item.get("polygon_group", "DEFAULT"),
        )
        grouped.setdefault(key, 0)
        grouped[key] += 1

    polygon_keys = {
        (
            polygon.get("table_type", "DIGER"),
            polygon.get("section", "Bilinmeyen Alan"),
            polygon.get("table_index", 0),
            polygon.get("polygon_group", "DEFAULT"),
        )
        for polygon in polygons or []
    }

    diagnostics = []
    for key, point_count in grouped.items():
        if point_count >= 3 or key in polygon_keys:
            continue
        table_type, _section, table_index, polygon_group = key
        diagnostics.append(
            make_diagnostic(
                GROUP_BELOW_POLYGON_SIZE,
                severity="warning",
                stage="polygon_builder",
                class_id="grouping_typing",
                table_index=table_index,
                table_type=table_type,
                polygon_group=polygon_group,
                point_count=point_count,
                detail=(
                    "Coordinate group has fewer than 3 vertices and "
                    "was not emitted as a polygon."
                ),
            )
        )
    return diagnostics


def _crs_export_diagnostics(coordinates, extra=None):
    diagnostics = []
    existing = {
        item.get("code")
        for item in extra or []
    }
    unresolved_utm = 0
    inherited = 0

    for point in coordinates or []:
        has_utm = (
            point.get("y") not in (None, "")
            and point.get("x") not in (None, "")
        )
        has_wgs84 = (
            point.get("transformed_longitude") not in (None, "")
            or point.get("longitude") not in (None, "")
        )
        zone = str(point.get("zone") or "").strip()
        zone_missing = zone in {"", "Bilinmiyor", "None"}
        if has_utm and has_wgs84 and zone_missing:
            inherited += 1
        elif has_utm and not has_wgs84:
            unresolved_utm += 1

    if inherited and not unresolved_utm and CRS_INHERITED not in existing:
        diagnostics.append(
            make_diagnostic(
                CRS_INHERITED,
                severity="info",
                stage="crs",
                class_id="crs_inheritance",
                point_count=inherited,
                detail=(
                    "WGS84 came from document-level or prior-table CRS "
                    "because table-local zone was missing."
                ),
            )
        )
    if unresolved_utm:
        diagnostics.append(
            make_diagnostic(
                CRS_UNRESOLVED_NO_TRANSFORM,
                severity="warning",
                stage="crs",
                class_id="crs_inheritance",
                point_count=unresolved_utm,
                detail=(
                    "UTM points exist but no table-local, prior-table, "
                    "or document CRS produced WGS84."
                ),
            )
        )
    return diagnostics


def format_diagnostics_text(diagnostics):
    if not diagnostics:
        return ""

    lines = [
        "Pipeline teşhisleri",
        "-------------------",
    ]
    for item in diagnostics:
        location = []
        if item.get("table_index") is not None:
            location.append(f"tablo {item['table_index']}")
        if item.get("polygon_group"):
            location.append(str(item["polygon_group"]))
        if item.get("table_type"):
            location.append(str(item["table_type"]))
        where = f" ({', '.join(location)})" if location else ""
        detail = item.get("detail") or ""
        lines.append(
            f"{item['code']}{where}: {detail}".rstrip()
        )
    return "\n".join(lines) + "\n"


def compact_diagnostics(diagnostics):
    compact = []
    for item in diagnostics or []:
        record = OrderedDict()
        for key in (
            "code",
            "severity",
            "stage",
            "class_id",
            "table_index",
            "table_type",
            "polygon_group",
            "point_count",
            "detail",
        ):
            if key in item:
                record[key] = item[key]
        compact.append(dict(record))
    return compact
