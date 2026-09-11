import math
import unittest

from src.coordinate.coordinate_engine import CoordinateEngine
from src.coordinate.polygon_builder import PolygonBuilder
from src.coordinate.ring_geometry import (
    count_lonlat_crossings,
    count_ring_crossings,
    repair_lonlat_rings,
    ring_is_simple,
)
from src.coordinate.state_machine import (
    parse_coordinate_blocks,
    parse_localized_number,
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


CRS = (
    "Koordinat Sırası : Sağa Yukarı",
    "Datum : ED-50",
    "Türü : UTM",
    "Zon : 36",
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


class LocalizedNumberTests(unittest.TestCase):
    def test_european_thousands_and_plain_decimals(self):
        self.assertEqual(
            parse_localized_number("4.205.189,12"),
            4205189.12,
        )
        self.assertEqual(
            parse_localized_number("434.529,00"),
            434529.0,
        )
        self.assertAlmostEqual(
            parse_localized_number("37.99035977"),
            37.99035977,
        )


class KmlKelebekRepairTests(unittest.TestCase):
    def test_lonlat_bowtie_is_repaired_when_utm_is_simple(self):
        # UTM order is a simple square; lon/lat on the same
        # vertices is a classic bow-tie (MADİNSAN/UYTAŞ class).
        points = [
            {
                "name": "A",
                "y": 434529,
                "x": 4205189,
                "longitude": 32.0,
                "latitude": 37.0,
            },
            {
                "name": "B",
                "y": 434629,
                "x": 4205189,
                "longitude": 32.1,
                "latitude": 37.1,
            },
            {
                "name": "C",
                "y": 434629,
                "x": 4205289,
                "longitude": 32.1,
                "latitude": 37.0,
            },
            {
                "name": "D",
                "y": 434529,
                "x": 4205289,
                "longitude": 32.0,
                "latitude": 37.1,
            },
        ]
        self.assertTrue(ring_is_simple(points))
        self.assertGreaterEqual(
            count_lonlat_crossings(
                [
                    (point["longitude"], point["latitude"])
                    for point in points
                ]
            ),
            1,
        )

        polygons = PolygonBuilder.build(
            [
                {
                    **point,
                    "table_type": "RUHSAT_ALANI",
                    "section": "Ruhsat Alanı",
                    "table_index": 1,
                    "polygon_group": "DEFAULT",
                }
                for point in points
            ]
        )
        self.assertEqual(len(polygons), 1)

        texts = KMLExporter._build_coordinate_texts(polygons[0])
        self.assertGreaterEqual(len(texts), 1)
        for text in texts:
            pairs = _parse_kml_pairs(text)
            self.assertEqual(count_lonlat_crossings(pairs), 0)

    def test_closed_six_point_lonlat_bowtie_is_repaired(self):
        lonlat = [
            (32.00, 37.00),
            (32.05, 37.00),
            (32.10, 37.10),
            (32.10, 37.00),
            (32.05, 37.10),
            (32.00, 37.10),
        ]
        self.assertGreaterEqual(count_lonlat_crossings(lonlat), 1)
        rings = repair_lonlat_rings(lonlat)
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
                for index, (lon, lat) in enumerate(lonlat)
            ]
        }
        for text in KMLExporter._build_coordinate_texts(polygon):
            self.assertEqual(
                count_lonlat_crossings(_parse_kml_pairs(text)),
                0,
            )

    def test_alkim_like_multi_cross_lonlat_becomes_simple(self):
        pairs = []
        for index in range(24):
            angle = -math.pi / 2 + index * 7 * 2 * math.pi / 24
            pairs.append(
                (
                    32.1 + 0.04 * math.cos(angle),
                    37.2 + 0.04 * math.sin(angle),
                )
            )
        self.assertGreaterEqual(count_lonlat_crossings(pairs), 4)

        polygon = {
            "points": [
                {
                    "name": f"P{index}",
                    "y": 434500 + 80 * math.cos(index * 2 * math.pi / 24),
                    "x": 4205200 + 80 * math.sin(index * 2 * math.pi / 24),
                    "longitude": lon,
                    "latitude": lat,
                }
                for index, (lon, lat) in enumerate(pairs)
            ]
        }
        self.assertTrue(
            ring_is_simple(polygon["points"])
        )

        texts = KMLExporter._build_coordinate_texts(polygon)
        self.assertGreaterEqual(len(texts), 1)
        for text in texts:
            self.assertEqual(
                count_lonlat_crossings(_parse_kml_pairs(text)),
                0,
            )


class ZeroPolygonLayoutTests(unittest.TestCase):
    def test_thousands_separated_utm_table_emits_polygons(self):
        text = page(
            1,
            "Tablo 1. Ruhsat Alanı Koordinatları",
            *CRS,
            "R1",
            "434.529,00",
            "4.205.189,00",
            "R2",
            "434.629,00",
            "4.205.289,00",
            "R3",
            "434.729,00",
            "4.205.389,00",
            "R4",
            "434.829,00",
            "4.205.489,00",
        )
        tables = TableDetector.find_tables(text)
        self.assertGreater(
            len(tables),
            0,
            "thousands-separated UTM table was not detected",
        )
        coordinates = CoordinateEngine.extract_coordinates(text)
        self.assertGreater(
            len(coordinates),
            0,
            "detected table produced 0 coordinates",
        )
        polygons = PolygonBuilder.build(coordinates)
        self.assertGreaterEqual(len(polygons), 1)
        self.assertEqual(polygons[0]["table_type"], "RUHSAT_ALANI")

        kml_texts = KMLExporter._build_coordinate_texts(polygons[0])
        self.assertTrue(
            any(text for text in kml_texts),
            "polygon had no KML coordinates",
        )

    def test_combined_thousands_utm_without_geo_parses(self):
        points = parse_coordinate_blocks(
            "\n".join(
                [
                    "KOORDINAT",
                    "Ruhsat Alanı Koordinatları",
                    "434.141,000:4.492.448,000",
                    "434.350,000:4.492.322,000",
                    "434.225,000:4.492.144,000",
                    "434.030,000:4.492.278,000",
                ]
            )
        )
        self.assertEqual(len(points), 4)
        self.assertEqual(points[0]["utm_y"], 434141.0)
        self.assertEqual(points[0]["utm_x"], 4492448.0)

    def test_ruhsat_is_kept_when_ced_shares_geometry(self):
        shared = [
            (434529, 4205189),
            (434629, 4205189),
            (434629, 4205289),
            (434529, 4205289),
        ]
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
                        "longitude": 32.0 + index * 0.001,
                        "latitude": 37.0 + (index % 2) * 0.001,
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


if __name__ == "__main__":
    unittest.main()
