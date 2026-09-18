import unittest

from src.coordinate.table_classifier import TableClassifier
from src.coordinate.table_detector import TableDetector
from src.coordinate.table_index import (
    extend_appendix_section_pages,
    fold_heading,
    is_coordinate_appendix_title,
    is_major_unrelated_section,
    is_selected_site_body_heading,
    is_toc_style_line,
    page_has_selected_site_body_heading,
    page_starts_major_unrelated_section,
    scope_selected_site_coordinate_text,
)


CRS = (
    "Koordinat Sırası : Sağa Yukarı",
    "Datum : ED-50",
    "Türü : UTM",
    "Zon : 36",
)


def page(page_number, *lines):
    return "\n".join(
        [
            f"--- Sayfa {page_number} [PDF METİN KATMANI] ---",
            *lines,
        ]
    )


def rows(prefix, start_y, start_x, count=4):
    block = []
    for index in range(count):
        block.extend(
            (
                f"{prefix}{index + 1}",
                str(start_y + index * 10),
                str(start_x + index * 10),
            )
        )
    return tuple(block)


class SelectedSiteHeadingDetectionTests(unittest.TestCase):
    def test_heading_variants_fold_turkish_and_ocr_noise(self):
        variants = (
            "PROJE İÇİN SEÇİLEN YERİN KOORDİNATLARI",
            "Proje icin secilen yerin koordinatlari",
            "EK-1 PROJE İÇİN SEÇİLEN YERİN KOORDİNATLARI",
            "Ek 1- Proje için seçilen yerin koordinatları",
            "EK1 PROJE ICIN SECILEN YERIN KOORDINATLARI",
            "PR0JE İÇİN SEÇİLEN YERİN KOORDİNATLARI",
            "PROJE İÇİN SEÇİLEN YERİN KOORDİNATLARI:",
            "EK-1 PROJE İÇİN SEÇİLEN ALANIN KOORDİNATLARI",
            "PROJE İÇİN SEÇİLEN ALAN KOORDİNATLARI",
        )
        for title in variants:
            self.assertTrue(
                is_coordinate_appendix_title(title),
                title,
            )
            self.assertIn("KOORDINAT", fold_heading(title))

        self.assertTrue(
            is_selected_site_body_heading(
                "PROJE İÇİN SEÇİLEN YERİN KOORDİNATLARI"
            )
        )
        self.assertTrue(
            is_selected_site_body_heading(
                "PROJE İÇİN SEÇİLEN YERİN KOORDİNATLARI",
                "EK-1",
            )
        )

    def test_related_secilen_alan_needs_ek1_or_proje_icin(self):
        self.assertTrue(
            is_coordinate_appendix_title(
                "EK-1 Seçilen Alan Koordinatları"
            )
        )
        self.assertFalse(
            is_coordinate_appendix_title(
                "Seçilen alanın özellikleri"
            )
        )
        self.assertFalse(
            is_coordinate_appendix_title(
                "Seçilen Alan Koordinatları"
            )
        )

    def test_toc_dotted_line_is_not_body_heading(self):
        toc = (
            "EK-1 PROJE İÇİN SEÇİLEN YERİN "
            "KOORDİNATLARI ......... 165"
        )
        self.assertTrue(is_coordinate_appendix_title(toc))
        self.assertTrue(is_toc_style_line(toc))
        self.assertFalse(is_selected_site_body_heading(toc))
        self.assertFalse(
            page_has_selected_site_body_heading(
                "İÇİNDEKİLER\n" + toc
            )
        )

    def test_folder_ek2_is_not_selected_site_heading(self):
        self.assertFalse(
            is_coordinate_appendix_title(
                "EK-2 Proje tanıtım dosyası"
            )
        )
        self.assertTrue(
            is_major_unrelated_section(
                "EK-2 PROJE TANITIM DOSYASI"
            )
        )
        self.assertTrue(
            is_major_unrelated_section("KAYNAKLAR")
        )
        self.assertFalse(
            is_major_unrelated_section(
                "PROJE İÇİN SEÇİLEN YERİN KOORDİNATLARI"
            )
        )


