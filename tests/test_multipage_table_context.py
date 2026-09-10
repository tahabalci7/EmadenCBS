import unittest

from src.coordinate.coordinate_engine import CoordinateEngine
from src.coordinate.polygon_builder import PolygonBuilder
from src.coordinate.table_classifier import TableClassifier
from src.coordinate.table_detector import TableDetector


def page(page_number, *lines):
    return "\n".join(
        [
            f"--- Sayfa {page_number} [PDF METİN KATMANI] ---",
            *lines,
        ]
    )


# Vertically stacked CRS block as produced by PDF text layers.
STACKED_CRS = (
    "Koordinat Sırası",
    ":",
    "Sağa Yukarı",
    "Datum",
    ":",
    "ED-50",
    "Türü",
    ":",
    "UTM",
    "D.O.M.",
    ":",
    "39",
    "Zon",
    ":",
    "37",
    "Ölçek Faktörü",
    ":",
    "0.9996",
    "Pafta No",
    ":",
    "M37-a3",
    "Koor. Sırası",
    ":",
    "Enlem Boylam",
    "Datum",
    ":",
    "WGS-84",
)

INLINE_CRS = (
    "Koordinat Sırası : Sağa Yukarı",
    "Datum : ED-50",
    "Türü : UTM",
    "D.O.M. : 39",
    "Zon : 37",
    "Ölçek Faktörü : 0.9996",
    "Pafta No : M37-a3",
    "Koor. Sırası : Enlem Boylam",
    "Datum : WGS-84",
)

RUNNING_HEADER = (
    "ABC Madencilik A.Ş.",
    "Demir-Bakır Ocağı Kapasite Artışı, Kırma Eleme Tesisi,",
    "Flotasyon Tesisi ve Atık Depolama Tesisi",
    "Nihai ÇED Raporu",
)


def stacked_points(labels, start=0):
    block = []
    for index, label in enumerate(labels):
        block.extend(
            (
                label,
                str(434529 + start + index),
                str(4205189 + start + index),
                "37.99035977:38.25422832",
            )
        )
    return tuple(block)


def combined_fixture(crs_lines):
    return "\n".join(
        [
            page(
                1,
                *RUNNING_HEADER,
                "48",
                "Tablo- 1.6. Proje Alanı Koordinatları",
                *crs_lines,
                "1 No.lu Ocak Alanı (5,12 ha)",
                *stacked_points(
                    [f"R{index}" for index in range(1, 10)],
                    0,
                ),
            ),
            page(
                2,
                *RUNNING_HEADER,
                "49",
                *crs_lines,
                *stacked_points(
                    [f"R{index}" for index in range(10, 18)],
                    10,
                ),
            ),
            page(
                3,
                *RUNNING_HEADER,
                "50",
                *crs_lines,
                "2 No.lu Galeri Alanı (2,20 ha)",
                *stacked_points(
                    [f"G2.{index}" for index in range(1, 5)],
                    20,
                ),
                "2 No.lu Toprak Depolama Alanı (1,10 ha)",
                *stacked_points(
                    [f"T2.{index}" for index in range(1, 5)],
                    30,
                ),
            ),
        ]
    )


JUNK_HEADING_SNIPPETS = (
    "Zon",
    "Ölçek",
    "Olcek",
    "Pafta",
    "Nihai ÇED Raporu",
    "Koor. Sırası",
    "Koordinat Sırası",
    "ABC Madencilik",
    "0.9996",
)


