"""Canonical synthetic fixtures for ÇED layout difference classes.

Named PDFs are QA witnesses only. These texts encode layout classes,
not projects, provinces, or filenames.
"""

import math
import os
import tempfile
import unittest
from pathlib import Path

from src.coordinate.coordinate_engine import CoordinateEngine
from src.coordinate.layout_capabilities import (
    LAYOUT_CLASS_IDS,
    LAYOUT_CLASSES,
    layout_class,
)
from src.coordinate.pipeline import run_coordinate_pipeline
from src.coordinate.pipeline_contract import (
    CRS_INHERITED,
    DETECTED_TABLE_NO_POINTS,
    GROUP_BELOW_POLYGON_SIZE,
    KML_NO_WGS84,
    KML_RING_STILL_CROSSED,
    NO_COORDINATE_TABLE,
    POINTS_NO_POLYGON,
    collect_pipeline_diagnostics,
    inspect_kml_polygons,
    reason_codes,
)
from src.coordinate.polygon_builder import PolygonBuilder
from src.coordinate.project_model import ProjectModel
from src.coordinate.ring_geometry import (
    collapse_consecutive_duplicates,
    count_lonlat_crossings,
    inferred_ring_tolerance,
    repair_lonlat_rings,
    repair_self_intersecting_rings,
    _force_split_lonlat_pairs,
    _resolve_lonlat_leftover,
)
from src.coordinate.state_machine import (
    parse_coordinate_blocks,
    parse_localized_number,
)
from src.coordinate.table_detector import TableDetector
from src.export.kml_exporter import KMLExporter
from src.project.project_info_extractor import ProjectInfoExtractor
from tools.scan_kml_geometry import scan_kml_file


def page(page_number, *lines):
    return "\n".join(
        [
            f"--- Sayfa {page_number} [PDF METİN KATMANI] ---",
            *lines,
        ]
    )


CRS = (
    "Koordinat Sırası : Sağa Yukarı",
    "Datum : ED-50",
    "Türü : UTM",
    "Zon : 36",
)


def square_utm(start_y=434529, start_x=4205189, size=100):
    return (
        (start_y, start_x),
        (start_y + size, start_x),
        (start_y + size, start_x + size),
        (start_y, start_x + size),
    )


def stacked_utm_lines(labels, pairs):
    lines = []
    for label, (easting, northing) in zip(labels, pairs):
        lines.extend((label, str(easting), str(northing)))
    return tuple(lines)


def compact_star_pairs(vertex_count=95, step=8, radius=0.004):
    pairs = []
    for index in range(vertex_count):
        angle = (
            -math.pi / 2
            + index * step * 2 * math.pi / vertex_count
        )
        pairs.append(
            (
                32.10 + radius * math.cos(angle),
                37.20 + radius * math.sin(angle),
            )
        )
    return pairs


