"""Canonical synthetic fixtures for ÇED layout difference classes.

Named PDFs are QA witnesses only. These texts encode layout classes,
not projects, provinces, or filenames.
"""

import math
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from src.coordinate.coordinate_engine import CoordinateEngine
from src.coordinate.crs_resolver import CRSResolver
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
    detect_area_type,
    parse_coordinate_blocks,
    parse_localized_number,
)
from src.coordinate.table_classifier import TableClassifier
from src.coordinate.table_detector import TableDetector
from src.coordinate.table_index import (
    expand_pages,
    extract_toc_appendix_entries,
    is_coordinate_appendix_title,
    parse_printed_page,
    planned_read_pages,
)
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
    def test_eight_difference_classes_are_registered(self):
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
                "coordinate_appendix_index",
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
        self.assertIn(
            "late_caption_not_previous_continuation",
            layout_class("table_continuation")["capabilities"],
        )
        self.assertIn(
            "auxiliary_not_inherit_dominant_ring",
            layout_class("grouping_typing")["capabilities"],
        )
        self.assertIn(
            "parenthetical_ced_is_not_tesisi_type",
            layout_class("grouping_typing")["capabilities"],
        )
        self.assertIn(
            "geo_ring_not_inherit_auxiliary",
            layout_class("grouping_typing")["capabilities"],
        )
        self.assertIn(
            "unattested_lattice_not_composite_ring",
            layout_class("grouping_typing")["capabilities"],
        )
        self.assertIn(
            "geographic_only_unlabeled_ring",
            layout_class("coordinate_record_layouts")["capabilities"],
        )
        self.assertIn(
            "dual_crs_yx_then_split_lat_lon",
            layout_class("coordinate_record_layouts")["capabilities"],
        )
        self.assertIn(
            "dual_crs_colon_yx_lat_lon",
            layout_class("coordinate_record_layouts")["capabilities"],
        )
        self.assertIn(
            "entrance_point_table_not_area_polygon",
            layout_class("grouping_typing")["capabilities"],
        )
        self.assertIn(
            "sicil_nolu_alan_is_ruhsat",
            layout_class("grouping_typing")["capabilities"],
        )
        self.assertIn(
            "toc_ek1_appendix_to_target_pages",
            layout_class("coordinate_appendix_index")["capabilities"],
        )
        self.assertIn(
            "appendix_pages_beyond_fast_scan",
            layout_class("coordinate_appendix_index")["capabilities"],
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

    def _stok_ced_scale_rings(self):
        """Witness class: ~0.23 ha STOK vs ~100 ha ÇED (UTM metres)."""

        stok_pairs = square_utm(434500, 4205100, 48)
        extra_stok = (
            (434512, 4205100),
            (434524, 4205100),
            (434536, 4205100),
            (434548, 4205100),
        )
        stok_pairs = (stok_pairs[0],) + extra_stok + stok_pairs[1:]
        ced_pairs = square_utm(430000, 4200000, 1000)
        extra_ced = tuple(
            (430000 + step * 80, 4200000)
            for step in range(1, 13)
        )
        ced_pairs = (ced_pairs[0],) + extra_ced + ced_pairs[1:]
        leftover_pairs = square_utm(434520, 4205120, 50)
        leftover_pairs = leftover_pairs + (
            (434545, 4205120),
        )
        return stok_pairs, ced_pairs, leftover_pairs

    def test_late_caption_ced_body_is_not_stok_continuation(self):
        """Headerless ÇED rows before Tablo N. Yeni ÇED are that table.

        Destekci class: attaching those rows to the open STOK table yields
        STOK ≫ ÇED (witness ~99 ha STOK vs ~0.23 ha Yeni ÇED). Tables say
        the large ring is ÇED (~1 km, ~100 ha) and STOK is the small
        stockpile (~50 m, ~0.23 ha).
        """

        stok_pairs, ced_pairs, leftover_pairs = self._stok_ced_scale_rings()
        text = "\n".join(
            [
                page(
                    1,
                    "Tablo 4. Stok Alanı Koordinatları",
                    *CRS,
                    *stacked_utm_lines(
                        tuple(f"S{i}" for i in range(1, 9)),
                        stok_pairs,
                    ),
                ),
                page(
                    2,
                    *CRS,
                    *stacked_utm_lines(
                        tuple(f"C{i}" for i in range(1, 17)),
                        ced_pairs,
                    ),
                    "Tablo 5. Yeni ÇED Alanı Koordinatları",
                    *CRS,
                    *stacked_utm_lines(
                        tuple(f"Y{i}" for i in range(1, 6)),
                        leftover_pairs,
                    ),
                ),
            ]
        )
        pipeline = run_coordinate_pipeline(text)
        polygons = pipeline["polygons"]
        stok_areas = [
            polygon["area_ha"]
            for polygon in polygons
            if polygon["table_type"] == "STOK_ALANI"
        ]
        ced_areas = [
            polygon["area_ha"]
            for polygon in polygons
            if polygon["table_type"]
            in {"CED_ALANI", "YENI_CED_ALANI", "MEVCUT_CED_ALANI"}
        ]
        self.assertTrue(stok_areas, "STOK ring missing")
        self.assertTrue(ced_areas, "ÇED ring missing")
        self.assertLess(max(stok_areas), 2.0)
        self.assertGreater(max(ced_areas), 50.0)
        self.assertLess(max(stok_areas) * 10, max(ced_areas))
        stok_labels = {
            point["name"]
            for point in pipeline["coordinates"]
            if point["table_type"] == "STOK_ALANI"
        }
        self.assertTrue(stok_labels)
        self.assertFalse(
            any(label.startswith("C") for label in stok_labels)
        )

    def test_same_page_ced_body_before_caption_is_not_stok(self):
        """Witness reading order: STOK caption, small ring, large ring,
        then Tablo N. Yeni ÇED, then a leftover fragment.

        PR #10 only detached this across a page break. Destekci reexport
        on a65dbfe still had STOK 99.4 ha / 15 pts and Yeni ÇED 0.23 ha.
        """

        stok_pairs, ced_pairs, leftover_pairs = self._stok_ced_scale_rings()
        # Witness leftover is 4 verts; keep the large ring at 15.
        leftover_pairs = leftover_pairs[:4]
        text = page(
            1,
            "Tablo 4. Stok Alanı Koordinatları",
            *CRS,
            *stacked_utm_lines(
                tuple(f"S{i}" for i in range(1, 9)),
                stok_pairs,
            ),
            *stacked_utm_lines(
                tuple(f"C{i}" for i in range(1, 17)),
                ced_pairs,
            ),
            "Tablo 5. Yeni ÇED Alanı Koordinatları",
            *CRS,
            *stacked_utm_lines(
                tuple(f"Y{i}" for i in range(1, 5)),
                leftover_pairs,
            ),
        )
        self._assert_stok_ced_not_inverted(text)

    def test_same_page_numeric_restart_before_yeni_ced_caption(self):
        stok_pairs, ced_pairs, leftover_pairs = self._stok_ced_scale_rings()
        leftover_pairs = leftover_pairs[:4]
        text = page(
            1,
            "Tablo 4. Stok Alanı Koordinatları",
            *CRS,
            *stacked_utm_lines(
                tuple(f"N{i}" for i in range(1, 9)),
                stok_pairs,
            ),
            *stacked_utm_lines(
                tuple(f"N{i}" for i in range(1, 17)),
                ced_pairs,
            ),
            "Tablo 5. Yeni ÇED Alanı Koordinatları",
            *CRS,
            *stacked_utm_lines(
                tuple(f"Y{i}" for i in range(1, 5)),
                leftover_pairs,
            ),
        )
        self._assert_stok_ced_not_inverted(text)

    def test_same_page_unnumbered_ced_heading_after_large_ring(self):
        stok_pairs, ced_pairs, leftover_pairs = self._stok_ced_scale_rings()
        leftover_pairs = leftover_pairs[:4]
        text = page(
            1,
            "Tablo 4. Stok Alanı Koordinatları",
            *CRS,
            *stacked_utm_lines(
                tuple(f"S{i}" for i in range(1, 9)),
                stok_pairs,
            ),
            *stacked_utm_lines(
                tuple(f"C{i}" for i in range(1, 17)),
                ced_pairs,
            ),
            "Yeni ÇED Alanı Koordinatları",
            *CRS,
            *stacked_utm_lines(
                tuple(f"Y{i}" for i in range(1, 5)),
                leftover_pairs,
            ),
        )
        self._assert_stok_ced_not_inverted(text)

    def _assert_stok_ced_not_inverted(self, text):
        pipeline = run_coordinate_pipeline(text)
        polygons = pipeline["polygons"]
        stok_areas = [
            polygon["area_ha"]
            for polygon in polygons
            if polygon["table_type"] == "STOK_ALANI"
        ]
        ced_areas = [
            polygon["area_ha"]
            for polygon in polygons
            if polygon["table_type"]
            in {"CED_ALANI", "YENI_CED_ALANI", "MEVCUT_CED_ALANI"}
        ]
        self.assertTrue(stok_areas, "STOK ring missing")
        self.assertTrue(ced_areas, "ÇED ring missing")
        self.assertLess(max(stok_areas), 2.0)
        self.assertGreater(max(ced_areas), 50.0)
        self.assertLess(max(stok_areas) * 10, max(ced_areas))
        stok_labels = {
            point["name"]
            for point in pipeline["coordinates"]
            if point["table_type"] == "STOK_ALANI"
            and not str(point["name"]).isdigit()
        }
        self.assertFalse(
            any(label.startswith("C") for label in stok_labels)
        )

    def test_split_yeni_ced_heading_is_not_swallowed_by_stok(self):
        stok_pairs, ced_pairs, _leftover = self._stok_ced_scale_rings()
        text = "\n".join(
            [
                page(
                    1,
                    "Tablo 4. Stok Alanı Koordinatları",
                    *CRS,
                    *stacked_utm_lines(
                        tuple(f"S{i}" for i in range(1, 9)),
                        stok_pairs,
                    ),
                ),
                page(
                    2,
                    "Yeni ÇED",
                    "Alanı",
                    "Koordinatları",
                    *CRS,
                    *stacked_utm_lines(
                        tuple(f"C{i}" for i in range(1, 17)),
                        ced_pairs,
                    ),
                ),
            ]
        )
        pipeline = run_coordinate_pipeline(text)
        types = {
            point["table_type"]
            for point in pipeline["coordinates"]
            if str(point["name"]).startswith("C")
        }
        self.assertTrue(
            types & {"CED_ALANI", "YENI_CED_ALANI"}
        )
        ced_areas = [
            polygon["area_ha"]
            for polygon in pipeline["polygons"]
            if polygon["table_type"]
            in {"CED_ALANI", "YENI_CED_ALANI", "MEVCUT_CED_ALANI"}
        ]
        stok_areas = [
            polygon["area_ha"]
            for polygon in pipeline["polygons"]
            if polygon["table_type"] == "STOK_ALANI"
        ]
        self.assertGreater(max(ced_areas), 50.0)
        self.assertLess(max(stok_areas or [0]), 2.0)

    def test_leftover_same_series_before_new_table_still_continues(self):
        text = "\n".join(
            [
                page(
                    1,
                    "Tablo 1. Proje Alanı Koordinatları",
                    *CRS,
                    *stacked_utm_lines(
                        ("P1", "P2"),
                        square_utm()[:2],
                    ),
                ),
                page(
                    2,
                    *CRS,
                    *stacked_utm_lines(
                        ("P3", "P4"),
                        square_utm()[2:],
                    ),
                    "Tablo 2. Stok Alanı Koordinatları",
                    *CRS,
                    *stacked_utm_lines(
                        ("S1", "S2", "S3", "S4"),
                        square_utm(434800, 4205400, 40),
                    ),
                ),
            ]
        )
        pipeline = run_coordinate_pipeline(text)
        p_types = {
            point["table_type"]
            for point in pipeline["coordinates"]
            if point["name"].startswith("P")
        }
        self.assertEqual(p_types, {"PROJE_ALANI"})
        s_types = {
            point["table_type"]
            for point in pipeline["coordinates"]
            if point["name"].startswith("S")
        }
        self.assertEqual(s_types, {"STOK_ALANI"})


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

    def _dual_crs_fragmented_rows(self, labels, utm_pairs, geo_pairs):
        """Index; space-separated Y/X; ENLEM; BOYLAM — dual-CRS dump."""

        lines = []
        for label, (easting, northing), (latitude, longitude) in zip(
            labels,
            utm_pairs,
            geo_pairs,
        ):
            lines.extend(
                (
                    str(label),
                    f"{easting:.3f} {northing:.3f}",
                    f"{latitude:.7f}",
                    f"{longitude:.7f}",
                )
            )
        return tuple(lines)

    def test_dual_crs_side_by_side_yx_then_split_lat_lon(self):
        """Side-by-side UTM + geographic headers; Y/X share a line.

        Destekci class: TableDetector accepts the tables but the parser
        dropped rows when SAĞA (Y) YUKARI (X) were space-separated and
        ENLEM / BOYLAM each followed on their own lines. Witnesses are
        named PDFs only — this fixture is the layout class.
        """

        ruhsat_utm = square_utm(675382, 4144399, 212)
        ruhsat_geo = (
            (37.4282393, 34.9817757),
            (37.4269372, 34.9793456),
            (37.4252000, 34.9790000),
            (37.4265000, 34.9820000),
        )
        ced_utm = square_utm(675000, 4144000, 400)
        ced_geo = (
            (37.4248000, 34.9780000),
            (37.4241000, 34.9735000),
            (37.4208000, 34.9742000),
            (37.4215000, 34.9788000),
        )
        stok_utm = square_utm(675200, 4144200, 48)
        stok_geo = (
            (37.4262000, 34.9800000),
            (37.4259000, 34.9795000),
            (37.4255000, 34.9798000),
            (37.4258000, 34.9803000),
        )
        text = "\n".join(
            [
                page(
                    35,
                    "Tablo 9. 1 Nolu Ruhsat Poligonu (P1) Koordinatları",
                    "UTM KOORDİNATLAR          COĞRAFİK KOORDİNATLAR",
                    "DATUM: ED-50              DATUM: WGS-84",
                    "ZON: 36",
                    "Sıra No SAĞA (Y) YUKARI (X)   ENLEM   BOYLAM",
                    *self._dual_crs_fragmented_rows(
                        ("1", "2", "3", "4"),
                        ruhsat_utm,
                        ruhsat_geo,
                    ),
                    "Toplam Alan: 262,57 ha",
                    "Tablo 10. ÇED Alanı Poligonu (Ç1) Koordinatları",
                    "UTM KOORDİNATLAR          COĞRAFİK KOORDİNATLAR",
                    "DATUM: ED-50              DATUM: WGS-84",
                    "Sıra No SAĞA (Y) YUKARI (X)   ENLEM   BOYLAM",
                    *self._dual_crs_fragmented_rows(
                        ("1", "2", "3", "4"),
                        ced_utm,
                        ced_geo,
                    ),
                    "Toplam Alan: 16,00 ha",
                ),
                page(
                    36,
                    "Tablo 11. Stok Alanı Koordinatları",
                    "UTM KOORDİNATLAR          COĞRAFİK KOORDİNATLAR",
                    "DATUM: ED-50              DATUM: WGS-84",
                    "Sıra No SAĞA (Y) YUKARI (X)   ENLEM   BOYLAM",
                    *self._dual_crs_fragmented_rows(
                        ("1", "2", "3", "4"),
                        stok_utm,
                        stok_geo,
                    ),
                    "Toplam Alan: 0,23 ha",
                ),
            ]
        )
        parsed = parse_coordinate_blocks(text)
        self.assertGreaterEqual(len(parsed), 12)
        self.assertEqual(parsed[0]["utm_y"], 675382.0)
        self.assertEqual(parsed[0]["utm_x"], 4144399.0)
        self.assertAlmostEqual(parsed[0]["latitude"], 37.4282393)
        self.assertAlmostEqual(parsed[0]["longitude"], 34.9817757)

        tables = TableDetector.find_tables(text)
        self.assertGreaterEqual(len(tables), 3)
        live_coordinates = CoordinateEngine.extract_coordinates(text)
        self.assertGreaterEqual(len(live_coordinates), 12)
        pipeline = run_coordinate_pipeline(text, tables=tables)
        self.assertGreaterEqual(len(pipeline["coordinates"]), 12)
        self.assertGreaterEqual(len(pipeline["polygons"]), 3)
        self.assertNotIn(DETECTED_TABLE_NO_POINTS, pipeline["reason_codes"])
        types = {
            polygon["table_type"]
            for polygon in pipeline["polygons"]
        }
        self.assertIn("RUHSAT_ALANI", types)
        self.assertTrue(
            types & {"CED_ALANI", "YENI_CED_ALANI", "MEVCUT_CED_ALANI"}
        )
        self.assertIn("STOK_ALANI", types)

    def test_dual_crs_live_interleave_is_not_detected_table_no_points(self):
        """Side-by-side columns often dump index+lat, then Y/X+lon."""

        pairs = square_utm(675382, 4144399, 212)
        geos = (
            (37.4282393, 34.9817757),
            (37.4269372, 34.9793456),
            (37.4252000, 34.9790000),
            (37.4265000, 34.9820000),
        )
        rows = []
        for index, (easting, northing), (latitude, longitude) in zip(
            ("1", "2", "3", "4"),
            pairs,
            geos,
        ):
            rows.extend(
                (
                    f"{index} {latitude:.7f}",
                    f"{easting:.3f} {northing:.3f} {longitude:.7f}",
                )
            )
        text = page(
            35,
            "Tablo 9. 1 Nolu Ruhsat Poligonu (P1) Koordinatları",
            "UTM KOORDİNATLAR          COĞRAFİK KOORDİNATLAR",
            "DATUM: ED-50              DATUM: WGS-84",
            "Sıra No SAĞA (Y) YUKARI (X)   ENLEM   BOYLAM",
            *rows,
            "Toplam Alan: 262,57 ha",
        )
        tables = TableDetector.find_tables(text)
        self.assertGreater(len(tables), 0)
        pipeline = run_coordinate_pipeline(text, tables=tables)
        self.assertGreaterEqual(len(pipeline["coordinates"]), 4)
        self.assertGreaterEqual(len(pipeline["polygons"]), 1)
        self.assertNotIn(DETECTED_TABLE_NO_POINTS, pipeline["reason_codes"])
        self.assertEqual(pipeline["coordinates"][0]["y"], 675382.0)


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

    def test_parenthetical_ced_does_not_retype_tesisi_or_stok_headings(self):
        self.assertEqual(
            detect_area_type(
                "Tablo 1  Kırma-Eleme Tesisi Koordinatları "
                "(Talep Edilen ÇED Alanı)"
            ),
            "KIRMA_ELEME_ALANI",
        )
        self.assertEqual(
            TableClassifier.classify(
                "Tablo 1  Kırma-Eleme Tesisi Koordinatları "
                "(Talep Edilen ÇED Alanı)\n"
                "N1\n434600\n4205200\n"
            ),
            "KIRMA_ELEME_ALANI",
        )
        self.assertEqual(
            detect_area_type("Mekanik Çözme Ünitesi Koordinatları"),
            "TESIS_ALANI",
        )
        self.assertEqual(
            detect_area_type("Malzeme Stok Alanı Koordinatları"),
            "STOK_ALANI",
        )
        self.assertEqual(
            TableClassifier.detect_ced_context_type(
                "Kırma-Eleme Tesisi Koordinatları (Talep Edilen ÇED Alanı)"
            ),
            "YENI_CED_ALANI",
        )

    def test_tesisi_malzeme_stok_and_15pt_geo_ring_are_not_inverted(self):
        """Witness shape (not Tablo-N Stok→Yeni ÇED): facility ÇED
        parenthetical, Malzeme Stok UTM, then a 15-pt lon/lat ring.

        Destekci on 8e8ba95: max(STOK)=99.4 ha / 15 pts typed STOK,
        max(YENI_CED)=0.23 ha facility. The large geo ring is ÇED.
        """

        tesisi_pairs = square_utm(434600, 4205200, 35)
        tesisi_extra = (
            (434610, 4205210),
            (434620, 4205220),
            (434630, 4205230),
            (434615, 4205235),
            (434605, 4205225),
        )
        tesisi_pairs = tesisi_pairs + tesisi_extra
        unite_pairs = square_utm(434700, 4205300, 48)
        stok_pairs = square_utm(434500, 4205100, 48)
        stok_extra = (
            (434510, 4205110),
            (434520, 4205120),
            (434530, 4205130),
            (434515, 4205135),
        )
        stok_pairs = stok_pairs + stok_extra

        lon0, lat0 = 31.686, 40.0645
        dlon, dlat = 0.006, 0.0045
        geo_lines = []
        for index in range(15):
            angle = 2 * math.pi * index / 15
            latitude = lat0 + dlat * math.sin(angle)
            longitude = lon0 + dlon * math.cos(angle)
            geo_lines.extend(
                (
                    f"{latitude:.6f}",
                    f"{longitude:.6f}",
                )
            )

        text = "\n".join(
            [
                page(
                    15,
                    "Tablo 1  Kırma-Eleme Tesisi Koordinatları "
                    "(Talep Edilen ÇED Alanı)",
                    *CRS,
                    *stacked_utm_lines(
                        tuple(f"N{i}" for i in range(1, 10)),
                        tesisi_pairs,
                    ),
                    "Mekanik Çözme Ünitesi Koordinatları",
                    *stacked_utm_lines(
                        ("U1", "U2", "U3", "U4"),
                        unite_pairs,
                    ),
                ),
                page(
                    16,
                    "Malzeme Stok Alanı Koordinatları",
                    *CRS,
                    *stacked_utm_lines(
                        tuple(f"S{i}" for i in range(1, 9)),
                        stok_pairs,
                    ),
                    *geo_lines,
                ),
            ]
        )

        pipeline = run_coordinate_pipeline(text)
        polygons = pipeline["polygons"]
        stok_areas = [
            polygon["area_ha"]
            for polygon in polygons
            if polygon["table_type"] == "STOK_ALANI"
        ]
        ced_areas = [
            polygon["area_ha"]
            for polygon in polygons
            if polygon["table_type"]
            in {"CED_ALANI", "YENI_CED_ALANI", "MEVCUT_CED_ALANI"}
        ]
        self.assertTrue(stok_areas, "Malzeme Stok ring missing")
        self.assertTrue(ced_areas, "15-pt geographic ÇED ring missing")
        self.assertLess(max(stok_areas), 2.0)
        self.assertGreater(max(ced_areas), 50.0)
        self.assertLess(max(stok_areas) * 10, max(ced_areas))

        geo_types = {
            point["table_type"]
            for point in pipeline["coordinates"]
            if point.get("latitude") is not None
            and point.get("longitude") is not None
            and (
                point.get("y") is None
                or abs(float(point["y"])) <= 180
            )
        }
        self.assertTrue(geo_types)
        self.assertTrue(
            geo_types
            <= {"CED_ALANI", "YENI_CED_ALANI", "MEVCUT_CED_ALANI"}
        )
        self.assertNotIn("STOK_ALANI", geo_types)

        tesisi_types = {
            point["table_type"]
            for point in pipeline["coordinates"]
            if str(point.get("name", "")).startswith("N")
        }
        self.assertTrue(
            tesisi_types
            <= {"KIRMA_ELEME_ALANI", "TESIS_ALANI"}
        )

    def test_headerless_geo_table_after_stok_does_not_inherit_stok(self):
        """Separate lon/lat table after Malzeme Stok (no Tablo N)."""

        geo_lines = []
        lon0, lat0 = 31.686, 40.0645
        for index in range(15):
            angle = 2 * math.pi * index / 15
            geo_lines.extend(
                (
                    f"{lat0 + 0.0045 * math.sin(angle):.6f}",
                    f"{lon0 + 0.006 * math.cos(angle):.6f}",
                )
            )
        text = "\n".join(
            [
                page(
                    15,
                    "Tablo 1  Kırma-Eleme Tesisi Koordinatları "
                    "(Talep Edilen ÇED Alanı)",
                    *CRS,
                    *stacked_utm_lines(
                        ("N1", "N2", "N3", "N4"),
                        square_utm(434600, 4205200, 35),
                    ),
                ),
                page(
                    16,
                    "Malzeme Stok Alanı Koordinatları",
                    *CRS,
                    *stacked_utm_lines(
                        ("S1", "S2", "S3", "S4"),
                        square_utm(434500, 4205100, 48),
                    ),
                    "Coğrafi Koordinatları",
                    *geo_lines,
                ),
            ]
        )
        pipeline = run_coordinate_pipeline(text)
        stok_areas = [
            polygon["area_ha"]
            for polygon in pipeline["polygons"]
            if polygon["table_type"] == "STOK_ALANI"
        ]
        ced_areas = [
            polygon["area_ha"]
            for polygon in pipeline["polygons"]
            if polygon["table_type"]
            in {"CED_ALANI", "YENI_CED_ALANI", "MEVCUT_CED_ALANI"}
        ]
        self.assertLess(max(stok_areas or [0]), 2.0)
        self.assertGreater(max(ced_areas or [0]), 50.0)


    def test_tesisi_plus_unattested_500m_grid_is_not_99ha_stok(self):
        """Destekci class: KML Stok Alanı 2 was tesisi verts + a 500 m
        lattice (387472/388972 × 4435315/4436315) that is not in the PDF.
        """

        tesisi = (
            (388232.5696, 4436109.12),
            (388266.12, 4436109.12),
            (388266.12, 4436164.80),
            (388204.00, 4436136.00),
        )
        grid = [
            (387472.0 + 500 * east, 4435315.0 + 500 * north)
            for east in range(4)
            for north in range(3)
        ]
        coordinates = []
        for index, (easting, northing) in enumerate(tesisi + tuple(grid)):
            coordinates.append(
                {
                    "name": f"P{index}",
                    "y": easting,
                    "x": northing,
                    "table_type": "STOK_ALANI",
                    "section": "Malzeme Stok Alanı",
                    "table_index": 5,
                    "polygon_group": "DEFAULT",
                }
            )

        polygons = PolygonBuilder.build(coordinates)
        stok_areas = [
            polygon["area_ha"]
            for polygon in polygons
            if polygon["table_type"] == "STOK_ALANI"
        ]
        self.assertLess(
            max(stok_areas or [0]),
            2.0,
            "invented 500 m lattice must not stay a ~99 ha STOK ring",
        )
        eastings = [
            point["y"]
            for polygon in polygons
            for point in polygon["points"]
        ]
        self.assertFalse(
            any(abs(easting - 387472) < 2 for easting in eastings),
            "unattested grid corner 387472 must not remain",
        )

    def test_real_captions_do_not_emit_invented_grid_easting(self):
        tesisi_pairs = (
            (388232.5696, 4436109.12),
            (388266.12, 4436109.12),
            (388266.12, 4436164.80),
            (388232.5696, 4436164.80),
            (388204.00, 4436136.00),
            (388240.00, 4436136.00),
            (388250.00, 4436120.00),
            (388220.00, 4436150.00),
            (388245.00, 4436140.00),
        )
        stok_pairs = square_utm(388180, 4436080, 48)
        text = "\n".join(
            [
                page(
                    15,
                    "Tablo 1  Kırma-Eleme Tesisi Koordinatları "
                    "(Talep Edilen ÇED Alanı)",
                    *CRS,
                    *stacked_utm_lines(
                        tuple(f"N{index}" for index in range(1, 10)),
                        tesisi_pairs,
                    ),
                    "Mekanik Çözme Ünitesi Koordinatları",
                    *stacked_utm_lines(
                        ("U1", "U2", "U3", "U4"),
                        square_utm(388300, 4436200, 48),
                    ),
                ),
                page(
                    16,
                    "Malzeme Stok Alanı Koordinatları",
                    *CRS,
                    *stacked_utm_lines(
                        ("S1", "S2", "S3", "S4"),
                        stok_pairs,
                    ),
                ),
            ]
        )
        pipeline = run_coordinate_pipeline(text)
        eastings = [point["y"] for point in pipeline["coordinates"]]
        self.assertFalse(
            any(abs(easting - 387472) < 2 for easting in eastings)
        )
        types = {
            polygon["table_type"]
            for polygon in pipeline["polygons"]
        }
        self.assertIn("STOK_ALANI", types)
        self.assertTrue(
            types & {"KIRMA_ELEME_ALANI", "TESIS_ALANI"}
        )
        stok_areas = [
            polygon["area_ha"]
            for polygon in pipeline["polygons"]
            if polygon["table_type"] == "STOK_ALANI"
        ]
        self.assertLess(max(stok_areas or [0]), 2.0)

    def _witness_tesisi_plus_500m_grid_utm(self):
        tesisi = (
            (388232.5696, 4436109.12),
            (388266.12, 4436109.12),
            (388266.12, 4436164.80),
            (388204.00, 4436136.00),
        )
        grid = [
            (387472.0 + 500 * east, 4435315.0 + 500 * north)
            for east in range(4)
            for north in range(3)
        ]
        return tesisi + tuple(grid)

    def _utm_to_lonlat(self, easting, northing):
        return CRSResolver.transform_to_wgs84(
            easting,
            northing,
            {
                "datum": "WGS84",
                "type": "UTM",
                "zone": 36,
                "projection": "UTM",
            },
        )

    def test_live_lonlat_path_drops_99ha_stok_composite(self):
        """Live process_pdf / GUI path: extract_pipeline stores leftover
        composite verts as lon/lat in y/x (no metre easting). Destekci
        inverse-UTM 36N of Stok Alanı 2 is tesisi + 387472/4435315 grid.

        #13 only trimmed metre y/x, so this ring survived as ~99 ha STOK.
        """

        coordinates = []
        for index, (easting, northing) in enumerate(
            self._witness_tesisi_plus_500m_grid_utm()
        ):
            longitude, latitude = self._utm_to_lonlat(easting, northing)
            coordinates.append(
                {
                    "name": f"P{index}",
                    "y": longitude,
                    "x": latitude,
                    "latitude": latitude,
                    "longitude": longitude,
                    "transformed_longitude": longitude,
                    "transformed_latitude": latitude,
                    "table_type": "STOK_ALANI",
                    "section": "Malzeme Stok Alanı",
                    "table_index": 5,
                    "polygon_group": "DEFAULT",
                }
            )

        polygons = PolygonBuilder.build(coordinates)
        stok_areas = [
            polygon["area_ha"]
            for polygon in polygons
            if polygon["table_type"] == "STOK_ALANI"
        ]
        self.assertLess(
            max(stok_areas or [0]),
            2.0,
            "live lon/lat y/x path must drop the ~99 ha STOK composite",
        )
        self.assertLess(
            max((polygon["area_ha"] for polygon in polygons), default=0),
            2.0,
            "no ~99 ha placemark of any type",
        )
        remaining_lons = [
            point["y"]
            for polygon in polygons
            for point in polygon["points"]
        ]
        self.assertFalse(
            any(abs(longitude - 31.680573) < 1e-4 for longitude in remaining_lons),
            "inverse-UTM grid corner 387472 / 31.68057 must not remain",
        )

        model = ProjectModel("witness.pdf", coordinates, polygons, [])
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "live-stok.kml")
            KMLExporter.export(model, path)
            kml_text = Path(path).read_text(encoding="utf-8")
        self.assertNotRegex(kml_text, r"9[0-9]\.\d{4} ha")
        self.assertNotRegex(kml_text, r"1[0-4]\d\.\d{4} ha")

    def test_extract_pipeline_lonlat_lattice_after_stok_is_not_99ha(self):
        """Same tables Destekci's process_pdf sees: tesisi UTM, Malzeme
        Stok UTM, then unlabeled lon/lat of tesisi+500 m grid.
        """

        tesisi_pairs = (
            (388232.5696, 4436109.12),
            (388266.12, 4436109.12),
            (388266.12, 4436164.80),
            (388232.5696, 4436164.80),
            (388204.00, 4436136.00),
            (388240.00, 4436136.00),
            (388250.00, 4436120.00),
            (388220.00, 4436150.00),
            (388245.00, 4436140.00),
        )
        geo_lines = []
        for easting, northing in self._witness_tesisi_plus_500m_grid_utm():
            longitude, latitude = self._utm_to_lonlat(easting, northing)
            geo_lines.extend(
                (
                    f"{latitude:.8f}",
                    f"{longitude:.8f}",
                )
            )
        text = "\n".join(
            [
                page(
                    15,
                    "Tablo 1  Kırma-Eleme Tesisi Koordinatları "
                    "(Talep Edilen ÇED Alanı)",
                    *CRS,
                    *stacked_utm_lines(
                        tuple(f"N{index}" for index in range(1, 10)),
                        tesisi_pairs,
                    ),
                ),
                page(
                    16,
                    "Malzeme Stok Alanı Koordinatları",
                    *CRS,
                    *stacked_utm_lines(
                        ("S1", "S2", "S3", "S4"),
                        square_utm(388180, 4436080, 48),
                    ),
                    *geo_lines,
                ),
            ]
        )
        pipeline = run_coordinate_pipeline(text)
        stok_areas = [
            polygon["area_ha"]
            for polygon in pipeline["polygons"]
            if polygon["table_type"] == "STOK_ALANI"
        ]
        self.assertLess(max(stok_areas or [0]), 2.0)
        self.assertFalse(
            any(
                polygon["area_ha"] > 50
                for polygon in pipeline["polygons"]
            ),
            "live extract_pipeline must not emit a ~99 ha composite",
        )

    def test_live_l_shaped_500m_mesh_plus_tesisi_is_not_99ha_stok(self):
        """Destekci dump on 1558526: y/x are UTM metres (not lon/lat).

        L-shaped partial grid 387500×{4435500,4436000,4436500} +
        {388000,388500,389000}×4435500 (6 of 12 cartesian cells) mixed
        with tesisi. filled (len>=0.6*12) is False; must still drop.
        """

        lattice = (
            (387500.0, 4435500.0),
            (387500.0, 4436000.0),
            (387500.0, 4436500.0),
        )
        tesisi = (
            (388232.569, 4436312.521),
            (388266.12, 4436109.12),
            (388266.12, 4436164.80),
            (388232.5696, 4436164.80),
            (388204.00, 4436136.00),
            (388240.00, 4436136.00),
            (388250.00, 4436120.00),
            (388220.00, 4436150.00),
            (388245.00, 4436140.00),
        )
        lattice_tail = (
            (389000.0, 4435500.0),
            (388500.0, 4435500.0),
            (388000.0, 4435500.0),
        )
        coordinates = []
        for index, (easting, northing) in enumerate(
            lattice + tesisi + lattice_tail
        ):
            coordinates.append(
                {
                    "name": f"P{index}",
                    "y": easting,
                    "x": northing,
                    "transformed_longitude": 31.68057,
                    "transformed_latitude": 40.06058,
                    "table_type": "STOK_ALANI",
                    "section": "Malzeme Stok Alanı",
                    "table_index": 5,
                    "polygon_group": "DEFAULT",
                }
            )

        self.assertEqual(len(coordinates), 15)
        polygons = PolygonBuilder.build(coordinates)
        stok_areas = [
            polygon["area_ha"]
            for polygon in polygons
            if polygon["table_type"] == "STOK_ALANI"
        ]
        self.assertLess(
            max(stok_areas or [0]),
            2.0,
            "L-shaped 500 m mesh + tesisi must not stay a ~99 ha STOK",
        )
        self.assertLess(
            max((polygon["area_ha"] for polygon in polygons), default=0),
            2.0,
            "no ~99 ha placemark of any type",
        )
        remaining = [
            (point["y"], point["x"])
            for polygon in polygons
            for point in polygon["points"]
        ]
        self.assertFalse(
            any(
                abs(easting - 387500) < 2 and abs(northing - 4435500) < 2
                for easting, northing in remaining
            ),
            "L-grid corner 387500/4435500 must not remain",
        )

        model = ProjectModel("witness.pdf", coordinates, polygons, [])
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "live-l-stok.kml")
            KMLExporter.export(model, path)
            kml_text = Path(path).read_text(encoding="utf-8")
        self.assertNotRegex(kml_text, r"9[0-9]\.\d{4} ha")
        self.assertNotRegex(kml_text, r"1[0-4]\d\.\d{4} ha")



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