class MultipageTableContextTests(unittest.TestCase):
    def test_scale_factor_is_not_a_section_start(self):
        self.assertFalse(
            TableDetector._looks_like_strong_section_start(
                ["0.9996", "Pafta No"],
                0,
            )
        )
        self.assertFalse(
            TableDetector._looks_like_strong_section_start(
                ["37.99035977", "Ocak Alanı"],
                0,
            )
        )
        self.assertTrue(
            TableDetector._looks_like_strong_section_start(
                [
                    "1.3",
                    "Projenin Yer ve Teknoloji Alternatifleri",
                ],
                0,
            )
        )

    def test_crs_metadata_is_not_a_caption(self):
        heading = TableClassifier._extract_heading(
            "\n".join(
                [
                    "Zon : 37",
                    "Ölçek Faktörü : 0.9996",
                    "Pafta No : M37-a3",
                    "R10",
                    "434539",
                    "4205199",
                    "37.99035977:38.25422832",
                ]
            )
        )
        self.assertFalse(heading)
        for snippet in ("Zon", "Ölçek", "Pafta"):
            self.assertNotIn(snippet, heading)

    def test_stacked_crs_continuation_keeps_caption_context(self):
        self._assert_continuation_context(
            combined_fixture(STACKED_CRS)
        )

    def test_inline_crs_continuation_keeps_caption_context(self):
        self._assert_continuation_context(
            combined_fixture(INLINE_CRS)
        )

    def test_single_page_caption_is_unchanged(self):
        text = page(
            1,
            "Tablo- 1.6. Proje Alanı Koordinatları",
            *INLINE_CRS,
            *stacked_points(["R1", "R2", "R3", "R4"], 0),
        )
        tables = TableDetector.find_tables(text)
        self.assertEqual(len(tables), 1)
        self.assertEqual(
            TableClassifier.classify(tables[0]),
            "PROJE_ALANI",
        )
        heading = TableClassifier._extract_heading(
            tables[0]
        )
        self.assertIn("Tablo-", heading)
        self.assertNotIn("Koordinat Sırası", heading)

        coordinates = CoordinateEngine.extract_coordinates(
            text
        )
        self.assertEqual(len(coordinates), 4)
        self.assertTrue(
            all(
                point["table_type"] == "PROJE_ALANI"
                for point in coordinates
            )
        )
        self.assertTrue(
            all(
                not _looks_like_junk_heading(
                    point.get("polygon_heading", "")
                )
                for point in coordinates
            )
        )

    def _assert_continuation_context(self, text):
        tables = TableDetector.find_tables(text)
        self.assertGreaterEqual(len(tables), 1)
        self.assertTrue(
            any(
                "Tablo-" in table
                for table in tables
            )
        )

        coordinates = CoordinateEngine.extract_coordinates(
            text
        )
        labels = {
            point["name"]
            for point in coordinates
        }
        self.assertTrue(
            {"R1", "R9", "R10", "R17", "G2.1", "T2.1"}
            <= labels
        )

        for point in coordinates:
            heading = point.get("polygon_heading", "")
            self.assertFalse(
                _looks_like_junk_heading(heading),
                msg=heading,
            )
            self.assertNotEqual(
                point["table_type"],
                "DIGER",
                msg=point["name"],
            )
            self.assertNotIn(
                "Koordinat Sırası",
                point.get("section", ""),
            )

        page_two_points = [
            point
            for point in coordinates
            if point["name"] in {"R10", "R17"}
        ]
        self.assertEqual(len(page_two_points), 2)
        for point in page_two_points:
            self.assertIn(
                point["table_type"],
                {"PROJE_ALANI", "OCAK_ALANI"},
            )

        polygons = PolygonBuilder.build(coordinates)
        types = {
            polygon["table_type"]
            for polygon in polygons
        }
        self.assertIn("GALERI_ALANI", types)
        self.assertIn("DEPOLAMA_ALANI", types)
        self.assertNotIn("DIGER", types)
        self.assertNotIn("KIRMA_ELEME_ALANI", types)

        galeri = [
            polygon
            for polygon in polygons
            if polygon["table_type"] == "GALERI_ALANI"
        ]
        self.assertEqual(len(galeri), 1)
        self.assertEqual(
            galeri[0]["polygon_heading"],
            "2 No.lu Galeri Alanı (2,20 ha)",
        )
        self.assertEqual(len(galeri[0]["points"]), 4)

        depolama = [
            polygon
            for polygon in polygons
            if polygon["table_type"] == "DEPOLAMA_ALANI"
        ]
        self.assertEqual(len(depolama), 1)
        self.assertEqual(
            depolama[0]["polygon_heading"],
            "2 No.lu Toprak Depolama Alanı (1,10 ha)",
        )


def _looks_like_junk_heading(heading):
    if not heading:
        return False
    return any(
        snippet.lower() in heading.lower()
        for snippet in JUNK_HEADING_SNIPPETS
    )


if __name__ == "__main__":
    unittest.main()
