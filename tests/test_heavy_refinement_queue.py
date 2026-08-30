import json
import os
import tempfile
import unittest
from pathlib import Path

from src.batch.heavy_refinement_queue import (
    COMPLETED,
    FAILED,
    IN_PROGRESS,
    PENDING,
    HeavyRefinementQueue,
    _queue_lock,
)


class HeavyRefinementQueueTests(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.pdf_path = self.root / "ANKARA" / "EK-2" / "sample.pdf"
        self.pdf_path.parent.mkdir(parents=True)
        self.pdf_path.write_bytes(b"%PDF-1.4\nqueue-test\n")
        self.queue = HeavyRefinementQueue(
            self.root / "queue.json",
            pdf_root=self.root,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    @staticmethod
    def useful_result(**overrides):
        result = {
            "project_type": "EK-2",
            "result_completeness": "USEFUL_PARTIAL",
            "status": "BASARILI",
            "coordinate_count": 20,
            "table_count": 3,
            "polygon_count": 2,
            "transformed_coordinate_count": 20,
            "extraction_strategy": "selective_ocr_full_discovery",
            "ocr_page_numbers": [10, 11],
            "elapsed_seconds": 12.5,
            "final_result_source": "pre_fallback",
            "candidate_page_scores": {"10": 300, "11": 200},
            "pre_fallback_coordinate_count": 20,
            "pre_fallback_table_count": 3,
            "pre_fallback_polygon_count": 2,
            "has_useful_result": True,
            "heavy_fallback_deferred": True,
            "heavy_fallback_defer_reason": "USEFUL_RESULT",
        }
        result.update(overrides)
        return result

    def enqueue(self, **overrides):
        return self.queue.enqueue_from_result(
            self.pdf_path,
            self.useful_result(**overrides),
        )

    def test_useful_partial_deferred_is_enqueued(self):
        outcome = self.enqueue()
        self.assertTrue(outcome["enqueued"])
        self.assertEqual(outcome["job"]["status"], PENDING)

    def test_complete_is_not_enqueued(self):
        outcome = self.enqueue(result_completeness="COMPLETE")
        self.assertFalse(outcome["enqueued"])
        self.assertEqual(outcome["reason"], "RESULT_NOT_USEFUL_PARTIAL")

    def test_insufficient_is_not_enqueued(self):
        outcome = self.enqueue(result_completeness="INSUFFICIENT")
        self.assertFalse(outcome["enqueued"])
        self.assertEqual(outcome["reason"], "RESULT_NOT_USEFUL_PARTIAL")

    def test_unchanged_pdf_is_deduplicated(self):
        first = self.enqueue()
        second = self.enqueue()
        self.assertTrue(first["enqueued"])
        self.assertFalse(second["enqueued"])
        self.assertEqual(
            second["reason"],
            "DUPLICATE_UNCHANGED_PDF",
        )
        self.assertEqual(
            first["job"]["job_id"],
            second["job"]["job_id"],
        )

    def test_pdf_root_does_not_change_canonical_identity(self):
        first = self.enqueue()
        queue_with_different_root = HeavyRefinementQueue(
            self.queue.storage_path,
            pdf_root=self.pdf_path.parent,
        )
        second = queue_with_different_root.enqueue_from_result(
            self.pdf_path,
            self.useful_result(),
        )
        self.assertFalse(second["enqueued"])
        self.assertEqual(
            first["job"]["job_id"],
            second["job"]["job_id"],
        )

    def test_changed_pdf_creates_new_job_identity(self):
        first = self.enqueue()
        self.pdf_path.write_bytes(
            b"%PDF-1.4\nqueue-test-changed\n"
        )
        stat = self.pdf_path.stat()
        os.utime(
            self.pdf_path,
            ns=(stat.st_atime_ns, stat.st_mtime_ns + 1),
        )
        second = self.enqueue()
        self.assertTrue(second["enqueued"])
        self.assertNotEqual(
            first["job"]["job_id"],
            second["job"]["job_id"],
        )

    def test_persistence_is_atomic_and_valid_json(self):
        self.enqueue()
        state = json.loads(
            self.queue.storage_path.read_text(encoding="utf-8")
        )
        self.assertEqual(state["schema_version"], 1)
        self.assertEqual(len(state["jobs"]), 1)
        self.assertEqual(
            list(self.root.glob("queue.json.tmp.*")),
            [],
        )

    def test_status_transitions_and_claim(self):
        job_id = self.enqueue()["job"]["job_id"]
        claimed = self.queue.claim_next()
        self.assertEqual(claimed["job_id"], job_id)
        self.assertEqual(claimed["status"], IN_PROGRESS)
        self.assertEqual(claimed["attempts"], 1)
        completed = self.queue.transition(
            job_id,
            COMPLETED,
            reason="REFINEMENT_SAVED_SEPARATELY",
        )
        self.assertEqual(completed["status"], COMPLETED)

    def test_invalid_transition_does_not_change_state(self):
        job_id = self.enqueue()["job"]["job_id"]
        before = self.queue.get_job(job_id)
        with self.assertRaises(ValueError):
            self.queue.transition(job_id, COMPLETED)
        after = self.queue.get_job(job_id)
        self.assertEqual(before, after)

    def test_primary_snapshot_is_preserved(self):
        source = self.useful_result()
        outcome = self.queue.enqueue_from_result(
            self.pdf_path,
            source,
        )
        job_id = outcome["job"]["job_id"]
        original_primary = outcome["job"]["primary"]
        source["coordinate_count"] = 999
        self.queue.claim_next()
        self.queue.transition(job_id, FAILED, reason="TEST")
        stored = self.queue.get_job(job_id)
        self.assertEqual(stored["primary"], original_primary)
        self.assertEqual(stored["primary"]["coordinate_count"], 20)
        self.assertIsNone(stored["refined_result"])

    def test_missing_optional_metadata_does_not_crash(self):
        minimal = {
            "result_completeness": "USEFUL_PARTIAL",
            "has_useful_result": True,
            "heavy_fallback_deferred": True,
        }
        outcome = self.queue.enqueue_from_result(
            self.pdf_path,
            minimal,
        )
        self.assertTrue(outcome["enqueued"])
        self.assertEqual(
            outcome["job"]["manual_review"]["candidate_pages"],
            [],
        )

    def test_manual_review_schema_is_ready(self):
        manual_review = self.enqueue()["job"]["manual_review"]
        self.assertEqual(manual_review["status"], "NOT_REVIEWED")
        self.assertEqual(manual_review["candidate_pages"], [10, 11])
        self.assertEqual(manual_review["selected_pages"], [])
        self.assertEqual(manual_review["selected_regions"], [])

    def test_in_progress_is_not_automatically_recovered(self):
        job_id = self.enqueue()["job"]["job_id"]
        self.queue.claim_next()
        reloaded = HeavyRefinementQueue(
            self.queue.storage_path,
            pdf_root=self.root,
        )
        self.assertEqual(
            reloaded.get_job(job_id)["status"],
            IN_PROGRESS,
        )
        recovered = reloaded.recover_in_progress(
            job_id,
            PENDING,
            reason="OPERATOR_CONFIRMED_RETRY",
        )
        self.assertEqual(recovered["status"], PENDING)
        self.assertTrue(
            recovered["status_history"][-1]["recovery"]
        )

    def test_lock_blocks_a_second_writer(self):
        with _queue_lock(self.queue.lock_path):
            with self.assertRaises(RuntimeError):
                self.enqueue()
        self.assertFalse(self.queue.lock_path.exists())


if __name__ == "__main__":
    unittest.main()
