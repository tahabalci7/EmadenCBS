import unittest

from src.coordinate.coordinate_engine import CoordinateEngine
from src.coordinate.polygon_builder import PolygonBuilder
from src.coordinate.state_machine import detect_area_type
from src.coordinate.table_classifier import TableClassifier
from src.coordinate.table_detector import TableDetector


def page(page_number, *lines):
    return "\n".join(
        [
            f"--- Sayfa {page_number} [PDF METİN KATMANI] ---",
            *lines,
        ]
    )


HEADER = (
    "Koordinat Sırası : Sağa Yukarı",
    "Datum : ED-50",
    "Türü : UTM",
    "Zon : 36",
    "Koor. Sırası : Enlem Boylam",
    "Datum : WGS-84",
)


def rows(prefix, start=0, count=4):
    block = []
    for index in range(count):
        block.extend(
            (
                f"{prefix}{index + 1}",
                str(434529 + start + index),
                str(4205189 + start + index),
                "37.99035977:38.25422832",
            )
        )
    return tuple(block)


class CedHeadingLayoutTests(unittest.TestCase):
    def test_ced_alan_koordinatlari_without_i_suffix(self):
        self.assertEqual(
            detect_area_type("Mevcut ÇED Alan Koordinatları"),
            "MEVCUT_CED_ALANI",
        )
        self.assertEqual(
            detect_area_type("ÇED Poligonları"),
            "CED_ALANI",
        )
        self.assertEqual(
            detect_area_type("Yeni ÇED Sahası"),
            "YENI_CED_ALANI",
        )

    def test_report_title_is_not_a_ced_area(self):
        self.assertIsNone(
            detect_area_type("Nihai ÇED Raporu")
        )

    def test_split_ced_heading_is_classified(self):
        table = "\n".join(
            [
                "ÇED",
                "Alanı",
                "Koordinatları",
                *HEADER,
                *rows("C"),
            ]
        )
        self.assertEqual(
            TableClassifier.classify(table),
            "CED_ALANI",
        )

    def test_headerless_ced_page_does_not_inherit_ruhsat(self):
        text = "\n".join(
            [
                page(
                    1,
                    "Tablo- 2.1. Ruhsat Alanı Koordinatları",
                    *HEADER,
                    *rows("R", 0, 4),
                ),
                page(
                    2,
                    "ABC Madencilik A.Ş.",
                    "Nihai ÇED Raporu",
                    *HEADER,
                    "Mevcut ÇED Alan Koordinatları",
                    *rows("C", 20, 4),
                ),
            ]
        )

        tables = TableDetector.find_tables(text)
        self.assertGreaterEqual(len(tables), 1)

        coordinates = CoordinateEngine.extract_coordinates(text)
        polygons = PolygonBuilder.build(coordinates)
        types = {
            polygon["table_type"]
            for polygon in polygons
        }

        self.assertIn("RUHSAT_ALANI", types)
        self.assertTrue(
            types & {"CED_ALANI", "MEVCUT_CED_ALANI"}
        )
        ced_polygons = [
            polygon
            for polygon in polygons
            if polygon["table_type"]
            in {"CED_ALANI", "MEVCUT_CED_ALANI", "YENI_CED_ALANI"}
        ]
        self.assertGreaterEqual(len(ced_polygons), 1)
        self.assertTrue(
            any(
                point["table_type"]
                in {"CED_ALANI", "MEVCUT_CED_ALANI", "YENI_CED_ALANI"}
                for point in coordinates
                if point["name"].startswith("C")
            )
        )

    def test_ced_poligonu_subheads_stay_ced(self):
        text = "\n".join(
            [
                page(
                    1,
                    "Tablo- 3.2. ÇED Poligonları",
                    *HEADER,
                    "1 No.lu ÇED Poligonu (12,4 ha)",
                    *rows("C1.", 0, 4),
                    "2 No.lu ÇED Poligonu (8,1 ha)",
                    *rows("C2.", 10, 4),
                ),
            ]
        )
        coordinates = CoordinateEngine.extract_coordinates(text)
        polygons = PolygonBuilder.build(coordinates)
        types = {
            polygon["table_type"]
            for polygon in polygons
        }
        self.assertIn("CED_ALANI", types)
        self.assertNotIn("DIGER", types)
        self.assertEqual(
            len(
                [
                    polygon
                    for polygon in polygons
                    if polygon["table_type"] == "CED_ALANI"
                ]
            ),
            2,
        )


if __name__ == "__main__":
    unittest.main()
