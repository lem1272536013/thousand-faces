#!/usr/bin/env python3
"""Structured, secret-safe telemetry for one local pipeline run."""

from __future__ import annotations

import json
import re
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TextIO

import redaction
from io_utils import atomic_write_json
from pipeline_models import (
    PipelineResult,
    StepResult,
    canonical_error_code,
    detail_error_code,
    normalize_error_token,
)


EVENT_SCHEMA_VERSION = 1
ERROR_MESSAGE_LIMIT = 500
RECOVERABLE_ERROR_CODES = frozenset(
    {
        "NETWORK_TIMEOUT",
        "PROVIDER_UNAVAILABLE",
        "RATE_LIMIT",
        "STALE_ARTIFACT",
        "WORKFLOW_STATE_ERROR",
    }
)
EVENT_NAMES = frozenset(
    {"pipeline_started", "pipeline_resumed", "step_started", "step_finished", "pipeline_finished"}
)
EVENT_LEVELS = frozenset({"info", "warn", "error"})
CORRELATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


class StructuredLogError(RuntimeError):
    """Raised when an existing structured event stream violates its contract."""


@dataclass(frozen=True, slots=True)
class ErrorDescriptor:
    error_code: str
    detail_code: str
    message: str
    recoverable: bool
    recovery_hint: str


@dataclass(frozen=True, slots=True)
class StepTimer:
    step_id: str
    started_at: str
    monotonic_started: float


@dataclass(frozen=True, slots=True)
class RunEvent:
    sequence: int
    timestamp: str
    event: str
    level: str
    correlation_id: str
    run_id: str
    step_id: str = ""
    status: str = ""
    started_at: str = ""
    completed_at: str = ""
    duration_ms: int = 0
    counts: Mapping[str, int] = field(
        default_factory=lambda: {"input": 0, "succeeded": 0, "failed": 0, "skipped": 0}
    )
    error_codes: tuple[str, ...] = ()
    recoverable: bool | None = None
    message: str = ""

    def __post_init__(self) -> None:
        if self.event not in EVENT_NAMES:
            raise StructuredLogError(f"unsupported event name: {self.event}")
        if self.level not in EVENT_LEVELS:
            raise StructuredLogError(f"unsupported event level: {self.level}")
        if self.sequence < 1:
            raise StructuredLogError("event sequence must be positive")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": EVENT_SCHEMA_VERSION,
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "event": self.event,
            "level": self.level,
            "correlation_id": self.correlation_id,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "counts": dict(self.counts),
            "error_codes": list(self.error_codes),
            "recoverable": self.recoverable,
            "message": self.message,
        }

    def console_line(self) -> str:
        parts = [
            f"event={self.event}",
            f"correlation_id={self.correlation_id}",
        ]
        if self.step_id:
            parts.append(f"step={self.step_id}")
        if self.status:
            parts.append(f"status={self.status}")
        if self.event in {"step_finished", "pipeline_finished"}:
            parts.append(f"duration_ms={self.duration_ms}")
            parts.extend(f"{key}={self.counts[key]}" for key in ("input", "succeeded", "failed", "skipped"))
        if self.error_codes:
            parts.append("error_codes=" + ",".join(self.error_codes))
        if self.message:
            parts.append(f"message={self.message}")
        return "[telemetry] " + " ".join(parts)


def _type_detail_code(error: BaseException) -> str:
    type_name = type(error).__name__
    aliases = {
        "ASRParseError": "ASR_PARSE_ERROR",
        "TranscriptMergeError": "TRANSCRIPT_MERGE_ERROR",
        "JSONDecodeError": "JSON_DECODE_ERROR",
        "InputValidationError": "INPUT_VALIDATION_ERROR",
    }
    return aliases.get(type_name, normalize_error_token(type_name) or "UNKNOWN_ERROR")


def _recovery_hint(error_code: str) -> str:
    if error_code in {"NETWORK_TIMEOUT", "PROVIDER_UNAVAILABLE", "RATE_LIMIT"}:
        return "retry the failed step after provider connectivity recovers"
    if error_code == "STALE_ARTIFACT":
        return "resume the run to rebuild stale artifacts from current inputs"
    if error_code == "WORKFLOW_STATE_ERROR":
        return "inspect logs/workflow_recovery_error.json before resuming"
    if error_code == "INVALID_MEDIA":
        return "replace or redownload the rejected media before resuming"
    if error_code == "ASR_PARSE_FAILED":
        return "inspect the preserved raw ASR response before resuming"
    if error_code == "INVALID_JSON":
        return "repair or replace the invalid JSON input before retrying"
    if error_code == "INVALID_INPUT":
        return "correct the rejected input or configuration and retry"
    return "inspect the failed step summary before retrying"


