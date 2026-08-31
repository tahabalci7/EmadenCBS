import unittest
from pathlib import Path
from unittest.mock import patch

from src.batch.ced_batch_processor import CEDBatchProcessor
from src.core.pdf_text_extraction_service import (
    PDFTextExtractionService,
)


class FullDiscoveryEarlyExitTests(unittest.TestCase):

    @staticmethod
    def _quality(
        coordinates=0,
        polygons=0,
        tables=0,
        required=False,
    ):
        return {
            "coordinate_count": coordinates,
            "polygon_count": polygons,
            "table_count": tables,
            "has_required_polygons": required,
            "has_useful_result": polygons > 0,
        }

    @classmethod
    def _quality_for_text(cls, text):
        if "COMPLETE" in text:
            return cls._quality(8, 2, 2, required=True)
        if "USABLE" in text:
            return cls._quality(4, 1, 1)
        if "LOW_COORD" in text:
            return cls._quality(2, 0, 1)
        if "HIGH_COORD" in text:
            return cls._quality(10, 0, 2)
        if "COORD" in text:
            return cls._quality(3, 0, 1)
        return cls._quality()

    @staticmethod
    def _text_layer_result(
        text="BASE",
        page_count=40,
        scanned_pages=40,
    ):
        return {
            "success": bool(text),
            "method": "PDF Metin Katmanı",
            "text": text,
            "page_count": page_count,
            "scanned_pages": scanned_pages,
            "text_layer_pages": scanned_pages,
            "ocr_pages": 0,
            "failed_pages": 0,
        }

    @staticmethod
    def _chunk_result(marker, page_number):
        return {
            "success": True,
            "text": (
                f"--- Sayfa {page_number} [OCR] ---\n{marker}"
            ),
            "failed_pages": 0,
        }

    def _run_groups(
        self,
        markers,
        groups=None,
        selected=None,
        base_text="FULL_BASE",
        defer=True,
        stage="FULL_DISCOVERY_OCR",
    ):
        calls = []
        selected = (
            selected
            or PDFTextExtractionService._new_selected_result()
        )
        groups = groups or [[5, 15, 25, 35]]

        def extract_selected_pages(_pdf_path, pages):
            calls.append(list(pages))
            marker = markers[len(calls) - 1]
            if isinstance(marker, Exception):
                raise marker
            return self._chunk_result(marker, pages[0])

        with (
            patch.object(
                PDFTextExtractionService,
                "_measure_text_quality",
                side_effect=self._quality_for_text,
            ),
            patch.object(
                PDFTextExtractionService,
                "_has_required_polygons",
                return_value=False,
            ),
            patch(
                "src.core.pdf_text_extraction_service."
                "OCREngine.extract_selected_pages",
                side_effect=extract_selected_pages,
            ),
        ):
            PDFTextExtractionService._run_target_groups(
                "sample.pdf",
                groups,
                40,
                selected,
                base_text=base_text,
                defer_when_useful=defer,
                stage=stage,
            )

        return selected, calls

    def test_defer_false_does_not_stop_on_partial_usable(self):
        selected, calls = self._run_groups(
            ["USABLE", "USABLE"],
            groups=[[3], [20]],
            defer=False,
        )

        self.assertEqual(len(calls), 2)
        self.assertFalse(selected["selective_ocr_early_exit"])

    def test_first_chunk_usable_stops_remaining_chunks(self):
        selected, calls = self._run_groups(
            ["USABLE", "SHOULD_NOT_RUN", "SHOULD_NOT_RUN"]
        )
        result = PDFTextExtractionService._build_selective_result(
            self._text_layer_result("FULL_BASE"),
            selected,
            strategy="selective_ocr_full_discovery",
            candidate_page_scores={},
            use_best=True,
        )

        self.assertEqual(len(calls), 1)
        self.assertTrue(selected["has_useful_result"])
        self.assertEqual(
            selected["selective_ocr_early_exit_stage"],
            "FULL_DISCOVERY_OCR",
        )
        self.assertEqual(
            selected["selective_ocr_early_exit_reason"],
            "usable_polygon_found",
        )
        self.assertEqual(selected["selective_ocr_chunks_processed"], 1)
        self.assertEqual(
            len(set(selected["selective_ocr_processed_pages"])),
            8,
        )
        self.assertTrue(result["selective_ocr_early_exit"])
        self.assertEqual(
            result["selective_ocr_early_exit_stage"],
            "FULL_DISCOVERY_OCR",
        )

    def test_second_chunk_usable_stops_third_chunk(self):
        selected, calls = self._run_groups(
            ["COORD", "USABLE", "SHOULD_NOT_RUN"]
        )

        self.assertEqual(len(calls), 2)
        self.assertTrue(selected["has_useful_result"])
        self.assertEqual(selected["selective_ocr_chunks_processed"], 2)
        self.assertEqual(
            len(set(selected["selective_ocr_processed_pages"])),
            16,
        )

    def test_fast_second_chunk_usable_stops_remaining_fast_ocr(self):
        selected, calls = self._run_groups(
            ["COORD", "USABLE", "SHOULD_NOT_RUN"],
            stage="FAST_WINDOW",
        )

        self.assertEqual(len(calls), 2)
        self.assertEqual(
            selected["selective_ocr_early_exit_stage"],
            "FAST_WINDOW",
        )

    def test_coordinates_without_polygon_process_all_chunks(self):
        selected, calls = self._run_groups(
            ["COORD", "COORD", "COORD"]
        )

        self.assertEqual(len(calls), 3)
        self.assertFalse(selected["has_useful_result"])
        self.assertFalse(selected["selective_ocr_early_exit"])

    def test_complete_criterion_stays_complete(self):
        selected, calls = self._run_groups(
            ["COMPLETE", "SHOULD_NOT_RUN", "SHOULD_NOT_RUN"]
        )

        self.assertEqual(len(calls), 1)
        self.assertTrue(selected["has_required_polygons"])
        self.assertEqual(
            selected["selective_ocr_early_exit_reason"],
            "complete_criterion_met",
        )

    def test_cumulative_text_contains_base_fast_and_full_ocr(self):
        selected = PDFTextExtractionService._new_selected_result()
        selected["parts"].append("FAST_OCR")
        observed = []

        def quality(text):
            observed.append(text)
            return self._quality_for_text(text)

        with (
            patch.object(
                PDFTextExtractionService,
                "_measure_text_quality",
                side_effect=quality,
            ),
            patch(
                "src.core.pdf_text_extraction_service."
                "OCREngine.extract_selected_pages",
                return_value=self._chunk_result("USABLE", 3),
            ),
        ):
            PDFTextExtractionService._run_target_groups(
                "sample.pdf",
                [[5]],
                40,
                selected,
                base_text="FULL_BASE",
                defer_when_useful=True,
                stage="FULL_DISCOVERY_OCR",
            )

        self.assertTrue(
            any(
                "FULL_BASE" in text
                and "FAST_OCR" in text
                and "USABLE" in text
                for text in observed
            )
        )

    def test_best_non_usable_candidate_is_preserved(self):
        selected, calls = self._run_groups(
            ["HIGH_COORD", "LOW_COORD", "LOW_COORD"]
        )
        result = PDFTextExtractionService._build_selective_result(
            self._text_layer_result("FULL_BASE"),
            selected,
            strategy="selective_ocr_full_discovery",
            candidate_page_scores={},
            use_best=True,
        )

        self.assertEqual(len(calls), 3)
        self.assertIn("HIGH_COORD", result["text"])
        self.assertNotIn("LOW_COORD", result["text"])

    def test_attempted_pages_are_not_ocrd_twice(self):
        selected = PDFTextExtractionService._new_selected_result()
        selected["attempted_pages"] = [3, 4, 5]
        selected, calls = self._run_groups(
            ["USABLE"],
            groups=[[5]],
            selected=selected,
        )

        self.assertEqual(calls, [[6, 7, 8]])
        self.assertEqual(
            sorted(set(selected["attempted_pages"])),
            [3, 4, 5, 6, 7, 8],
        )

    def test_exception_keeps_best_candidate_for_fallback(self):
        selected, calls = self._run_groups(
            ["HIGH_COORD", RuntimeError("ocr failed")]
        )
        result = PDFTextExtractionService._build_selective_result(
            self._text_layer_result("FULL_BASE"),
            selected,
            strategy="selective_ocr_full_discovery",
            candidate_page_scores={},
            use_best=True,
        )

        self.assertEqual(len(calls), 2)
        self.assertEqual(selected["execution_error"], "ocr failed")
        self.assertIn("HIGH_COORD", result["text"])

    def test_fast_window_usable_skips_full_discovery(self):
        fast_result = self._text_layer_result(
            "FAST_BASE",
            page_count=300,
            scanned_pages=150,
        )
        with (
            patch(
                "src.core.pdf_text_extraction_service."
                "OCREngine.extract_text_layer",
                return_value=fast_result,
            ) as extract_text_layer,
            patch(
                "src.core.pdf_text_extraction_service."
                "OCREngine.extract_selected_pages",
                return_value=self._chunk_result("USABLE", 3),
            ),
            patch.object(
                PDFTextExtractionService,
                "_target_groups",
                return_value=([[5]], {5: 100}),
            ),
            patch.object(
                PDFTextExtractionService,
                "_has_required_polygons",
                return_value=False,
            ),
            patch.object(
                PDFTextExtractionService,
                "_measure_text_quality",
                side_effect=self._quality_for_text,
            ),
        ):
            result = PDFTextExtractionService.extract(
                "sample.pdf",
                defer_heavy_fallback_if_useful=True,
            )

        self.assertEqual(extract_text_layer.call_count, 1)
        self.assertEqual(result["result_completeness"], "USEFUL_PARTIAL")
        self.assertTrue(result["heavy_fallback_deferred"])
        self.assertEqual(
            result["selective_ocr_early_exit_stage"],
            "FAST_WINDOW",
        )
        self.assertEqual(result["selective_ocr_chunks_processed"], 1)
        self.assertEqual(result["selective_ocr_pages_processed"], 5)
        self.assertEqual(
            result["selective_ocr_early_exit_reason"],
            "usable_polygon_found",
        )

    def test_complete_result_is_not_marked_partial_or_deferred(self):
        fast_result = self._text_layer_result("FAST_BASE")
        with (
            patch(
                "src.core.pdf_text_extraction_service."
                "OCREngine.extract_text_layer",
                return_value=fast_result,
            ),
            patch(
                "src.core.pdf_text_extraction_service."
                "OCREngine.extract_selected_pages",
                return_value=self._chunk_result("COMPLETE", 3),
            ),
            patch.object(
                PDFTextExtractionService,
                "_target_groups",
                return_value=([[5]], {5: 100}),
            ),
            patch.object(
                PDFTextExtractionService,
                "_has_required_polygons",
                return_value=False,
            ),
            patch.object(
                PDFTextExtractionService,
                "_measure_text_quality",
                side_effect=self._quality_for_text,
            ),
        ):
            result = PDFTextExtractionService.extract(
                "sample.pdf",
                defer_heavy_fallback_if_useful=True,
            )

        self.assertEqual(result["result_completeness"], "COMPLETE")
        self.assertFalse(result["heavy_fallback_deferred"])
        self.assertTrue(result["selective_ocr_early_exit"])
        self.assertEqual(
            result["selective_ocr_early_exit_reason"],
            "complete_criterion_met",
        )

    def test_full_text_discovery_usable_skips_selected_ocr(self):
        fast_result = self._text_layer_result(
            "FAST_BASE",
            page_count=300,
            scanned_pages=150,
        )
        full_result = self._text_layer_result(
            "FULL_USABLE",
            page_count=300,
            scanned_pages=300,
        )
        with (
            patch(
                "src.core.pdf_text_extraction_service."
                "OCREngine.extract_text_layer",
                side_effect=[fast_result, full_result],
            ),
            patch(
                "src.core.pdf_text_extraction_service."
                "OCREngine.extract_selected_pages",
            ) as extract_selected_pages,
            patch.object(
                PDFTextExtractionService,
                "_target_groups",
                return_value=([], {}),
            ),
            patch.object(
                PDFTextExtractionService,
                "_has_required_polygons",
                return_value=False,
            ),
            patch.object(
                PDFTextExtractionService,
                "_measure_text_quality",
                side_effect=self._quality_for_text,
            ),
        ):
            result = PDFTextExtractionService.extract(
                "sample.pdf",
                defer_heavy_fallback_if_useful=True,
            )

        extract_selected_pages.assert_not_called()
        self.assertEqual(result["result_completeness"], "USEFUL_PARTIAL")
        self.assertEqual(
            result["selective_ocr_early_exit_stage"],
            "FULL_TEXT_DISCOVERY",
        )
        self.assertEqual(result["selective_ocr_chunks_processed"], 0)
        self.assertEqual(result["selective_ocr_pages_processed"], 0)

    def test_all_insufficient_reaches_existing_general_fallback(self):
        fast_result = self._text_layer_result("FAST_BASE")
        fallback_result = self._text_layer_result("")
        with (
            patch(
                "src.core.pdf_text_extraction_service."
                "OCREngine.extract_text_layer",
                return_value=fast_result,
            ),
            patch(
                "src.core.pdf_text_extraction_service."
                "OCREngine.extract_selected_pages",
                return_value=self._chunk_result("COORD", 3),
            ),
            patch(
                "src.core.pdf_text_extraction_service."
                "OCREngine.extract_text",
                return_value=fallback_result,
            ) as extract_text,
            patch.object(
                PDFTextExtractionService,
                "_target_groups",
                return_value=([[5]], {5: 100}),
            ),
            patch.object(
                PDFTextExtractionService,
                "_has_required_polygons",
                return_value=False,
            ),
            patch.object(
                PDFTextExtractionService,
                "_measure_text_quality",
                side_effect=self._quality_for_text,
            ),
        ):
            result = PDFTextExtractionService.extract(
                "sample.pdf",
                defer_heavy_fallback_if_useful=True,
            )

        extract_text.assert_called_once_with("sample.pdf", max_pages=None)
        self.assertTrue(result["general_fallback_used"])
        self.assertFalse(result["heavy_fallback_deferred"])
        self.assertEqual(result["result_completeness"], "INSUFFICIENT")

    def test_general_fallback_remains_full_document_call(self):
        pre_result = {
            **self._text_layer_result("PRE"),
            "strategy": "selective_ocr_full_discovery",
            "ocr_page_numbers": [],
            "ocr_attempted_page_numbers": [],
        }
        fallback_result = {
            **self._text_layer_result("FALLBACK"),
            "strategy": "general_ocr_fallback",
        }
        with (
            patch.object(
                PDFTextExtractionService,
                "_measure_text_quality",
                side_effect=self._quality_for_text,
            ),
            patch(
                "src.core.pdf_text_extraction_service."
                "OCREngine.extract_text",
                return_value=fallback_result,
            ) as extract_text,
            patch(
                "src.core.pdf_text_extraction_service."
                "OCREngine.extract_selected_pages",
            ) as extract_selected_pages,
        ):
            result = PDFTextExtractionService._fallback_with_preservation(
                "sample.pdf",
                pre_result,
                reason="test",
            )

        extract_text.assert_called_once_with("sample.pdf", max_pages=None)
        extract_selected_pages.assert_not_called()
        self.assertTrue(result["general_fallback_used"])
        self.assertFalse(result["heavy_fallback_deferred"])

    def test_batch_result_copies_selective_diagnostics(self):
        extraction_result = {
            **self._text_layer_result("RAW_TEXT"),
            "strategy": "selective_ocr_fast_window",
            "ocr_page_numbers": [3],
            "selective_ocr_early_exit": True,
            "selective_ocr_early_exit_stage": "FAST_WINDOW",
            "selective_ocr_early_exit_reason": (
                "usable_polygon_found"
            ),
            "selective_ocr_chunks_processed": 1,
            "selective_ocr_pages_processed": 5,
            "result_completeness": "USEFUL_PARTIAL",
            "has_useful_result": True,
            "heavy_fallback_deferred": True,
            "general_fallback_used": False,
            "final_result_source": "pre_fallback",
        }
        processor = CEDBatchProcessor("ANKARA")

        with (
            patch(
                "src.batch.ced_batch_processor."
                "PDFTextExtractionService.extract",
                return_value=extraction_result,
            ),
            patch(
                "src.batch.ced_batch_processor."
                "TableDetector.find_tables",
                return_value=["TABLE"],
            ),
            patch(
                "src.batch.ced_batch_processor."
                "CoordinateEngine.extract_coordinates",
                return_value=[{"label": "1"}],
            ),
            patch(
                "src.batch.ced_batch_processor."
                "PolygonBuilder.build",
                return_value=[{"table_type": "PROJE_ALANI"}],
            ),
            patch.object(
                processor.project_info_extractor,
                "extract",
                return_value={},
            ),
        ):
            result = processor.process_pdf(
                pdf_path=Path("sample.pdf"),
                project_type="EK-1",
                defer_heavy_fallback_if_useful=True,
            )

        self.assertTrue(result["selective_ocr_early_exit"])
        self.assertEqual(
            result["selective_ocr_early_exit_stage"],
            "FAST_WINDOW",
        )
        self.assertEqual(
            result["selective_ocr_early_exit_reason"],
            "usable_polygon_found",
        )
        self.assertEqual(result["selective_ocr_chunks_processed"], 1)
        self.assertEqual(result["selective_ocr_pages_processed"], 5)


if __name__ == "__main__":
    unittest.main()
