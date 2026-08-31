import unittest

from src.coordinate.coordinate_engine import CoordinateEngine
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


def rows(prefix, start=0):
    return (
        f"{prefix}1",
        str(434529 + start),
        str(4205189 + start),
        "37.99035977:38.25422832",
        f"{prefix}2",
        str(434629 + start),
        str(4205289 + start),
        "37.99135977:38.25522832",
    )


def first_page():
    return page(
        1,
        "Tablo 1. Proje Alanı Koordinatları",
        *HEADER,
        *rows("P"),
    )


class MultiPageCoordinateTableContinuationTests(unittest.TestCase):
    def test_normal_continuation_is_one_table(self):
        text = "\n".join(
            [
                first_page(),
                page(2, *HEADER, *rows("R", 1000)),
            ]
        )

        tables = TableDetector.find_tables(text)

        self.assertEqual(len(tables), 1)
        self.assertIn("R1", tables[0])
        sources = CoordinateEngine._match_table_line_sources(text, tables)
        pages = {
            source["source_page"]
            for source in sources[0]
            if source["source_page"] is not None
        }
        self.assertEqual(pages, {1, 2})

    def test_long_header_before_rows_is_continuation(self):
        long_header = (
            *HEADER,
            *(f"Metadata açıklaması {index}" for index in range(30)),
        )
        text = "\n".join(
            [
                first_page(),
                page(2, *long_header, *rows("R", 1000)),
            ]
        )

        tables = TableDetector.find_tables(text)

        self.assertEqual(len(tables), 1)
        self.assertIn("R2", tables[0])

    def test_numbered_section_and_prose_are_excluded(self):
        text = "\n".join(
            [
                first_page(),
                page(
                    2,
                    *HEADER,
                    *rows("R", 1000),
                    "1.3",
                    "Projenin Yer ve Teknoloji Alternatifleri",
                    "Bu bölüm normal açıklama metnidir.",
                    "1.4 Proje Yerinin Arazi Kullanım Durumu",
                ),
            ]
        )

        tables = TableDetector.find_tables(text)

        self.assertEqual(len(tables), 1)
        self.assertNotIn("Projenin Yer ve Teknoloji", tables[0])
        self.assertNotIn("normal açıklama", tables[0])
        self.assertNotIn("1.4 Proje Yerinin", tables[0])

    def test_header_only_page_is_not_continuation(self):
        text = "\n".join(
            [
                first_page(),
                page(2, *HEADER),
            ]
        )

        tables = TableDetector.find_tables(text)

        self.assertEqual(len(tables), 1)
        self.assertNotIn("--- Sayfa 2", tables[0])

    def test_ordinary_prose_page_is_not_continuation(self):
        text = "\n".join(
            [
                first_page(),
                page(2, "Bu sayfa yalnız normal proje açıklamasıdır."),
            ]
        )

        tables = TableDetector.find_tables(text)

        self.assertEqual(len(tables), 1)
        self.assertNotIn("normal proje açıklaması", tables[0])

    def test_new_explicit_coordinate_table_starts_new_table(self):
        text = "\n".join(
            [
                first_page(),
                page(
                    2,
                    "Tablo 2. Yeni Alan Koordinatları",
                    *HEADER,
                    *rows("N", 2000),
                ),
            ]
        )

        tables = TableDetector.find_tables(text)

        self.assertEqual(len(tables), 2)
        self.assertNotIn("N1", tables[0])
        self.assertIn("N1", tables[1])

    def test_rows_without_repeated_header_are_continuation(self):
        text = "\n".join(
            [
                first_page(),
                page(2, *rows("R", 1000)),
            ]
        )

        tables = TableDetector.find_tables(text)

        self.assertEqual(len(tables), 1)
        self.assertIn("R2", tables[0])

    def test_coordinate_labels_are_not_section_headings(self):
        for label in ("C1.3", "SA1.3", "R.3"):
            with self.subTest(label=label):
                self.assertFalse(
                    TableDetector._looks_like_strong_section_start(
                        [label, "434529", "4205189"],
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
        self.assertTrue(
            TableDetector._looks_like_strong_section_start(
                ["1.3 Projenin Yer ve Teknoloji Alternatifleri"],
                0,
            )
        )

    def test_blank_or_figure_gap_is_not_bridged(self):
        text = "\n".join(
            [
                first_page(),
                page(2, "Şekil 4. Proje yerleşim planı"),
                page(3, *HEADER, *rows("R", 1000)),
            ]
        )

        tables = TableDetector.find_tables(text)

        self.assertGreaterEqual(len(tables), 1)
        self.assertNotIn("R1", tables[0])
        self.assertTrue(
            any("R1" in table for table in tables[1:])
        )

    def test_legacy_text_without_page_marker_is_preserved(self):
        text = "\n".join(
            [
                "Tablo 1. Proje Alanı Koordinatları",
                *HEADER,
                *rows("P"),
            ]
        )

        tables = TableDetector.find_tables(text)

        self.assertEqual(len(tables), 1)
        self.assertIn("P1", tables[0])

    def test_cizelge_and_boundary_headings_are_detected(self):
        text = "\n".join(
            [
                page(
                    1,
                    "Çizelge 4. Ruhsat sahası sınır noktaları",
                    *HEADER,
                    *rows("R"),
                ),
                page(
                    2,
                    "Proje Alanı",
                    "KOORDİNATLARI",
                    *HEADER,
                    *rows("P", 500),
                ),
            ]
        )

        tables = TableDetector.find_tables(text)

        self.assertEqual(len(tables), 2)
        self.assertIn("R1", tables[0])
        self.assertIn("P1", tables[1])

    def test_word_style_enlem_boylam_header_without_utm_word(self):
        text = page(
            1,
            "Tablo 2. Mevcut ÇED alanı köşe noktaları",
            "Nokta No",
            "Y",
            "X",
            "Enlem",
            "Boylam",
            *rows("C"),
        )

        tables = TableDetector.find_tables(text)

        self.assertEqual(len(tables), 1)
        self.assertIn("C1", tables[0])

    def test_sondaj_coordinate_window_is_not_taken_as_area_table(self):
        text = page(
            1,
            "Sondaj Koordinatları",
            "Datum : ED-50",
            "Türü : UTM",
            "Zon : 36",
            "Enlem",
            "Boylam",
            *rows("S"),
        )

        tables = TableDetector.find_tables(text)

        self.assertEqual(tables, [])


if __name__ == "__main__":
    unittest.main()
