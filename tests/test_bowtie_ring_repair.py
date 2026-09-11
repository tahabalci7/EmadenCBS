import unittest

from src.coordinate.polygon_builder import PolygonBuilder
from src.coordinate.ring_geometry import (
    find_bowtie_edge_pair,
    repair_self_intersecting_ring,
    ring_is_simple,
)


def vertex(y, x, name="P"):
    return {
        "name": name,
        "y": y,
        "x": x,
    }


class BowtieRingRepairTests(unittest.TestCase):
    def test_classic_bowtie_is_repaired(self):
        bowtie = [
            vertex(0, 0, "A"),
            vertex(10, 10, "B"),
            vertex(10, 0, "C"),
            vertex(0, 10, "D"),
        ]
        self.assertFalse(ring_is_simple(bowtie))
        repaired = repair_self_intersecting_ring(bowtie)
        self.assertTrue(ring_is_simple(repaired))
        self.assertEqual(len(repaired), 4)
        self.assertEqual(
            {(point["y"], point["x"]) for point in repaired},
            {(0, 0), (10, 10), (10, 0), (0, 10)},
        )

    def test_simple_square_is_unchanged(self):
        square = [
            vertex(0, 0, "A"),
            vertex(10, 0, "B"),
            vertex(10, 10, "C"),
            vertex(0, 10, "D"),
        ]
        self.assertTrue(ring_is_simple(square))
        repaired = repair_self_intersecting_ring(square)
        self.assertEqual(
            [(point["y"], point["x"]) for point in repaired],
            [(0, 0), (10, 0), (10, 10), (0, 10)],
        )

    def test_concave_arrowhead_is_unchanged(self):
        concave = [
            vertex(0, 0, "A"),
            vertex(10, 0, "B"),
            vertex(4, 4, "C"),
            vertex(10, 10, "D"),
            vertex(0, 10, "E"),
        ]
        self.assertIsNone(find_bowtie_edge_pair(concave))
        repaired = repair_self_intersecting_ring(concave)
        self.assertEqual(
            [(point["y"], point["x"]) for point in repaired],
            [(0, 0), (10, 0), (4, 4), (10, 10), (0, 10)],
        )

    def test_polygon_builder_repairs_bowtie_group(self):
        coordinates = [
            {
                "name": "A",
                "y": 0,
                "x": 0,
                "table_type": "CED_ALANI",
                "section": "ÇED Alanı",
                "table_index": 1,
                "polygon_group": "DEFAULT",
            },
            {
                "name": "B",
                "y": 10,
                "x": 10,
                "table_type": "CED_ALANI",
                "section": "ÇED Alanı",
                "table_index": 1,
                "polygon_group": "DEFAULT",
            },
            {
                "name": "C",
                "y": 10,
                "x": 0,
                "table_type": "CED_ALANI",
                "section": "ÇED Alanı",
                "table_index": 1,
                "polygon_group": "DEFAULT",
            },
            {
                "name": "D",
                "y": 0,
                "x": 10,
                "table_type": "CED_ALANI",
                "section": "ÇED Alanı",
                "table_index": 1,
                "polygon_group": "DEFAULT",
            },
        ]
        polygons = PolygonBuilder.build(coordinates)
        self.assertEqual(len(polygons), 1)
        self.assertTrue(ring_is_simple(polygons[0]["points"]))


if __name__ == "__main__":
    unittest.main()
