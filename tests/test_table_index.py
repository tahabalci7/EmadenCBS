import unittest

import tempfile
from pathlib import Path

import fitz

from src.coordinate.table_index import (
    TableIndexLocator,
    apply_printed_page_offset,
    expand_pages,
    extract_index_entries,
    extract_toc_appendix_entries,
    is_coordinate_appendix_title,
    is_geometry_title,
    parse_joined_appendix_lines,
    planned_read_pages,
    resolve_appendix_entry,
    resolve_entry,
    split_entry,
    split_toc_appendix_line,
    table_no_variants,
    text_layer_has_utm_pairs,
)


class TableIndexTests(unittest.TestCase):
    def test_index_entry_with_printed_page(self):
        lines = [
            "İÇİNDEKİLER",
            "Tablolar Dizini",
            "Tablo 1.6 Ruhsat Alanı Koordinatları ......... 48",
            "Tablo 2.1 Flora Listesi ...................... 90",
            "Şekiller Dizini",
        ]
        entries = extract_index_entries(lines, 8)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["table_no"], "1.6")
        self.assertTrue(is_geometry_title(entries[0]["table_title"]))
        self.assertFalse(is_geometry_title(entries[1]["table_title"]))

    def test_roman_and_lettered_table_numbers(self):
        roman = split_entry(
            "Tablo I.2.2.2.1. Ruhsat Alanı Koordinatları ..... 40"
        )
        lettered = split_entry(
            "Tablo-1.b.4 ÇED Alanı Koordinatları 23"
        )
        self.assertEqual(roman["table_no"], "I.2.2.2.1")
        self.assertEqual(lettered["table_no"], "1.B.4")
        self.assertIn("1.2.2.2.1", table_no_variants("I.2.2.2.1"))

    def test_resolve_prefers_title_and_number(self):
        entry = split_entry(
            "Tablo 1.6 Ruhsat Alanı Koordinatları ......... 48"
        )
        pages = [
            {
                "physical_page": 10,
                "text": "Tablo 1.6 Başka bir şey",
            },
            {
                "physical_page": 52,
                "text": "Tablo 1.6 Ruhsat Alanı Koordinatları\nR1",
            },
        ]
        resolved = resolve_entry(entry, pages)
        self.assertEqual(resolved["physical_page"], 52)
        self.assertEqual(resolved["page_offset"], 4)

    def test_resolve_skips_index_page_and_uses_printed_page(self):
        entry = split_entry(
            "Tablo I.2.2.2.1 Ruhsat Alanı Koordinatları ......... 40"
        )
        pages = [
            {
                "physical_page": 12,
                "text": "Tablo I.2.2.2.1 Ruhsat Alanı Koordinatları ......... 40",
            },
            {
                "physical_page": 41,
                "text": "Tablo I.2.2.2.1 Ruhsat Alanı Koordinatları\nR1",
            },
        ]
        resolved = resolve_entry(entry, pages, skip_pages=[12])
        self.assertEqual(resolved["physical_page"], 41)

    def test_printed_page_offset_fills_unresolved(self):
        entries = [
            {
                "physical_page": 52,
                "printed_page_first": 48,
                "page_offset": 4,
            },
            {
                "physical_page": None,
                "printed_page_first": 50,
                "page_offset": None,
            },
        ]
        filled = apply_printed_page_offset(entries)
        self.assertEqual(filled[1]["physical_page"], 54)
        self.assertEqual(filled[1]["resolve_kind"], "PRINTED_PAGE_OFFSET")

    def test_expand_pages_includes_continuation(self):
        self.assertEqual(
            expand_pages([41], 80),
            [40, 41, 42, 43, 44],
        )

    def test_toc_appendix_variants_and_late_targets(self):
        variants = (
            "EK-1 PROJE İÇİN SEÇİLEN YERİN KOORDİNATLARI ......... 165",
            "Ek 1- Proje için seçilen yerin koordinatları ..... 120",
            "1- Proje için seçilen yerin koordinatları  179",
        )
        for line in variants:
            parsed = split_toc_appendix_line(line)
            self.assertIsNotNone(parsed, line)
            self.assertTrue(
                is_coordinate_appendix_title(parsed["table_title"])
            )
            self.assertTrue(parsed["printed_page_raw"])

        self.assertIsNone(
            split_toc_appendix_line("EK-1 Listesi ......... 12")
        )
        self.assertIsNone(
            split_toc_appendix_line(
                "EK-2 Proje tanıtım dosyası ......... 200"
            )
        )

        pages = [
            {
                "physical_page": 6,
                "text": "İÇİNDEKİLER\n1. GİRİŞ ......... 1\n",
            },
            {
                "physical_page": 7,
                "text": (
                    "EK-1 PROJE İÇİN SEÇİLEN YERİN "
                    "KOORDİNATLARI ......... 165\n"
                ),
            },
        ]
        entries = extract_toc_appendix_entries(pages)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["physical_index_page"], 7)

        resolved = resolve_appendix_entry(
            entries[0],
            [
                {
                    "physical_page": 7,
                    "text": (
                        "EK-1 PROJE İÇİN SEÇİLEN YERİN "
                        "KOORDİNATLARI ......... 165"
                    ),
                },
                {
                    "physical_page": 171,
                    "text": (
                        "EK-1\n"
                        "PROJE İÇİN SEÇİLEN YERİN KOORDİNATLARI\n"
                        "Tablo 1"
                    ),
                },
            ],
            skip_pages=[7],
        )
        self.assertEqual(resolved["physical_page"], 171)

        read = planned_read_pages(332, 150, [164, 165, 175])
        self.assertEqual(min(read), 1)
        self.assertIn(150, read)
        self.assertNotIn(151, read)
        self.assertIn(165, read)
        self.assertIn(175, read)

    def test_unnumbered_and_wrapped_toc_titles(self):
        self.assertIsNotNone(
            split_toc_appendix_line(
                "Ek 1 Proje için seçilen yerin koordinatları"
            )
        )
        self.assertFalse(
            split_toc_appendix_line(
                "Ek 1 Proje için seçilen yerin koordinatları"
            )["printed_page_raw"]
        )
        wrapped = parse_joined_appendix_lines(
            [
                "EK-1",
                "PROJE İÇİN SEÇİLEN YERİN KOORDİNATLARI",
            ]
        )
        self.assertIsNotNone(wrapped)
        self.assertTrue(
            is_coordinate_appendix_title(wrapped["table_title"])
        )
        self.assertFalse(
            text_layer_has_utm_pairs(
                "Ek 1 Proje için seçilen yerin koordinatları"
            )
        )

        pages = [
            {
                "physical_page": 7,
                "text": (
                    "İÇİNDEKİLER\n"
                    "EK-1\n"
                    "PROJE İÇİN SEÇİLEN YERİN KOORDİNATLARI\n"
                ),
            },
        ]
        entries = extract_toc_appendix_entries(pages)
        self.assertEqual(len(entries), 1)

    def _write_pdf(self, path, page_texts):
        document = fitz.open()
        for text in page_texts:
            page = document.new_page()
            y_position = 72
            for line in str(text).splitlines() or [""]:
                page.insert_text((72, y_position), line)
                y_position += 14
        document.save(path)
        document.close()

    def test_plan_unnumbered_toc_includes_late_body_under_max_pages(self):
        pages = [""] * 180
        pages[5] = "ICINDEKILER\n1. GIRIS ......... 1"
        pages[6] = "Ek 1 Proje icin secilen yerin koordinatlari"
        pages[159] = (
            "EK-1\n"
            "PROJE ICIN SECILEN YERIN KOORDINATLARI\n"
            "N1 434529 4205189"
        )
        with tempfile.TemporaryDirectory() as folder:
            pdf_path = Path(folder) / "late-appendix.pdf"
            self._write_pdf(pdf_path, pages)
            plan = TableIndexLocator.plan(str(pdf_path))

        self.assertTrue(plan["appendix_entries"])
        self.assertIn(160, plan["target_pages"])
        read = planned_read_pages(
            plan["page_count"],
            150,
            plan["target_pages"],
        )
        self.assertIn(160, read)
        self.assertNotIn(151, read)

    def test_plan_wrapped_toc_includes_late_body(self):
        pages = [""] * 185
        pages[5] = "ICINDEKILER\n1. GIRIS ......... 1"
        pages[6] = "EK-1"
        pages[7] = "PROJE ICIN SECILEN YERIN KOORDINATLARI"
        pages[167] = (
            "EK-1\n"
            "PROJE ICIN SECILEN YERIN KOORDINATLARI\n"
            "P1 434529 4205189"
        )
        with tempfile.TemporaryDirectory() as folder:
            pdf_path = Path(folder) / "wrapped-appendix.pdf"
            self._write_pdf(pdf_path, pages)
            plan = TableIndexLocator.plan(str(pdf_path))

        self.assertTrue(plan["appendix_entries"])
        self.assertIn(168, plan["target_pages"])


if __name__ == "__main__":
    unittest.main()
