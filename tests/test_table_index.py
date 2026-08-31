import unittest

from src.coordinate.table_index import (
    apply_printed_page_offset,
    expand_pages,
    extract_index_entries,
    is_geometry_title,
    resolve_entry,
    split_entry,
    table_no_variants,
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


if __name__ == "__main__":
    unittest.main()