def compact_four_cross_pairs(vertex_count=95, radius=0.003):
    """Mostly-simple compact ellipse with four leftover-style bow-ties."""

    pairs = []
    for index in range(vertex_count):
        angle = 2 * math.pi * index / vertex_count
        pairs.append(
            (
                32.10 + radius * math.cos(angle),
                37.20 + 0.7 * radius * math.sin(angle),
            )
        )
    points = list(pairs)
    for twist in range(4):
        index = 6 + twist * (vertex_count // 4)
        points[index], points[index + 2] = (
            points[index + 2],
            points[index],
        )
    return points


def compact_leftover_multi_cross_pairs(vertex_count=95, radius=0.003):
    """Compact ring whose first force-split still has crossings on both parts.

    Destekci class: ~95 vertices, span ≪ 0.01°, a handful of leftover
    crossings after a first repair/split. Named PDFs are witnesses only.
    """

    pairs = []
    for index in range(vertex_count):
        angle = 2 * math.pi * index / vertex_count
        pairs.append(
            (
                32.10 + radius * math.cos(angle),
                37.20 + 0.7 * radius * math.sin(angle),
            )
        )
    points = list(pairs)
    for twist in range(4):
        index = 6 + twist * (vertex_count // 4)
        other = (index + 3) % vertex_count
        points[index], points[other] = points[other], points[index]
    return points


def parse_kml_coordinate_text(coordinate_text):
    pairs = []
    for line in coordinate_text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(",")
        pairs.append((float(parts[0]), float(parts[1])))
    closed = list(pairs)
    if (
        len(pairs) >= 2
        and pairs[0][0] == pairs[-1][0]
        and pairs[0][1] == pairs[-1][1]
    ):
        pairs = pairs[:-1]
    return pairs, closed


def transformed_kml_texts(pairs):
    """Production KML path prefers transformed lon/lat over table lon/lat."""

    polygon = {
        "points": [
            {
                "name": f"P{index}",
                "y": 434500 + index,
                "x": 4205100 + index,
                "transformed_longitude": longitude,
                "transformed_latitude": latitude,
            }
            for index, (longitude, latitude) in enumerate(pairs)
        ]
    }
    return KMLExporter._build_coordinate_texts(polygon)


def compact_mevcut_ced_polygon(pairs):
    return {
        "table_type": "MEVCUT_CED_ALANI",
        "polygon_group": "DEFAULT",
        "points": [
            {
                "name": f"P{index}",
                "y": 434500 + index,
                "x": 4205100 + index,
                "transformed_longitude": longitude,
                "transformed_latitude": latitude,
            }
            for index, (longitude, latitude) in enumerate(pairs)
        ],
    }


def export_and_scan_kml(pairs):
    """Destekci path: write KML XML, then scan LinearRing coordinate text."""

    model = ProjectModel(
        "witness.pdf",
        [],
        [compact_mevcut_ced_polygon(pairs)],
        [],
    )
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "compact.kml")
        KMLExporter.export(model, path)
        return scan_kml_file(path)


class LayoutCapabilityMapTests(unittest.TestCase):
    def test_seven_difference_classes_are_registered(self):
        self.assertEqual(
            LAYOUT_CLASS_IDS,
            (
                "table_continuation",
                "coordinate_record_layouts",
                "detector_parser_contract",
                "crs_inheritance",
                "ring_geometry",
                "grouping_typing",
                "metadata_kml_naming",
            ),
        )
        for item in LAYOUT_CLASSES:
            self.assertTrue(item["modules"])
            self.assertTrue(item["capabilities"])
            self.assertTrue(item["contract"])
            layout_class(item["id"])
        self.assertIn(
            "compact_degree_no_leftover_crossings",
            layout_class("ring_geometry")["capabilities"],
        )
        self.assertIn(
            "nolu_vertex_is_not_polygon_group",
            layout_class("grouping_typing")["capabilities"],
        )
        self.assertIn(
            "ed50_space_and_dilim_zone_aliases",
            layout_class("crs_inheritance")["capabilities"],
        )

    def test_extract_coordinates_still_returns_a_list(self):
        result = CoordinateEngine.extract_coordinates("prose without tables")
        self.assertIsInstance(result, list)
        self.assertEqual(result, [])


class TableContinuationClassTests(unittest.TestCase):
    def test_headerless_page_keeps_one_table_and_crs_scale_is_not_a_section(self):
        text = "\n".join(
            [
                page(
                    1,
                    "Tablo 1. Ruhsat Alanı Koordinatları",
                    *CRS,
                    "Ölçek Faktörü : 0.9996",
                    *stacked_utm_lines(
                        ("R1", "R2"),
                        square_utm()[:2],
                    ),
                ),
                page(
                    2,
                    "Nihai ÇED Raporu",
                    "Ölçek Faktörü",
                    "0.9996",
                    "37.99035977",
                    *stacked_utm_lines(
                        ("R3", "R4"),
                        square_utm()[2:],
                    ),
                ),
            ]
        )
        tables = TableDetector.find_tables(text)
        self.assertEqual(len(tables), 1, "continuation split into extra tables")
        pipeline = run_coordinate_pipeline(text, tables=tables)
        self.assertEqual(len(pipeline["coordinates"]), 4)
        self.assertEqual(len(pipeline["polygons"]), 1)
        self.assertNotIn(DETECTED_TABLE_NO_POINTS, pipeline["reason_codes"])


class CoordinateRecordLayoutClassTests(unittest.TestCase):
    def test_full_block_utm_only_column_major_and_thousands(self):
        full_block = parse_coordinate_blocks(
            "\n".join(
                [
                    "KOORDINAT TABLOSU",
                    "R.1",
                    "430000",
                    "4203425",
                    "37.97412423",
                    "38.20282746",
                ]
            )
        )
        self.assertEqual(len(full_block), 1)
        self.assertEqual(full_block[0]["latitude"], 37.97412423)

        utm_only = parse_coordinate_blocks(
            "\n".join(
                [
                    "KOORDINAT",
                    "Ruhsat Alanı Koordinatları",
                    "R1 434529 4205189",
                    "R2 434629 4205289",
                    "R3 434729 4205389",
                    "R4 434829 4205489",
                ]
            )
        )
        self.assertEqual(len(utm_only), 4)

        swapped = parse_coordinate_blocks(
            "\n".join(
                [
                    "KOORDINAT",
                    "Ruhsat Alanı Koordinatları",
                    "R1",
                    "4205189",
                    "434529",
                    "R2",
                    "4205289",
                    "434629",
                    "R3",
                    "4205389",
                    "434729",
                ]
            )
        )
        self.assertEqual(swapped[0]["utm_y"], 434529.0)
        self.assertEqual(swapped[0]["utm_x"], 4205189.0)

        unlabeled = parse_coordinate_blocks(
            "\n".join(
                [
                    "KOORDINAT",
                    "Ruhsat Alanı Koordinatları",
                    "374141.000:4492448.000",
                    "374350.000:4492322.000",
                    "374225.000:4492144.000",
                    "374030.000:4492278.000",
                ]
            )
        )
        self.assertEqual(len(unlabeled), 4)

        self.assertEqual(parse_localized_number("463 000"), 463000.0)
        self.assertEqual(parse_localized_number("4.205.189,00"), 4205189.0)

        text = page(
            1,
            "Tablo 2. Ruhsat Alanı Koordinatları",
            *CRS,
            "Nokta No",
            "R1",
            "R2",
            "R3",
            "R4",
            "Y",
            "434529",
            "434629",
            "434729",
            "434829",
            "X",
            "4205189",
            "4205289",
            "4205389",
            "4205489",
        )
        pipeline = run_coordinate_pipeline(text)
        self.assertEqual(len(pipeline["coordinates"]), 4)
        self.assertEqual(len(pipeline["polygons"]), 1)
        self.assertNotIn(DETECTED_TABLE_NO_POINTS, pipeline["reason_codes"])


class DetectorParserContractClassTests(unittest.TestCase):
    def test_accepted_table_without_parseable_points_is_not_silent(self):
        text = page(
            1,
            "Tablo 1. Ruhsat Alanı Koordinatları",
            "UTM Datum Zon",
            "Pafta açıklaması: 434529 nolu parse edilemeyen metin",
            "Diğer açıklama: 4205189 nolu parse edilemeyen metin",
            "Başka açıklama: 434629 nolu parse edilemeyen metin",
            "Son açıklama: 4205289 nolu parse edilemeyen metin",
        )
        tables = TableDetector.find_tables(text)
        self.assertGreater(len(tables), 0)
        pipeline = run_coordinate_pipeline(text, tables=tables)
        self.assertEqual(pipeline["coordinates"], [])
        self.assertIn(DETECTED_TABLE_NO_POINTS, pipeline["reason_codes"])
        self.assertTrue(
            any(
                item["code"] == DETECTED_TABLE_NO_POINTS
                and item["severity"] == "error"
                for item in pipeline["diagnostics"]
            )
        )

    def test_no_table_reports_structured_info(self):
        pipeline = run_coordinate_pipeline("Bu belgede koordinat tablosu yok.")
        self.assertEqual(pipeline["tables"], [])
        self.assertIn(NO_COORDINATE_TABLE, pipeline["reason_codes"])

    def test_unindexed_points_are_not_a_silent_table_miss(self):
        diagnostics = collect_pipeline_diagnostics(
            tables=["accepted-table"],
            coordinates=[{"name": "1", "y": 434529, "x": 4205189}],
            polygons=[{"table_type": "PROJE_ALANI", "points": [{}] * 4}],
        )
        self.assertNotIn(DETECTED_TABLE_NO_POINTS, reason_codes(diagnostics))


class CrsInheritanceClassTests(unittest.TestCase):
    def test_document_crs_transforms_table_without_local_zone(self):
        text = "\n".join(
            [
                page(
                    1,
                    "Koordinat Sistemi",
                    "Datum : ED-50",
                    "Türü : UTM",
                    "Zon : 36",
                    "6 Derece",
                ),
                page(
                    2,
                    "Tablo 2. Ruhsat Alanı Koordinatları",
                    *stacked_utm_lines(
                        ("N1", "N2", "N3", "N4"),
                        square_utm(463000, 4014000),
                    ),
                ),
            ]
        )
        pipeline = run_coordinate_pipeline(text)
        self.assertGreaterEqual(len(pipeline["coordinates"]), 4)
        self.assertTrue(
            any(
                point.get("transformed_longitude") is not None
                and point.get("transformed_latitude") is not None
                for point in pipeline["coordinates"]
            )
        )
        self.assertGreaterEqual(len(pipeline["polygons"]), 1)
        self.assertTrue(
            any(
                KMLExporter._build_coordinate_texts(polygon)
                for polygon in pipeline["polygons"]
            )
        )
        self.assertIn(CRS_INHERITED, pipeline["reason_codes"])
        self.assertNotIn(KML_NO_WGS84, pipeline["reason_codes"])

    def test_ed50_space_and_dilim_outside_table_still_export(self):
        text = "\n".join(
            [
                page(
                    1,
                    "Koordinat Sistemi",
                    "Datum : ED 50",
                    "Türü : UTM",
                    "Dilim : 36",
                    "6 Derece",
                ),
                page(
                    2,
                    "Tablo 2. Ruhsat Alanı Koordinatları",
                    *stacked_utm_lines(
                        ("N1", "N2", "N3", "N4"),
                        square_utm(463000, 4014000),
                    ),
                ),
            ]
        )
        pipeline = run_coordinate_pipeline(text)
        self.assertGreaterEqual(len(pipeline["coordinates"]), 4)
        self.assertGreaterEqual(len(pipeline["polygons"]), 1)
        self.assertTrue(
            any(
                KMLExporter._build_coordinate_texts(polygon)
                for polygon in pipeline["polygons"]
            )
        )
        self.assertNotIn(KML_NO_WGS84, pipeline["reason_codes"])


class RingGeometryClassTests(unittest.TestCase):
    def test_degree_scale_does_not_use_metre_collapse(self):
        points = []
        for index in range(8):
            points.append(
                {
                    "name": f"P{index}",
                    "y": 32.10 + index * 0.003,
                    "x": 37.20 + (index % 2) * 0.003,
                }
            )
        smashed = collapse_consecutive_duplicates(points, 0.01)
        self.assertLess(len(smashed), len(points))
        kept = collapse_consecutive_duplicates(points)
        self.assertEqual(len(kept), len(points))
        self.assertLess(inferred_ring_tolerance(points), 1e-6)

    def test_bowtie_and_lonlat_mismatch_are_repaired(self):
        bowtie = [
            {"name": "A", "y": 0, "x": 0},
            {"name": "B", "y": 10, "x": 10},
            {"name": "C", "y": 10, "x": 0},
            {"name": "D", "y": 0, "x": 10},
        ]
        rings = repair_self_intersecting_rings(bowtie)
        self.assertEqual(len(rings), 1)

        pairs = [
            (32.0, 37.0),
            (32.2, 37.2),
            (32.2, 37.0),
            (32.0, 37.2),
        ]
        self.assertGreater(count_lonlat_crossings(pairs), 0)
        repaired = repair_lonlat_rings(pairs)
        for ring in repaired:
            self.assertEqual(count_lonlat_crossings(ring), 0)

    def test_compact_degree_star_is_not_smashed(self):
        pairs = compact_star_pairs()
        self.assertGreaterEqual(count_lonlat_crossings(pairs), 4)
        rings = repair_lonlat_rings(pairs)
        self.assertGreaterEqual(len(rings), 1)
        for ring in rings:
            self.assertEqual(count_lonlat_crossings(ring), 0)
            self.assertGreaterEqual(len(ring), 3)

    def test_compact_degree_kml_text_has_zero_crossings(self):
        """Destekci scans exported KML text, not only in-memory rings.

        Production export prefers transformed lon/lat. A compact ~95-vertex
        ring with leftover-style crossings must not keep those crossings
        in the LinearRing coordinate text.
        """

        for pairs in (
            compact_star_pairs(),
            compact_four_cross_pairs(),
            compact_leftover_multi_cross_pairs(),
        ):
            span = max(lon for lon, _lat in pairs) - min(
                lon for lon, _lat in pairs
            )
            self.assertLess(span, 0.01)
            self.assertGreaterEqual(count_lonlat_crossings(pairs), 4)

            texts = transformed_kml_texts(pairs)
            self.assertGreaterEqual(len(texts), 1)
            for text in texts:
                open_pairs, closed_pairs = parse_kml_coordinate_text(text)
                self.assertGreaterEqual(len(open_pairs), 3)
                self.assertEqual(count_lonlat_crossings(open_pairs), 0)
                self.assertEqual(count_lonlat_crossings(closed_pairs), 0)

            scan = export_and_scan_kml(pairs)
            self.assertGreaterEqual(scan["ring_count"], 1)
            self.assertEqual(scan["empty_rings"], 0)
            self.assertEqual(scan["crossed_rings"], 0)
            for ring in scan["rings"]:
                self.assertEqual(ring["crossings"], 0)
                self.assertGreaterEqual(ring["vertex_count"], 3)

            diagnostics = inspect_kml_polygons(
                [compact_mevcut_ced_polygon(pairs)]
            )
            self.assertNotIn(
                KML_RING_STILL_CROSSED,
                reason_codes(diagnostics),
            )

    def test_leftover_drain_does_not_reexport_crossed_compact_ring(self):
        """Force-split remainders that still cross must be finished, not dropped.

        The old leftover drain queued still-crossing parts onto a throwaway
        list, then re-exported the original ~95-vertex ring.
        """

        pairs = compact_leftover_multi_cross_pairs()
        parts = _force_split_lonlat_pairs(pairs, 1e-12)
        self.assertIsNotNone(parts)
        self.assertTrue(
            all(count_lonlat_crossings(part) for part in parts)
        )

        repaired = []
        _resolve_lonlat_leftover(
            pairs,
            repaired,
            [],
            {tuple(pairs)},
            1e-12,
        )
        self.assertGreaterEqual(len(repaired), 1)
        for ring in repaired:
            self.assertEqual(count_lonlat_crossings(ring), 0)
            self.assertGreaterEqual(len(ring), 3)

        for ring in repair_lonlat_rings(pairs):
            self.assertEqual(count_lonlat_crossings(ring), 0)


class GroupingTypingClassTests(unittest.TestCase):
    def test_nolu_heading_and_ruhsat_survives_shared_geometry(self):
        text = page(
            1,
            "Tablo 1. ÇED Alanı Koordinatları",
            *CRS,
            "1 NOLU POLİGON (1.2 ha)",
            *stacked_utm_lines(("A1", "A2", "A3", "A4"), square_utm()),
            "2 NOLU POLİGON (0.8 ha)",
            *stacked_utm_lines(
                ("B1", "B2", "B3", "B4"),
                square_utm(434729, 4205389),
            ),
        )
        pipeline = run_coordinate_pipeline(text)
        self.assertGreaterEqual(len(pipeline["coordinates"]), 8)
        self.assertGreaterEqual(len(pipeline["polygons"]), 1)
        self.assertTrue(
            any("POLIGON" in str(point.get("polygon_group"))
                for point in pipeline["coordinates"])
        )

        shared = square_utm()
        coordinates = []
        for table_type, section, table_index in (
            ("CED_ALANI", "ÇED Alanı", 1),
            ("RUHSAT_ALANI", "Ruhsat Alanı", 2),
        ):
            for index, (y, x) in enumerate(shared):
                coordinates.append(
                    {
                        "name": f"P{index}",
                        "y": y,
                        "x": x,
                        "table_type": table_type,
                        "section": section,
                        "table_index": table_index,
                        "polygon_group": "DEFAULT",
                    }
                )
        polygons = PolygonBuilder.build(coordinates)
        types = {polygon["table_type"] for polygon in polygons}
        self.assertIn("CED_ALANI", types)
        self.assertIn("RUHSAT_ALANI", types)

    def test_nolu_nokta_vertices_are_one_ring_not_sub3_groups(self):
        """Diagnose can parse ~6 UTM points while export is poly=0 if
        each 'N NOLU NOKTA' line is treated as a polygon heading."""

        vertex_lines = []
        pairs = (
            (463000, 4014000),
            (463080, 4014000),
            (463160, 4014000),
            (463160, 4014080),
            (463080, 4014080),
            (463000, 4014080),
        )
        for index, (easting, northing) in enumerate(pairs, start=1):
            vertex_lines.extend(
                (
                    f"{index} NOLU NOKTA",
                    str(easting),
                    str(northing),
                )
            )
        text = page(
            1,
            "Tablo 1. Ruhsat Alanı Koordinatları",
            *CRS,
            *vertex_lines,
        )
        parsed = parse_coordinate_blocks(text)
        self.assertGreaterEqual(len(parsed), 6)
        self.assertFalse(
            any(
                str(point.get("polygon_group", "")).startswith("POLIGON_")
                and "NOKTA" in str(point.get("polygon_group", ""))
                for point in parsed
            )
        )
        pipeline = run_coordinate_pipeline(text)
        self.assertGreaterEqual(len(pipeline["coordinates"]), 6)
        self.assertGreaterEqual(
            len(pipeline["polygons"]),
            1,
            "parsed UTM points must become a polygon, not poly=0",
        )
        self.assertNotIn(POINTS_NO_POLYGON, pipeline["reason_codes"])
        self.assertTrue(
            any(
                KMLExporter._build_coordinate_texts(polygon)
                for polygon in pipeline["polygons"]
            )
        )

    def test_group_below_three_vertices_is_reported(self):
        coordinates = [
            {
                "name": "A1",
                "y": 434529,
                "x": 4205189,
                "table_type": "CED_ALANI",
                "section": "ÇED Alanı",
                "table_index": 1,
                "polygon_group": "POLIGON_1",
            },
            {
                "name": "A2",
                "y": 434629,
                "x": 4205189,
                "table_type": "CED_ALANI",
                "section": "ÇED Alanı",
                "table_index": 1,
                "polygon_group": "POLIGON_1",
            },
        ]
        polygons = PolygonBuilder.build(coordinates)
        self.assertEqual(polygons, [])
        diagnostics = collect_pipeline_diagnostics(
            tables=["accepted-table"],
            coordinates=coordinates,
            polygons=polygons,
        )
        self.assertIn(GROUP_BELOW_POLYGON_SIZE, reason_codes(diagnostics))


class MetadataKmlNamingClassTests(unittest.TestCase):
    def test_sicil_and_company_junk_are_general_extractor_rules(self):
        text = "\n".join(
            [
                "Nihai ÇED Raporu",
                "PROJE SAHİBİNİN ADI: Örnek Madencilik A.Ş.",
                "SICIL NO: 42077",
                "NUMARALI MANYEZİT MADEN OCAĞI",
            ]
        )
        info = ProjectInfoExtractor().extract(text)
        self.assertEqual(info["license_no"], "42077")
        self.assertEqual(info["ek_tip"], "Ek-1")
        self.assertIn("Örnek Madencilik", info["company"])
        self.assertFalse(info["company"].upper().startswith("PROJE"))
        name = ProjectInfoExtractor.build_project_export_name(info)
        self.assertTrue(name.startswith("42077"))
        self.assertIn("42077", name)
        self.assertNotIn("NUMARALI", name)
        self.assertNotIn("Nihai ÇED Raporu", name)
        relative = ProjectInfoExtractor.build_export_relative_path(
            {
                **info,
                "province": "Ankara",
            }
        )
        self.assertEqual(
            Path(relative).parts[-2],
            "Ek-1",
        )
        self.assertTrue(
            Path(relative).name.startswith("42077 - ")
        )
        self.assertTrue(relative.endswith(".kml"))


if __name__ == "__main__":
    unittest.main()
