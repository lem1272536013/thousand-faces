#!/usr/bin/env python3
"""Safe OSS object identities and lifecycle records for temporary ASR audio."""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Literal, Mapping, cast

from artifacts import file_sha256
from io_utils import atomic_write_json
from redaction import scrub_text


DEFAULT_PREFIX = "creator-agent-studio/audio"
_SAFE_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SAFE_SUFFIX = re.compile(r"\.[A-Za-z0-9]{1,16}\Z")
_MANIFEST_LOCK = threading.RLock()
_MANIFEST_SCHEMA_VERSION = 1
_MIN_FAILURE_RETENTION_SECONDS = 60
_MAX_FAILURE_RETENTION_SECONDS = 30 * 24 * 60 * 60


class OSSLifecycleError(ValueError):
    """Raised when an OSS object or lifecycle setting is outside policy."""


def _safe_segment(value: object, *, label: str) -> str:
    raw = str(value).strip()
    if not raw:
        raise OSSLifecycleError(f"{label} must not be empty")
    if _SAFE_SEGMENT.fullmatch(raw) and raw not in {".", ".."}:
        return raw

    import hashlib

    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"{label}-{digest}"


def configured_prefix(environment: Mapping[str, str] | None = None) -> str:
    source = os.environ if environment is None else environment
    raw = source.get("ALI_OSS_PREFIX", DEFAULT_PREFIX).strip("/")
    parts = raw.split("/") if raw else []
    if not parts or any(
        part in {"", ".", ".."} or not _SAFE_SEGMENT.fullmatch(part)
        for part in parts
    ):
        raise OSSLifecycleError("ALI_OSS_PREFIX must contain only safe path segments")
    return "/".join(parts)


@dataclass(frozen=True)
class OSSObjectContext:
    project_id: str
    run_id: str
    video_id: str
    chunk_id: str

    def __post_init__(self) -> None:
        for label, value in (
            ("project", self.project_id),
            ("run", self.run_id),
            ("video", self.video_id),
            ("chunk", self.chunk_id),
        ):
            if value in {".", ".."} or not _SAFE_SEGMENT.fullmatch(value):
                raise OSSLifecycleError(f"{label} contains an unsafe OSS path segment")

    @classmethod
    def from_run_dir(
        cls,
        run_dir: Path,
        *,
        video_id: str,
        chunk_id: str,
    ) -> "OSSObjectContext":
        run_path = Path(run_dir)
        return cls(
            project_id=_safe_segment(run_path.parent.name, label="project"),
            run_id=_safe_segment(run_path.name, label="run"),
            video_id=_safe_segment(video_id, label="video"),
            chunk_id=_safe_segment(chunk_id, label="chunk"),
        )

    def path(self) -> str:
        return "/".join((self.project_id, self.run_id, self.video_id, self.chunk_id))


@dataclass(frozen=True)
class OSSUpload:
    bucket_name: str
    object_key: str
    source_sha256: str
    source_size_bytes: int
    signed_url: str = field(repr=False)
    uploaded_at: str
    context: OSSObjectContext


@dataclass(frozen=True)
class OSSLifecyclePolicy:
    mode: Literal["delete_after_asr", "retain"]
    failure_retention_seconds: int


@dataclass(frozen=True)
class OSSLifecycleOutcome:
    cleanup_status: str
    retain_until: str | None = None
    cleanup_issue: str | None = None


def build_upload(
    file_path: Path,
    *,
    context: OSSObjectContext,
    bucket_name: str,
    signed_url: str,
    now: datetime | None = None,
    environment: Mapping[str, str] | None = None,
) -> OSSUpload:
    source = Path(file_path)
    if not source.is_file():
        raise OSSLifecycleError(f"OSS upload source is not a file: {source.name}")
    digest = file_sha256(source)
    suffix = source.suffix.lower() if _SAFE_SUFFIX.fullmatch(source.suffix) else ""
    object_key = f"{configured_prefix(environment)}/{context.path()}/{digest}{suffix}"
    timestamp = now or datetime.now(timezone.utc)
    return OSSUpload(
        bucket_name=bucket_name,
        object_key=object_key,
        source_sha256=digest,
        source_size_bytes=source.stat().st_size,
        signed_url=signed_url,
        uploaded_at=timestamp.isoformat(),
        context=context,
    )


