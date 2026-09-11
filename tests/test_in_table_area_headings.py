import unittest

from src.coordinate.coordinate_engine import CoordinateEngine
from src.coordinate.polygon_builder import PolygonBuilder
from src.coordinate.state_machine import detect_area_type
from src.coordinate.table_classifier import TableClassifier
from src.coordinate.table_detector import TableDetector


HEADER = (
    "Koordinat Sırası : Sağa Yukarı",
    "Datum : ED-50",
    "Türü : UTM",
    "Zon : 36",
    "Koor. Sırası : Enlem Boylam",
    "Datum : WGS-84",
)


def page(page_number, *lines):
    return "\n".join(
        [
            f"--- Sayfa {page_number} [PDF METİN KATMANI] ---",
            *lines,
        ]
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


class InTableAreaHeadingTests(unittest.TestCase):
    def test_tablo_hyphen_is_numbered_heading(self):
        self.assertTrue(
            TableDetector._looks_like_table_number(
                "TABLO- 1.6. PROJE ALANI KOORDİNATLARI"
            )
        )

    def test_report_title_is_not_kirma_eleme_area(self):
        self.assertIsNone(
            detect_area_type(
                "Demir-Bakır Ocağı Kapasite Artışı, Kırma Eleme Tesisi,"
            )
        )
        self.assertEqual(
            detect_area_type("Kırma Eleme Alanı (2,1 ha)"),
            "KIRMA_ELEME_ALANI",
        )

    def test_classifier_uses_tablo_hyphen_not_previous_prose(self):
        table = "\n".join(
            [
                "besleyici stok alanı, kırma eleme tesisi, yakıt depolama alanı yer alacaktır.",
                "Tablo- 1.6. Proje Alanı Koordinatları",
                *HEADER,
                *rows("R"),
            ]
        )
        self.assertEqual(
            TableClassifier.classify(table),
            "PROJE_ALANI",
        )

    def test_subheadings_keep_separate_polygons(self):
        text = "\n".join(
            [
                page(
                    1,
                    "Firma Adı",
                    "Kapasite Artışı, Kırma Eleme Tesisi,",
                    "Flotasyon Tesisi ve Atık Depolama Tesisi",
                    "Nihai ÇED Raporu",
                    "Tablo- 1.6. Proje Alanı Koordinatları",
                    *HEADER,
                    "85421 Nolu Ruhsat Alanı (1919,1 ha)",
                    *rows("R", 0, 4),
                ),
                page(
                    2,
                    "Firma Adı",
                    "Kapasite Artışı, Kırma Eleme Tesisi,",
                    "Nihai ÇED Raporu",
                    *HEADER,
                    *rows("R", 10, 4),
                    "201600266 Nolu Ruhsat Alanı (1985,83 ha)",
                    *rows("R.", 20, 4),
                    "1 No.lu ÇED Poligonu (300,46 ha)",
                    *rows("C1.", 30, 4),
                    "2 No.lu ÇED Poligonu (95,78 ha)",
                    *rows("C2.", 40, 4),
                    "Pasa Döküm Alanı (9,90 ha)",
                    *rows("P.", 50, 4),
                ),
            ]
        )

        tables = TableDetector.find_tables(text)
        self.assertEqual(len(tables), 1)
        self.assertTrue(tables[0].strip().startswith("Tablo-"))

        coordinates = CoordinateEngine.extract_coordinates(text)
        polygons = PolygonBuilder.build(coordinates)
        types = {
            polygon["table_type"]
            for polygon in polygons
        }

        self.assertIn("RUHSAT_ALANI", types)
        self.assertIn("CED_ALANI", types)
        self.assertIn("PASA_ALANI", types)
        self.assertNotIn("KIRMA_ELEME_ALANI", types)

        ruhsat_polygons = [
            polygon
            for polygon in polygons
            if polygon["table_type"] == "RUHSAT_ALANI"
        ]
        self.assertEqual(len(ruhsat_polygons), 2)

        ced_polygons = [
            polygon
            for polygon in polygons
            if polygon["table_type"] == "CED_ALANI"
        ]
        self.assertEqual(len(ced_polygons), 2)


if __name__ == "__main__":
    unittest.main()
