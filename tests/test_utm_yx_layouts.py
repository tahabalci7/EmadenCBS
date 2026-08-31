import unittest

from src.coordinate.coordinate_engine import CoordinateEngine
from src.coordinate.polygon_builder import PolygonBuilder
from src.coordinate.state_machine import (
    is_label,
    parse_coordinate_blocks,
)


class UtmYXLayoutTests(unittest.TestCase):
    def test_six_digit_easting_is_not_a_point_label(self):
        self.assertFalse(
            is_label("409456", allow_numeric_labels=True)
        )
        self.assertFalse(
            is_label("4337600", allow_numeric_labels=True)
        )
        self.assertTrue(
            is_label("1", allow_numeric_labels=True)
        )
        self.assertFalse(
            is_label("38.3645019", allow_numeric_labels=True)
        )

    def test_unlabeled_combined_utm_then_geographic_runs(self):
        text = "\n".join(
            [
                "KOORDINAT",
                "Ocak Alanı Koordinatları",
                "374141.000:4492448.000",
                "374350.000:4492322.000",
                "374225.000:4492144.000",
                "374030.000:4492278.000",
                "40.57161382:43.51308519",
                "40.57051084:43.51557861",
                "40.56888882:43.51413782",
                "40.57006595:43.51180819",
                "ALAN =50.500 m2 (5,05 HEKTAR)",
            ]
        )
        points = parse_coordinate_blocks(text)
        self.assertEqual(len(points), 4)
        self.assertEqual(points[0]["utm_y"], 374141.0)
        self.assertEqual(points[0]["utm_x"], 4492448.0)
        self.assertEqual(points[0]["label"], "P1")
        self.assertEqual(
            points[0]["table_type_override"],
            "OCAK_ALANI",
        )

    def test_duplicate_numeric_label_two_column_block(self):
        text = "\n".join(
            [
                "KOORDINAT",
                "Ruhsat Alanı Koordinatları",
                "1",
                "409456",
                "4337600",
                "1",
                "39.18126938",
                "31.95136414",
                "2",
                "411103",
                "4337600",
                "2",
                "39.18143944",
                "31.97042995",
            ]
        )
        points = parse_coordinate_blocks(text)
        self.assertEqual(len(points), 2)
        self.assertEqual(points[0]["label"], "1")
        self.assertEqual(points[0]["utm_y"], 409456.0)
        self.assertEqual(points[0]["utm_x"], 4337600.0)
        self.assertEqual(
            points[0]["table_type_override"],
            "RUHSAT_ALANI",
        )

    def test_dotted_numeric_labels_are_point_names(self):
        text = "\n".join(
            [
                "KOORDINAT",
                "1. Poligon ÇED Alan Koordinatları",
                "1.1",
                "410585",
                "4341089",
                "1.1",
                "39.21282052",
                "31.96397188",
                "1.2",
                "410623",
                "4341039",
                "1.2",
                "39.21237396",
                "31.96441858",
            ]
        )
        points = parse_coordinate_blocks(text)
        self.assertEqual(len(points), 2)
        self.assertEqual(points[0]["label"], "1.1")
        self.assertEqual(
            points[0]["table_type_override"],
            "CED_ALANI",
        )

    def test_y_x_split_by_colon_with_decimal_places(self):
        text = "\n".join(
            [
                "KOORDINAT",
                "Kırma Eleme Tesisi Alan Koordinatları( 1.64 Ha)",
                "KET1",
                "371093.298 :",
                "4270170.517",
                "KET1",
                "38,5690721",
                ":",
                "37,5200623",
            ]
        )
        points = parse_coordinate_blocks(text)
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["label"], "KET1")
        self.assertEqual(points[0]["utm_y"], 371093.298)
        self.assertEqual(points[0]["utm_x"], 4270170.517)
        self.assertAlmostEqual(
            points[0]["latitude"],
            38.5690721,
        )
        self.assertAlmostEqual(
            points[0]["longitude"],
            37.5200623,
        )

    def test_unlabeled_four_line_y_x_lat_lon(self):
        text = "\n".join(
            [
                "KOORDINAT",
                "Stok Alanı Koordinatları",
                "374030.000",
                "4492278.000",
                "40.57006595",
                "43.51180819",
            ]
        )
        points = parse_coordinate_blocks(text)
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["utm_y"], 374030.0)
        self.assertTrue(points[0]["label"].startswith("P"))

    def test_engine_keeps_area_from_table_heading(self):
        text = "\n".join(
            [
                "--- Sayfa 2 [PDF METİN KATMANI] ---",
                "Tablo 1. Ocak Alanı Koordinatları",
                "Koor. Sırası : Sağa, Yukarı",
                "Datum : ED-50",
                "Türü : UTM",
                "Zon : 38",
                "374141.000:4492448.000",
                "374350.000:4492322.000",
                "374225.000:4492144.000",
                "374030.000:4492278.000",
                "40.57161382:43.51308519",
                "40.57051084:43.51557861",
                "40.56888882:43.51413782",
                "40.57006595:43.51180819",
            ]
        )
        coordinates = CoordinateEngine.extract_coordinates(text)
        polygons = PolygonBuilder.build(coordinates)
        self.assertEqual(len(coordinates), 4)
        self.assertEqual(len(polygons), 1)
        self.assertEqual(polygons[0]["table_type"], "OCAK_ALANI")

    def test_five_line_comma_decimals_with_utm_xy_headers(self):
        text = "\n".join(
            [
                "Tablo 3. Ruhsat Sahası Sınır Koordinatları",
                "UTM Koordinatlar",
                "Coğrafik Koordinatlar",
                "X",
                "Y",
                "R1",
                "759771.003",
                "4250619.011",
                "38,3645019",
                "35,9728089",
                "R2",
                "760218.004",
                "4250605.011",
                "38,3642461",
                "35,9779135",
            ]
        )
        coordinates = CoordinateEngine.extract_coordinates(text)
        self.assertEqual(len(coordinates), 2)
        self.assertEqual(coordinates[0]["name"], "R1")
        self.assertEqual(coordinates[0]["y"], 759771.003)

    def test_numeric_label_combined_yx_then_latlon(self):
        text = "\n".join(
            [
                "Tablo 13. Ruhsat Alanı Koordinatları",
                "Türü",
                "UTM",
                "Sr.",
                "Sağa:Yukarı",
                "1",
                "562000.005 : 4027826.029",
                "1",
                "36,3920118 : 33,6909533",
                "2",
                "563456.005 : 4027331.029",
                "2",
                "36,3874546 : 33,7071472",
            ]
        )
        coordinates = CoordinateEngine.extract_coordinates(text)
        self.assertEqual(len(coordinates), 2)
        self.assertEqual(coordinates[0]["y"], 562000.005)
        self.assertEqual(coordinates[0]["x"], 4027826.029)

    def test_area_size_in_header_does_not_end_table(self):
        text = "\n".join(
            [
                "--- Sayfa 1 [PDF METİN KATMANI] ---",
                "Tablo 13. Ruhsat Alanı Koordinatları",
                "Ruhsat Alanı Koordinatları",
                "Alan : 1138,08 ha",
                "Türü",
                "UTM",
                "1",
                "562000.005 : 4027826.029",
                "1",
                "36,3920118 : 33,6909533",
                "2",
                "563456.005 : 4027331.029",
                "2",
                "36,3874546 : 33,7071472",
                "3",
                "563597.005 : 4027089.029",
                "3",
                "36,3852637 : 33,7086994",
            ]
        )
        from src.coordinate.table_detector import TableDetector
        tables = TableDetector.find_tables(text)
        self.assertEqual(len(tables), 1)
        self.assertIn("Tablo 13", tables[0])
        coordinates = CoordinateEngine.extract_coordinates(text)
        self.assertEqual(len(coordinates), 3)
        self.assertEqual(coordinates[0]["table_type"], "RUHSAT_ALANI")


if __name__ == "__main__":
    unittest.main()