def object_key_for_file(
    file_path: Path,
    *,
    context: OSSObjectContext,
    environment: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    source = Path(file_path)
    digest = file_sha256(source)
    suffix = source.suffix.lower() if _SAFE_SUFFIX.fullmatch(source.suffix) else ""
    key = f"{configured_prefix(environment)}/{context.path()}/{digest}{suffix}"
    return key, digest


def assert_managed_object_key(
    object_key: str,
    environment: Mapping[str, str] | None = None,
) -> None:
    prefix = configured_prefix(environment)
    if not object_key.startswith(f"{prefix}/"):
        raise OSSLifecycleError("refusing to operate on an unmanaged OSS object key")
    parts = object_key.split("/")
    prefix_parts = prefix.split("/")
    if len(parts) != len(prefix_parts) + 5 or any(
        part in {"", ".", ".."} or not _SAFE_SEGMENT.fullmatch(part)
        for part in parts
    ):
        raise OSSLifecycleError("OSS object key does not match the managed object layout")


def load_policy(environment: Mapping[str, str] | None = None) -> OSSLifecyclePolicy:
    source = os.environ if environment is None else environment
    mode = source.get("ALI_OSS_LIFECYCLE_POLICY", "delete_after_asr").strip().lower()
    if mode not in {"delete_after_asr", "retain"}:
        raise OSSLifecycleError(
            "ALI_OSS_LIFECYCLE_POLICY must be delete_after_asr or retain"
        )
    raw_retention = source.get("ALI_OSS_FAILURE_RETENTION_SECONDS", "86400")
    try:
        retention = int(raw_retention)
    except ValueError as error:
        raise OSSLifecycleError(
            "ALI_OSS_FAILURE_RETENTION_SECONDS must be an integer"
        ) from error
    if not _MIN_FAILURE_RETENTION_SECONDS <= retention <= _MAX_FAILURE_RETENTION_SECONDS:
        raise OSSLifecycleError(
            "ALI_OSS_FAILURE_RETENTION_SECONDS must be between 60 and 2592000"
        )
    return OSSLifecyclePolicy(
        mode=cast(Literal["delete_after_asr", "retain"], mode),
        failure_retention_seconds=retention,
    )


def _manifest_path(run_dir: Path) -> Path:
    return Path(run_dir) / "logs" / "oss_lifecycle.json"


def _timestamp(value: datetime | None) -> datetime:
    result = value or datetime.now(timezone.utc)
    if result.tzinfo is None:
        raise OSSLifecycleError("lifecycle timestamps must include a timezone")
    return result


def _empty_manifest(policy: OSSLifecyclePolicy) -> dict:
    return {
        "schema_version": _MANIFEST_SCHEMA_VERSION,
        "status": "active",
        "policy": {
            "mode": policy.mode,
            "failure_retention_seconds": policy.failure_retention_seconds,
        },
        "objects": [],
        "issues": [],
    }


def _load_manifest(run_dir: Path, policy: OSSLifecyclePolicy) -> dict:
    path = _manifest_path(run_dir)
    if not path.exists():
        return _empty_manifest(policy)
    import json

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise OSSLifecycleError("OSS lifecycle manifest is unreadable") from error
    if not isinstance(payload, dict) or payload.get("schema_version") != _MANIFEST_SCHEMA_VERSION:
        raise OSSLifecycleError("OSS lifecycle manifest has an unsupported schema")
    if not isinstance(payload.get("objects"), list) or not isinstance(payload.get("issues"), list):
        raise OSSLifecycleError("OSS lifecycle manifest has an invalid structure")
    return payload


def _entry_for_upload(upload: OSSUpload, created_at: str) -> dict:
    return {
        "bucket": upload.bucket_name,
        "object_key": upload.object_key,
        "source_sha256": upload.source_sha256,
        "source_size_bytes": upload.source_size_bytes,
        "context": {
            "project_id": upload.context.project_id,
            "run_id": upload.context.run_id,
            "video_id": upload.context.video_id,
            "chunk_id": upload.context.chunk_id,
        },
        "uploaded_at": upload.uploaded_at,
        "registered_at": created_at,
        "asr_outcome": "pending",
        "cleanup": {"status": "pending"},
    }


def _find_entry(manifest: dict, object_key: str) -> dict | None:
    return next(
        (
            item
            for item in manifest["objects"]
            if isinstance(item, dict) and item.get("object_key") == object_key
        ),
        None,
    )


def _assert_current_bucket(bucket_name: object) -> None:
    configured = os.environ.get("ALI_OSS_BUCKET", "")
    if not configured or str(bucket_name) != configured:
        raise OSSLifecycleError(
            "refusing OSS cleanup because the configured bucket does not match the manifest"
        )


def _cleanup_failure(
    manifest: dict,
    entry: dict,
    *,
    object_key: str,
    error: Exception,
    recorded_at: str,
) -> OSSLifecycleOutcome:
    safe_error = scrub_text(error, limit=1000)
    issue = f"OSS cleanup failed for {object_key}: {safe_error}"
    previous_cleanup = entry.get("cleanup")
    cleanup_record = {
        "status": "cleanup_failed",
        "recorded_at": recorded_at,
        "issue": issue,
    }
    if isinstance(previous_cleanup, dict) and previous_cleanup.get("retain_until"):
        cleanup_record["retain_until"] = previous_cleanup["retain_until"]
    entry["cleanup"] = cleanup_record
    manifest["issues"].append(
        {
            "code": "OSS_CLEANUP_FAILED",
            "object_key": object_key,
            "message": issue,
            "recorded_at": recorded_at,
        }
    )
    return OSSLifecycleOutcome(
        cleanup_status="cleanup_failed",
        cleanup_issue=issue,
    )


def _write_manifest(run_dir: Path, manifest: dict) -> None:
    statuses = {
        item.get("cleanup", {}).get("status")
        for item in manifest["objects"]
        if isinstance(item, dict)
    }
    manifest["status"] = (
        "complete" if statuses and statuses <= {"deleted", "retained"} else "action_required"
        if statuses & {"cleanup_failed", "pending_expiry"}
        else "active"
    )
    atomic_write_json(_manifest_path(run_dir), manifest)


def register_upload(
    run_dir: Path,
    upload: OSSUpload,
    *,
    now: datetime | None = None,
) -> None:
    """Persist a secret-free record for a newly uploaded temporary object."""
    assert_managed_object_key(upload.object_key)
    timestamp = _timestamp(now).isoformat()
    policy = load_policy()
    with _MANIFEST_LOCK:
        manifest = _load_manifest(run_dir, policy)
        entry = _find_entry(manifest, upload.object_key)
        if entry is None:
            manifest["objects"].append(_entry_for_upload(upload, timestamp))
        elif entry.get("source_sha256") != upload.source_sha256:
            raise OSSLifecycleError("OSS object key is already registered for different content")
        _write_manifest(run_dir, manifest)


def finalize_upload(
    run_dir: Path,
    upload: OSSUpload,
    *,
    asr_outcome: Literal["succeeded", "failed"],
    delete_callback: Callable[[str], None],
    now: datetime | None = None,
) -> OSSLifecycleOutcome:
    """Apply the configured cleanup policy and atomically record its outcome."""
    if asr_outcome not in {"succeeded", "failed"}:
        raise OSSLifecycleError("ASR outcome must be succeeded or failed")
    moment = _timestamp(now)
    policy = load_policy()
    with _MANIFEST_LOCK:
        manifest = _load_manifest(run_dir, policy)
        entry = _find_entry(manifest, upload.object_key)
        if entry is None:
            entry = _entry_for_upload(upload, moment.isoformat())
            manifest["objects"].append(entry)
        entry["asr_outcome"] = asr_outcome

        if policy.mode == "retain":
            entry["cleanup"] = {
                "status": "retained",
                "reason": "explicit_retain",
                "recorded_at": moment.isoformat(),
            }
            _write_manifest(run_dir, manifest)
            return OSSLifecycleOutcome(cleanup_status="retained")

        if asr_outcome == "failed":
            retain_until = (moment + timedelta(seconds=policy.failure_retention_seconds)).isoformat()
            entry["cleanup"] = {
                "status": "pending_expiry",
                "reason": "asr_failed",
                "retain_until": retain_until,
                "recorded_at": moment.isoformat(),
            }
            _write_manifest(run_dir, manifest)
            return OSSLifecycleOutcome(
                cleanup_status="pending_expiry",
                retain_until=retain_until,
            )

        try:
            _assert_current_bucket(upload.bucket_name)
            delete_callback(upload.object_key)
        except Exception as error:
            outcome = _cleanup_failure(
                manifest,
                entry,
                object_key=upload.object_key,
                error=error,
                recorded_at=moment.isoformat(),
            )
            _write_manifest(run_dir, manifest)
            return outcome

        entry["cleanup"] = {
            "status": "deleted",
            "deleted_at": moment.isoformat(),
        }
        _write_manifest(run_dir, manifest)
        return OSSLifecycleOutcome(cleanup_status="deleted")


def cleanup_expired_uploads(
    run_dir: Path,
    *,
    delete_callback: Callable[[str], None],
    now: datetime | None = None,
) -> tuple[OSSLifecycleOutcome, ...]:
    """Delete failed-ASR objects whose bounded retention window has elapsed."""
    moment = _timestamp(now)
    policy = load_policy()
    outcomes: list[OSSLifecycleOutcome] = []
    changed = False
    with _MANIFEST_LOCK:
        manifest = _load_manifest(run_dir, policy)
        for entry in manifest["objects"]:
            if not isinstance(entry, dict):
                continue
            cleanup = entry.get("cleanup")
            if not isinstance(cleanup, dict):
                continue
            previous_status = cleanup.get("status")
            if previous_status not in {"pending_expiry", "cleanup_failed"}:
                continue
            raw_retain_until = cleanup.get("retain_until")
            if raw_retain_until:
                try:
                    retain_until = datetime.fromisoformat(str(raw_retain_until))
                except ValueError as error:
                    raise OSSLifecycleError(
                        "OSS lifecycle manifest contains an invalid retain_until timestamp"
                    ) from error
                if retain_until.tzinfo is None:
                    raise OSSLifecycleError(
                        "OSS lifecycle manifest retain_until timestamp must include a timezone"
                    )
                if retain_until > moment:
                    continue
            elif previous_status == "pending_expiry":
                raise OSSLifecycleError(
                    "OSS lifecycle manifest pending_expiry cleanup is missing retain_until"
                )

            object_key = str(entry.get("object_key") or "")
            try:
                assert_managed_object_key(object_key)
                _assert_current_bucket(entry.get("bucket"))
                delete_callback(object_key)
            except Exception as error:
                outcomes.append(
                    _cleanup_failure(
                        manifest,
                        entry,
                        object_key=object_key or "<missing-object-key>",
                        error=error,
                        recorded_at=moment.isoformat(),
                    )
                )
            else:
                entry["cleanup"] = {
                    "status": "deleted",
                    "reason": (
                        "cleanup_retry_succeeded"
                        if previous_status == "cleanup_failed"
                        else "retention_elapsed"
                    ),
                    "deleted_at": moment.isoformat(),
                }
                outcomes.append(OSSLifecycleOutcome(cleanup_status="deleted"))
            changed = True

        if changed:
            _write_manifest(run_dir, manifest)
    return tuple(outcomes)
