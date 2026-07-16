#!/usr/bin/env python3
"""Stable structured results shared by pipeline entry points and automation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

import redaction
from io_utils import atomic_write_json


StepStatus = Literal["succeeded", "partial", "failed", "skipped"]
PipelineStatus = Literal["succeeded", "partial", "failed"]
PIPELINE_RESULT_SCHEMA_VERSION = 2
ERROR_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
BRACKETED_ERROR_CODE_PATTERN = re.compile(r"^\[([A-Z][A-Z0-9_]{2,63})\]")
CANONICAL_ERROR_CODES = frozenset(
    {
        "NETWORK_TIMEOUT",
        "RATE_LIMIT",
        "PROVIDER_UNAVAILABLE",
        "INVALID_MEDIA",
        "ASR_PARSE_FAILED",
        "STALE_ARTIFACT",
        "INVALID_JSON",
        "INVALID_INPUT",
        "WORKFLOW_STATE_ERROR",
        "QUALITY_GATE_FAILED",
        "MISSING_TRANSCRIPTS",
        "DOWNLOAD_FAILED",
        "AUDIO_EXTRACTION_FAILED",
        "ASR_FAILED",
        "STEP_FAILED",
        "UNEXPECTED_ERROR",
    }
)


def normalize_error_token(value: object) -> str:
    """Convert a provider/exception token into a bounded machine label."""

    text = str(value or "").strip()
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", text)
    token = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").upper()
    return token[:64] if ERROR_CODE_PATTERN.fullmatch(token[:64]) else ""


def detail_error_code(value: object) -> str:
    """Extract an explicit bracketed code or normalize a direct code value."""

    text = str(value or "").strip()
    bracketed = BRACKETED_ERROR_CODE_PATTERN.match(text)
    return bracketed.group(1) if bracketed else normalize_error_token(text)


def canonical_error_code(detail_code: object) -> str:
    """Map detailed subsystem failures to a small, stable operational taxonomy."""

    detail = detail_error_code(detail_code)
    if not detail:
        return "UNEXPECTED_ERROR"
    if detail in CANONICAL_ERROR_CODES:
        return detail
    if detail == "RATE_LIMIT":
        return "RATE_LIMIT"
    if (
        detail in {"NETWORK_CONNECTION_ERROR", "PROVIDER_CONNECT_TIMEOUT"}
        or "DEADLINE" in detail
        or detail.endswith("_TIMEOUT")
        or detail in {"CONNECT_TIMEOUT", "READ_TIMEOUT", "CONNECTION_ERROR"}
    ):
        return "NETWORK_TIMEOUT"
    if detail in {"HTTP_SERVER_ERROR", "PROVIDER_UNAVAILABLE"}:
        return "PROVIDER_UNAVAILABLE"
    if detail.startswith("MEDIA_") or detail in {
        "DOWNLOAD_EMPTY",
        "DOWNLOAD_TOO_LARGE",
        "DOWNLOAD_CONTENT_REJECTED",
    }:
        return "INVALID_MEDIA"
    if detail in {"ASR_PARSE_ERROR", "TRANSCRIPT_MERGE_ERROR", "ASR_PARSE_FAILED"}:
        return "ASR_PARSE_FAILED"
    if detail in {"ARTIFACT_STALE", "STALE_ARTIFACT", "FINGERPRINT_MISMATCH"}:
        return "STALE_ARTIFACT"
    if detail in {"JSON_DECODE_ERROR", "INVALID_JSON"}:
        return "INVALID_JSON"
    if detail in {"INPUT_VALIDATION_ERROR", "ARGUMENT_TYPE_ERROR", "INVALID_INPUT"}:
        return "INVALID_INPUT"
    if detail in {"WORKFLOW_STATE_ERROR", "WORKFLOW_CORRUPT"}:
        return "WORKFLOW_STATE_ERROR"
    return "UNEXPECTED_ERROR"


def fallback_step_error_code(step_id: str) -> str:
    return {
        "download_videos": "DOWNLOAD_FAILED",
        "extract_audio_with_ffmpeg": "AUDIO_EXTRACTION_FAILED",
        "transcribe_with_aliyun_asr": "ASR_FAILED",
        "normalize_transcripts": "MISSING_TRANSCRIPTS",
        "quality_check": "QUALITY_GATE_FAILED",
    }.get(step_id, "STEP_FAILED")


@dataclass(frozen=True, slots=True)
class StepResult:
    """Terminal result for one pipeline step."""

    step_id: str
    status: StepStatus
    input_count: int = 0
    succeeded_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    duration_ms: int = 0
    started_at: str = ""
    completed_at: str = ""
    error_codes: tuple[str, ...] = ()
    output_paths: tuple[str, ...] = ()
    issues: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {"succeeded", "partial", "failed", "skipped"}:
            raise ValueError(f"unsupported step status: {self.status}")
        if not self.step_id:
            raise ValueError("step_id must not be empty")
        counts = (self.input_count, self.succeeded_count, self.failed_count, self.skipped_count)
        if any(not isinstance(value, int) or value < 0 for value in counts):
            raise ValueError("step counts must be non-negative integers")
        if self.succeeded_count + self.failed_count + self.skipped_count != self.input_count:
            raise ValueError("step counts must add up to input_count")
        if not isinstance(self.duration_ms, int) or self.duration_ms < 0:
            raise ValueError("duration_ms must be a non-negative integer")
        if bool(self.started_at) != bool(self.completed_at):
            raise ValueError("step timing must include both started_at and completed_at")
        if self.started_at:
            try:
                started = datetime.fromisoformat(self.started_at)
                completed = datetime.fromisoformat(self.completed_at)
            except ValueError as error:
                raise ValueError("step timing must use ISO-8601 timestamps") from error
            if started.tzinfo is None or completed.tzinfo is None or completed < started:
                raise ValueError("step timing must be timezone-aware and ordered")
        if self.status == "succeeded" and (self.failed_count or self.skipped_count):
            raise ValueError("succeeded step counts cannot include failed or skipped items")
        if self.status == "failed" and (self.failed_count == 0 or self.succeeded_count or self.skipped_count):
            raise ValueError("failed step counts must contain only failed items")
        if self.status == "partial" and sum(value > 0 for value in counts[1:]) < 2:
            raise ValueError("partial step counts must contain at least two outcomes")
        if self.status == "skipped" and (self.succeeded_count or self.failed_count):
            raise ValueError("skipped step counts cannot include succeeded or failed items")
        if self.error_codes and not self.failed_count:
            raise ValueError("error_codes require at least one failed item")
        object.__setattr__(
            self,
            "issues",
            tuple(redaction.scrub_text(issue, limit=500) for issue in self.issues),
        )
        normalized_codes = tuple(
            dict.fromkeys(canonical_error_code(code) for code in self.error_codes)
        )
        if self.failed_count and not normalized_codes:
            normalized_codes = (fallback_step_error_code(self.step_id),)
        object.__setattr__(self, "error_codes", normalized_codes)

    @property
    def counts(self) -> dict[str, int]:
        return {
            "input": self.input_count,
            "succeeded": self.succeeded_count,
            "failed": self.failed_count,
            "skipped": self.skipped_count,
        }

    @classmethod
    def succeeded(
        cls,
        step_id: str,
        *,
        input_count: int = 1,
        duration_ms: int = 0,
        output_paths: tuple[str, ...] = (),
    ) -> StepResult:
        return cls(
            step_id=step_id,
            status="succeeded",
            input_count=input_count,
            succeeded_count=input_count,
            duration_ms=duration_ms,
            output_paths=output_paths,
        )

    @classmethod
    def failed(
        cls,
        step_id: str,
        *,
        input_count: int = 1,
        duration_ms: int = 0,
        output_paths: tuple[str, ...] = (),
        issues: tuple[str, ...] = (),
        error_codes: tuple[str, ...] = (),
    ) -> StepResult:
        return cls(
            step_id=step_id,
            status="failed",
            input_count=input_count,
            failed_count=input_count,
            duration_ms=duration_ms,
            output_paths=output_paths,
            issues=issues,
            error_codes=error_codes,
        )

    @classmethod
    def skipped(
        cls,
        step_id: str,
        *,
        input_count: int = 0,
        duration_ms: int = 0,
        issues: tuple[str, ...] = (),
    ) -> StepResult:
        return cls(
            step_id=step_id,
            status="skipped",
            input_count=input_count,
            skipped_count=input_count,
            duration_ms=duration_ms,
            issues=issues,
        )

    @classmethod
    def from_rows(
        cls,
        step_id: str,
        rows: Sequence[Mapping[str, Any]],
        *,
        duration_ms: int = 0,
        output_paths: tuple[str, ...] = (),
    ) -> StepResult:
        succeeded_count = 0
        failed_count = 0
        skipped_count = 0
        issues: list[str] = []
        error_codes: list[str] = []
        success_statuses = {"succeeded", "completed", "downloaded", "extracted", "transcribed"}
        for row in rows:
            status = str(row.get("status") or "").lower()
            cleanup_issue = str(row.get("cleanup_issue") or "").strip()
            if cleanup_issue:
                issues.append(cleanup_issue[:500])
            verified_cache = status == "skipped" and row.get("cache_status") == "verified" and bool(
                row.get("path") or row.get("transcript")
            )
            if status in success_statuses or verified_cache:
                succeeded_count += 1
            elif status == "skipped":
                skipped_count += 1
                reason = str(row.get("reason") or "").strip()
                if reason:
                    issues.append(reason[:500])
            else:
                failed_count += 1
                issue = str(row.get("error") or row.get("reason") or f"unexpected row status: {status or 'missing'}")
                issues.append(issue[:500])
                detail = detail_error_code(row.get("error_code") or issue)
                canonical = canonical_error_code(detail)
                if canonical != "UNEXPECTED_ERROR":
                    error_codes.append(canonical)

        input_count = len(rows)
        outcome_kinds = sum(value > 0 for value in (succeeded_count, failed_count, skipped_count))
        if input_count == 0:
            status_value: StepStatus = "skipped"
        elif outcome_kinds > 1:
            status_value = "partial"
        elif failed_count:
            status_value = "failed"
        elif skipped_count:
            status_value = "skipped"
        else:
            status_value = "succeeded"
        return cls(
            step_id=step_id,
            status=status_value,
            input_count=input_count,
            succeeded_count=succeeded_count,
            failed_count=failed_count,
            skipped_count=skipped_count,
            duration_ms=duration_ms,
            output_paths=output_paths,
            issues=tuple(dict.fromkeys(issues)),
            error_codes=tuple(dict.fromkeys(error_codes)),
        )

    def with_timing(
        self,
        *,
        started_at: str,
        completed_at: str,
        duration_ms: int,
    ) -> StepResult:
        return replace(
            self,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "status": self.status,
            "counts": self.counts,
            "duration_ms": self.duration_ms,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error_codes": list(self.error_codes),
            "output_paths": list(self.output_paths),
            "issues": list(self.issues),
        }


@dataclass(frozen=True, slots=True)
class PipelineResult:
    """Terminal pipeline result whose status and process exit code cannot diverge."""

    run_dir: str
    status: PipelineStatus
    exit_code: int
    steps: tuple[StepResult, ...]
    quality_passed: bool | None
    error: Mapping[str, str] | None = None
    finished_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    schema_version: int = PIPELINE_RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.status not in {"succeeded", "partial", "failed"}:
            raise ValueError(f"unsupported pipeline status: {self.status}")
        expected_exit_code = 0 if self.status == "succeeded" else 1
        if self.exit_code != expected_exit_code:
            raise ValueError("pipeline exit_code must match terminal status")
        if self.status == "succeeded" and self.quality_passed is not True:
            raise ValueError("successful pipeline requires quality_passed=true")
        if self.error is not None:
            object.__setattr__(
                self,
                "error",
                {
                    str(key): (
                        redaction.redact_secret(value)
                        if redaction.is_secret_key(key)
                        else redaction.scrub_text(value, limit=500)
                    )
                    for key, value in self.error.items()
                },
            )

    @classmethod
    def from_steps(
        cls,
        run_dir: str,
        steps: Sequence[StepResult],
        *,
        quality_passed: bool | None,
        error: Mapping[str, str] | None = None,
    ) -> PipelineResult:
        terminal_steps = tuple(steps)
        if error is not None or quality_passed is not True or any(step.status == "failed" for step in terminal_steps):
            status: PipelineStatus = "failed"
        elif any(step.status == "partial" for step in terminal_steps):
            status = "partial"
        else:
            status = "succeeded"
        return cls(
            run_dir=run_dir,
            status=status,
            exit_code=0 if status == "succeeded" else 1,
            steps=terminal_steps,
            quality_passed=quality_passed,
            error=dict(error) if error is not None else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_dir": self.run_dir,
            "status": self.status,
            "exit_code": self.exit_code,
            "quality_passed": self.quality_passed,
            "steps": [step.to_dict() for step in self.steps],
            "error": dict(self.error) if self.error is not None else None,
            "finished_at": self.finished_at,
        }


def write_pipeline_result(path: Path, result: PipelineResult) -> Path:
    atomic_write_json(path, result.to_dict())
    return path
