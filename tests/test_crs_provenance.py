import unittest
from unittest import mock

from src.coordinate.coordinate_engine import CoordinateEngine
from src.coordinate.crs_resolver import CRSResolver
from src.coordinate.datum_detector import DatumDetector
from src.coordinate.polygon_builder import PolygonBuilder
from src.coordinate.table_detector import TableDetector


class CRSProvenanceTests(unittest.TestCase):

    @staticmethod
    def point(y_value, x_value, epsg):
        return {
            "y": y_value,
            "x": x_value,
            "projected_crs_epsg": epsg,
            "crs_source": "EXPLICIT_TABLE_TEXT",
            "crs_confidence": "HIGH",
            "crs_zone_candidates": [str(epsg)[-2:]] if epsg else [],
            "crs_datum_candidates": ["ED-50"] if epsg else [],
            "crs_conflict": False,
            "crs_conflicting_epsg": [],
            "crs_conflict_reason": "",
            "source_table_identity": "tbl_original",
            "source_observation_identity": "obs_original",
        }

    def test_single_explicit_ed50_zone_35_is_high(self):
        result = DatumDetector.detect("ED-50\nZON 35\n6 Derece")
        self.assertEqual(result["crs_confidence"], "HIGH")
        self.assertEqual(result["crs_source"], "EXPLICIT_TABLE_TEXT")
        self.assertEqual(result["crs_datum_candidates"], ["ED-50"])
        self.assertEqual(result["crs_zone_candidates"], ["35"])
        self.assertEqual(result["crs_conflict_reason"], "")

    def test_single_explicit_ed50_zone_36_is_high(self):
        result = DatumDetector.detect("ED50\nZONE: 36\nUTM")
        self.assertEqual(result["crs_confidence"], "HIGH")
        self.assertEqual(result["zone"], "36")

    def test_missing_zone_is_unresolved(self):
        result = DatumDetector.detect("ED-50\n6 Derece")
        self.assertEqual(result["crs_confidence"], "UNRESOLVED")
        self.assertEqual(result["crs_source"], "UNRESOLVED")

    def test_three_degree_projection_is_not_high_utm_confidence(self):
        result = DatumDetector.detect("ED-50\nZON 35\n3 Derece")
        self.assertEqual(result["crs_confidence"], "UNRESOLVED")
        self.assertIn(
            "UNSUPPORTED_PROJECTION_CONTEXT",
            result["crs_conflict_reason"],
        )

    def test_multiple_explicit_zones_are_conflicting(self):
        result = DatumDetector.detect("ED-50\nZON 35\nZONE 36")
        self.assertEqual(result["crs_confidence"], "CONFLICTING")
        self.assertEqual(result["crs_zone_candidates"], ["35", "36"])
        self.assertIn(
            "SAME_OBSERVATION_ZONE_CONFLICT",
            result["crs_conflict_reason"],
        )

    def test_dom_does_not_supply_zone(self):
        result = DatumDetector.detect("ED-50\nDOM 33\n6 Derece")
        self.assertEqual(result["dom"], "33")
        self.assertEqual(result["zone"], "Bilinmiyor")
        self.assertEqual(result["crs_zone_candidates"], [])
        self.assertEqual(result["crs_confidence"], "UNRESOLVED")

    def test_reliable_resolver_behavior_is_preserved(self):
        crs = CRSResolver.resolve_projected_crs(
            {
                "datum": "ED-50",
                "type": "UTM",
                "zone": "36",
                "projection": "6 Derece",
            }
        )
        self.assertIsNotNone(crs)
        self.assertEqual(crs.to_epsg(), 23036)

    def test_same_numeric_pair_same_epsg_has_no_conflict(self):
        records = [
            self.point("312452.230", "4312554.000", 23035),
            self.point("312452.23", "4312554", 23035),
        ]
        records[1]["source_table_identity"] = "tbl_other"
        records[1]["source_observation_identity"] = "obs_other"
        CoordinateEngine._mark_cross_observation_crs_conflicts(records)
        self.assertTrue(all(not item["crs_conflict"] for item in records))

    def test_same_numeric_pair_different_epsg_marks_conflict(self):
        records = [
            self.point("312452.230", "4312554.000", 23035),
            self.point("312452.23", "4312554", 23036),
        ]
        CoordinateEngine._mark_cross_observation_crs_conflicts(records)
        for record in records:
            self.assertTrue(record["crs_conflict"])
            self.assertEqual(record["crs_confidence"], "HIGH")
            self.assertEqual(record["crs_source"], "EXPLICIT_TABLE_TEXT")
            self.assertEqual(record["crs_conflicting_epsg"], [23035, 23036])
            self.assertEqual(record["source_table_identity"], "tbl_original")
            self.assertEqual(
                record["source_observation_identity"],
                "obs_original",
            )

    def test_resolved_and_unresolved_same_pair_is_not_epsg_conflict(self):
        resolved = self.point(312452.23, 4312554, 23035)
        unresolved = self.point("312452.230", "4312554.000", None)
        unresolved["crs_confidence"] = "UNRESOLVED"
        records = [resolved, unresolved]
        CoordinateEngine._mark_cross_observation_crs_conflicts(records)
        self.assertFalse(resolved["crs_conflict"])
        self.assertFalse(unresolved["crs_conflict"])
        self.assertEqual(resolved["crs_confidence"], "HIGH")
        self.assertEqual(unresolved["crs_confidence"], "UNRESOLVED")

    def test_no_three_decimal_rounding_collision(self):
        records = [
            self.point("312452.0004", 4312554, 23035),
            self.point("312452.0005", 4312554, 23036),
        ]
        CoordinateEngine._mark_cross_observation_crs_conflicts(records)
        self.assertTrue(all(not item["crs_conflict"] for item in records))

    def test_conflicting_observation_does_not_resolve_epsg(self):
        table = "ED-50\nZON 35\nZONE 36\n1 500000 4200000 38 35"
        parsed_point = {
            "label": "1",
            "utm_y": 500000,
            "utm_x": 4200000,
            "latitude": 38,
            "longitude": 35,
            "polygon_group": "DEFAULT",
        }
        with mock.patch.object(
            TableDetector,
            "find_tables",
            return_value=[table],
        ), mock.patch(
            "src.coordinate.coordinate_engine.parse_coordinate_blocks",
            return_value=[parsed_point],
        ):
            results = CoordinateEngine.extract_coordinates(table)
        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0]["projected_crs_epsg"])
        self.assertEqual(results[0]["crs_confidence"], "CONFLICTING")
        self.assertTrue(results[0]["crs_conflict"])
        self.assertIn("source_table_identity", results[0])
        self.assertIn("source_observation_identity", results[0])

    def test_high_observation_preserves_resolver_and_point_provenance(self):
        table = "ED-50\nZONE 36\n6 Derece\n1 500000 4200000 38 35"
        parsed_point = {
            "label": "1",
            "utm_y": 500000,
            "utm_x": 4200000,
            "latitude": 38,
            "longitude": 35,
            "polygon_group": "DEFAULT",
        }
        with mock.patch.object(
            TableDetector,
            "find_tables",
            return_value=[table],
        ), mock.patch(
            "src.coordinate.coordinate_engine.parse_coordinate_blocks",
            return_value=[parsed_point],
        ):
            results = CoordinateEngine.extract_coordinates(table)
        self.assertEqual(results[0]["projected_crs_epsg"], 23036)
        self.assertEqual(results[0]["crs_confidence"], "HIGH")
        self.assertEqual(results[0]["crs_source"], "EXPLICIT_TABLE_TEXT")
        self.assertEqual(results[0]["crs_zone_candidates"], ["36"])
        self.assertFalse(results[0]["crs_conflict"])
        self.assertIn("source_table_identity", results[0])
        self.assertIn("source_observation_identity", results[0])

    def test_polygon_preserves_high_evidence_with_cross_conflict(self):
        points = []
        for index, (y_value, x_value) in enumerate(
            [(0, 0), (10, 0), (10, 10)],
            start=1,
        ):
            point = self.point(y_value, x_value, 23035)
            point.update(
                {
                    "name": str(index),
                    "table_type": "PROJE_ALANI",
                    "section": "Test",
                    "table_index": 1,
                    "polygon_group": "DEFAULT",
                    "crs_conflict": index == 1,
                    "crs_conflicting_epsg": (
                        [23035, 23036] if index == 1 else []
                    ),
                }
            )
            points.append(point)
        polygon = PolygonBuilder.build(points)[0]
        self.assertTrue(polygon["crs_conflict"])
        self.assertEqual(polygon["crs_confidence"], "HIGH")
        self.assertEqual(polygon["crs_conflicting_epsg"], [23035, 23036])
        self.assertTrue(polygon["points"][0]["crs_conflict"])

    def test_strong_comparison_predicate_requires_high_without_conflict(self):
        high_clean = {
            "crs_confidence": "HIGH",
            "crs_conflict": False,
        }
        high_conflicted = {
            "crs_confidence": "HIGH",
            "crs_conflict": True,
        }
        predicate = lambda item: (
            item.get("crs_confidence") == "HIGH"
            and item.get("crs_conflict") is False
        )
        self.assertTrue(predicate(high_clean))
        self.assertFalse(predicate(high_conflicted))


if __name__ == "__main__":
    unittest.main()
