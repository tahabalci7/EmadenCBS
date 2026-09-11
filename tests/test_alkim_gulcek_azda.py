import math
import unittest

from src.coordinate.coordinate_engine import CoordinateEngine
from src.coordinate.polygon_builder import PolygonBuilder
from src.coordinate.ring_geometry import (
    count_lonlat_crossings,
    repair_lonlat_rings,
)
from src.coordinate.state_machine import (
    parse_coordinate_blocks,
    parse_row_coordinate,
)
from src.coordinate.table_detector import TableDetector
from src.export.kml_exporter import KMLExporter


def page(page_number, *lines):
    return "\n".join(
        [
            f"--- Sayfa {page_number} [PDF METİN KATMANI] ---",
            *lines,
        ]
    )


def _parse_kml_pairs(coordinate_text):
    pairs = []
    for line in coordinate_text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(",")
        pairs.append((float(parts[0]), float(parts[1])))
    if (
        len(pairs) >= 2
        and pairs[0][0] == pairs[-1][0]
        and pairs[0][1] == pairs[-1][1]
    ):
        pairs = pairs[:-1]
    return pairs


class AlkimLeftoverKelebekTests(unittest.TestCase):
    def test_compact_degree_star_leftover_crosses_are_cleared(self):
        # ALKİM-class: ~95 vertices inside << 0.01°, so a metre-space
        # collapse/quantize of 0.01 would smash the ring and leave
        # leftover lon/lat crossings after the first repair pass.
        pairs = []
        vertex_count = 95
        step = 8
        for index in range(vertex_count):
            angle = (
                -math.pi / 2
                + index * step * 2 * math.pi / vertex_count
            )
            pairs.append(
                (
                    32.10 + 0.004 * math.cos(angle),
                    37.20 + 0.004 * math.sin(angle),
                )
            )
        self.assertGreaterEqual(count_lonlat_crossings(pairs), 4)

        rings = repair_lonlat_rings(pairs)
        self.assertGreaterEqual(len(rings), 1)
        for ring in rings:
            self.assertEqual(count_lonlat_crossings(ring), 0)
            self.assertGreaterEqual(len(ring), 3)

        polygon = {
            "points": [
                {
                    "name": f"P{index}",
                    "y": 434500 + index,
                    "x": 4205100 + index,
                    "longitude": lon,
                    "latitude": lat,
                }
                for index, (lon, lat) in enumerate(pairs)
            ]
        }
        texts = KMLExporter._build_coordinate_texts(polygon)
        self.assertGreaterEqual(len(texts), 1)
        for text in texts:
            self.assertEqual(
                count_lonlat_crossings(_parse_kml_pairs(text)),
                0,
            )

    def test_small_degree_zigzag_leftover_is_split_simple(self):
        pairs = []
        for index in range(24):
            pairs.append(
                (
                    32.10 + (index % 2) * 0.001 + index * 0.00004,
                    37.20 + ((index // 2) % 2) * 0.0015,
                )
            )
        self.assertGreaterEqual(count_lonlat_crossings(pairs), 2)
        rings = repair_lonlat_rings(pairs)
        self.assertGreaterEqual(len(rings), 1)
        for ring in rings:
            self.assertEqual(count_lonlat_crossings(ring), 0)
            self.assertGreaterEqual(len(ring), 3)


class GulcekAzdaZeroPolygonTests(unittest.TestCase):
    def test_space_grouped_row_utm_parses(self):
        self.assertIsNotNone(
            parse_row_coordinate("N1 463 000 4 014 000", True)
        )
        points = parse_coordinate_blocks(
            "\n".join(
                [
                    "KOORDINAT",
                    "Ruhsat Alanı Koordinatları",
                    "N1 463 000 4 014 000",
                    "N2 463 100 4 014 100",
                    "N3 463 200 4 014 200",
                    "N4 463 050 4 014 250",
                    "N5 463 020 4 014 180",
                    "N6 463 080 4 014 080",
                ]
            )
        )
        self.assertEqual(len(points), 6)
        self.assertEqual(points[0]["utm_y"], 463000.0)
        self.assertEqual(points[0]["utm_x"], 4014000.0)

    def test_space_grouped_grid_lines_parse_and_export(self):
        # Diagnose-style: space-separated thousands on their own
        # lines produce points; export must still emit polygons.
        text = page(
            1,
            "Tablo 1. Ruhsat Alanı Koordinatları",
            "Koordinat Sırası : Sağa Yukarı",
            "Datum : ED-50",
            "Türü : UTM",
            "Zon : 36",
            "N1",
            "463 000",
            "4 014 000",
            "N2",
            "463 100",
            "4 014 100",
            "N3",
            "463 200",
            "4 014 200",
            "N4",
            "463 150",
            "4 014 250",
            "N5",
            "463 050",
            "4 014 220",
            "N6",
            "463 020",
            "4 014 080",
        )
        tables = TableDetector.find_tables(text)
        self.assertGreater(len(tables), 0)
        parsed = parse_coordinate_blocks(tables[0])
        self.assertGreaterEqual(len(parsed), 6)

        coordinates = CoordinateEngine.extract_coordinates(text)
        self.assertGreaterEqual(len(coordinates), 6)
        polygons = PolygonBuilder.build(coordinates)
        self.assertGreaterEqual(len(polygons), 1)
        kml_texts = KMLExporter._build_coordinate_texts(polygons[0])
        self.assertTrue(any(kml_texts))

    def test_parsed_points_without_table_zone_still_export(self):
        # Gülçek/AZDA class: parser accepts UTM points, table slice
        # has no Zon line, but the document states ED-50 / zone 36.
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
                    "N1",
                    "463 000",
                    "4 014 000",
                    "N2",
                    "463 100",
                    "4 014 100",
                    "N3",
                    "463 200",
                    "4 014 200",
                    "N4",
                    "463 150",
                    "4 014 250",
                    "N5",
                    "463 050",
                    "4 014 220",
                    "N6",
                    "463 020",
                    "4 014 080",
                ),
            ]
        )
        tables = TableDetector.find_tables(text)
        self.assertGreater(len(tables), 0)
        parsed = parse_coordinate_blocks(tables[-1])
        self.assertGreaterEqual(
            len(parsed),
            6,
            "diagnose-style parse produced no points",
        )

        coordinates = CoordinateEngine.extract_coordinates(text)
        self.assertGreaterEqual(len(coordinates), 6)
        self.assertTrue(
            any(
                point.get("transformed_longitude") is not None
                and point.get("transformed_latitude") is not None
                for point in coordinates
            ),
            "parsed UTM points were not transformed for KML",
        )
        polygons = PolygonBuilder.build(coordinates)
        self.assertGreaterEqual(
            len(polygons),
            1,
            "diagnose parsed points but export poly=0",
        )
        kml_texts = KMLExporter._build_coordinate_texts(polygons[0])
        self.assertTrue(
            any(kml_texts),
            "polygon had no KML coordinates after CRS fallback",
        )

    def test_space_row_headings_do_not_drop_below_polygon_size(self):
        # One parsed point per heading used to yield poly=0.
        text = page(
            1,
            "Tablo 1. Ruhsat Alanı Koordinatları",
            "Koordinat Sırası : Sağa Yukarı",
            "Datum : ED-50",
            "Türü : UTM",
            "Zon : 36",
            "1 NOLU POLİGON (1.2 ha)",
            "A1 463 000 4 014 000",
            "A2 463 100 4 014 000",
            "A3 463 100 4 014 100",
            "A4 463 000 4 014 100",
            "2 NOLU POLİGON (0.8 ha)",
            "B1 463 200 4 014 000",
            "B2 463 300 4 014 000",
            "B3 463 300 4 014 100",
            "B4 463 200 4 014 100",
        )
        coordinates = CoordinateEngine.extract_coordinates(text)
        self.assertGreaterEqual(len(coordinates), 8)
        polygons = PolygonBuilder.build(coordinates)
        self.assertGreaterEqual(len(polygons), 1)
        self.assertTrue(
            all(
                KMLExporter._build_coordinate_texts(polygon)
                for polygon in polygons
            )
        )


if __name__ == "__main__":
    unittest.main()
