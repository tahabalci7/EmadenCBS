import argparse
import json
from pathlib import Path

from src.batch.ced_batch_processor import CEDBatchProcessor
from src.batch.heavy_refinement_queue import (
    HeavyRefinementQueue,
)


class RefinementPipeline:
    """Return primary results immediately and enqueue safe refinements."""

    def __init__(
        self,
        queue,
        batch_processor=None,
        processor_factory=CEDBatchProcessor,
    ):
        self.queue = queue
        self.batch_processor = batch_processor
        self.processor_factory = processor_factory

    def process_pdf(self, pdf_path, project_type):
        pdf_path = Path(pdf_path)
        processor = self._processor_for(pdf_path)
        result = processor.process_pdf(
            pdf_path=pdf_path,
            project_type=project_type,
            defer_heavy_fallback_if_useful=True,
            include_geometry_snapshot=True,
        )
        if not isinstance(result, dict):
            raise TypeError(
                "CEDBatchProcessor sonucu dict olmalıdır."
            )

        result["refinement"] = self._enqueue_primary(
            pdf_path,
            result,
        )
        return result

    def process_all(self, pdf_items):
        """Process an iterable of ``(pdf_path, project_type)`` pairs."""
        return [
            self.process_pdf(pdf_path, project_type)
            for pdf_path, project_type in pdf_items
        ]

    def _enqueue_primary(self, pdf_path, result):
        completeness = result.get(
            "result_completeness"
        )
        metadata = {
            "eligible": False,
            "enqueued": False,
            "job_id": None,
            "enqueue_reason": None,
            "primary_result_completeness": completeness,
            "queue_error": None,
        }

        if result.get("status") == "HATA":
            metadata["enqueue_reason"] = (
                "PRIMARY_EXTRACTION_ERROR"
            )
            return metadata

        if completeness != "USEFUL_PARTIAL":
            metadata["enqueue_reason"] = (
                "PRIMARY_NOT_USEFUL_PARTIAL"
            )
            return metadata

        try:
            outcome = self.queue.enqueue_from_result(
                pdf_path,
                result,
            )
        except Exception as error:
            metadata["enqueue_reason"] = (
                "QUEUE_ERROR"
            )
            metadata["queue_error"] = str(error)
            return metadata

        reason = outcome.get("reason")
        job = outcome.get("job")
        metadata["eligible"] = bool(
            outcome.get("enqueued")
            or reason == "DUPLICATE_UNCHANGED_PDF"
        )
        metadata["enqueued"] = bool(
            outcome.get("enqueued")
        )
        metadata["job_id"] = (
            job.get("job_id")
            if isinstance(job, dict)
            else None
        )
        metadata["enqueue_reason"] = reason
        if outcome.get("error"):
            metadata["queue_error"] = str(
                outcome["error"]
            )
        return metadata

    def _processor_for(self, pdf_path):
        if self.batch_processor is not None:
            return self.batch_processor

        province, downloads_root = (
            _infer_archive_context(pdf_path)
        )
        return self.processor_factory(
            province=province,
            downloads_root=downloads_root,
        )


def _infer_archive_context(pdf_path):
    resolved = Path(pdf_path).resolve()
    if len(resolved.parents) < 3:
        raise ValueError(
            "PDF yolu <root>/<province>/<project_type>/<pdf> "
            "yapısında olmalıdır veya batch_processor verilmelidir."
        )
    return resolved.parent.parent.name, resolved.parents[2]


def _build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Primary PDF extraction çalıştırır ve güvenli partial "
            "sonuçları heavy refinement queue'ya ekler."
        )
    )
    parser.add_argument("--pdf", required=True)
    parser.add_argument(
        "--project-type",
        required=True,
        choices=("EK-1", "EK-2"),
    )
    parser.add_argument("--queue", required=True)
    parser.add_argument("--pdf-root")
    return parser


def main(argv=None):
    args = _build_parser().parse_args(argv)
    queue = HeavyRefinementQueue(
        args.queue,
        pdf_root=args.pdf_root,
    )
    result = RefinementPipeline(queue).process_pdf(
        args.pdf,
        args.project_type,
    )
    print(
        "REFINEMENT_PIPELINE="
        + json.dumps(
            {
                "pdf": result.get("pdf"),
                "status": result.get("status"),
                "result_completeness": result.get(
                    "result_completeness"
                ),
                "refinement": result.get("refinement"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return result


if __name__ == "__main__":
    main()
