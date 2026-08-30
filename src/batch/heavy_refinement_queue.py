import copy
import hashlib
import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


PENDING = "PENDING"
IN_PROGRESS = "IN_PROGRESS"
COMPLETED = "COMPLETED"
FAILED = "FAILED"
SKIPPED = "SKIPPED"

JOB_STATUSES = {
    PENDING,
    IN_PROGRESS,
    COMPLETED,
    FAILED,
    SKIPPED,
}

_STATUS_TRANSITIONS = {
    PENDING: {IN_PROGRESS, SKIPPED},
    IN_PROGRESS: {COMPLETED, FAILED, SKIPPED},
    COMPLETED: set(),
    FAILED: {PENDING, SKIPPED},
    SKIPPED: {PENDING},
}

_PRIMARY_FIELDS = (
    "result_completeness",
    "status",
    "coordinate_count",
    "table_count",
    "polygon_count",
    "transformed_coordinate_count",
    "extraction_strategy",
    "ocr_page_numbers",
    "elapsed_seconds",
    "final_result_source",
)

_EXTRACTION_FIELDS = (
    "candidate_page_numbers",
    "candidate_page_scores",
    "pre_fallback_coordinate_count",
    "pre_fallback_table_count",
    "pre_fallback_polygon_count",
    "has_useful_result",
    "heavy_fallback_deferred",
    "heavy_fallback_defer_reason",
)


