import unittest

from src.project.mine_type_allowlist import (
    UNKNOWN,
    allowlisted_canonical,
    filter_mine_type,
    is_missing_mine_type,
)
from src.project.project_info_extractor import ProjectInfoExtractor


class MineTypeAllowlistTests(unittest.TestCase):
    def test_junk_tokens_are_rejected(self):
        for raw in (
            "MADEN",
            "MADENİ",
            "MADENI",
            "MADENLER",
            "İŞLETME",
            "RUHSAT",
            "AÇIK",
            "ATIK",
            "CEVHERI",
            "CEVHERLERI",
            "TAŞ",
            "ÇÖZELTİ",
            "ÇÖZELTİ / MADENLER",
        ):
            with self.subTest(raw=raw):
                self.assertEqual(filter_mine_type(raw), UNKNOWN)
                self.assertTrue(is_missing_mine_type(raw))
                self.assertEqual(allowlisted_canonical(raw.split()[0]), "")

    def test_valid_singles_and_diacritic_fold(self):
        cases = {
            "KROM": "KROM",
            "KALAY": "KALAY",
            "KUVARSİT": "KUVARSİT",
            "KUVARSIT": "KUVARSİT",
            "ÇİNKO": "ÇİNKO",
            "CINKO": "ÇİNKO",
            "KURŞUN": "KURŞUN",
            "BOKSIT": "BOKSİT",
            "BOKSİT": "BOKSİT",
            "LINYIT": "LİNYİT",
            "LİNYİT": "LİNYİT",
            "DEMIR": "DEMİR",
            "DEMİR": "DEMİR",
            "MANYEZİT": "MANYEZİT",
            "PERLİT": "PERLİT",
            "PERLIT": "PERLİT",
            "TUZ": "TUZ",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(filter_mine_type(raw), expected)
                self.assertFalse(is_missing_mine_type(raw))

    def test_hyphen_compounds_stay_hyphenated(self):
        self.assertEqual(
            filter_mine_type("KURŞUN-ÇİNKO"),
            "KURŞUN-ÇİNKO",
        )
        self.assertEqual(
            filter_mine_type("ÇİNKO-BARİT"),
            "ÇİNKO-BARİT",
        )
        self.assertEqual(
            filter_mine_type("KURSUN-CINKO"),
            "KURŞUN-ÇİNKO",
        )

    def test_slash_mixes_drop_junk_keep_minerals(self):
        self.assertEqual(filter_mine_type("KROM / İŞLETME"), "KROM")
        self.assertEqual(filter_mine_type("KROM / RUHSAT"), "KROM")
        self.assertEqual(filter_mine_type("ATIK / KALAY"), "KALAY")
        self.assertEqual(
            filter_mine_type("ÇİNKO / KALAY / KURŞUN / İŞLETME"),
            "ÇİNKO / KALAY / KURŞUN",
        )
        self.assertEqual(
            filter_mine_type("DEMIR / CEVHERLERI / CEVHERI / AÇIK"),
            "DEMİR",
        )
        self.assertEqual(
            filter_mine_type("ATIK / CEVHERLERI / KALAY"),
            "KALAY",
        )
        self.assertEqual(
            filter_mine_type("KÖMÜR / KİL"),
            "KÖMÜR / KİL",
        )

    def test_empty_and_unknown_stay_missing(self):
        self.assertEqual(filter_mine_type(""), UNKNOWN)
        self.assertEqual(filter_mine_type(None), UNKNOWN)
        self.assertEqual(filter_mine_type(UNKNOWN), UNKNOWN)
        self.assertTrue(is_missing_mine_type(None))

    def test_numarali_residue_does_not_block_mineral(self):
        self.assertEqual(
            filter_mine_type("NUMARALI MANYEZİT MADEN"),
            "MANYEZİT",
        )
        self.assertEqual(
            filter_mine_type("NUMARALI BİTÜMLÜ ŞEYL"),
            "BİTÜMLÜ ŞEYL",
        )


class MineTypeExtractAndExportTests(unittest.TestCase):
    def setUp(self):
        self.extractor = ProjectInfoExtractor()

    def test_labeled_krom_isletme_keeps_krom(self):
        info = self.extractor.extract("MADEN CİNSİ: KROM / İŞLETME")
        self.assertEqual(info["mine_type"], "KROM")
        self.assertFalse(info["mine_type_missing"])

    def test_labeled_madeni_alone_is_missing(self):
        info = self.extractor.extract("MADEN CİNSİ: MADENİ")
        self.assertEqual(info["mine_type"], "Bilinmiyor")
        self.assertTrue(info["mine_type_missing"])
        self.assertTrue(
            ProjectInfoExtractor.is_missing_mine_type(info)
        )
        name = ProjectInfoExtractor.build_export_filename(
            {
                "license_no": "42077",
                "company": "Örnek Madencilik A.Ş.",
                **info,
            }
        )
        self.assertTrue(name.endswith(" - Bilinmiyor"))
        self.assertNotIn("MADENİ", name)
        self.assertNotIn("MADENI", name)

    def test_labeled_kursun_cinko_stays(self):
        info = self.extractor.extract("MADEN CİNSİ: KURŞUN-ÇİNKO")
        self.assertEqual(info["mine_type"], "KURŞUN-ÇİNKO")
        self.assertFalse(info["mine_type_missing"])

    def test_labeled_atik_kalay_keeps_kalay(self):
        info = self.extractor.extract("MADEN CİNSİ: ATIK / KALAY")
        self.assertEqual(info["mine_type"], "KALAY")
        self.assertFalse(info["mine_type_missing"])

    def test_isletme_ocagi_does_not_invent_mine_type(self):
        info = self.extractor.extract("AÇIK İŞLETME OCAĞI")
        self.assertEqual(info["mine_type"], "Bilinmiyor")
        self.assertTrue(info["mine_type_missing"])

    def test_krom_ocagi_still_works(self):
        info = self.extractor.extract("KROM OCAĞI")
        self.assertEqual(info["mine_type"], "KROM")
        self.assertFalse(info["mine_type_missing"])

    def test_export_stem_does_not_use_junk_mine_type(self):
        name = ProjectInfoExtractor.build_project_export_name(
            {
                "license_no": "67802",
                "company": "Örnek Madencilik A.Ş.",
                "mine_type": "KROM / İŞLETME",
            }
        )
        self.assertEqual(
            name,
            "67802 - Örnek Madencilik A.Ş. - KROM",
        )


if __name__ == "__main__":
    unittest.main()
