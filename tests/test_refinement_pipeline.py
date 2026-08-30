import copy
import inspect
import json
import os
import tempfile
import unittest
from pathlib import Path

from src.batch.ced_batch_processor import CEDBatchProcessor
from src.batch.heavy_refinement_queue import (
    HeavyRefinementQueue,
    build_compact_geometry_snapshot,
)
from src.batch.refinement_pipeline import (
    RefinementPipeline,
)


class FakeProcessor:

    def __init__(self, result):
        self.result = result
        self.calls = []

    def process_pdf(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        return copy.deepcopy(self.result)


class ErrorQueue:

    def enqueue_from_result(self, pdf_path, result):
        raise OSError("queue locked")


class RefinementPipelineTests(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.pdf_path = (
            self.root / "ANKARA" / "EK-2" / "sample.pdf"
        )
        self.pdf_path.parent.mkdir(parents=True)
        self.pdf_path.write_bytes(b"%PDF-1.4\npipeline-test\n")
        self.queue = HeavyRefinementQueue(
            self.root / "queue.json",
            pdf_root=self.root,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    @staticmethod
    def geometry_snapshot():
        coordinates = [
            {
                "y": 500000,
                "x": 4200000,
                "table_type": "PROJE_ALANI",
                "section": "Test",
                "table_index": 1,
                "polygon_group": "DEFAULT",
                "projected_crs_epsg": 23036,
                "crs_confidence": "HIGH",
                "crs_conflict": False,
                "source_table_identity": "tbl_test",
                "source_observation_identity": "obs_test",
            },
            {
                "y": 500100,
                "x": 4200000,
                "table_type": "PROJE_ALANI",
                "section": "Test",
                "table_index": 1,
                "polygon_group": "DEFAULT",
                "projected_crs_epsg": 23036,
                "crs_confidence": "HIGH",
                "crs_conflict": False,
                "source_table_identity": "tbl_test",
                "source_observation_identity": "obs_test",
            },
            {
                "y": 500100,
                "x": 4200100,
                "table_type": "PROJE_ALANI",
                "section": "Test",
                "table_index": 1,
                "polygon_group": "DEFAULT",
                "projected_crs_epsg": 23036,
                "crs_confidence": "HIGH",
                "crs_conflict": False,
                "source_table_identity": "tbl_test",
                "source_observation_identity": "obs_test",
            },
        ]
        polygon = {
            "table_type": "PROJE_ALANI",
            "section": "Test",
            "table_index": 1,
            "polygon_group": "DEFAULT",
            "projected_crs_epsg": 23036,
            "crs_confidence": "HIGH",
            "crs_conflict": False,
            "points": coordinates,
        }
        return build_compact_geometry_snapshot(
            coordinates,
            [polygon],
        )

    def result(self, completeness="USEFUL_PARTIAL", **overrides):
        useful = completeness == "USEFUL_PARTIAL"
        result = {
            "pdf": str(self.pdf_path),
            "file_name": self.pdf_path.name,
            "province": "ANKARA",
            "project_type": "EK-2",
            "status": "BASARILI",
            "result_completeness": completeness,
            "has_useful_result": useful,
            "heavy_fallback_deferred": useful,
            "coordinate_count": 3,
            "table_count": 1,
            "polygon_count": 1,
            "geometry_snapshot": self.geometry_snapshot(),
        }
        result.update(overrides)
        return result

    def pipeline(self, result, queue=None):
        processor = FakeProcessor(result)
        pipeline = RefinementPipeline(
            queue or self.queue,
            batch_processor=processor,
        )
        return pipeline, processor

    def test_complete_returns_primary_without_enqueue(self):
        pipeline, processor = self.pipeline(
            self.result("COMPLETE")
        )
        result = pipeline.process_pdf(self.pdf_path, "EK-2")
        self.assertEqual(result["status"], "BASARILI")
        self.assertFalse(result["refinement"]["eligible"])
        self.assertFalse(result["refinement"]["enqueued"])
        self.assertEqual(self.queue.list_jobs(), [])
        self.assertEqual(len(processor.calls), 1)

    def test_useful_partial_returns_primary_and_enqueues(self):
        source = self.result()
        pipeline, _ = self.pipeline(source)
        result = pipeline.process_pdf(self.pdf_path, "EK-2")
        metadata = result["refinement"]
        self.assertEqual(result["coordinate_count"], 3)
        self.assertTrue(metadata["eligible"])
        self.assertTrue(metadata["enqueued"])
        self.assertIsNotNone(metadata["job_id"])
        job = self.queue.get_job(metadata["job_id"])
        self.assertEqual(job["primary"]["coordinate_count"], 3)
        self.assertEqual(
            job["primary_geometry"]["strong_unique_projected_count"],
            3,
        )

    def test_primary_extraction_uses_exact_flags(self):
        pipeline, processor = self.pipeline(self.result())
        pipeline.process_pdf(self.pdf_path, "EK-2")
        call = processor.calls[0]
        self.assertIs(
            call["defer_heavy_fallback_if_useful"],
            True,
        )
        self.assertIs(call["include_geometry_snapshot"], True)

    def test_insufficient_does_not_enqueue(self):
        pipeline, _ = self.pipeline(
            self.result(
                "INSUFFICIENT",
                has_useful_result=False,
                heavy_fallback_deferred=False,
                coordinate_count=0,
                polygon_count=0,
            )
        )
        result = pipeline.process_pdf(self.pdf_path, "EK-2")
        self.assertFalse(result["refinement"]["enqueued"])
        self.assertEqual(self.queue.list_jobs(), [])

    def test_duplicate_unchanged_is_idempotent(self):
        pipeline, _ = self.pipeline(self.result())
        first = pipeline.process_pdf(self.pdf_path, "EK-2")
        second = pipeline.process_pdf(self.pdf_path, "EK-2")
        self.assertTrue(first["refinement"]["enqueued"])
        self.assertFalse(second["refinement"]["enqueued"])
        self.assertTrue(second["refinement"]["eligible"])
        self.assertEqual(
            second["refinement"]["enqueue_reason"],
            "DUPLICATE_UNCHANGED_PDF",
        )
        self.assertEqual(len(self.queue.list_jobs()), 1)

    def test_changed_pdf_creates_new_job(self):
        pipeline, _ = self.pipeline(self.result())
        first = pipeline.process_pdf(self.pdf_path, "EK-2")
        current_mtime = self.pdf_path.stat().st_mtime_ns
        self.pdf_path.write_bytes(
            b"%PDF-1.4\npipeline-test-changed\n"
        )
        os.utime(
            self.pdf_path,
            ns=(current_mtime + 1, current_mtime + 1),
        )
        second = pipeline.process_pdf(self.pdf_path, "EK-2")
        self.assertNotEqual(
            first["refinement"]["job_id"],
            second["refinement"]["job_id"],
        )
        self.assertEqual(len(self.queue.list_jobs()), 2)

    def test_queue_error_does_not_hide_primary(self):
        pipeline, _ = self.pipeline(
            self.result(),
            queue=ErrorQueue(),
        )
        result = pipeline.process_pdf(self.pdf_path, "EK-2")
        self.assertEqual(result["status"], "BASARILI")
        self.assertEqual(result["coordinate_count"], 3)
        self.assertEqual(
            result["refinement"]["enqueue_reason"],
            "QUEUE_ERROR",
        )
        self.assertIn(
            "queue locked",
            result["refinement"]["queue_error"],
        )

    def test_extraction_error_does_not_enqueue(self):
        pipeline, _ = self.pipeline(
            self.result(
                "",
                status="HATA",
                error="OCR failed",
            )
        )
        result = pipeline.process_pdf(self.pdf_path, "EK-2")
        self.assertEqual(result["status"], "HATA")
        self.assertEqual(self.queue.list_jobs(), [])
        self.assertEqual(
            result["refinement"]["enqueue_reason"],
            "PRIMARY_EXTRACTION_ERROR",
        )

    def test_metadata_is_json_safe(self):
        pipeline, _ = self.pipeline(self.result())
        result = pipeline.process_pdf(self.pdf_path, "EK-2")
        json.dumps(result["refinement"], ensure_ascii=False)

    def test_default_batch_processor_contract_is_unchanged(self):
        parameters = inspect.signature(
            CEDBatchProcessor.process_pdf
        ).parameters
        self.assertIs(
            parameters[
                "defer_heavy_fallback_if_useful"
            ].default,
            False,
        )
        self.assertIs(
            parameters["include_geometry_snapshot"].default,
            False,
        )

    def test_orchestration_does_not_change_primary_geometry(self):
        source = self.result()
        geometry_before = copy.deepcopy(
            source["geometry_snapshot"]
        )
        counts_before = (
            source["coordinate_count"],
            source["table_count"],
            source["polygon_count"],
        )
        pipeline, _ = self.pipeline(source)
        result = pipeline.process_pdf(self.pdf_path, "EK-2")
        self.assertEqual(
            result["geometry_snapshot"],
            geometry_before,
        )
        self.assertEqual(
            (
                result["coordinate_count"],
                result["table_count"],
                result["polygon_count"],
            ),
            counts_before,
        )

    def test_worker_is_not_started(self):
        pipeline, _ = self.pipeline(self.result())
        pipeline.process_pdf(self.pdf_path, "EK-2")
        job = self.queue.list_jobs()[0]
        self.assertEqual(job["status"], "PENDING")
        self.assertEqual(job["attempts"], 0)

    def test_process_all_uses_same_orchestration(self):
        pipeline, processor = self.pipeline(
            self.result("COMPLETE")
        )
        results = pipeline.process_all(
            [(self.pdf_path, "EK-2")]
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(len(processor.calls), 1)
        self.assertIn("refinement", results[0])


if __name__ == "__main__":
    unittest.main()
