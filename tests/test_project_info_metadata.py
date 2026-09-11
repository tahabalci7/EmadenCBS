import unittest

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
        self.assertIn("42077", name)
        self.assertNotIn("Bilinmiyor", name)
        self.assertNotIn("NUMARALI", name)

    def test_filename_does_not_lead_with_bilinmiyor_when_sicil_exists(self):
        file_name = ProjectInfoExtractor.build_export_filename(
            {
                "company": "Bilinmiyor",
                "license_no": "38302",
                "mine_type": "NUMARALI BİTÜMLÜ ŞEYL",
            }
        )
        self.assertEqual(file_name, "38302")
        self.assertNotIn("Bilinmiyor", file_name)
        self.assertNotIn("NUMARALI", file_name)

    def test_junk_mine_type_is_not_a_name_token(self):
        name = ProjectInfoExtractor.build_project_export_name(
            {
                "company": "Ülkem İnşaat Mad.",
                "license_no": "Bilinmiyor",
                "mine_type": "NUMARALI PERLIT",
            }
        )
        self.assertEqual(name, "Ülkem İnşaat Mad.")
        self.assertNotIn("NUMARALI", name)
        self.assertNotIn("Bilinmiyor", name)


if __name__ == "__main__":
    unittest.main()
