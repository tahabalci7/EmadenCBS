import json
import os
import tempfile
import unittest
from pathlib import Path

from src.batch.primary_production_benchmark import (
    AMBIGUOUS,
    HEAVY_INLINE_USABLE,
    NO_USABLE_RESULT,
    QUICK_USABLE,
    classify_primary_result,
    prepare_representative_manifest,
    representative_allocation,
    run_primary_benchmark,
    select_representative_sample,
    weighted_projection,
)


class FakeProcessor:

    calls = []

    def __init__(self, province, downloads_root):
        self.province = province
        self.downloads_root = downloads_root

    def process_pdf(
        self,
        pdf_path,
        project_type,
        defer_heavy_fallback_if_useful=False,
        include_geometry_snapshot=False,
    ):
        self.__class__.calls.append(str(pdf_path))
        partial = "partial" in Path(pdf_path).stem
        return {
            "status": "BASARILI",
            "result_completeness": (
                "USEFUL_PARTIAL" if partial else "COMPLETE"
            ),
            "has_useful_result": partial,
            "heavy_fallback_deferred": partial,
            "general_fallback_used": False,
            "coordinate_count": 3,
            "table_count": 1,
            "polygon_count": 1,
            "transformed_coordinate_count": 3,
            "ocr_page_numbers": [],
            "geometry_snapshot": {
                "strong_unique_projected_count": 3,
                "crs_conflicted_record_count": 0,
                "strong_comparable_polygon_count": 1,
            },
        }


