import unittest
from pathlib import Path

from src.project.project_info_extractor import ProjectInfoExtractor


class ProjectInfoMetadataTests(unittest.TestCase):
    def setUp(self):
        self.extractor = ProjectInfoExtractor()

    def test_sicil_ascii_label_in_prose(self):
        text = "\n".join(
            [
                "PROJE SAHİBİNİN ADI: Örnek Madencilik A.Ş.",
                "SICIL NO: 42077",
                "MANYEZİT MADEN OCAĞI",
            ]
        )
        info = self.extractor.extract(text)
        self.assertEqual(info["license_no"], "42077")
        self.assertNotIn("PROJE SAHİBİNİN ADI", info["company"])
        self.assertIn("Örnek Madencilik", info["company"])

    def test_sicil_table_value_on_next_line(self):
        text = "\n".join(
            [
                "PROJE SAHİBİNİN ADI",
                "Türkiye Kömür İşletmeleri",
                "SİCİL NO",
                "38302",
                "BİTÜMLÜ ŞEYL OCAĞI",
            ]
        )
        info = self.extractor.extract(text)
        self.assertEqual(info["license_no"], "38302")
        self.assertEqual(
            info["company"],
            "Türkiye Kömür İşletmeleri",
        )

    def test_sayili_ruhsat_and_numarali_title(self):
        text = "\n".join(
            [
                "PROJE SAHİBİNİN ADI: Ülkem İnşaat Mad. Ltd. Şti.",
                "35727 sayılı ruhsat kapsamında PERLİT OCAĞI",
            ]
        )
        info = self.extractor.extract(text)
        self.assertEqual(info["license_no"], "35727")

    def test_numarali_without_ruhsat_word_is_sicil(self):
        text = (
            "42077 NUMARALI MANYEZİT MADEN OCAĞI "
            "ÇED BAŞVURU DOSYASI"
        )
        info = self.extractor.extract(text)
        self.assertEqual(info["license_no"], "42077")
        self.assertEqual(info["ek_tip"], "Ek-1")

    def test_coordinate_labels_are_not_license_numbers(self):
        text = "\n".join(
            [
                "İR-1-1 434529 4205189",
                "R-1 434629 4205289",
                "P1 434729 4205389",
            ]
        )
        info = self.extractor.extract(text)
        self.assertEqual(info["license_no"], "Bilinmiyor")
        self.assertTrue(info["license_no_missing"])
        self.assertTrue(
            ProjectInfoExtractor.is_missing_license_no(info)
        )

    def test_company_label_prefix_is_stripped(self):
        text = "PROJE SAHİBİNİN ADI: Söğütsen Seramik Sanayi A.Ş."
        info = self.extractor.extract(text)
        self.assertEqual(
            info["company"],
            "Söğütsen Seramik Sanayi A.Ş.",
        )
        self.assertFalse(
            info["company"].upper().startswith("PROJE")
        )

    def test_numarali_residue_stripped_from_mine_type(self):
        cleaned = self.extractor._clean_mine_type(
            "NUMARALI MANYEZİT MADEN"
        )
        self.assertEqual(cleaned, "MANYEZİT MADEN")
        self.assertFalse(cleaned.startswith("NUMARALI"))

    def test_export_name_uses_sicil_not_bilinmiyor(self):
        name = ProjectInfoExtractor.build_project_export_name(
            {
                "company": "Söğütsen Seramik Sanayi",
                "license_no": "42077",
                "mine_type": "NUMARALI MANYEZİT MADEN",
            }
        )
        self.assertTrue(name.startswith("42077"))
        self.assertEqual(
            name,
            "42077 - Söğütsen Seramik Sanayi - Bilinmiyor",
        )
        self.assertNotIn("NUMARALI", name)
        self.assertFalse(
            ProjectInfoExtractor.is_missing_license_no(
                {
                    "company": "Söğütsen Seramik Sanayi",
                    "license_no": "42077",
                    "mine_type": "NUMARALI MANYEZİT MADEN",
                }
            )
        )

    def test_filename_does_not_lead_with_bilinmiyor_when_sicil_exists(self):
        file_name = ProjectInfoExtractor.build_export_filename(
            {
                "company": "Bilinmiyor",
                "license_no": "38302",
                "mine_type": "NUMARALI BİTÜMLÜ ŞEYL",
            }
        )
        self.assertEqual(
            file_name,
            "38302 - Bilinmiyor - Bilinmiyor",
        )
        self.assertTrue(file_name.startswith("38302"))
        self.assertNotIn("NUMARALI", file_name)

    def test_missing_sicil_keeps_placeholder_in_front(self):
        name = ProjectInfoExtractor.build_project_export_name(
            {
                "company": "Ülkem İnşaat Mad.",
                "license_no": "Bilinmiyor",
                "mine_type": "NUMARALI PERLIT",
            }
        )
        self.assertEqual(
            name,
            "Bilinmiyor - Ülkem İnşaat Mad. - Bilinmiyor",
        )
        self.assertTrue(name.startswith("Bilinmiyor"))
        self.assertNotIn("NUMARALI", name)

    def test_export_relative_path_uses_il_ek_sicil_company(self):
        """Destekci path contract restored after PR #2 company-first stems."""

        relative = ProjectInfoExtractor.build_export_relative_path(
            {
                "province": "Ankara",
                "ek_tip": "Ek-1",
                "license_no": "3927",
                "company": "ALKİM A.Ş.",
            }
        )
        self.assertEqual(
            Path(relative),
            Path("Ankara")
            / "Ek-1"
            / "3927 - ALKİM A.Ş. - Bilinmiyor.kml",
        )

    def test_export_relative_path_accepts_project_type_alias(self):
        relative = ProjectInfoExtractor.build_export_relative_path(
            {
                "province": "Konya",
                "project_type": "EK-2",
                "license_no": "86538",
                "company": "Madinsan Ltd. Şti.",
            }
        )
        self.assertEqual(
            Path(relative),
            Path("Konya")
            / "Ek-2"
            / "86538 - Madinsan Ltd. Şti. - Bilinmiyor.kml",
        )

    def test_missing_fields_stay_visible_in_relative_path(self):
        relative = ProjectInfoExtractor.build_export_relative_path(
            {
                "company": "Koyuncu Nakliye Ltd. Şti.",
            }
        )
        self.assertEqual(
            Path(relative),
            Path("Bilinmiyor")
            / "Bilinmiyor"
            / "Bilinmiyor - Koyuncu Nakliye Ltd. Şti. - Bilinmiyor.kml",
        )

    def test_path_separators_in_company_are_sanitized(self):
        relative = ProjectInfoExtractor.build_export_relative_path(
            {
                "province": "İzmir",
                "ek_tip": "Ek-2",
                "license_no": "53284",
                "company": "Uytaş A/S",
            }
        )
        self.assertEqual(
            Path(relative),
            Path("İzmir")
            / "Ek-2"
            / "53284 - Uytaş A_S - Bilinmiyor.kml",
        )

    def test_missing_sicil_flag_does_not_invent_license(self):
        info = {
            "company": "Ülkem İnşaat Mad.",
            "license_no": "Bilinmiyor",
            "mine_type": "PERLIT",
        }
        self.assertTrue(
            ProjectInfoExtractor.is_missing_license_no(info)
        )
        name = ProjectInfoExtractor.build_export_filename(info)
        self.assertTrue(name.startswith("Bilinmiyor - "))
        self.assertIn("PERLIT", name)
        self.assertNotEqual(
            name.split(" - ", 1)[0],
            "Ülkem İnşaat Mad.",
        )

    def test_export_stem_includes_extracted_mine_type(self):
        file_name = ProjectInfoExtractor.build_export_filename(
            {
                "company": "Söğütsen Seramik Sanayi",
                "license_no": "42077",
                "mine_type": "MANYEZİT",
            }
        )
        self.assertEqual(
            file_name,
            "42077 - Söğütsen Seramik Sanayi - MANYEZİT",
        )

    def test_extract_feeds_mine_type_into_relative_path(self):
        text = "\n".join(
            [
                "NİHAİ ÇED RAPORU",
                "ANKARA İLİ",
                "PROJE SAHİBİNİN ADI: Örnek Madencilik A.Ş.",
                "SİCİL NO: 3927",
                "MADEN CİNSİ: MANYEZİT",
            ]
        )
        info = self.extractor.extract(text)
        self.assertEqual(info["mine_type"], "MANYEZİT")
        self.assertFalse(info["license_no_missing"])
        relative = ProjectInfoExtractor.build_export_relative_path(info)
        self.assertEqual(
            Path(relative),
            Path("Ankara")
            / "Ek-1"
            / "3927 - Örnek Madencilik A.Ş. - MANYEZİT.kml",
        )

    def test_export_relative_path_keeps_ek_in_folder(self):
        relative = ProjectInfoExtractor.build_export_relative_path(
            {
                "province": "Ankara",
                "ek_tip": "Ek-1",
                "license_no": "3927",
                "company": "ALKİM A.Ş.",
                "mine_type": "TUZ",
            }
        )
        self.assertEqual(
            Path(relative),
            Path("Ankara") / "Ek-1" / "3927 - ALKİM A.Ş. - TUZ.kml",
        )
        self.assertEqual(Path(relative).parts[0], "Ankara")
        self.assertEqual(Path(relative).parts[1], "Ek-1")
        self.assertNotIn("Ek-1", Path(relative).stem)

    def test_path_separators_in_mine_type_are_sanitized(self):
        relative = ProjectInfoExtractor.build_export_relative_path(
            {
                "province": "Konya",
                "ek_tip": "Ek-2",
                "license_no": "86538",
                "company": "Madinsan Ltd. Şti.",
                "mine_type": "KÖMÜR / KİL",
            }
        )
        self.assertEqual(
            Path(relative),
            Path("Konya")
            / "Ek-2"
            / "86538 - Madinsan Ltd. Şti. - KÖMÜR _ KİL.kml",
        )
        self.assertEqual(len(Path(relative).parts), 3)

    def test_ek_tip_from_ced_cover_title(self):
        text = "\n".join(
            [
                "NİHAİ ÇED RAPORU",
                "ANKARA İLİ",
                "PROJE SAHİBİNİN ADI: Örnek Madencilik A.Ş.",
                "SİCİL NO: 3927",
            ]
        )
        info = self.extractor.extract(text)
        self.assertEqual(info["ek_tip"], "Ek-1")
        self.assertEqual(info["province"], "Ankara")
        self.assertEqual(info["license_no"], "3927")
        self.assertFalse(info["license_no_missing"])

    def test_ek_tip_from_ptd_cover_title(self):
        text = "\n".join(
            [
                "PROJE TANITIM DOSYASI",
                "İL: Konya",
                "PROJE SAHİBİNİN ADI: Madinsan Ltd. Şti.",
                "SICIL NO: 86538",
            ]
        )
        info = self.extractor.extract(text)
        self.assertEqual(info["ek_tip"], "Ek-2")
        self.assertEqual(info["province"], "Konya")
        self.assertEqual(info["license_no"], "86538")

    def test_source_path_fills_missing_il_and_ek_tip(self):
        text = "\n".join(
            [
                "PROJE SAHİBİNİN ADI: Koyuncu Nakliye Ltd. Şti.",
                "SICIL NO: 11880",
            ]
        )
        info = self.extractor.extract(
            text,
            source_path="/data/downloads/ANKARA/EK-2/ornek.pdf",
        )
        self.assertEqual(info["ek_tip"], "Ek-2")
        self.assertEqual(info["province"], "Ankara")
        relative = ProjectInfoExtractor.build_export_relative_path(info)
        self.assertEqual(
            Path(relative),
            Path("Ankara")
            / "Ek-2"
            / "11880 - Koyuncu Nakliye Ltd. Şti. - Bilinmiyor.kml",
        )

    def test_pdf_ek_tip_wins_over_source_folder(self):
        text = "\n".join(
            [
                "Nihai ÇED Raporu",
                "PROJE SAHİBİNİN ADI: Örnek Madencilik A.Ş.",
                "SICIL NO: 42077",
            ]
        )
        info = self.extractor.extract(
            text,
            source_path="/data/downloads/ANKARA/EK-2/ornek.pdf",
        )
        self.assertEqual(info["ek_tip"], "Ek-1")


if __name__ == "__main__":
    unittest.main()
