import unittest

from src.coordinate.state_machine import (
    is_label,
    parse_coordinate_blocks,
)


class CombinedGeographicCoordinateTests(unittest.TestCase):
    def assert_combined_point(
        self,
        label,
        utm_y,
        utm_x,
        geographic,
        latitude,
        longitude,
    ):
        text = "\n".join(
            [
                "KOORDINAT TABLOSU",
                label,
                str(utm_y),
                str(utm_x),
                geographic,
            ]
        )

        points = parse_coordinate_blocks(text)

        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["label"], label)
        self.assertEqual(points[0]["utm_y"], float(utm_y))
        self.assertEqual(points[0]["utm_x"], float(utm_x))
        self.assertEqual(points[0]["latitude"], latitude)
        self.assertEqual(points[0]["longitude"], longitude)

    def test_r1_combined_geographic(self):
        self.assert_combined_point(
            "R1",
            434529,
            4205189,
            "37.99035977:38.25422832",
            37.99035977,
            38.25422832,
        )

    def test_c2_10_combined_geographic(self):
        self.assert_combined_point(
            "C2.10",
            435176.41,
            4199761.79,
            "37.94149545:38.26209034",
            37.94149545,
            38.26209034,
        )

    def test_sa2_15_combined_geographic(self):
        self.assert_combined_point(
            "SA2.15",
            434931.54,
            4199950.86,
            "37.94318187:38.25928666",
            37.94318187,
            38.25928666,
        )

    def test_classic_five_line_block_is_unchanged(self):
        points = parse_coordinate_blocks(
            "\n".join(
                [
                    "KOORDINAT TABLOSU",
                    "R.1",
                    "430000",
                    "4203425",
                    "37.97412423",
                    "38.20282746",
                ]
            )
        )

        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["label"], "R.1")
        self.assertEqual(points[0]["utm_y"], 430000.0)
        self.assertEqual(points[0]["utm_x"], 4203425.0)
        self.assertEqual(points[0]["latitude"], 37.97412423)
        self.assertEqual(points[0]["longitude"], 38.20282746)

    def test_invalid_utm_ranges_are_rejected(self):
        points = parse_coordinate_blocks(
            "KOORDINAT\nTEST\n123\n456\n37.9:38.2"
        )
        self.assertEqual(points, [])

    def test_invalid_geographic_ranges_are_rejected(self):
        points = parse_coordinate_blocks(
            "KOORDINAT\nR1\n434529\n4205189\n99.0:150.0"
        )
        self.assertEqual(points, [])

    def test_arbitrary_colon_text_is_rejected(self):
        points = parse_coordinate_blocks(
            "KOORDINAT\nR1\n434529\n4205189\nlatitude:longitude"
        )
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["utm_y"], 434529.0)
        self.assertIsNone(points[0]["latitude"])
        self.assertIsNone(points[0]["longitude"])

    def test_existing_label_policy_accepts_real_examples(self):
        for label in ("R1", "R.1", "C1.1", "ADT.1", "SA2.15"):
            with self.subTest(label=label):
                self.assertTrue(is_label(label, allow_numeric_labels=False))

    def test_numeric_label_policy_is_preserved(self):
        points = parse_coordinate_blocks(
            "KOORDINAT\n1\n434529\n4205189\n37.9:38.2"
        )
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["label"], "1")

    def test_three_line_combined_utm_and_geographic(self):
        points = parse_coordinate_blocks(
            "\n".join(
                [
                    "KOORDINAT",
                    "R1",
                    "720000.000:4404500.000",
                    "39.76037917:35.56786753",
                ]
            )
        )
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["utm_y"], 720000.0)
        self.assertEqual(points[0]["utm_x"], 4404500.0)
        self.assertEqual(points[0]["latitude"], 39.76037917)
        self.assertEqual(points[0]["longitude"], 35.56786753)

    def test_three_line_combined_allows_spaces_around_colon(self):
        points = parse_coordinate_blocks(
            "\n".join(
                [
                    "KOORDINAT",
                    "Ç1",
                    "722988.000: 4403000.000",
                    "39.74610125: 35.60220634",
                ]
            )
        )
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["label"], "Ç1")
        self.assertEqual(points[0]["utm_y"], 722988.0)

    def test_longitude_before_latitude_is_reordered(self):
        points = parse_coordinate_blocks(
            "\n".join(
                [
                    "KOORDINAT",
                    "R1",
                    "322191",
                    "4461000",
                    "30.908088",
                    "40.278989",
                ]
            )
        )
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["latitude"], 40.278989)
        self.assertEqual(points[0]["longitude"], 30.908088)


if __name__ == "__main__":
    unittest.main()
