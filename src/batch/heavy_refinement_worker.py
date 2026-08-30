import argparse
import copy
import time
from pathlib import Path

from src.batch.ced_batch_processor import CEDBatchProcessor
from src.batch.heavy_refinement_queue import (
    FAILED,
    HeavyRefinementQueue,
    build_refined_result_snapshot,
    compare_geometry_snapshots,
)


class HeavyRefinementWorker:

    def __init__(
        self,
        queue,
        pdf_root=None,
        processor_factory=CEDBatchProcessor,
    ):
        self.queue = queue
        self.pdf_root = (
            Path(pdf_root).resolve()
            if pdf_root is not None
            else None
        )
        self.processor_factory = processor_factory

    def run_once(self):
        job = self.queue.claim_next()
        if job is None:
            return None

        job_id = job["job_id"]
        try:
            pdf_path = self._resolve_pdf_path(job)
            self._validate_file_identity(
                pdf_path,
                job["identity"],
            )
            project_type = job.get("project_type")
            if not project_type:
                raise ValueError(
                    "Heavy refinement job project_type içermiyor."
                )

            province = self._resolve_province(
                job,
                pdf_path,
            )
            processor = self.processor_factory(
                province=province,
                downloads_root=(
                    self.pdf_root
                    if self.pdf_root is not None
                    else pdf_path.parent
                ),
            )
            started = time.perf_counter()
            batch_result = processor.process_pdf(
                pdf_path=pdf_path,
                project_type=project_type,
                defer_heavy_fallback_if_useful=False,
                include_geometry_snapshot=True,
            )
            elapsed_seconds = (
                time.perf_counter() - started
            )

            if not isinstance(batch_result, dict):
                raise RuntimeError(
                    "CEDBatchProcessor geçersiz result döndürdü."
                )
            if batch_result.get("status") == "HATA":
                raise RuntimeError(
                    batch_result.get("error")
                    or "Heavy extraction HATA döndürdü."
                )

            batch_result = copy.deepcopy(batch_result)
            batch_result["elapsed_seconds"] = round(
                elapsed_seconds,
                6,
            )
            refinement_outcome = (
                "REFINEMENT_USABLE"
                if int(batch_result.get("polygon_count") or 0) > 0
                else "REFINEMENT_UNUSABLE"
            )
            batch_result["refinement_outcome"] = (
                refinement_outcome
            )
            refined_result = build_refined_result_snapshot(
                batch_result
            )
            refined_result["refinement_outcome"] = (
                refinement_outcome
            )
            comparison = compare_geometry_snapshots(
                job.get("primary_geometry"),
                refined_result.get("geometry"),
                primary_summary=job.get("primary"),
                refined_summary=refined_result.get("summary"),
            )
            comparison["refinement_outcome"] = (
                refinement_outcome
            )
            completed_job = (
                self.queue.complete_with_refined_result(
                    job_id,
                    refined_result,
                    comparison,
                    reason=refinement_outcome,
                )
            )
            return {
                "processed": True,
                "job_id": job_id,
                "status": completed_job["status"],
                "comparison": copy.deepcopy(
                    comparison
                ),
                "refined_result": copy.deepcopy(
                    refined_result
                ),
            }
        except Exception as error:
            failed_job = self.queue.transition(
                job_id,
                FAILED,
                reason=str(error),
            )
            return {
                "processed": True,
                "job_id": job_id,
                "status": failed_job["status"],
                "error": str(error),
            }

    def run(self, max_jobs=None):
        if max_jobs is not None and max_jobs <= 0:
            raise ValueError(
                "max_jobs pozitif olmalıdır."
            )

        results = []
        while max_jobs is None or len(results) < max_jobs:
            result = self.run_once()
            if result is None:
                break
            results.append(result)
        return results

    def _resolve_pdf_path(self, job):
        identity = job.get("identity", {})
        canonical_path = identity.get(
            "canonical_path"
        )
        if canonical_path:
            canonical_candidate = Path(
                canonical_path
            )
            if canonical_candidate.is_file():
                return canonical_candidate.resolve()

        relative_path = identity.get("relative_path")
        if self.pdf_root is not None and relative_path:
            relative_candidate = (
                self.pdf_root / relative_path
            ).resolve()
            if relative_candidate.is_file():
                return relative_candidate

        raise FileNotFoundError(
            "Heavy refinement job PDF'i bulunamadı."
        )

    @staticmethod
    def _validate_file_identity(pdf_path, identity):
        stat = pdf_path.stat()
        if (
            stat.st_size != identity.get("file_size")
            or stat.st_mtime_ns
            != identity.get("modified_time_ns")
        ):
            raise RuntimeError(
                "Heavy refinement job PDF identity değişmiş."
            )

    @staticmethod
    def _resolve_province(job, pdf_path):
        province = job.get("province")
        if province:
            return str(province)

        relative_path = job.get(
            "identity",
            {},
        ).get("relative_path")
        if relative_path:
            parts = Path(relative_path).parts
            if parts:
                return parts[0]

        return pdf_path.parent.parent.name or "BILINMIYOR"


def _build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "PENDING heavy refinement işlerini sequential işler."
        )
    )
    parser.add_argument(
        "--queue",
        required=True,
        help="Heavy refinement queue JSON yolu",
    )
    parser.add_argument(
        "--pdf-root",
        help="Taşınmış relative PDF yolları için corpus root",
    )
    mode = parser.add_mutually_exclusive_group(
        required=True
    )
    mode.add_argument(
        "--once",
        action="store_true",
        help="Yalnız bir PENDING job işle",
    )
    mode.add_argument(
        "--max-jobs",
        type=int,
        help="En fazla N PENDING job işle",
    )
    return parser


def main(argv=None):
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.max_jobs is not None and args.max_jobs <= 0:
        parser.error("--max-jobs pozitif olmalıdır.")

    queue = HeavyRefinementQueue(
        args.queue,
        pdf_root=args.pdf_root,
    )
    worker = HeavyRefinementWorker(
        queue,
        pdf_root=args.pdf_root,
    )
    results = (
        [worker.run_once()]
        if args.once
        else worker.run(max_jobs=args.max_jobs)
    )
    processed = [
        result
        for result in results
        if result is not None
    ]
    for result in processed:
        print(
            f"HEAVY_REFINEMENT | "
            f"{result['job_id']} | "
            f"{result['status']}"
        )
    if not processed:
        print("HEAVY_REFINEMENT | PENDING_JOB_YOK")
    return processed


if __name__ == "__main__":
    main()
