import unittest

from src.coordinate.table_detector import TableDetector


def utm_point(label, easting, northing):
    return {
        "label": label,
        "utm_y": easting,
        "utm_x": northing,
        "latitude": None,
        "longitude": None,
    }


def geo_point(label, latitude, longitude):
    return {
        "label": label,
        "utm_y": None,
        "utm_x": None,
        "latitude": latitude,
        "longitude": longitude,
    }


def square_pairs(origin_y, origin_x, size):
    return (
        (origin_y, origin_x),
        (origin_y + size, origin_x),
        (origin_y + size, origin_x + size),
        (origin_y, origin_x + size),
    )


def scale_break_points():
    """Small ~0.23 ha ring then a ≫ ~100 ha ring, one numeric series."""

    small = square_pairs(434500, 4205100, 48)
    extra_small = (
        (434512, 4205100),
        (434524, 4205100),
        (434536, 4205100),
        (434548, 4205100),
    )
    small = (small[0],) + extra_small + small[1:]
    large = square_pairs(430000, 4200000, 1000)
    extra_large = tuple(
        (430000 + step * 80, 4200000)
        for step in range(1, 13)
    )
    large = (large[0],) + extra_large + large[1:]
    points = []
    for index, (easting, northing) in enumerate(small + large):
        points.append(
            utm_point(str(index + 1), easting, northing)
        )
    return points, len(small)


class IncompletePointShoelaceTests(unittest.TestCase):
    def test_area_scale_break_skips_none_utm(self):
        points, small_count = scale_break_points()
        incomplete = points[3]
        incomplete["utm_x"] = None
        incomplete["utm_y"] = None

        break_at = TableDetector._area_scale_break(points)

        self.assertIsNotNone(break_at)
        self.assertGreaterEqual(break_at, 4)
        self.assertLessEqual(break_at, small_count + 1)

    def test_ring_break_index_skips_none_utm(self):
        points, _ = scale_break_points()
        points[5]["utm_x"] = None

        break_at = TableDetector._ring_break_index(points)

        self.assertIsNotNone(break_at)

    def test_area_scale_break_skips_none_lonlat(self):
        points = [
            geo_point(str(index + 1), 37.6 + 0.01 * index, 35.8)
            for index in range(8)
        ]
        points.extend(
            geo_point(str(index + 9), 38.5, 36.0 + 0.02 * index)
            for index in range(8)
        )
        points[2]["latitude"] = None
        points[4]["longitude"] = None

        break_at = TableDetector._area_scale_break(points)

        self.assertIsNone(break_at)

    def test_shoelace_vertices_drop_incomplete_pairs(self):
        items = [
            utm_point("1", 434500, 4205100),
            utm_point("2", None, 4205200),
            utm_point("3", 434700, None),
            {"label": "4"},
            utm_point("5", 434800, 4205300),
            utm_point("6", 434900, 4205400),
            geo_point("7", 37.66, 35.85),
        ]

        vertices = TableDetector._shoelace_vertices(items)

        self.assertEqual(
            vertices,
            [
                (434500.0, 4205100.0),
                (434800.0, 4205300.0),
                (434900.0, 4205400.0),
            ],
        )

    def test_shoelace_vertices_fall_back_to_lonlat(self):
        items = [
            utm_point("1", None, None),
            geo_point("2", 37.66, 35.85),
            geo_point("3", 37.67, 35.86),
            geo_point("4", 37.68, 35.87),
            geo_point("5", None, 35.88),
        ]

        vertices = TableDetector._shoelace_vertices(items)

        self.assertEqual(
            vertices,
            [
                (35.85, 37.66),
                (35.86, 37.67),
                (35.87, 37.68),
            ],
        )

    def test_find_tables_does_not_crash_on_geo_only_late_caption(self):
        """Geographic-only vertices have utm_x/utm_y None; find_tables
        still has to walk ``_area_scale_break`` when captions change.
        """

        latitudes = [f"{37.10 + index * 0.01:.8f}" for index in range(8)]
        longitudes = [f"{35.20 + index * 0.01:.8f}" for index in range(8)]
        text = "\n".join(
            [
                "--- Sayfa 1 [PDF METİN KATMANI] ---",
                "Tablo 4. Stok Alanı Koordinatları",
                *[str(index) for index in range(1, 9)],
                *latitudes,
                *longitudes,
                "Tablo 5. Yeni ÇED Alanı Koordinatları",
                "1",
                "37.20000000",
                "35.30000000",
                "2",
                "37.21000000",
                "35.31000000",
                "3",
                "37.22000000",
                "35.32000000",
            ]
        )

        tables = TableDetector.find_tables(text)

        self.assertGreaterEqual(len(tables), 1)


if __name__ == "__main__":
    unittest.main()