class PrimaryProductionBenchmarkTests(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "corpus"
        self.output = self.root / "benchmark"
        self.preflight_path = (
            Path(self.temp_dir.name) / "preflight.jsonl"
        )
        self.manifest_path = (
            Path(self.temp_dir.name) / "manifest.txt"
        )
        FakeProcessor.calls = []

    def tearDown(self):
        self.temp_dir.cleanup()

    def make_record(
        self,
        index,
        classification="FAST_TEXT_LIKELY",
        project_type="EK-2",
        partial=False,
    ):
        name = f"{index:03d}{'_partial' if partial else ''}.pdf"
        path = self.root / "ANKARA" / project_type / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"%PDF-1.4\ntest\n")
        stat = path.stat()
        relative = path.relative_to(self.root).as_posix()
        record = {
            "path": path.resolve(),
            "relative_path": relative,
            "province": "ANKARA",
            "project_type": project_type,
            "file_size": stat.st_size,
            "modified_time_ns": stat.st_mtime_ns,
            "modified_time": "2026-01-01T00:00:00+00:00",
        }
        preflight = {
            key: value
            for key, value in record.items()
            if key != "path"
        }
        preflight["classification"] = classification
        return record, preflight

    def balanced_fixture(self):
        records = []
        preflight = []
        index = 0
        for classification in (
            "FAST_TEXT_LIKELY",
            "SELECTIVE_OCR_CANDIDATE",
            "WIDER_DISCOVERY_NEEDED",
            "SCAN_OR_HEAVY_FALLBACK_RISK",
            "UNCERTAIN",
        ):
            for project_type in ("EK-1", "EK-2"):
                for _ in range(4):
                    index += 1
                    record, item = self.make_record(
                        index,
                        classification,
                        project_type,
                    )
                    records.append(record)
                    preflight.append(item)
        return records, preflight

    def write_preflight(self, items):
        with self.preflight_path.open(
            "w",
            encoding="utf-8",
        ) as file:
            for item in items:
                file.write(json.dumps(item) + "\n")

    def test_representative_allocation_total_and_cell_coverage(self):
        _, preflight = self.balanced_fixture()
        allocation = representative_allocation(
            preflight,
            sample_size=20,
        )
        self.assertEqual(sum(allocation.values()), 20)
        self.assertTrue(all(count > 0 for count in allocation.values()))

    def test_sample_is_deterministic_and_has_no_duplicates(self):
        records, preflight = self.balanced_fixture()
        first, _ = select_representative_sample(
            records,
            preflight,
            sample_size=20,
        )
        second, _ = select_representative_sample(
            list(reversed(records)),
            list(reversed(preflight)),
            sample_size=20,
        )
        first_paths = [item["relative_path"] for item in first]
        second_paths = [item["relative_path"] for item in second]
        self.assertEqual(first_paths, second_paths)
        self.assertEqual(len(first_paths), len(set(first_paths)))

    def test_manifest_hash_is_stable(self):
        _, preflight = self.balanced_fixture()
        self.write_preflight(preflight)
        first = prepare_representative_manifest(
            self.root,
            self.output,
            self.preflight_path,
            self.manifest_path,
            sample_size=20,
        )
        second = prepare_representative_manifest(
            self.root,
            self.output,
            self.preflight_path,
            self.manifest_path,
            sample_size=20,
        )
        self.assertEqual(
            first["manifest_sha256"],
            second["manifest_sha256"],
        )
        self.assertEqual(
            len(self.manifest_path.read_text().splitlines()),
            20,
        )

    def test_speed_classification(self):
        self.assertEqual(
            classify_primary_result({
                "status": "BASARILI",
                "polygon_count": 1,
                "general_fallback_used": False,
            }),
            QUICK_USABLE,
        )
        self.assertEqual(
            classify_primary_result({
                "status": "BASARILI",
                "polygon_count": 1,
                "general_fallback_used": True,
            }),
            HEAVY_INLINE_USABLE,
        )
        self.assertEqual(
            classify_primary_result({
                "status": "BASARILI",
                "polygon_count": 0,
                "general_fallback_used": False,
            }),
            NO_USABLE_RESULT,
        )
        self.assertEqual(
            classify_primary_result({
                "status": "BASARILI",
                "polygon_count": 1,
            }),
            AMBIGUOUS,
        )

    def test_run_resume_and_isolated_pending_queue(self):
        records = []
        preflight = []
        for index, partial in ((1, False), (2, True)):
            record, item = self.make_record(
                index,
                partial=partial,
            )
            records.append(record)
            preflight.append(item)
        self.write_preflight(preflight)
        self.manifest_path.write_text(
            "\n".join(item["relative_path"] for item in records) + "\n",
            encoding="utf-8",
        )
        first = run_primary_benchmark(
            self.root,
            self.output,
            self.preflight_path,
            self.manifest_path,
            "test_run",
            processor_factory=FakeProcessor,
        )
        calls_after_first = len(FakeProcessor.calls)
        second = run_primary_benchmark(
            self.root,
            self.output,
            self.preflight_path,
            self.manifest_path,
            "test_run",
            resume=True,
            processor_factory=FakeProcessor,
        )
        self.assertEqual(calls_after_first, 2)
        self.assertEqual(len(FakeProcessor.calls), calls_after_first)
        self.assertTrue(first["completed"])
        self.assertTrue(second["completed"])
        queue_path = (
            self.output
            / "runs"
            / "test_run"
            / "heavy_refinement_queue.json"
        )
        state = json.loads(queue_path.read_text(encoding="utf-8"))
        jobs = list(state["jobs"].values())
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["status"], "PENDING")
        self.assertEqual(jobs[0]["attempts"], 0)

    def test_weighted_projection_and_zero_sample_cell(self):
        preflight = [
            {
                "classification": "FAST_TEXT_LIKELY",
                "project_type": "EK-1",
            },
            {
                "classification": "FAST_TEXT_LIKELY",
                "project_type": "EK-2",
            },
        ]
        results = [
            {
                "preflight_class": "FAST_TEXT_LIKELY",
                "project_type": "EK-1",
                "primary_speed_class": QUICK_USABLE,
            }
        ]
        projection = weighted_projection(results, preflight)
        self.assertEqual(projection["corpus_population"], 2)
        self.assertEqual(projection["covered_population"], 1)
        self.assertEqual(projection["coverage_percent"], 50.0)
        self.assertTrue(projection["partial_coverage"])
        missing = projection["cells"]["FAST_TEXT_LIKELY|EK-2"]
        self.assertFalse(missing["projection_available"])


if __name__ == "__main__":
    unittest.main()
