import math
import unittest

from src.coordinate import ring_geometry as ring_geometry_module
from src.coordinate.polygon_builder import PolygonBuilder
from src.coordinate.ring_geometry import (
    count_ring_crossings,
    find_bowtie_edge_pair,
    repair_self_intersecting_ring,
    repair_self_intersecting_rings,
    ring_is_simple,
)


def vertex(y, x, name="P"):
    return {
        "name": name,
        "y": y,
        "x": x,
    }


def star_ring(vertex_count, step, scale=1000.0):
    points = []
    for index in range(vertex_count):
        angle = -math.pi / 2 + index * step * 2 * math.pi / vertex_count
        points.append(
            vertex(
                scale * math.cos(angle),
                scale * math.sin(angle),
                f"P{index}",
            )
        )
    return points


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
        rings = repair_self_intersecting_rings(bowtie)
        self.assertEqual(len(rings), 1)
        self.assertTrue(ring_is_simple(rings[0]))

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

    def test_few_cross_ring_becomes_simple(self):
        # Three proper crossings; iterative uncross yields one simple ring.
        ring = [
            vertex(0, 3),
            vertex(6, 3),
            vertex(0, 0),
            vertex(6, 0),
            vertex(0, 6),
            vertex(6, 6),
        ]
        self.assertGreaterEqual(count_ring_crossings(ring), 2)
        rings = repair_self_intersecting_rings(ring)
        self.assertGreaterEqual(len(rings), 1)
        for part in rings:
            self.assertTrue(ring_is_simple(part))
            self.assertGreaterEqual(len(part), 3)
            self.assertEqual(count_ring_crossings(part), 0)

    def test_pentagram_multi_cross_becomes_simple(self):
        pentagram = star_ring(5, 2)
        self.assertGreaterEqual(count_ring_crossings(pentagram), 4)
        rings = repair_self_intersecting_rings(pentagram)
        self.assertGreaterEqual(len(rings), 1)
        for part in rings:
            self.assertTrue(ring_is_simple(part))
            self.assertEqual(count_ring_crossings(part), 0)

    def test_dense_star_is_repaired_or_split_into_simple_parts(self):
        star = star_ring(9, 4)
        self.assertGreaterEqual(count_ring_crossings(star), 4)
        rings = repair_self_intersecting_rings(star)
        self.assertGreaterEqual(len(rings), 1)
        for part in rings:
            self.assertTrue(ring_is_simple(part))
            self.assertEqual(count_ring_crossings(part), 0)
            self.assertGreaterEqual(len(part), 3)

    def test_split_path_produces_simple_parts_when_uncross_is_disabled(self):
        pentagram = star_ring(5, 2)
        original_limit = ring_geometry_module.MAX_UNCROSS_ITERATIONS
        ring_geometry_module.MAX_UNCROSS_ITERATIONS = 0
        try:
            rings = repair_self_intersecting_rings(pentagram)
        finally:
            ring_geometry_module.MAX_UNCROSS_ITERATIONS = original_limit

        self.assertGreaterEqual(len(rings), 2)
        for part in rings:
            self.assertTrue(ring_is_simple(part))
            self.assertEqual(count_ring_crossings(part), 0)

        bowtie = [
            vertex(0, 0, "A"),
            vertex(10, 10, "B"),
            vertex(10, 0, "C"),
            vertex(0, 10, "D"),
        ]
        ring_geometry_module.MAX_UNCROSS_ITERATIONS = 0
        try:
            split_bowtie = repair_self_intersecting_rings(bowtie)
        finally:
            ring_geometry_module.MAX_UNCROSS_ITERATIONS = original_limit
        self.assertEqual(len(split_bowtie), 2)
        self.assertTrue(all(ring_is_simple(part) for part in split_bowtie))

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

    def test_polygon_builder_emits_simple_parts_for_multi_cross_group(self):
        pentagram = star_ring(5, 2)
        coordinates = []
        for point in pentagram:
            coordinates.append(
                {
                    "name": point["name"],
                    "y": point["y"],
                    "x": point["x"],
                    "table_type": "CED_ALANI",
                    "section": "ÇED Alanı",
                    "table_index": 1,
                    "polygon_group": "DEFAULT",
                }
            )

        original_limit = ring_geometry_module.MAX_UNCROSS_ITERATIONS
        ring_geometry_module.MAX_UNCROSS_ITERATIONS = 0
        try:
            polygons = PolygonBuilder.build(coordinates)
        finally:
            ring_geometry_module.MAX_UNCROSS_ITERATIONS = original_limit

        self.assertGreaterEqual(len(polygons), 2)
        for polygon in polygons:
            self.assertTrue(ring_is_simple(polygon["points"]))
            self.assertGreaterEqual(polygon["point_count"], 3)


if __name__ == "__main__":
    unittest.main()
