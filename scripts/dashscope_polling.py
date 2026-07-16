#!/usr/bin/env python3
"""Deadline-bounded DashScope task state handling."""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Sequence
from typing import Any

import redaction


ACTIVE_STATUSES = frozenset({"PENDING", "QUEUED", "RUNNING", "PROCESSING"})
FAILED_STATUSES = frozenset({"FAILED", "CANCELED"})


class DashScopePollingError(RuntimeError):
    """A terminal, unknown, or deadline-bounded DashScope polling failure."""

    def __init__(
        self,
        code: str,
        *,
        poll_count: int,
        status: str = "",
        safe_summary: str = "",
    ) -> None:
        self.code = code
        self.poll_count = poll_count
        self.status = status
        self.safe_summary = safe_summary
        status_text = f", status={status}" if status else ""
        summary_text = f": {safe_summary}" if safe_summary else ""
        super().__init__(
            f"[{code}] DashScope task stopped after {poll_count} polls"
            f"{status_text}{summary_text}"
        )


def response_status(response: object) -> str:
    output = getattr(response, "output", None)
    if isinstance(output, dict):
        raw_status = output.get("task_status", "")
    else:
        raw_status = getattr(output, "task_status", "")
    return str(raw_status or "").strip().upper()


def safe_response_summary(response: object, known_secrets: Sequence[str]) -> str:
    values = (
        getattr(response, "message", ""),
        getattr(getattr(response, "output", None), "message", ""),
    )
    rendered = " | ".join(str(value) for value in values if value)
    return redaction.scrub_text(rendered, known_secrets=known_secrets, limit=500)


def validate_poll_timing(poll_seconds: float, deadline_seconds: float) -> None:
    values = (poll_seconds, deadline_seconds)
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) <= 0
        for value in values
    ):
        raise ValueError("poll interval and deadline must be finite positive numbers")


def _validate_response(
    response: object,
    *,
    poll_count: int,
    known_secrets: Sequence[str],
) -> str:
    status = response_status(response)
    if status == "SUCCEEDED":
        return status
    if status in FAILED_STATUSES:
        raise DashScopePollingError(
            "ASR_TASK_FAILED",
            poll_count=poll_count,
            status=status,
            safe_summary=safe_response_summary(response, known_secrets),
        )
    if status in ACTIVE_STATUSES:
        return status
    raise DashScopePollingError(
        "ASR_TASK_STATUS_UNKNOWN",
        poll_count=poll_count,
        status=status or "<empty>",
        safe_summary=safe_response_summary(response, known_secrets),
    )


def poll_dashscope_task(
    *,
    task_id: str,
    fetch: Callable[[str], object],
    poll_seconds: float,
    deadline_seconds: float,
    known_secrets: Sequence[str] = (),
    fetch_with_timeout: Callable[[str, float], object] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> object:
    """Poll a DashScope task without exceeding one total wall-clock budget."""

    validate_poll_timing(poll_seconds, deadline_seconds)
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("task_id must not be empty")

    started = monotonic()
    poll_count = 0
    while True:
        remaining = float(deadline_seconds) - (monotonic() - started)
        if remaining <= 0:
            raise DashScopePollingError(
                "ASR_POLL_DEADLINE_EXCEEDED",
                poll_count=poll_count,
            )
        response = (
            fetch_with_timeout(task_id, remaining)
            if fetch_with_timeout is not None
            else fetch(task_id)
        )
        poll_count += 1
        status = _validate_response(
            response,
            poll_count=poll_count,
            known_secrets=known_secrets,
        )
        remaining = float(deadline_seconds) - (monotonic() - started)
        if remaining <= 0:
            raise DashScopePollingError(
                "ASR_POLL_DEADLINE_EXCEEDED",
                poll_count=poll_count,
                status=status,
            )
        if status == "SUCCEEDED":
            return response
        if remaining <= float(poll_seconds):
            raise DashScopePollingError(
                "ASR_POLL_DEADLINE_EXCEEDED",
                poll_count=poll_count,
                status=status,
            )
        sleep(float(poll_seconds))


def await_dashscope_task(
    transcription: Any,
    *,
    task_id: str,
    wait_mode: str,
    poll_seconds: float,
    deadline_seconds: float,
    known_secrets: Sequence[str] = (),
    fetch_with_timeout: Callable[[str, float], object] | None = None,
) -> object:
    """Await through bounded local polling for both supported legacy modes.

    Some DashScope SDK releases accept ``wait_timeout`` through ``**kwargs``
    without enforcing it. Keeping ``wait`` as a configuration alias while
    using the local loop makes the deadline real across supported releases.
    """

    normalized_mode = wait_mode.strip().lower()
    if normalized_mode not in {"poll", "wait"}:
        raise ValueError("ALI_ASR_WAIT_MODE must be 'poll' or 'wait'")
    return poll_dashscope_task(
        task_id=task_id,
        fetch=lambda active_task_id: transcription.fetch(task=active_task_id),
        fetch_with_timeout=fetch_with_timeout,
        poll_seconds=poll_seconds,
        deadline_seconds=deadline_seconds,
        known_secrets=known_secrets,
    )