class HeavyRefinementQueue:
    """Persistent metadata queue for deferred heavy refinement jobs."""

    schema_version = 1

    def __init__(self, storage_path, pdf_root=None):
        self.storage_path = Path(storage_path).resolve()
        self.lock_path = self.storage_path.with_suffix(
            self.storage_path.suffix + ".lock"
        )
        self.pdf_root = (
            Path(pdf_root).resolve()
            if pdf_root is not None
            else None
        )
        self.storage_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

    def enqueue_from_result(self, pdf_path, batch_result):
        eligibility = self._enqueue_eligibility(
            batch_result
        )
        if eligibility is not None:
            return {
                "enqueued": False,
                "reason": eligibility,
                "job": None,
            }

        try:
            identity = self._build_file_identity(
                pdf_path
            )
        except (FileNotFoundError, OSError) as error:
            return {
                "enqueued": False,
                "reason": "PDF_IDENTITY_UNAVAILABLE",
                "error": str(error),
                "job": None,
            }

        job_id = self._make_job_id(identity)
        now = _utc_now()
        primary = _snapshot_fields(
            batch_result,
            _PRIMARY_FIELDS,
        )
        extraction = _snapshot_fields(
            batch_result,
            _EXTRACTION_FIELDS,
        )
        candidate_pages = _candidate_pages(
            extraction
        )
        project_type = batch_result.get(
            "project_type"
        )

        job = {
            "job_id": job_id,
            "status": PENDING,
            "status_reason": "",
            "attempts": 0,
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "completed_at": None,
            "identity": identity,
            "project_type": (
                _json_safe(project_type)
                if project_type is not None
                else None
            ),
            "primary": primary,
            "extraction": extraction,
            "manual_review": {
                "status": "NOT_REVIEWED",
                "candidate_pages": candidate_pages,
                "selected_pages": [],
                "selected_regions": [],
            },
            "refined_result": None,
            "status_history": [
                {
                    "status": PENDING,
                    "at": now,
                    "reason": "ENQUEUED",
                }
            ],
        }

        with _queue_lock(self.lock_path):
            state = self._load_state()
            existing = state["jobs"].get(job_id)
            if existing is not None:
                return {
                    "enqueued": False,
                    "reason": "DUPLICATE_UNCHANGED_PDF",
                    "job": copy.deepcopy(existing),
                }

            state["jobs"][job_id] = job
            self._persist_state(state)

        return {
            "enqueued": True,
            "reason": "ENQUEUED",
            "job": copy.deepcopy(job),
        }

    def get_job(self, job_id):
        state = self._load_state()
        job = state["jobs"].get(job_id)
        return copy.deepcopy(job)

    def list_jobs(self, status=None):
        if status is not None and status not in JOB_STATUSES:
            raise ValueError(
                f"Geçersiz queue status: {status}"
            )

        jobs = self._load_state()["jobs"].values()
        selected = [
            copy.deepcopy(job)
            for job in jobs
            if status is None or job["status"] == status
        ]
        return sorted(
            selected,
            key=lambda item: (
                item["created_at"],
                item["job_id"],
            ),
        )

    def claim_next(self):
        with _queue_lock(self.lock_path):
            state = self._load_state()
            pending_jobs = sorted(
                (
                    job
                    for job in state["jobs"].values()
                    if job["status"] == PENDING
                ),
                key=lambda item: (
                    item["created_at"],
                    item["job_id"],
                ),
            )
            if not pending_jobs:
                return None

            job = pending_jobs[0]
            self._apply_transition(
                job,
                IN_PROGRESS,
                reason="CLAIMED",
            )
            self._persist_state(state)
            return copy.deepcopy(job)

    def transition(self, job_id, new_status, reason=""):
        if new_status not in JOB_STATUSES:
            raise ValueError(
                f"Geçersiz queue status: {new_status}"
            )

        with _queue_lock(self.lock_path):
            state = self._load_state()
            job = self._require_job(
                state,
                job_id,
            )
            current_status = job["status"]
            if new_status == current_status:
                return copy.deepcopy(job)
            if new_status not in _STATUS_TRANSITIONS[
                current_status
            ]:
                raise ValueError(
                    f"Geçersiz status geçişi: "
                    f"{current_status} -> {new_status}"
                )

            self._apply_transition(
                job,
                new_status,
                reason=reason,
            )
            self._persist_state(state)
            return copy.deepcopy(job)

    def recover_in_progress(
        self,
        job_id,
        recovery_status,
        reason,
    ):
        if recovery_status not in {PENDING, FAILED}:
            raise ValueError(
                "Recovery status PENDING veya FAILED olmalıdır."
            )
        if not str(reason).strip():
            raise ValueError(
                "IN_PROGRESS recovery için reason zorunludur."
            )

        with _queue_lock(self.lock_path):
            state = self._load_state()
            job = self._require_job(
                state,
                job_id,
            )
            if job["status"] != IN_PROGRESS:
                raise ValueError(
                    "Yalnız IN_PROGRESS job recovery edilebilir."
                )

            self._apply_transition(
                job,
                recovery_status,
                reason=reason,
                recovery=True,
            )
            self._persist_state(state)
            return copy.deepcopy(job)

    def _enqueue_eligibility(self, result):
        if not isinstance(result, dict):
            return "INVALID_RESULT"
        if "result_completeness" not in result:
            return "MISSING_RESULT_COMPLETENESS"
        if result.get("result_completeness") != "USEFUL_PARTIAL":
            return "RESULT_NOT_USEFUL_PARTIAL"
        if "has_useful_result" not in result:
            return "MISSING_HAS_USEFUL_RESULT"
        if result.get("has_useful_result") is not True:
            return "RESULT_NOT_USEFUL"
        if "heavy_fallback_deferred" not in result:
            return "MISSING_HEAVY_FALLBACK_DEFERRED"
        if result.get("heavy_fallback_deferred") is not True:
            return "HEAVY_FALLBACK_NOT_DEFERRED"
        return None

    def _build_file_identity(self, pdf_path):
        resolved_path = Path(pdf_path).resolve(
            strict=True
        )
        if not resolved_path.is_file():
            raise FileNotFoundError(
                f"PDF bulunamadı: {resolved_path}"
            )

        stat = resolved_path.stat()
        relative_path = None
        if self.pdf_root is not None:
            try:
                relative_path = resolved_path.relative_to(
                    self.pdf_root
                ).as_posix()
            except ValueError:
                relative_path = None

        return {
            "canonical_path": os.path.normcase(
                str(resolved_path)
            ),
            "relative_path": relative_path,
            "file_size": stat.st_size,
            "modified_time_ns": stat.st_mtime_ns,
        }

    @staticmethod
    def _make_job_id(identity):
        identity_key = {
            "canonical_path": identity["canonical_path"],
            "file_size": identity["file_size"],
            "modified_time_ns": identity["modified_time_ns"],
        }
        payload = json.dumps(
            identity_key,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return "heavy_" + hashlib.sha256(
            payload.encode("utf-8")
        ).hexdigest()

    def _load_state(self):
        if not self.storage_path.exists():
            return {
                "schema_version": self.schema_version,
                "updated_at": None,
                "jobs": {},
            }

        try:
            with self.storage_path.open(
                "r",
                encoding="utf-8",
            ) as file:
                state = json.load(file)
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError(
                f"Heavy refinement queue okunamadı: "
                f"{self.storage_path}"
            ) from error

        if (
            state.get("schema_version")
            != self.schema_version
            or not isinstance(state.get("jobs"), dict)
        ):
            raise RuntimeError(
                "Heavy refinement queue şeması geçersiz."
            )
        return state

    def _persist_state(self, state):
        state["schema_version"] = self.schema_version
        state["updated_at"] = _utc_now()
        temp_path = self.storage_path.with_name(
            self.storage_path.name
            + f".tmp.{os.getpid()}.{uuid.uuid4().hex}"
        )
        try:
            with temp_path.open(
                "w",
                encoding="utf-8",
                newline="\n",
            ) as file:
                json.dump(
                    state,
                    file,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(
                temp_path,
                self.storage_path,
            )
        finally:
            temp_path.unlink(missing_ok=True)

    @staticmethod
    def _require_job(state, job_id):
        try:
            return state["jobs"][job_id]
        except KeyError as error:
            raise KeyError(
                f"Queue job bulunamadı: {job_id}"
            ) from error

    @staticmethod
    def _apply_transition(
        job,
        new_status,
        reason,
        recovery=False,
    ):
        now = _utc_now()
        job["status"] = new_status
        job["status_reason"] = str(reason or "")
        job["updated_at"] = now

        if new_status == IN_PROGRESS:
            job["attempts"] += 1
            job["started_at"] = now
            job["completed_at"] = None
        elif new_status in {COMPLETED, FAILED, SKIPPED}:
            job["completed_at"] = now
        elif new_status == PENDING:
            job["started_at"] = None
            job["completed_at"] = None

        job["status_history"].append(
            {
                "status": new_status,
                "at": now,
                "reason": str(reason or ""),
                "recovery": bool(recovery),
            }
        )


def _snapshot_fields(source, field_names):
    return {
        field: _json_safe(source[field])
        for field in field_names
        if field in source
    }


def _candidate_pages(extraction):
    explicit = extraction.get(
        "candidate_page_numbers"
    )
    if isinstance(explicit, (list, tuple)):
        return _json_safe(list(explicit))

    scores = extraction.get(
        "candidate_page_scores"
    )
    if not isinstance(scores, dict):
        return []

    pages = []
    for page in scores:
        try:
            pages.append(int(page))
        except (TypeError, ValueError):
            continue
    return sorted(set(pages))


def _json_safe(value):
    if isinstance(value, Path):
        return str(value)
    return json.loads(
        json.dumps(
            value,
            ensure_ascii=False,
        )
    )


def _utc_now():
    return datetime.now(
        timezone.utc
    ).isoformat()


@contextmanager
def _queue_lock(lock_path):
    lock_path = Path(lock_path)
    try:
        descriptor = os.open(
            lock_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        )
    except FileExistsError as error:
        raise RuntimeError(
            f"Heavy refinement queue kilitli: {lock_path}"
        ) from error

    try:
        with os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                {
                    "pid": os.getpid(),
                    "started_at": _utc_now(),
                },
                file,
                ensure_ascii=False,
                indent=2,
            )
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        yield lock_path
    finally:
        lock_path.unlink(missing_ok=True)