class SelectedSiteHeadingScopeTests(unittest.TestCase):
    def test_scope_stops_at_next_major_section(self):
        text = "\n".join(
            [
                page(20, "Tablo 1.6 Ruhsat Alanı Koordinatları"),
                page(
                    165,
                    "EK-1",
                    "PROJE İÇİN SEÇİLEN YERİN KOORDİNATLARI",
                    "Tablo 1. Ruhsat Alanı Koordinatları",
                    "Tablo 2. ÇED Alanı Koordinatları",
                ),
                page(
                    180,
                    "EK-2 PROJE TANITIM DOSYASI",
                    "Tablo 9. Başka Koordinatları",
                ),
            ]
        )
        scoped = scope_selected_site_coordinate_text(text)
        self.assertIsNotNone(scoped)
        self.assertIn("Tablo 1. Ruhsat Alanı Koordinatları", scoped)
        self.assertIn("Tablo 2. ÇED Alanı Koordinatları", scoped)
        self.assertNotIn("Tablo 1.6", scoped)
        self.assertNotIn("EK-2", scoped)
        self.assertNotIn("Tablo 9", scoped)

    def test_toc_does_not_scope_the_whole_document(self):
        text = "\n".join(
            [
                page(
                    6,
                    "İÇİNDEKİLER",
                    "EK-1 PROJE İÇİN SEÇİLEN YERİN "
                    "KOORDİNATLARI ......... 165",
                ),
                page(40, "1. GİRİŞ", "prose"),
                page(
                    165,
                    "PROJE İÇİN SEÇİLEN YERİN KOORDİNATLARI",
                    "Tablo 1. Ruhsat Alanı Koordinatları",
                ),
                page(200, "KAYNAKLAR"),
            ]
        )
        scoped = scope_selected_site_coordinate_text(text)
        self.assertIsNotNone(scoped)
        self.assertIn("Tablo 1. Ruhsat Alanı Koordinatları", scoped)
        self.assertNotIn("1. GİRİŞ", scoped)
        self.assertNotIn("KAYNAKLAR", scoped)

    def test_section_pages_stop_at_ek2(self):
        pages = {
            164: "önceki sayfa",
            165: "PROJE İÇİN SEÇİLEN YERİN KOORDİNATLARI\nTablo 1",
            166: "Tablo 2. ÇED Alanı Koordinatları",
            167: "Tablo 3. Ocak Alanı Koordinatları",
            168: "EK-2 PROJE TANITIM DOSYASI",
            169: "devam",
        }
        extended = extend_appendix_section_pages(
            165,
            200,
            pages.get,
        )
        self.assertEqual(extended, [164, 165, 166, 167])
        self.assertTrue(
            page_starts_major_unrelated_section(pages[168])
        )

    def test_body_heading_search_stays_in_late_window(self):
        seen = []

        def lookup(physical_page):
            seen.append(physical_page)
            return "no heading here"

        from src.coordinate.table_index import (
            locate_selected_site_heading_page,
        )

        found = locate_selected_site_heading_page(
            500,
            lookup,
        )
        self.assertEqual(found, [])
        self.assertEqual(min(seen), 421)
        self.assertEqual(max(seen), 500)
        self.assertNotIn(40, seen)
        self.assertNotIn(150, seen)


class SelectedSiteHeadingTableDiscoveryTests(unittest.TestCase):
    def test_all_numbered_tables_under_heading_are_found(self):
        text = "\n".join(
            [
                page(
                    20,
                    "Tablo 1.6 Ruhsat Alanı Koordinatları",
                    *CRS,
                    *rows("E", 111111, 4111111),
                ),
                page(
                    165,
                    "EK-1",
                    "PROJE İÇİN SEÇİLEN YERİN KOORDİNATLARI",
                    *CRS,
                    "Tablo 1. Ruhsat Alanı Koordinatları",
                    *rows("R", 434529, 4205189),
                    "Tablo 2. ÇED Alanı Koordinatları",
                    *rows("C", 435000, 4206000),
                    "Tablo 3. Ocak Alanı Koordinatları",
                    *rows("O", 436000, 4207000),
                ),
                page(
                    180,
                    "EK-2 PROJE TANITIM DOSYASI",
                    "Tablo 9. Stok Alanı Koordinatları",
                    *CRS,
                    *rows("X", 500000, 4100000),
                ),
            ]
        )
        tables = TableDetector.find_tables(text)
        types = [TableClassifier.classify(table) for table in tables]
        self.assertEqual(
            types,
            ["RUHSAT_ALANI", "CED_ALANI", "OCAK_ALANI"],
        )
        joined = "\n".join(tables)
        self.assertNotIn("Tablo 1.6", joined)
        self.assertNotIn("Tablo 9", joined)

    def test_all_unnumbered_tables_under_heading_are_found(self):
        text = "\n".join(
            [
                page(
                    165,
                    "PROJE İÇİN SEÇİLEN YERİN KOORDİNATLARI",
                    *CRS,
                    "Ruhsat Alanı Koordinatları",
                    *rows("R", 434529, 4205189),
                    "ÇED Alanı Koordinatları",
                    *rows("C", 435000, 4206000),
                    "Ocak Alanı Koordinatları",
                    *rows("O", 436000, 4207000),
                ),
                page(200, "KAYNAKLAR", "1. Some paper"),
            ]
        )
        tables = TableDetector.find_tables(text)
        types = [TableClassifier.classify(table) for table in tables]
        self.assertEqual(
            types,
            ["RUHSAT_ALANI", "CED_ALANI", "OCAK_ALANI"],
        )
        self.assertTrue(
            tables[1].strip().startswith("ÇED Alanı Koordinatları")
        )

    def test_split_heading_and_ocr_variant_still_scopes(self):
        text = "\n".join(
            [
                page(10, "Tablo 1.6 Ruhsat Alanı Koordinatları"),
                page(
                    171,
                    "EK-1",
                    "PR0JE ICIN SECILEN YERIN KOORDINATLARI",
                    *CRS,
                    "Tablo 1. Ruhsat Alanı Koordinatları",
                    *rows("R", 434529, 4205189),
                    "Tablo 2. ÇED Alanı Koordinatları",
                    *rows("C", 435000, 4206000),
                ),
            ]
        )
        tables = TableDetector.find_tables(text)
        types = [TableClassifier.classify(table) for table in tables]
        self.assertEqual(types, ["RUHSAT_ALANI", "CED_ALANI"])

    def test_without_heading_keeps_full_text_discovery(self):
        text = page(
            20,
            "Tablo 1.6 Ruhsat Alanı Koordinatları",
            *CRS,
            *rows("R", 434529, 4205189),
        )
        tables = TableDetector.find_tables(text)
        self.assertEqual(len(tables), 1)
        self.assertEqual(
            TableClassifier.classify(tables[0]),
            "RUHSAT_ALANI",
        )


if __name__ == "__main__":
    unittest.main()
