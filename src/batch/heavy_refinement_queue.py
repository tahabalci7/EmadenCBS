import copy
import hashlib
import json
import math
import os
import uuid
from collections import Counter
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
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

_REFINED_SUMMARY_FIELDS = _PRIMARY_FIELDS + (
    "error",
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
        province = batch_result.get(
            "province"
        )
        primary_geometry = batch_result.get(
            "geometry_snapshot"
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
            "province": (
                _json_safe(province)
                if province is not None
                else None
            ),
            "primary": primary,
            "primary_geometry": (
                _json_safe(primary_geometry)
                if isinstance(primary_geometry, dict)
                else None
            ),
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

    def complete_with_refined_result(
        self,
        job_id,
        refined_result,
        comparison,
        reason="REFINEMENT_COMPLETED",
    ):
        refined_snapshot = _json_safe(
            refined_result
        )
        comparison_snapshot = _json_safe(
            comparison
        )

        with _queue_lock(self.lock_path):
            state = self._load_state()
            job = self._require_job(
                state,
                job_id,
            )
            if job["status"] != IN_PROGRESS:
                raise ValueError(
                    "Refined result yalnız IN_PROGRESS job'a "
                    "yazılabilir."
                )

            job["refined_result"] = refined_snapshot
            job["comparison"] = comparison_snapshot
            self._apply_transition(
                job,
                COMPLETED,
                reason=reason,
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


def build_compact_geometry_snapshot(
    coordinates,
    polygons,
):
    coordinate_entries = [
        (point, _projected_coordinate_token(point))
        for point in coordinates
    ]
    coordinate_entries = [
        (point, token)
        for point, token in coordinate_entries
        if token is not None
    ]
    coordinate_tokens = [
        token for _, token in coordinate_entries
    ]
    unique_coordinate_tokens = sorted(
        set(coordinate_tokens)
    )
    strong_coordinate_tokens = [
        token
        for point, token in coordinate_entries
        if _is_strong_projected_point(
            point,
            token,
        )
    ]
    strong_unique_coordinate_tokens = sorted(
        set(strong_coordinate_tokens)
    )
    unresolved_coordinate_count = sum(
        token.startswith("CRS_UNRESOLVED|")
        for token in coordinate_tokens
    )
    crs_high_record_count = sum(
        point.get("crs_confidence") == "HIGH"
        for point in coordinates
    )
    crs_conflicted_record_count = sum(
        point.get("crs_conflict") is True
        or point.get("crs_confidence") == "CONFLICTING"
        for point in coordinates
    )
    crs_unresolved_record_count = sum(
        point.get("crs_confidence")
        in {None, "UNRESOLVED"}
        for point in coordinates
    )
    cross_observation_conflict_record_count = sum(
        "CROSS_OBSERVATION_EPSG_CONFLICT"
        in str(point.get("crs_conflict_reason", ""))
        for point in coordinates
    )
    conflicting_numeric_pair_count = (
        _conflicting_numeric_pair_count(
            coordinate_entries
        )
    )

    polygon_snapshots = [
        _polygon_snapshot(
            polygon,
            coordinates,
        )
        for polygon in polygons
    ]
    area_type_counts = Counter(
        polygon.get("area_type") or "DIGER"
        for polygon in polygon_snapshots
    )
    semantic_counts = Counter(
        (
            polygon.get("area_type") or "DIGER",
            polygon.get("polygon_group") or "DEFAULT",
        )
        for polygon in polygon_snapshots
    )
    invalid_coordinate_count = (
        len(coordinates) - len(coordinate_tokens)
    )
    strong_polygon_count = sum(
        polygon.get("strong_geometry_comparable") is True
        for polygon in polygon_snapshots
    )
    geometry_identity_reliable = (
        len(strong_coordinate_tokens) == len(coordinates)
        and strong_polygon_count == len(polygon_snapshots)
    )

    return {
        "record_count": len(coordinates),
        "coordinate_record_count": len(coordinates),
        "valid_projected_coordinate_count": len(
            coordinate_tokens
        ),
        "invalid_projected_coordinate_count": invalid_coordinate_count,
        "unresolved_crs_coordinate_count": unresolved_coordinate_count,
        "geometry_identity_reliable": geometry_identity_reliable,
        "unique_projected_coordinate_count": len(
            unique_coordinate_tokens
        ),
        "unique_projected_coordinate_tokens": (
            unique_coordinate_tokens
        ),
        "coordinate_token_provenance": (
            _build_token_provenance(
                coordinate_entries
            )
        ),
        "projected_coordinate_fingerprint": (
            _fingerprint_values(unique_coordinate_tokens)
        ),
        "strong_record_count": len(
            strong_coordinate_tokens
        ),
        "strong_unique_projected_count": len(
            strong_unique_coordinate_tokens
        ),
        "strong_unique_projected_tokens": (
            strong_unique_coordinate_tokens
        ),
        "strong_projected_coordinate_fingerprint": (
            _fingerprint_values(
                strong_unique_coordinate_tokens
            )
        ),
        "crs_high_record_count": crs_high_record_count,
        "crs_conflicted_record_count": (
            crs_conflicted_record_count
        ),
        "crs_unresolved_record_count": (
            crs_unresolved_record_count
        ),
        "cross_observation_conflict_record_count": (
            cross_observation_conflict_record_count
        ),
        "conflicting_numeric_pair_count": (
            conflicting_numeric_pair_count
        ),
        "transformed_coordinate_count": sum(
            1
            for point in coordinates
            if _has_transformed_coordinate(point)
        ),
        "polygon_count": len(polygon_snapshots),
        "strong_comparable_polygon_count": (
            strong_polygon_count
        ),
        "polygon_area_type_counts": dict(
            sorted(area_type_counts.items())
        ),
        "polygon_semantic_counts": {
            f"{area_type}|{polygon_group}": count
            for (area_type, polygon_group), count
            in sorted(semantic_counts.items())
        },
        "polygons": polygon_snapshots,
    }


def build_refined_result_snapshot(batch_result):
    return {
        "summary": _snapshot_fields(
            batch_result,
            _REFINED_SUMMARY_FIELDS,
        ),
        "geometry": (
            _json_safe(batch_result["geometry_snapshot"])
            if isinstance(
                batch_result.get("geometry_snapshot"),
                dict,
            )
            else None
        ),
    }


def compare_geometry_snapshots(
    primary_geometry,
    refined_geometry,
    primary_summary=None,
    refined_summary=None,
):
    primary_summary = primary_summary or {}
    refined_summary = refined_summary or {}

    if not isinstance(primary_geometry, dict):
        return {
            "comparison_status": (
                "PRIMARY_GEOMETRY_UNAVAILABLE"
            ),
            "classification": (
                "PRIMARY_GEOMETRY_UNAVAILABLE"
            ),
            "classification_reason": (
                "PRIMARY_GEOMETRY_UNAVAILABLE"
            ),
            "diagnostic_reason": (
                "PRIMARY_GEOMETRY_UNAVAILABLE"
            ),
            "primary_coordinate_records": (
                primary_summary.get("coordinate_count")
            ),
            "refined_coordinate_records": (
                refined_summary.get("coordinate_count")
            ),
            "primary_polygon_count": (
                primary_summary.get("polygon_count")
            ),
            "refined_polygon_count": (
                refined_summary.get("polygon_count")
            ),
        }

    if not isinstance(refined_geometry, dict):
        return {
            "comparison_status": (
                "REFINED_GEOMETRY_UNAVAILABLE"
            ),
            "classification": "MIXED_OR_OTHER",
            "classification_reason": (
                "REFINED_GEOMETRY_UNAVAILABLE"
            ),
            "diagnostic_reason": (
                "REFINED_GEOMETRY_UNAVAILABLE"
            ),
            "primary_coordinate_records": (
                primary_geometry.get(
                    "coordinate_record_count"
                )
            ),
            "refined_coordinate_records": (
                refined_summary.get("coordinate_count")
            ),
            "primary_polygon_count": (
                primary_geometry.get("polygon_count")
            ),
            "refined_polygon_count": (
                refined_summary.get("polygon_count")
            ),
        }

    primary_tokens = primary_geometry.get(
        "unique_projected_coordinate_tokens"
    )
    refined_tokens = refined_geometry.get(
        "unique_projected_coordinate_tokens"
    )
    if not isinstance(primary_tokens, list) or not isinstance(
        refined_tokens,
        list,
    ):
        return {
            "comparison_status": (
                "TOKEN_COMPARISON_UNAVAILABLE"
            ),
            "classification": (
                "PRIMARY_GEOMETRY_UNAVAILABLE"
            ),
            "classification_reason": (
                "TOKEN_COMPARISON_UNAVAILABLE"
            ),
            "diagnostic_reason": (
                "TOKEN_COMPARISON_UNAVAILABLE"
            ),
            "diagnostic_reasons": [
                "TOKEN_COMPARISON_UNAVAILABLE"
            ],
            "primary_coordinate_records": (
                primary_geometry.get(
                    "coordinate_record_count"
                )
            ),
            "refined_coordinate_records": (
                refined_geometry.get(
                    "coordinate_record_count"
                )
            ),
            "primary_polygon_count": (
                primary_geometry.get("polygon_count")
            ),
            "refined_polygon_count": (
                refined_geometry.get("polygon_count")
            ),
        }

    primary_strong_tokens = primary_geometry.get(
        "strong_unique_projected_tokens"
    )
    refined_strong_tokens = refined_geometry.get(
        "strong_unique_projected_tokens"
    )
    if not isinstance(primary_strong_tokens, list):
        return {
            "comparison_status": (
                "STRONG_TOKEN_COMPARISON_UNAVAILABLE"
            ),
            "classification": (
                "PRIMARY_GEOMETRY_UNAVAILABLE"
            ),
            "classification_reason": (
                "TOKEN_COMPARISON_UNAVAILABLE"
            ),
            "diagnostic_reason": (
                "TOKEN_COMPARISON_UNAVAILABLE"
            ),
            "diagnostic_reasons": [
                "TOKEN_COMPARISON_UNAVAILABLE"
            ],
            "primary_coordinate_records": (
                primary_geometry.get(
                    "coordinate_record_count"
                )
            ),
            "refined_coordinate_records": (
                refined_geometry.get(
                    "coordinate_record_count"
                )
            ),
            "primary_polygon_count": (
                primary_geometry.get("polygon_count")
            ),
            "refined_polygon_count": (
                refined_geometry.get("polygon_count")
            ),
        }
    if not isinstance(refined_strong_tokens, list):
        return {
            "comparison_status": (
                "STRONG_TOKEN_COMPARISON_UNAVAILABLE"
            ),
            "classification": "MIXED_OR_OTHER",
            "classification_reason": (
                "TOKEN_COMPARISON_UNAVAILABLE"
            ),
            "diagnostic_reason": (
                "TOKEN_COMPARISON_UNAVAILABLE"
            ),
            "diagnostic_reasons": [
                "TOKEN_COMPARISON_UNAVAILABLE"
            ],
            "primary_coordinate_records": (
                primary_geometry.get(
                    "coordinate_record_count"
                )
            ),
            "refined_coordinate_records": (
                refined_geometry.get(
                    "coordinate_record_count"
                )
            ),
            "primary_polygon_count": (
                primary_geometry.get("polygon_count")
            ),
            "refined_polygon_count": (
                refined_geometry.get("polygon_count")
            ),
        }

    primary_tokens = set(primary_tokens)
    refined_tokens = set(refined_tokens)
    primary_strong_tokens = set(
        primary_strong_tokens
    )
    refined_strong_tokens = set(
        refined_strong_tokens
    )
    common_tokens = primary_tokens & refined_tokens
    refined_only_tokens = refined_tokens - primary_tokens
    primary_only_tokens = primary_tokens - refined_tokens
    strong_common_tokens = (
        primary_strong_tokens
        & refined_strong_tokens
    )
    strong_refined_only_tokens = (
        refined_strong_tokens
        - primary_strong_tokens
    )
    strong_primary_only_tokens = (
        primary_strong_tokens
        - refined_strong_tokens
    )

    primary_polygon_fingerprints = {
        polygon.get("canonical_ring_fingerprint")
        for polygon in primary_geometry.get("polygons", [])
        if polygon.get("canonical_ring_fingerprint")
    }
    refined_polygon_fingerprints = {
        polygon.get("canonical_ring_fingerprint")
        for polygon in refined_geometry.get("polygons", [])
        if polygon.get("canonical_ring_fingerprint")
    }
    common_polygon_fingerprints = (
        primary_polygon_fingerprints
        & refined_polygon_fingerprints
    )
    primary_strong_polygon_fingerprints = {
        polygon.get("canonical_ring_fingerprint")
        for polygon in primary_geometry.get("polygons", [])
        if (
            polygon.get("strong_geometry_comparable") is True
            and polygon.get("canonical_ring_fingerprint")
        )
    }
    refined_strong_polygon_fingerprints = {
        polygon.get("canonical_ring_fingerprint")
        for polygon in refined_geometry.get("polygons", [])
        if (
            polygon.get("strong_geometry_comparable") is True
            and polygon.get("canonical_ring_fingerprint")
        )
    }
    strong_common_polygon_fingerprints = (
        primary_strong_polygon_fingerprints
        & refined_strong_polygon_fingerprints
    )
    strong_refined_only_polygons = (
        refined_strong_polygon_fingerprints
        - primary_strong_polygon_fingerprints
    )
    strong_primary_only_polygons = (
        primary_strong_polygon_fingerprints
        - refined_strong_polygon_fingerprints
    )

    primary_records = primary_geometry.get(
        "coordinate_record_count",
        0,
    )
    refined_records = refined_geometry.get(
        "coordinate_record_count",
        0,
    )
    primary_polygon_count = primary_geometry.get(
        "polygon_count",
        0,
    )
    refined_polygon_count = refined_geometry.get(
        "polygon_count",
        0,
    )

    diagnostic_reasons = []
    if (
        primary_geometry.get(
            "crs_conflicted_record_count",
            0,
        )
        or refined_geometry.get(
            "crs_conflicted_record_count",
            0,
        )
    ):
        diagnostic_reasons.append(
            "CRS_CONFLICT_PRESENT"
        )
    if (
        primary_geometry.get("strong_record_count", 0)
        < primary_records
        or refined_geometry.get("strong_record_count", 0)
        < refined_records
        or primary_geometry.get(
            "strong_comparable_polygon_count",
            0,
        )
        < primary_polygon_count
        or refined_geometry.get(
            "strong_comparable_polygon_count",
            0,
        )
        < refined_polygon_count
    ):
        diagnostic_reasons.append(
            "PARTIAL_STRONG_GEOMETRY"
        )

    primary_has_strong_geometry = bool(
        primary_strong_tokens
    ) and (
        primary_polygon_count == 0
        or bool(primary_strong_polygon_fingerprints)
    )
    refined_has_strong_geometry = bool(
        refined_strong_tokens
    ) and (
        refined_polygon_count == 0
        or bool(refined_strong_polygon_fingerprints)
    )

    same_coordinate_geometry = (
        primary_strong_tokens
        == refined_strong_tokens
    )
    same_polygon_geometry = (
        primary_strong_polygon_fingerprints
        == refined_strong_polygon_fingerprints
    )
    same_record_distribution = (
        primary_records == refined_records
        and primary_polygon_count == refined_polygon_count
    )
    same_semantics = primary_geometry.get(
        "polygon_semantic_counts",
        {},
    ) == refined_geometry.get(
        "polygon_semantic_counts",
        {},
    )

    if not (
        primary_has_strong_geometry
        and refined_has_strong_geometry
    ):
        classification = "MIXED_OR_OTHER"
        classification_reason = (
            "NO_STRONG_CRS_GEOMETRY"
        )
        diagnostic_reasons.append(
            "NO_STRONG_CRS_GEOMETRY"
        )
    elif same_coordinate_geometry and same_polygon_geometry:
        classification = (
            "SAME_GEOMETRY"
            if same_record_distribution and same_semantics
            else "SEMANTIC_OR_REPEAT_ONLY"
        )
        classification_reason = (
            "STRONG_GEOMETRY_AND_SEMANTICS_MATCH"
            if classification == "SAME_GEOMETRY"
            else "STRONG_GEOMETRY_MATCH_WITH_NON_PHYSICAL_DIFFERENCES"
        )
    elif (
        (
            strong_refined_only_tokens
            or strong_refined_only_polygons
        )
        and not strong_primary_only_tokens
        and not strong_primary_only_polygons
    ):
        classification = "NEW_UNIQUE_GEOMETRY"
        classification_reason = (
            "REFINED_ADDS_STRONG_GEOMETRY"
        )
    else:
        classification = "MIXED_OR_OTHER"
        classification_reason = (
            "BIDIRECTIONAL_STRONG_GEOMETRY_DIFFERENCE"
            if (
                strong_primary_only_tokens
                and strong_refined_only_tokens
            )
            else "REFINED_LOSES_OR_CHANGES_PRIMARY_STRONG_GEOMETRY"
        )

    return {
        "comparison_status": "COMPARED",
        "classification": classification,
        "classification_reason": classification_reason,
        "diagnostic_reason": classification_reason,
        "diagnostic_reasons": sorted(
            set(diagnostic_reasons)
        ),
        "primary_coordinate_records": primary_records,
        "refined_coordinate_records": refined_records,
        "primary_unique_projected": len(primary_tokens),
        "refined_unique_projected": len(refined_tokens),
        "common_unique_projected": len(common_tokens),
        "refined_only_unique_projected": len(
            refined_only_tokens
        ),
        "primary_only_unique_projected": len(
            primary_only_tokens
        ),
        "primary_strong_unique": len(
            primary_strong_tokens
        ),
        "refined_strong_unique": len(
            refined_strong_tokens
        ),
        "strong_common": len(
            strong_common_tokens
        ),
        "strong_refined_only": len(
            strong_refined_only_tokens
        ),
        "strong_primary_only": len(
            strong_primary_only_tokens
        ),
        "primary_polygon_count": primary_polygon_count,
        "refined_polygon_count": refined_polygon_count,
        "exact_common_polygon_count": len(
            common_polygon_fingerprints
        ),
        "primary_strong_polygon_count": len(
            primary_strong_polygon_fingerprints
        ),
        "refined_strong_polygon_count": len(
            refined_strong_polygon_fingerprints
        ),
        "strong_common_polygon_count": len(
            strong_common_polygon_fingerprints
        ),
        "strong_refined_only_polygon_count": len(
            strong_refined_only_polygons
        ),
        "strong_primary_only_polygon_count": len(
            strong_primary_only_polygons
        ),
        "polygon_count_delta": (
            refined_polygon_count - primary_polygon_count
        ),
        "coordinate_record_delta": (
            refined_records - primary_records
        ),
        "unique_coordinate_delta": (
            len(refined_tokens) - len(primary_tokens)
        ),
        "primary_area_type_counts": _json_safe(
            primary_geometry.get(
                "polygon_area_type_counts",
                {},
            )
        ),
        "refined_area_type_counts": _json_safe(
            refined_geometry.get(
                "polygon_area_type_counts",
                {},
            )
        ),
    }


def _polygon_snapshot(polygon, coordinates):
    points = polygon.get("points", [])
    point_tokens = [
        _projected_coordinate_token(point)
        for point in points
    ]
    valid_point_tokens = [
        token for token in point_tokens if token is not None
    ]
    canonical_ring = _canonical_ring_tokens(
        valid_point_tokens
    )
    crs_tokens = {
        token.split("|", 1)[0]
        for token in valid_point_tokens
    }
    polygon_confidence = polygon.get(
        "crs_confidence"
    )
    if polygon_confidence is None:
        point_confidences = {
            point.get("crs_confidence")
            for point in points
        }
        polygon_confidence = (
            point_confidences.pop()
            if len(point_confidences) == 1
            else "UNRESOLVED"
        )
    polygon_conflict = (
        polygon.get("crs_conflict") is True
        or any(
            point.get("crs_conflict") is True
            for point in points
        )
    )
    conflicting_epsg = sorted(
        {
            epsg
            for source in [polygon, *points]
            for epsg in source.get(
                "crs_conflicting_epsg",
                [],
            )
            if isinstance(epsg, int)
        }
    )
    strong_geometry_comparable = (
        len(valid_point_tokens) == len(points)
        and len(crs_tokens) == 1
        and "CRS_UNRESOLVED" not in crs_tokens
        and polygon_confidence == "HIGH"
        and polygon_conflict is False
        and all(
            _is_strong_projected_point(
                point,
                token,
            )
            for point, token in zip(
                points,
                point_tokens,
            )
        )
    )
    group_coordinates = _polygon_group_coordinates(
        polygon,
        coordinates,
    )
    source_pages = sorted(
        {
            point.get("source_page")
            for point in group_coordinates
            if isinstance(point.get("source_page"), int)
        }
    )
    table_identities = sorted(
        {
            point.get("source_table_identity")
            for point in group_coordinates
            if point.get("source_table_identity")
        }
    )
    observation_identities = sorted(
        {
            point.get("source_observation_identity")
            for point in group_coordinates
            if point.get("source_observation_identity")
        }
    )

    return {
        "area_type": polygon.get(
            "table_type",
            "DIGER",
        ),
        "polygon_group": polygon.get(
            "polygon_group",
            "DEFAULT",
        ),
        "point_count": polygon.get(
            "point_count",
            len(points),
        ),
        "unique_point_count": len(set(valid_point_tokens)),
        "invalid_projected_point_count": (
            len(points) - len(valid_point_tokens)
        ),
        "geometry_identity_reliable": strong_geometry_comparable,
        "crs_confidence": polygon_confidence,
        "crs_conflict": polygon_conflict,
        "crs_conflicting_epsg": conflicting_epsg,
        "strong_geometry_comparable": (
            strong_geometry_comparable
        ),
        "source_page_start": (
            min(source_pages)
            if source_pages
            else None
        ),
        "source_page_end": (
            max(source_pages)
            if source_pages
            else None
        ),
        "source_table_identity": (
            table_identities[0]
            if len(table_identities) == 1
            else None
        ),
        "source_table_identities": table_identities,
        "source_observation_identity": (
            observation_identities[0]
            if len(observation_identities) == 1
            else None
        ),
        "source_observation_identities": (
            observation_identities
        ),
        "projected_crs_epsg": polygon.get(
            "projected_crs_epsg"
        ),
        "transformed_point_count": sum(
            1
            for point in points
            if _has_transformed_coordinate(point)
        ),
        "canonical_ring_tokens": canonical_ring,
        "canonical_ring_fingerprint": (
            _fingerprint_sequence(canonical_ring)
        ),
    }


def _polygon_group_coordinates(polygon, coordinates):
    polygon_key = (
        polygon.get("table_type", "DIGER"),
        polygon.get("section", "Bilinmeyen Alan"),
        polygon.get("table_index", 0),
        polygon.get("polygon_group", "DEFAULT"),
    )
    return [
        point
        for point in coordinates
        if (
            point.get("table_type", "DIGER"),
            point.get("section", "Bilinmeyen Alan"),
            point.get("table_index", 0),
            point.get("polygon_group", "DEFAULT"),
        )
        == polygon_key
    ]


def _canonical_decimal(value):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not number.is_finite():
        return None
    if number == 0:
        return "0"
    return format(number.normalize(), "f")


def _projected_crs_token(point):
    epsg = point.get("projected_crs_epsg")
    if epsg is None or str(epsg).strip() == "":
        return "CRS_UNRESOLVED"
    value = str(epsg).strip().upper()
    if value.startswith("EPSG:"):
        value = value[5:].strip()
    try:
        epsg_number = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return "CRS_UNRESOLVED"
    if (
        not epsg_number.is_finite()
        or epsg_number <= 0
        or epsg_number != epsg_number.to_integral_value()
    ):
        return "CRS_UNRESOLVED"
    value = str(int(epsg_number))
    return f"EPSG:{value}"


def _projected_coordinate_token(point):
    y_value = point.get("y", point.get("utm_y"))
    x_value = point.get("x", point.get("utm_x"))
    y_value = _canonical_decimal(y_value)
    x_value = _canonical_decimal(x_value)
    if y_value is None or x_value is None:
        return None
    return f"{_projected_crs_token(point)}|{y_value}|{x_value}"


def _is_strong_projected_point(point, token=None):
    token = token or _projected_coordinate_token(
        point
    )
    return (
        isinstance(token, str)
        and token.startswith("EPSG:")
        and point.get("crs_confidence") == "HIGH"
        and point.get("crs_conflict") is False
    )


def _build_token_provenance(coordinate_entries):
    provenance = {}
    for point, token in coordinate_entries:
        item = provenance.setdefault(
            token,
            {
                "crs_confidences": set(),
                "crs_conflict": False,
                "source_table_identities": set(),
                "source_observation_identities": set(),
            },
        )
        confidence = point.get("crs_confidence")
        if confidence:
            item["crs_confidences"].add(
                str(confidence)
            )
        item["crs_conflict"] = (
            item["crs_conflict"]
            or point.get("crs_conflict") is True
        )
        table_identity = point.get(
            "source_table_identity"
        )
        if table_identity:
            item["source_table_identities"].add(
                str(table_identity)
            )
        observation_identity = point.get(
            "source_observation_identity"
        )
        if observation_identity:
            item[
                "source_observation_identities"
            ].add(str(observation_identity))

    return {
        token: {
            "crs_confidences": sorted(
                item["crs_confidences"]
            ),
            "crs_conflict": item["crs_conflict"],
            "source_table_identities": sorted(
                item["source_table_identities"]
            ),
            "source_observation_identities": sorted(
                item[
                    "source_observation_identities"
                ]
            ),
        }
        for token, item in sorted(provenance.items())
    }


def _conflicting_numeric_pair_count(
    coordinate_entries,
):
    epsg_by_numeric_pair = {}
    for _, token in coordinate_entries:
        parts = token.split("|", 2)
        if len(parts) != 3 or not parts[0].startswith(
            "EPSG:"
        ):
            continue
        numeric_pair = (parts[1], parts[2])
        epsg_by_numeric_pair.setdefault(
            numeric_pair,
            set(),
        ).add(parts[0])
    return sum(
        len(epsg_values) > 1
        for epsg_values in epsg_by_numeric_pair.values()
    )


def _canonical_ring_tokens(tokens):
    ring = list(tokens)
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring.pop()
    if not ring:
        return []

    candidates = []
    for sequence in (ring, list(reversed(ring))):
        candidates.extend(
            tuple(sequence[index:] + sequence[:index])
            for index in range(len(sequence))
        )
    return list(min(candidates))


def _has_transformed_coordinate(point):
    try:
        longitude = float(
            point.get("transformed_longitude")
        )
        latitude = float(
            point.get("transformed_latitude")
        )
    except (TypeError, ValueError):
        return False
    return math.isfinite(longitude) and math.isfinite(
        latitude
    )


def _fingerprint_values(values):
    return hashlib.sha256(
        "\n".join(sorted(values)).encode("utf-8")
    ).hexdigest()


def _fingerprint_sequence(values):
    return hashlib.sha256(
        "\n".join(values).encode("utf-8")
    ).hexdigest()


def _unreliable_comparison(
    primary_geometry,
    refined_geometry,
    reason,
    token_sets=None,
    polygon_sets=None,
):
    primary_tokens, refined_tokens = token_sets or (set(), set())
    primary_polygons, refined_polygons = polygon_sets or (set(), set())
    return {
        "comparison_status": "COMPARISON_UNRELIABLE",
        "classification": "MIXED_OR_OTHER",
        "diagnostic_reason": reason,
        "primary_coordinate_records": primary_geometry.get(
            "coordinate_record_count"
        ),
        "refined_coordinate_records": refined_geometry.get(
            "coordinate_record_count"
        ),
        "primary_unique_projected": len(primary_tokens),
        "refined_unique_projected": len(refined_tokens),
        "common_unique_projected": len(primary_tokens & refined_tokens),
        "refined_only_unique_projected": len(
            refined_tokens - primary_tokens
        ),
        "primary_only_unique_projected": len(
            primary_tokens - refined_tokens
        ),
        "primary_polygon_count": primary_geometry.get("polygon_count"),
        "refined_polygon_count": refined_geometry.get("polygon_count"),
        "exact_common_polygon_count": len(
            primary_polygons & refined_polygons
        ),
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
