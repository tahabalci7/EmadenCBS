import unittest

from src.coordinate.coordinate_engine import CoordinateEngine
from src.coordinate.polygon_builder import PolygonBuilder
from src.coordinate.state_machine import parse_coordinate_blocks
from src.coordinate.table_detector import TableDetector


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


class TableCoordinateDropRegressionTests(unittest.TestCase):
    """Guard the 42077-class failure: tables detected, zero coordinates."""

    def test_detected_utm_only_ruhsat_table_emits_coordinates(self):
        text = page(
            1,
            "Tablo 1. Ruhsat Alanı Koordinatları",
            *CRS,
            "R1",
            "434529",
            "4205189",
            "R2",
            "434629",
            "4205289",
            "R3",
            "434729",
            "4205389",
            "R4",
            "434829",
            "4205489",
        )

        tables = TableDetector.find_tables(text)
        self.assertGreater(len(tables), 0)

        coordinates = CoordinateEngine.extract_coordinates(text)
        self.assertGreater(
            len(coordinates),
            0,
            "extractable UTM table was detected but produced 0 coordinates",
        )
        self.assertEqual(len(coordinates), 4)
        self.assertTrue(
            all(point["table_type"] == "RUHSAT_ALANI" for point in coordinates)
        )

        polygons = PolygonBuilder.build(coordinates)
        self.assertEqual(len(polygons), 1)
        self.assertEqual(polygons[0]["table_type"], "RUHSAT_ALANI")
        self.assertEqual(len(polygons[0]["points"]), 4)

    def test_unlabeled_combined_utm_without_geographic_is_extractable(self):
        text = page(
            1,
            "Tablo 4. Ruhsat Alanı Koordinatları",
            *CRS,
            "374141.000:4492448.000",
            "374350.000:4492322.000",
            "374225.000:4492144.000",
            "374030.000:4492278.000",
        )
        tables = TableDetector.find_tables(text)
        self.assertGreater(len(tables), 0)
        coordinates = CoordinateEngine.extract_coordinates(text)
        self.assertEqual(len(coordinates), 4)
        self.assertEqual(coordinates[0]["y"], 374141.0)
        self.assertEqual(coordinates[0]["x"], 4492448.0)
        polygons = PolygonBuilder.build(coordinates)
        self.assertEqual(len(polygons), 1)

    def test_row_utm_only_points_are_parsed(self):
        points = parse_coordinate_blocks(
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
        self.assertEqual(len(points), 4)
        self.assertEqual(points[0]["label"], "R1")
        self.assertEqual(points[0]["utm_y"], 434529.0)
        self.assertIsNone(points[0]["latitude"])

    def test_column_major_utm_dump_is_extractable(self):
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
        tables = TableDetector.find_tables(text)
        self.assertGreater(len(tables), 0)
        coordinates = CoordinateEngine.extract_coordinates(text)
        self.assertEqual(
            len(coordinates),
            4,
            "column-major UTM dump was detected but dropped coordinates",
        )
        labels = [point["name"] for point in coordinates]
        self.assertEqual(labels, ["R1", "R2", "R3", "R4"])
        self.assertEqual(coordinates[0]["y"], 434529.0)
        self.assertEqual(coordinates[0]["x"], 4205189.0)
        polygons = PolygonBuilder.build(coordinates)
        self.assertEqual(len(polygons), 1)
        self.assertEqual(polygons[0]["table_type"], "RUHSAT_ALANI")

    def test_swapped_northing_easting_stacked_points_are_parsed(self):
        points = parse_coordinate_blocks(
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
        self.assertEqual(len(points), 3)
        self.assertEqual(points[0]["label"], "R1")
        self.assertEqual(points[0]["utm_y"], 434529.0)
        self.assertEqual(points[0]["utm_x"], 4205189.0)

    def test_ced_with_geo_and_ruhsat_utm_only_both_survive(self):
        text = "\n".join(
            [
                page(
                    1,
                    "Tablo 1. Ruhsat Alanı Koordinatları",
                    *CRS,
                    "R1",
                    "434529",
                    "4205189",
                    "R2",
                    "434629",
                    "4205289",
                    "R3",
                    "434729",
                    "4205389",
                    "R4",
                    "434829",
                    "4205489",
                ),
                page(
                    2,
                    "Tablo 2. ÇED Alanı Koordinatları",
                    *CRS,
                    "C1",
                    "435529",
                    "4206189",
                    "37.99035977:38.25422832",
                    "C2",
                    "435629",
                    "4206289",
                    "37.99135977:38.25522832",
                    "C3",
                    "435729",
                    "4206389",
                    "37.99235977:38.25622832",
                    "C4",
                    "435829",
                    "4206489",
                    "37.99335977:38.25722832",
                ),
            ]
        )
        tables = TableDetector.find_tables(text)
        self.assertGreaterEqual(len(tables), 2)
        coordinates = CoordinateEngine.extract_coordinates(text)
        self.assertGreater(len(coordinates), 0)
        types = {point["table_type"] for point in coordinates}
        self.assertIn("RUHSAT_ALANI", types)
        self.assertIn("CED_ALANI", types)
        polygons = PolygonBuilder.build(coordinates)
        polygon_types = {polygon["table_type"] for polygon in polygons}
        self.assertIn("RUHSAT_ALANI", polygon_types)
        self.assertIn("CED_ALANI", polygon_types)

    def test_full_five_line_blocks_still_keep_geographic(self):
        points = parse_coordinate_blocks(
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
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["latitude"], 37.97412423)
        self.assertEqual(points[0]["longitude"], 38.20282746)


if __name__ == "__main__":
    unittest.main()