class CoordinateAppendixIndexClassTests(unittest.TestCase):
    def test_toc_ek1_appendix_beyond_fast_scan(self):
        """İÇİNDEKİLER EK-1 coordinate appendix is a late target.

        Folder EK-2 (PTD) is not this appendix label. Empty
        index_target_pages + appendix after page 150 is why late
        PTD/ÇED files look like NO_COORDINATE_TABLE.
        """

        for title in (
            "EK-1 PROJE İÇİN SEÇİLEN YERİN KOORDİNATLARI",
            "Ek 1- Proje için seçilen yerin koordinatları",
            "1- Proje için seçilen yerin koordinatları",
        ):
            self.assertTrue(
                is_coordinate_appendix_title(title),
                title,
            )
        self.assertFalse(
            is_coordinate_appendix_title(
                "EK-1 Listesi uygulanacak projeler"
            )
        )
        self.assertFalse(
            is_coordinate_appendix_title(
                "EK-2 Proje tanıtım dosyası"
            )
        )

        pages = [
            {
                "physical_page": 6,
                "text": "\n".join(
                    (
                        "İÇİNDEKİLER",
                        "1. GİRİŞ ................................ 1",
                    )
                ),
            },
            {
                "physical_page": 7,
                "text": (
                    "EK-1 PROJE İÇİN SEÇİLEN YERİN "
                    "KOORDİNATLARI ......... 165"
                ),
            },
        ]
        entries = extract_toc_appendix_entries(pages)
        self.assertEqual(len(entries), 1)
        self.assertEqual(
            parse_printed_page(entries[0]["printed_page_raw"])[1],
            165,
        )
        targets = expand_pages(
            [165],
            332,
            before=1,
            after=10,
        )
        self.assertIn(165, targets)
        self.assertIn(175, targets)
        read = planned_read_pages(332, 150, targets)
        self.assertIn(1, read)
        self.assertIn(150, read)
        self.assertNotIn(151, read)
        self.assertIn(165, read)
        self.assertIn(175, read)


