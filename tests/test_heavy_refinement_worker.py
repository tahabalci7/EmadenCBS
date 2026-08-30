import copy
import json
import tempfile
import unittest
import inspect
from pathlib import Path

from src.batch.heavy_refinement_queue import (
    COMPLETED,
    FAILED,
    HeavyRefinementQueue,
    build_compact_geometry_snapshot,
    compare_geometry_snapshots,
)
from src.batch.heavy_refinement_worker import (
    HeavyRefinementWorker,
    main,
)
from src.batch.ced_batch_processor import CEDBatchProcessor


class FakeProcessor:

    def __init__(self, result, calls, error=None):
        self.result = result
        self.calls = calls
        self.error = error

    def process_pdf(
        self,
        pdf_path,
        project_type,
        defer_heavy_fallback_if_useful,
        include_geometry_snapshot=False,
    ):
        self.calls.append(
            {
                "pdf_path": str(pdf_path),
                "project_type": project_type,
                "defer": defer_heavy_fallback_if_useful,
                "include_geometry_snapshot": include_geometry_snapshot,
            }
        )
        if self.error is not None:
            raise self.error
        return copy.deepcopy(self.result)


class HeavyRefinementWorkerTests(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.pdf_path = (
            self.root / "ANKARA" / "EK-2" / "sample.pdf"
        )
        self.pdf_path.parent.mkdir(parents=True)
        self.pdf_path.write_bytes(b"%PDF-1.4\nworker-test\n")
        self.queue = HeavyRefinementQueue(
            self.root / "queue.json",
            pdf_root=self.root,
        )
        self.calls = []

    def tearDown(self):
        self.temp_dir.cleanup()

    @staticmethod
    def coordinates(extra=False, duplicate=False):
        points = [
            HeavyRefinementWorkerTests.point(500000, 4200000),
            HeavyRefinementWorkerTests.point(500100, 4200000),
            HeavyRefinementWorkerTests.point(500100, 4200100),
        ]
        if extra:
            points.append(
                HeavyRefinementWorkerTests.point(
                    500000,
                    4200100,
                )
            )
        if duplicate:
            points.append(copy.deepcopy(points[0]))
        return points

    @staticmethod
    def point(
        y_value,
        x_value,
        epsg=23036,
        confidence="HIGH",
        conflict=False,
        observation="obs_test",
    ):
        return {
            "y": y_value,
            "x": x_value,
            "table_type": "PROJE_ALANI",
            "section": "Test Tablosu",
            "table_index": 1,
            "polygon_group": "DEFAULT",
            "source_page": 10,
            "source_table_identity": "tbl_test",
            "source_observation_identity": observation,
            "projected_crs_epsg": epsg,
            "crs_confidence": confidence,
            "crs_conflict": conflict,
            "crs_conflicting_epsg": [],
            "crs_conflict_reason": "",
            "transformed_longitude": 35.0,
            "transformed_latitude": 38.0,
        }

    @staticmethod
    def geometry(extra=False, duplicate=False):
        coordinates = HeavyRefinementWorkerTests.coordinates(
            extra=extra,
            duplicate=duplicate,
        )
        polygon = {
            "table_type": "PROJE_ALANI",
            "section": "Test Tablosu",
            "table_index": 1,
            "polygon_group": "DEFAULT",
            "projected_crs_epsg": 23036,
            "crs_confidence": "HIGH",
            "crs_conflict": False,
            "crs_conflicting_epsg": [],
            "points": coordinates[:4],
            "point_count": min(len(coordinates), 4),
        }
        return build_compact_geometry_snapshot(
            coordinates,
            [polygon],
        )

    def primary_result(self, geometry=True):
        result = {
            "province": "ANKARA",
            "project_type": "EK-2",
            "result_completeness": "USEFUL_PARTIAL",
            "status": "BASARILI",
            "coordinate_count": 3,
            "table_count": 1,
            "polygon_count": 1,
            "transformed_coordinate_count": 3,
            "extraction_strategy": "selective_ocr_full_discovery",
            "ocr_page_numbers": [10],
            "elapsed_seconds": 2.0,
            "final_result_source": "pre_fallback",
            "has_useful_result": True,
            "heavy_fallback_deferred": True,
        }
        if geometry:
            result["geometry_snapshot"] = self.geometry()
        return result

    def refined_result(self, geometry=None):
        geometry = geometry or self.geometry()
        return {
            "province": "ANKARA",
            "project_type": "EK-2",
            "status": "BASARILI",
            "coordinate_count": geometry[
                "coordinate_record_count"
            ],
            "table_count": 1,
            "polygon_count": geometry["polygon_count"],
            "transformed_coordinate_count": geometry[
                "transformed_coordinate_count"
            ],
            "extraction_strategy": "general_ocr_fallback",
            "ocr_page_numbers": [10, 11],
            "final_result_source": "general_fallback",
            "geometry_snapshot": geometry,
            "error": "",
        }

    def factory(self, result=None, error=None):
        result = result or self.refined_result()

        def create(**kwargs):
            return FakeProcessor(
                result,
                self.calls,
                error=error,
            )

        return create

    def enqueue(self, geometry=True):
        return self.queue.enqueue_from_result(
            self.pdf_path,
            self.primary_result(geometry=geometry),
        )["job"]

    def worker(self, result=None, error=None):
        return HeavyRefinementWorker(
            self.queue,
            pdf_root=self.root,
            processor_factory=self.factory(
                result=result,
                error=error,
            ),
        )

    def test_pending_job_completes_with_production_heavy_flag(self):
        job_id = self.enqueue()["job_id"]
        outcome = self.worker().run_once()
        self.assertEqual(outcome["status"], COMPLETED)
        self.assertEqual(
            self.queue.get_job(job_id)["status"],
            COMPLETED,
        )
        self.assertEqual(len(self.calls), 1)
        self.assertIs(self.calls[0]["defer"], False)
        self.assertIs(
            self.calls[0]["include_geometry_snapshot"],
            True,
        )
        self.assertEqual(
            outcome["refined_result"]["refinement_outcome"],
            "REFINEMENT_USABLE",
        )

    def test_refined_result_is_separate_and_primary_unchanged(self):
        job = self.enqueue()
        primary_before = copy.deepcopy(job["primary"])
        outcome = self.worker().run_once()
        stored = self.queue.get_job(job["job_id"])
        self.assertEqual(stored["primary"], primary_before)
        self.assertEqual(
            stored["refined_result"],
            outcome["refined_result"],
        )
        self.assertIsNotNone(stored["refined_result"])

    def test_extraction_exception_marks_job_failed(self):
        job_id = self.enqueue()["job_id"]
        outcome = self.worker(
            error=RuntimeError("OCR failed")
        ).run_once()
        self.assertEqual(outcome["status"], FAILED)
        stored = self.queue.get_job(job_id)
        self.assertEqual(stored["status"], FAILED)
        self.assertIn("OCR failed", stored["status_reason"])

    def test_returned_hata_marks_job_failed(self):
        result = self.refined_result()
        result.update({"status": "HATA", "error": "terminal failure"})
        job_id = self.enqueue()["job_id"]
        outcome = self.worker(result=result).run_once()
        self.assertEqual(outcome["status"], FAILED)
        self.assertIn(
            "terminal failure",
            self.queue.get_job(job_id)["status_reason"],
        )

    def test_no_text_completes_as_refinement_unusable(self):
        geometry = build_compact_geometry_snapshot([], [])
        result = self.refined_result(geometry=geometry)
        result.update(
            {
                "status": "METIN_YOK",
                "coordinate_count": 0,
                "table_count": 0,
                "polygon_count": 0,
            }
        )
        job_id = self.enqueue()["job_id"]
        outcome = self.worker(result=result).run_once()
        stored = self.queue.get_job(job_id)
        self.assertEqual(outcome["status"], COMPLETED)
        self.assertEqual(
            stored["refined_result"]["refinement_outcome"],
            "REFINEMENT_UNUSABLE",
        )
        self.assertEqual(
            stored["comparison"]["refinement_outcome"],
            "REFINEMENT_UNUSABLE",
        )

    def test_geometry_snapshot_is_opt_in_by_default(self):
        parameter = inspect.signature(
            CEDBatchProcessor.process_pdf
        ).parameters["include_geometry_snapshot"]
        self.assertIs(parameter.default, False)

    def test_missing_pdf_marks_job_failed(self):
        job_id = self.enqueue()["job_id"]
        self.pdf_path.unlink()
        outcome = self.worker().run_once()
        self.assertEqual(outcome["status"], FAILED)
        self.assertEqual(
            self.queue.get_job(job_id)["status"],
            FAILED,
        )
        self.assertEqual(self.calls, [])

    def test_second_worker_cannot_take_claimed_job(self):
        claimed = self.enqueue()
        self.queue.claim_next()
        outcome = self.worker().run_once()
        self.assertIsNone(outcome)
        self.assertEqual(
            self.queue.get_job(claimed["job_id"])["status"],
            "IN_PROGRESS",
        )

    def test_coordinate_fingerprint_is_deterministic(self):
        coordinates = self.coordinates()
        forward = build_compact_geometry_snapshot(
            coordinates,
            [],
        )
        reverse = build_compact_geometry_snapshot(
            list(reversed(coordinates)),
            [],
        )
        self.assertEqual(
            forward["projected_coordinate_fingerprint"],
            reverse["projected_coordinate_fingerprint"],
        )

    def test_decimal_coordinate_tokens_are_exact_and_canonical(self):
        points = [
            self.point("312452.230", "4312554.000"),
            self.point("312452.23", "4312554"),
            self.point("1.0005", "-0"),
            self.point("1.0004", "0"),
        ]
        snapshot = build_compact_geometry_snapshot(points, [])
        tokens = snapshot["unique_projected_coordinate_tokens"]
        self.assertEqual(len(tokens), 3)
        self.assertIn("EPSG:23036|312452.23|4312554", tokens)
        self.assertIn("EPSG:23036|1.0005|0", tokens)
        self.assertIn("EPSG:23036|1.0004|0", tokens)

    def test_nan_and_infinity_are_invalid(self):
        snapshot = build_compact_geometry_snapshot(
            [self.point("NaN", 1), self.point(1, "Infinity")],
            [],
        )
        self.assertEqual(snapshot["valid_projected_coordinate_count"], 0)
        self.assertEqual(snapshot["invalid_projected_coordinate_count"], 2)

    def test_same_numbers_with_different_epsg_are_distinct(self):
        first = self.point(500000, 4200000)
        second = copy.deepcopy(first)
        second["projected_crs_epsg"] = 23035
        snapshot = build_compact_geometry_snapshot([first, second], [])
        self.assertEqual(snapshot["unique_projected_coordinate_count"], 2)

    def test_only_clean_high_coordinate_enters_strong_set(self):
        clean = self.point(1, 2)
        high_conflict = self.point(
            3,
            4,
            conflict=True,
        )
        conflicting = self.point(
            5,
            6,
            confidence="CONFLICTING",
            conflict=True,
        )
        unresolved = self.point(
            7,
            8,
            epsg=None,
            confidence="UNRESOLVED",
        )
        snapshot = build_compact_geometry_snapshot(
            [clean, high_conflict, conflicting, unresolved],
            [],
        )
        self.assertEqual(snapshot["record_count"], 4)
        self.assertEqual(snapshot["strong_record_count"], 1)
        self.assertEqual(snapshot["strong_unique_projected_count"], 1)
        self.assertEqual(
            snapshot["strong_unique_projected_tokens"],
            ["EPSG:23036|1|2"],
        )
        self.assertEqual(snapshot["crs_high_record_count"], 2)
        self.assertEqual(snapshot["crs_conflicted_record_count"], 2)
        self.assertEqual(snapshot["crs_unresolved_record_count"], 1)

    def test_token_provenance_is_compact_and_deduplicated(self):
        first = self.point(1, 2, observation="obs_a")
        second = self.point(1, 2, observation="obs_b")
        snapshot = build_compact_geometry_snapshot(
            [first, second, copy.deepcopy(second)],
            [],
        )
        provenance = snapshot["coordinate_token_provenance"][
            "EPSG:23036|1|2"
        ]
        self.assertEqual(
            provenance["source_observation_identities"],
            ["obs_a", "obs_b"],
        )
        self.assertEqual(
            provenance["source_table_identities"],
            ["tbl_test"],
        )

    def test_same_numeric_pair_cross_crs_conflict_is_not_new_geometry(self):
        primary_point = self.point(
            500000,
            4200000,
            epsg=23035,
            conflict=True,
            observation="obs_a",
        )
        primary_point["crs_conflicting_epsg"] = [23035, 23036]
        primary_point["crs_conflict_reason"] = (
            "CROSS_OBSERVATION_EPSG_CONFLICT"
        )
        refined_point = self.point(
            500000,
            4200000,
            epsg=23036,
            conflict=True,
            observation="obs_b",
        )
        refined_point["crs_conflicting_epsg"] = [23035, 23036]
        refined_point["crs_conflict_reason"] = (
            "CROSS_OBSERVATION_EPSG_CONFLICT"
        )
        primary = build_compact_geometry_snapshot(
            [primary_point],
            [],
        )
        refined = build_compact_geometry_snapshot(
            [primary_point, refined_point],
            [],
        )
        comparison = compare_geometry_snapshots(primary, refined)
        self.assertEqual(comparison["classification"], "MIXED_OR_OTHER")
        self.assertNotEqual(
            comparison["classification"],
            "NEW_UNIQUE_GEOMETRY",
        )
        self.assertIn(
            "CRS_CONFLICT_PRESENT",
            comparison["diagnostic_reasons"],
        )
        self.assertIn(
            "NO_STRONG_CRS_GEOMETRY",
            comparison["diagnostic_reasons"],
        )
        self.assertEqual(refined["conflicting_numeric_pair_count"], 1)

    def test_polygon_strong_comparability_requires_no_conflict(self):
        clean = self.geometry()
        self.assertTrue(
            clean["polygons"][0]["strong_geometry_comparable"]
        )
        conflicted_points = self.coordinates()
        for point in conflicted_points:
            point["crs_conflict"] = True
            point["crs_conflicting_epsg"] = [23035, 23036]
        conflicted_polygon = {
            "table_type": "PROJE_ALANI",
            "section": "Test Tablosu",
            "table_index": 1,
            "polygon_group": "DEFAULT",
            "projected_crs_epsg": 23036,
            "crs_confidence": "HIGH",
            "crs_conflict": True,
            "crs_conflicting_epsg": [23035, 23036],
            "points": conflicted_points,
        }
        conflicted = build_compact_geometry_snapshot(
            conflicted_points,
            [conflicted_polygon],
        )
        self.assertFalse(
            conflicted["polygons"][0]["strong_geometry_comparable"]
        )

    def test_polygon_ring_is_start_orientation_and_closure_invariant(self):
        points = self.coordinates(extra=True)
        variants = [
            points,
            points[2:] + points[:2],
            list(reversed(points)),
            points + [copy.deepcopy(points[0])],
        ]
        fingerprints = []
        for variant in variants:
            polygon = {
                "table_type": "PROJE_ALANI",
                "polygon_group": "DEFAULT",
                "points": variant,
            }
            fingerprints.append(
                build_compact_geometry_snapshot(
                    variant,
                    [polygon],
                )["polygons"][0]["canonical_ring_fingerprint"]
            )
        self.assertEqual(len(set(fingerprints)), 1)

    def test_polygon_same_point_set_different_topology_is_distinct(self):
        points = self.coordinates(extra=True)
        crossed = [points[0], points[2], points[1], points[3]]
        def fingerprint(ring):
            return build_compact_geometry_snapshot(
                ring,
                [{"table_type": "PROJE_ALANI", "points": ring}],
            )["polygons"][0]["canonical_ring_fingerprint"]
        self.assertNotEqual(fingerprint(points), fingerprint(crossed))

    def test_polygon_same_numbers_different_epsg_is_distinct(self):
        points = self.coordinates(extra=True)
        other = copy.deepcopy(points)
        for point in other:
            point["projected_crs_epsg"] = 23035
        def fingerprint(ring):
            return build_compact_geometry_snapshot(
                ring,
                [{"table_type": "PROJE_ALANI", "points": ring}],
            )["polygons"][0]["canonical_ring_fingerprint"]
        self.assertNotEqual(fingerprint(points), fingerprint(other))

    def test_duplicate_records_do_not_inflate_unique_count(self):
        snapshot = self.geometry(duplicate=True)
        self.assertEqual(snapshot["coordinate_record_count"], 4)
        self.assertEqual(
            snapshot["unique_projected_coordinate_count"],
            3,
        )

    def test_same_geometry_classification(self):
        geometry = self.geometry()
        comparison = compare_geometry_snapshots(
            geometry,
            copy.deepcopy(geometry),
        )
        self.assertEqual(
            comparison["classification"],
            "SAME_GEOMETRY",
        )

    def test_new_unique_geometry_classification(self):
        refined_coordinates = self.coordinates(
            extra=True
        )
        refined_polygon_points = refined_coordinates[:3]
        refined = build_compact_geometry_snapshot(
            refined_coordinates,
            [{
                "table_type": "PROJE_ALANI",
                "section": "Test Tablosu",
                "table_index": 1,
                "polygon_group": "DEFAULT",
                "projected_crs_epsg": 23036,
                "crs_confidence": "HIGH",
                "crs_conflict": False,
                "points": refined_polygon_points,
                "point_count": 3,
            }],
        )
        comparison = compare_geometry_snapshots(
            self.geometry(),
            refined,
        )
        self.assertEqual(
            comparison["classification"],
            "NEW_UNIQUE_GEOMETRY",
        )
        self.assertEqual(
            comparison["refined_only_unique_projected"],
            1,
        )

    def test_semantic_or_repeat_only_classification(self):
        primary = self.geometry()
        refined = copy.deepcopy(primary)
        repeated_polygon = copy.deepcopy(
            refined["polygons"][0]
        )
        repeated_polygon["area_type"] = "STOK_ALANI"
        refined["polygons"].append(repeated_polygon)
        refined["polygon_count"] = 2
        refined["polygon_area_type_counts"] = {
            "PROJE_ALANI": 1,
            "STOK_ALANI": 1,
        }
        comparison = compare_geometry_snapshots(
            primary,
            refined,
        )
        self.assertEqual(
            comparison["classification"],
            "SEMANTIC_OR_REPEAT_ONLY",
        )

    def test_bidirectional_strong_difference_is_mixed(self):
        primary_points = self.coordinates()
        refined_points = copy.deepcopy(primary_points)
        refined_points[-1] = self.point(500200, 4200200)
        primary = build_compact_geometry_snapshot(
            primary_points,
            [{
                "table_type": "PROJE_ALANI",
                "projected_crs_epsg": 23036,
                "crs_confidence": "HIGH",
                "crs_conflict": False,
                "points": primary_points,
            }],
        )
        refined = build_compact_geometry_snapshot(
            refined_points,
            [{
                "table_type": "PROJE_ALANI",
                "projected_crs_epsg": 23036,
                "crs_confidence": "HIGH",
                "crs_conflict": False,
                "points": refined_points,
            }],
        )
        comparison = compare_geometry_snapshots(primary, refined)
        self.assertEqual(comparison["classification"], "MIXED_OR_OTHER")
        self.assertEqual(comparison["strong_primary_only"], 1)
        self.assertEqual(comparison["strong_refined_only"], 1)

    def test_unresolved_crs_comparison_is_conservative(self):
        points = self.coordinates()
        for point in points:
            point["projected_crs_epsg"] = None
        polygon = {"table_type": "PROJE_ALANI", "points": points}
        geometry = build_compact_geometry_snapshot(points, [polygon])
        comparison = compare_geometry_snapshots(geometry, geometry)
        self.assertEqual(comparison["classification"], "MIXED_OR_OTHER")
        self.assertEqual(
            comparison["diagnostic_reason"],
            "NO_STRONG_CRS_GEOMETRY",
        )
        self.assertIn(
            "NO_STRONG_CRS_GEOMETRY",
            comparison["diagnostic_reasons"],
        )

    def test_legacy_hash_only_snapshot_falls_back_safely(self):
        legacy = {
            "coordinate_record_count": 1,
            "unique_projected_coordinate_hashes": ["old-hash"],
            "polygon_count": 0,
            "polygons": [],
        }
        comparison = compare_geometry_snapshots(legacy, self.geometry())
        self.assertEqual(
            comparison["classification"],
            "PRIMARY_GEOMETRY_UNAVAILABLE",
        )
        self.assertEqual(
            comparison["diagnostic_reason"],
            "TOKEN_COMPARISON_UNAVAILABLE",
        )

    def test_missing_primary_geometry_is_unavailable(self):
        job = self.enqueue(geometry=False)
        outcome = self.worker().run_once()
        self.assertEqual(
            outcome["comparison"]["classification"],
            "PRIMARY_GEOMETRY_UNAVAILABLE",
        )
        self.assertEqual(
            self.queue.get_job(job["job_id"])["status"],
            COMPLETED,
        )

    def test_manual_review_is_unchanged(self):
        job = self.enqueue()
        before = copy.deepcopy(job["manual_review"])
        self.worker().run_once()
        after = self.queue.get_job(
            job["job_id"]
        )["manual_review"]
        self.assertEqual(before, after)

    def test_old_job_without_primary_geometry_is_supported(self):
        job = self.enqueue()
        state = json.loads(
            self.queue.storage_path.read_text(encoding="utf-8")
        )
        state["jobs"][job["job_id"]].pop(
            "primary_geometry"
        )
        self.queue.storage_path.write_text(
            json.dumps(state),
            encoding="utf-8",
        )
        outcome = self.worker().run_once()
        self.assertEqual(
            outcome["comparison"]["classification"],
            "PRIMARY_GEOMETRY_UNAVAILABLE",
        )

    def test_cli_requires_explicit_work_limit(self):
        with self.assertRaises(SystemExit):
            main(
                [
                    "--queue",
                    str(self.queue.storage_path),
                    "--pdf-root",
                    str(self.root),
                ]
            )


if __name__ == "__main__":
    unittest.main()