def classify_exception(
    error: BaseException,
    *,
    known_secrets: Sequence[str] = (),
) -> ErrorDescriptor:
    """Return a stable low-cardinality category and bounded diagnostic summary."""

    raw_code = getattr(error, "code", "")
    explicit_detail = detail_error_code(raw_code)
    detail_code = explicit_detail or _type_detail_code(error)
    error_code = canonical_error_code(detail_code)
    message = redaction.scrub_text(
        str(error) or type(error).__name__,
        known_secrets=known_secrets,
        limit=ERROR_MESSAGE_LIMIT,
    )
    return ErrorDescriptor(
        error_code=error_code,
        detail_code=detail_code,
        message=message,
        recoverable=error_code in RECOVERABLE_ERROR_CODES,
        recovery_hint=_recovery_hint(error_code),
    )


class StructuredRunLogger:
    """Persist a small atomic event stream and render those same events to a console."""

    def __init__(
        self,
        run_dir: Path,
        *,
        correlation_id: str | None = None,
        known_secrets: Sequence[str] = (),
        utc_now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        monotonic: Callable[[], float] = time.monotonic,
        console: TextIO = sys.stdout,
    ) -> None:
        self.run_dir = Path(run_dir)
        self.run_id = self.run_dir.name
        self.correlation_id = correlation_id or self.run_id
        if not CORRELATION_ID_PATTERN.fullmatch(self.correlation_id):
            raise StructuredLogError("correlation_id must be a bounded machine label")
        self.known_secrets = tuple(known_secrets)
        self.utc_now = utc_now
        self.monotonic = monotonic
        self.console = console
        self.path = self.run_dir / "logs" / "pipeline_events.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._events = self._load_existing_events()

    def _load_existing_events(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise StructuredLogError(
                f"cannot read existing structured event log: {type(error).__name__}"
            ) from None
        if not isinstance(payload, dict) or payload.get("schema_version") != EVENT_SCHEMA_VERSION:
            raise StructuredLogError("structured event log schema is invalid")
        if payload.get("correlation_id") != self.correlation_id:
            raise StructuredLogError("structured event log correlation_id does not match this run")
        if payload.get("run_id") != self.run_id:
            raise StructuredLogError("structured event log run_id does not match this run")
        events = payload.get("events")
        if not isinstance(events, list) or any(not isinstance(event, dict) for event in events):
            raise StructuredLogError("structured event log events must be an array of objects")
        for expected_sequence, event in enumerate(events, start=1):
            if (
                event.get("schema_version") != EVENT_SCHEMA_VERSION
                or event.get("sequence") != expected_sequence
                or event.get("event") not in EVENT_NAMES
                or event.get("correlation_id") != self.correlation_id
                or event.get("run_id") != self.run_id
            ):
                raise StructuredLogError(
                    f"structured event log event {expected_sequence} violates its identity contract"
                )
        return list(events)

    def _timestamp(self) -> str:
        value = self.utc_now()
        if value.tzinfo is None:
            raise StructuredLogError("event timestamps must be timezone-aware")
        return value.isoformat()

    def _safe_message(self, value: object) -> str:
        return redaction.scrub_text(
            value,
            known_secrets=self.known_secrets,
            limit=ERROR_MESSAGE_LIMIT,
        )

    def _emit(
        self,
        *,
        event: str,
        level: str,
        step_id: str = "",
        status: str = "",
        started_at: str = "",
        completed_at: str = "",
        duration_ms: int = 0,
        counts: Mapping[str, int] | None = None,
        error_codes: tuple[str, ...] = (),
        recoverable: bool | None = None,
        message: str = "",
    ) -> RunEvent:
        record = RunEvent(
            sequence=len(self._events) + 1,
            timestamp=self._timestamp(),
            correlation_id=self.correlation_id,
            run_id=self.run_id,
            event=event,
            level=level,
            step_id=step_id,
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            counts=counts or {"input": 0, "succeeded": 0, "failed": 0, "skipped": 0},
            error_codes=error_codes,
            recoverable=recoverable,
            message=message,
        )
        self._events.append(record.to_dict())
        atomic_write_json(
            self.path,
            {
                "schema_version": EVENT_SCHEMA_VERSION,
                "correlation_id": self.correlation_id,
                "run_id": self.run_id,
                "events": self._events,
            },
        )
        print(record.console_line(), file=self.console)
        return record

    def pipeline_started(self, *, resumed: bool = False, message: str = "") -> RunEvent:
        return self._emit(
            event="pipeline_resumed" if resumed else "pipeline_started",
            level="info",
            status="running",
            message=self._safe_message(message),
        )

    def step_started(self, step_id: str, *, message: str = "") -> StepTimer:
        started_at = self._timestamp()
        timer = StepTimer(step_id, started_at, self.monotonic())
        self._emit(
            event="step_started",
            level="info",
            step_id=step_id,
            status="running",
            started_at=started_at,
            message=self._safe_message(message),
        )
        return timer

    def step_finished(
        self,
        timer: StepTimer,
        result: StepResult,
        *,
        message: str = "",
    ) -> StepResult:
        if timer.step_id != result.step_id:
            raise StructuredLogError(
                f"step timer mismatch: expected {timer.step_id}, got {result.step_id}"
            )
        wall_completed_at = datetime.fromisoformat(self._timestamp())
        duration_ms = max(0, round((self.monotonic() - timer.monotonic_started) * 1000))
        started_at = datetime.fromisoformat(timer.started_at)
        monotonic_completed_at = started_at + timedelta(milliseconds=duration_ms)
        completed_at = max(wall_completed_at, monotonic_completed_at).isoformat()
        timed_result = result.with_timing(
            started_at=timer.started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
        )
        detail = message or "; ".join(timed_result.issues[:3])
        level = "error" if timed_result.status == "failed" else (
            "warn" if timed_result.status == "partial" else "info"
        )
        self._emit(
            event="step_finished",
            level=level,
            step_id=timed_result.step_id,
            status=timed_result.status,
            started_at=timed_result.started_at,
            completed_at=timed_result.completed_at,
            duration_ms=timed_result.duration_ms,
            counts=timed_result.counts,
            error_codes=timed_result.error_codes,
            recoverable=(
                all(code in RECOVERABLE_ERROR_CODES for code in timed_result.error_codes)
                if timed_result.error_codes
                else None
            ),
            message=self._safe_message(detail),
        )
        return timed_result

    def pipeline_finished(self, result: PipelineResult) -> RunEvent:
        counts = {
            key: sum(step.counts[key] for step in result.steps)
            for key in ("input", "succeeded", "failed", "skipped")
        }
        error_codes = tuple(
            dict.fromkeys(code for step in result.steps for code in step.error_codes)
        )
        top_level_error = canonical_error_code(
            (result.error or {}).get("error_code", "")
        )
        if result.error is not None:
            error_codes = tuple(dict.fromkeys((*error_codes, top_level_error)))
        duration_ms = sum(step.duration_ms for step in result.steps)
        message = (result.error or {}).get("message", "")
        return self._emit(
            event="pipeline_finished",
            level="error" if result.status == "failed" else (
                "warn" if result.status == "partial" else "info"
            ),
            status=result.status,
            duration_ms=duration_ms,
            counts=counts,
            error_codes=error_codes,
            recoverable=(
                all(code in RECOVERABLE_ERROR_CODES for code in error_codes)
                if error_codes
                else None
            ),
            message=self._safe_message(message),
        )


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _powershell_quote(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _pipeline_payload(
    run_dir: Path,
    pipeline_result: PipelineResult | Mapping[str, Any] | None,
) -> dict[str, Any]:
    if isinstance(pipeline_result, PipelineResult):
        return pipeline_result.to_dict()
    if isinstance(pipeline_result, Mapping):
        return dict(pipeline_result)
    return _read_json_object(run_dir / "logs" / "pipeline_result.json")


def build_execution_summary(
    run_dir: Path,
    *,
    pipeline_result: PipelineResult | Mapping[str, Any] | None = None,
    quality_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a bounded operator summary from the terminal result and event stream."""

    run_path = Path(run_dir)
    pipeline = _pipeline_payload(run_path, pipeline_result)
    raw_steps = pipeline.get("steps")
    steps = [dict(step) for step in raw_steps if isinstance(step, Mapping)] if isinstance(raw_steps, list) else []
    total_duration_ms = sum(
        int(step.get("duration_ms") or 0)
        for step in steps
        if isinstance(step.get("duration_ms"), int)
    )
    slowest_step = None
    if steps:
        slowest = max(steps, key=lambda step: int(step.get("duration_ms") or 0))
        slowest_step = {
            "step_id": str(slowest.get("step_id") or ""),
            "duration_ms": int(slowest.get("duration_ms") or 0),
            "status": str(slowest.get("status") or ""),
        }

    failed_steps: list[dict[str, Any]] = []
    for step in steps:
        raw_counts = step.get("counts")
        counts: Mapping[str, Any] = raw_counts if isinstance(raw_counts, Mapping) else {}
        failed_count = int(counts.get("failed") or 0)
        if step.get("status") not in {"failed", "partial"} and failed_count == 0:
            continue
        failed_steps.append(
            {
                "step_id": str(step.get("step_id") or ""),
                "status": str(step.get("status") or ""),
                "failed_count": failed_count,
                "error_codes": [str(code) for code in step.get("error_codes") or []],
                "issues": [
                    redaction.scrub_text(issue, limit=ERROR_MESSAGE_LIMIT)
                    for issue in (step.get("issues") or [])[:3]
                ],
            }
        )
    failed_step_codes = tuple(
        dict.fromkeys(
            code
            for step in failed_steps
            for code in step["error_codes"]
        )
    )

    raw_error = pipeline.get("error")
    error = dict(raw_error) if isinstance(raw_error, Mapping) else {}
    detail_code = detail_error_code(error.get("detail_code") or error.get("type"))
    error_code = str(error.get("error_code") or canonical_error_code(detail_code))
    recoverable = str(error.get("recoverable") or "").lower() == "true"
    pipeline_error = None
    if error:
        pipeline_error = {
            "error_code": canonical_error_code(error_code),
            "detail_code": detail_code or "UNKNOWN_ERROR",
            "message": redaction.scrub_text(error.get("message", ""), limit=ERROR_MESSAGE_LIMIT),
            "recoverable": recoverable,
            "recovery_hint": redaction.scrub_text(
                error.get("recovery_hint") or _recovery_hint(canonical_error_code(error_code)),
                limit=ERROR_MESSAGE_LIMIT,
            ),
        }
    elif failed_step_codes:
        recoverable = all(code in RECOVERABLE_ERROR_CODES for code in failed_step_codes)

    event_payload = _read_json_object(run_path / "logs" / "pipeline_events.json")
    raw_events = event_payload.get("events")
    event_count = len(raw_events) if isinstance(raw_events, list) else 0
    input_payload = _read_json_object(run_path / "input.json")
    project_name = str(input_payload.get("project_name") or run_path.parent.name or "creator")
    quality = quality_report or {}
    pipeline_status = str(pipeline.get("status") or "unknown")
    if pipeline_status != "succeeded":
        next_action = {
            "command": (
                "python scripts/resume_creator_run.py --run-dir "
                f"{_powershell_quote(run_path)} --project-name {_powershell_quote(project_name)}"
            ),
            "reason": (
                (pipeline_error or {}).get("recovery_hint")
                or (_recovery_hint(failed_step_codes[0]) if failed_step_codes else "")
                or "inspect the failed step summary, then resume the run"
            ),
            "recoverable": recoverable,
        }
    elif not bool(quality.get("ready_for_use")):
        next_action = {
            "command": (
                "python scripts/prepare_host_refinement.py --run-dir "
                f"{_powershell_quote(run_path)}"
            ),
            "reason": "complete host-agent refinement before direct use",
            "recoverable": True,
        }
    else:
        next_action = {
            "command": "",
            "reason": "no recovery action is required",
            "recoverable": True,
        }

    return {
        "schema_version": EVENT_SCHEMA_VERSION,
        "correlation_id": str(event_payload.get("correlation_id") or run_path.name),
        "pipeline_status": pipeline_status,
        "total_duration_ms": total_duration_ms,
        "steps": steps,
        "slowest_step": slowest_step,
        "failed_steps": failed_steps,
        "pipeline_error": pipeline_error,
        "event_log": "logs/pipeline_events.json",
        "event_count": event_count,
        "next_action": next_action,
    }