def hexagon_utm(center_y, center_x, area_ha):
    """Regular hexagon in metres whose shoelace area is ``area_ha``."""

    side = math.sqrt(area_ha * 10000 * 2 / (3 * math.sqrt(3)))
    pairs = []
    for index in range(6):
        angle = math.pi / 6 + index * math.pi / 3
        pairs.append(
            (
                center_y + side * math.cos(angle),
                center_x + side * math.sin(angle),
            )
        )
    return tuple(pairs)


def _colon_column_major_rows(labels, utm_pairs, geo_pairs):
    """1..n; then Y:X; then lat:lon — colon dual-CRS appendix dump."""

    lines = [str(label) for label in labels]
    lines.extend(f"{easting:.3f}:{northing:.3f}" for easting, northing in utm_pairs)
    lines.extend(
        f"{latitude:.8f}:{longitude:.8f}"
        for latitude, longitude in geo_pairs
    )
    return tuple(lines)


class EntrancePointAndColonDualCrsTests(unittest.TestCase):
    """Entrance-point tables vs area tables; colon dual-CRS appendix."""

    RUHSAT_GEO = (
        (37.66316512, 35.85063454),
        (37.66300000, 35.86600000),
        (37.65180000, 35.86920000),
        (37.63920000, 35.86040000),
        (37.64100000, 35.84500000),
        (37.65540000, 35.84320000),
    )
    GIRIS_UTM = (
        (750554.527, 4169276.059),
        (752800.000, 4169400.000),
        (753400.000, 4172000.000),
        (751600.000, 4172800.000),
        (749800.000, 4171600.000),
        (749400.000, 4169800.000),
        (750200.000, 4168600.000),
    )
    GIRIS_GEO = (
        (37.63484396, 35.83912217),
        (37.63600000, 35.86400000),
        (37.65900000, 35.87100000),
        (37.66600000, 35.85100000),
        (37.65500000, 35.83100000),
        (37.63900000, 35.82600000),
        (37.62800000, 35.83500000),
    )

    def test_headings_distinguish_entrance_points_from_gallery_area(self):
        self.assertEqual(
            TableClassifier.classify("Galeri Giriş Koordinatları"),
            "GALERI_GIRIS",
        )
        self.assertEqual(
            detect_area_type("Galeri Giriş Koordinatları"),
            "GALERI_GIRIS",
        )
        self.assertEqual(
            TableClassifier.classify("Galeri Girişi Koordinatları"),
            "GALERI_GIRIS",
        )
        self.assertEqual(
            TableClassifier.classify("2 No.lu Galeri Alanı (2,20 ha)"),
            "GALERI_ALANI",
        )
        self.assertEqual(
            detect_area_type("2 No.lu Galeri Alanı (2,20 ha)"),
            "GALERI_ALANI",
        )
        self.assertEqual(
            TableClassifier.classify(
                "1719 Sicil Nolu Alana Ait Koordinatlar ( 1.849,19 Hektar )"
            ),
            "RUHSAT_ALANI",
        )
        self.assertEqual(
            detect_area_type(
                "1719 Sicil Nolu Alana Ait Koordinatlar ( 1.849,19 Hektar )"
            ),
            "RUHSAT_ALANI",
        )
        self.assertEqual(
            TableClassifier.classify(
                "Tablo 1. Sicil 1719 Ruhsatlı Alan ve ÇED Alanı Koordinatları"
            ),
            "RUHSAT_ALANI",
        )

    def test_colon_dual_crs_ruhsat_block_is_full_ring(self):
        ruhsat_utm = hexagon_utm(751475.0, 4172450.0, 1849.19)
        text = page(
            37,
            "PROJE İÇİN SEÇİLEN YERİN KOORDİNATLARI",
            "UTM KOORDİNATLAR          COĞRAFİK KOORDİNATLAR",
            "DATUM: ED-50              DATUM: WGS-84",
            "ZON: 36",
            "Sıra No SAĞA (Y) YUKARI (X)   ENLEM   BOYLAM",
            "1719 Sicil Nolu Alana Ait Koordinatlar ( 1.849,19 Hektar )",
            *_colon_column_major_rows(
                ("1", "2", "3", "4", "5", "6"),
                ruhsat_utm,
                self.RUHSAT_GEO,
            ),
        )
        pipeline = run_coordinate_pipeline(text)
        ruhsat = [
            polygon
            for polygon in pipeline["polygons"]
            if polygon["table_type"] == "RUHSAT_ALANI"
        ]
        self.assertEqual(len(pipeline["coordinates"]), 6)
        self.assertEqual(len(ruhsat), 1)
        self.assertEqual(ruhsat[0]["point_count"], 6)
        self.assertAlmostEqual(ruhsat[0]["area_ha"], 1849.19, delta=2.0)
        self.assertNotIn(DETECTED_TABLE_NO_POINTS, pipeline["reason_codes"])

    def test_galeri_giris_point_list_is_not_an_area_polygon(self):
        ruhsat_utm = hexagon_utm(751475.0, 4172450.0, 1849.19)
        text = page(
            37,
            "PROJE İÇİN SEÇİLEN YERİN KOORDİNATLARI",
            "UTM KOORDİNATLAR          COĞRAFİK KOORDİNATLAR",
            "DATUM: ED-50              DATUM: WGS-84",
            "ZON: 36",
            "Sıra No SAĞA (Y) YUKARI (X)   ENLEM   BOYLAM",
            "1719 Sicil Nolu Alana Ait Koordinatlar ( 1.849,19 Hektar )",
            *_colon_column_major_rows(
                ("1", "2", "3", "4", "5", "6"),
                ruhsat_utm,
                self.RUHSAT_GEO,
            ),
            "Galeri Giriş Koordinatları",
            *_colon_column_major_rows(
                ("1", "2", "3", "4", "5", "6", "7"),
                self.GIRIS_UTM,
                self.GIRIS_GEO,
            ),
        )
        parsed = parse_coordinate_blocks(text)
        giris_points = [
            point
            for point in parsed
            if point.get("table_type_override") == "GALERI_GIRIS"
        ]
        self.assertEqual(len(giris_points), 7)

        pipeline = run_coordinate_pipeline(text)
        ruhsat = [
            feature
            for feature in pipeline["polygons"]
            if feature["table_type"] == "RUHSAT_ALANI"
            and feature.get("geometry_type", "POLYGON") == "POLYGON"
        ]
        giris = [
            feature
            for feature in pipeline["polygons"]
            if feature.get("geometry_type") == "POINT"
            and feature["table_type"] in {"GALERI_GIRIS", "GALERI_ALANI"}
        ]
        galeri_area = [
            feature
            for feature in pipeline["polygons"]
            if feature.get("geometry_type", "POLYGON") == "POLYGON"
            and feature["table_type"] in {"GALERI_ALANI", "GALERI_GIRIS"}
            and feature["area_ha"] > 100
        ]
        self.assertEqual(len(ruhsat), 1)
        self.assertEqual(ruhsat[0]["point_count"], 6)
        self.assertAlmostEqual(ruhsat[0]["area_ha"], 1849.19, delta=2.0)
        self.assertEqual(len(giris), 1)
        self.assertEqual(giris[0]["point_count"], 7)
        self.assertEqual(galeri_area, [])

    def test_stacked_colon_dual_crs_and_gallery_area_still_close(self):
        """Stacked index / Y:X / lat:lon still parses; Galeri Alanı stays area."""

        ruhsat_utm = hexagon_utm(751475.0, 4172450.0, 1849.19)
        stacked = []
        for label, (easting, northing), (latitude, longitude) in zip(
            ("1", "2", "3", "4", "5", "6"),
            ruhsat_utm,
            self.RUHSAT_GEO,
        ):
            stacked.extend(
                (
                    str(label),
                    f"{easting:.3f}:{northing:.3f}",
                    f"{latitude:.8f}:{longitude:.8f}",
                )
            )
        galeri_utm = square_utm(750200, 4169100, 140)
        text = page(
            37,
            "PROJE İÇİN SEÇİLEN YERİN KOORDİNATLARI",
            "UTM KOORDİNATLAR          COĞRAFİK KOORDİNATLAR",
            "DATUM: ED-50              DATUM: WGS-84",
            "ZON: 36",
            "1719 Sicil Nolu Alana Ait Koordinatlar ( 1.849,19 Hektar )",
            *stacked,
            "2 No.lu Galeri Alanı (2,20 ha)",
            *stacked_utm_lines(("G1", "G2", "G3", "G4"), galeri_utm),
        )
        pipeline = run_coordinate_pipeline(text)
        types = {
            polygon["table_type"]
            for polygon in pipeline["polygons"]
        }
        self.assertIn("RUHSAT_ALANI", types)
        self.assertIn("GALERI_ALANI", types)
        ruhsat = [
            polygon
            for polygon in pipeline["polygons"]
            if polygon["table_type"] == "RUHSAT_ALANI"
        ]
        self.assertEqual(ruhsat[0]["point_count"], 6)
        galeri = [
            feature
            for feature in pipeline["polygons"]
            if feature["table_type"] == "GALERI_ALANI"
        ]
        self.assertEqual(len(galeri), 1)
        self.assertEqual(galeri[0].get("geometry_type", "POLYGON"), "POLYGON")

    def test_page37_appendix_sicil_block_beats_giris_hull(self):
        """EK-1 appendix page: sicil colon block is ruhsat; giriş is pins."""

        ruhsat_utm = hexagon_utm(751475.0, 4172450.0, 1849.19)
        text = page(
            37,
            "PROJE İÇİN SEÇİLEN YERİN KOORDİNATLARI",
            "UTM KOORDİNATLAR          COĞRAFİK KOORDİNATLAR",
            "DATUM: ED-50              DATUM: WGS-84",
            "ZON: 36",
            "Sıra No SAĞA (Y) YUKARI (X)   ENLEM   BOYLAM",
            "1719 Sicil Nolu Alana Ait Koordinatlar ( 1.849,19 Hektar )",
            *_colon_column_major_rows(
                ("1", "2", "3", "4", "5", "6"),
                ruhsat_utm,
                self.RUHSAT_GEO,
            ),
            "Galeri Giriş Koordinatları",
            *_colon_column_major_rows(
                ("1", "2", "3", "4", "5", "6", "7"),
                self.GIRIS_UTM,
                self.GIRIS_GEO,
            ),
        )
        pipeline = run_coordinate_pipeline(text)
        area_polygons = [
            feature
            for feature in pipeline["polygons"]
            if feature.get("geometry_type", "POLYGON") == "POLYGON"
        ]
        self.assertEqual(
            [feature["table_type"] for feature in area_polygons],
            ["RUHSAT_ALANI"],
        )
        self.assertAlmostEqual(area_polygons[0]["area_ha"], 1849.19, delta=2.0)
        self.assertEqual(area_polygons[0]["point_count"], 6)

        model = ProjectModel(
            pdf_path="appendix.pdf",
            coordinates=pipeline["coordinates"],
            polygons=pipeline["polygons"],
            tables=pipeline["tables"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            kml_path = Path(tmp) / "appendix.kml"
            KMLExporter.export(model, str(kml_path))
            tree = ET.parse(kml_path)
        polygons = tree.findall(".//{http://www.opengis.net/kml/2.2}Polygon")
        points = tree.findall(".//{http://www.opengis.net/kml/2.2}Point")
        self.assertEqual(len(polygons), 1)
        self.assertEqual(len(points), 7)

    def test_large_galeri_hull_without_alani_caption_is_pins(self):
        """Safety net: a huge GALERI_ALANI hull is pins, not a filled area."""

        spread = (
            (750000.0, 4168000.0),
            (753000.0, 4168000.0),
            (753000.0, 4172000.0),
            (750000.0, 4172000.0),
        )
        self.assertGreater(
            PolygonBuilder._calculate_area(
                [{"y": easting, "x": northing} for easting, northing in spread]
            ),
            PolygonBuilder.POINT_AREA_M2_THRESHOLD,
        )
        self.assertTrue(
            PolygonBuilder._should_emit_as_pins(
                "GALERI_ALANI",
                [{"y": easting, "x": northing} for easting, northing in spread],
                "Galeri Koordinatları",
            )
        )
        self.assertFalse(
            PolygonBuilder._should_emit_as_pins(
                "GALERI_ALANI",
                [
                    {"y": easting, "x": northing}
                    for easting, northing in square_utm(750200, 4169100, 140)
                ],
                "2 No.lu Galeri Alanı (2,20 ha)",
            )
        )


if __name__ == "__main__":
    unittest.main()
