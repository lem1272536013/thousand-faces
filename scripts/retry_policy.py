#!/usr/bin/env python3
"""Bounded retry policy for provider HTTP and SDK calls."""

from __future__ import annotations

import math
import random
import socket
import time
import urllib.error
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import TypeVar

from requests import exceptions as requests_exceptions

import redaction


RETRYABLE_HTTP_STATUSES = frozenset({500, 502, 503, 504})
ERROR_SUMMARY_LIMIT = 500
T = TypeVar("T")

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_DEADLINE_SECONDS = 300.0
DEFAULT_BASE_DELAY_SECONDS = 1.0
DEFAULT_MAX_DELAY_SECONDS = 10.0
DEFAULT_JITTER_RATIO = 0.2
MAX_ATTEMPTS_LIMIT = 20
MAX_REQUEST_SECONDS = 3600.0


@dataclass(frozen=True)
class RetryPolicy:
    """One request retry budget, including all attempts and backoff sleeps."""

    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    request_timeout_seconds: float = 60.0
    deadline_seconds: float = DEFAULT_DEADLINE_SECONDS
    base_delay_seconds: float = DEFAULT_BASE_DELAY_SECONDS
    max_delay_seconds: float = DEFAULT_MAX_DELAY_SECONDS
    jitter_ratio: float = DEFAULT_JITTER_RATIO

    def __post_init__(self) -> None:
        if isinstance(self.max_attempts, bool) or not isinstance(self.max_attempts, int):
            raise ValueError("max_attempts must be a positive integer")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        if self.max_attempts > MAX_ATTEMPTS_LIMIT:
            raise ValueError(f"max_attempts must not exceed {MAX_ATTEMPTS_LIMIT}")
        numeric_fields = {
            "request_timeout_seconds": self.request_timeout_seconds,
            "deadline_seconds": self.deadline_seconds,
            "base_delay_seconds": self.base_delay_seconds,
            "max_delay_seconds": self.max_delay_seconds,
            "jitter_ratio": self.jitter_ratio,
        }
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            for value in numeric_fields.values()
        ):
            raise ValueError("retry policy timing values must be finite numbers")
        if self.request_timeout_seconds <= 0 or self.deadline_seconds <= 0:
            raise ValueError("request timeout and deadline must be positive")
        if (
            self.request_timeout_seconds > MAX_REQUEST_SECONDS
            or self.deadline_seconds > MAX_REQUEST_SECONDS
        ):
            raise ValueError(
                f"request timeout and deadline must not exceed {MAX_REQUEST_SECONDS:g} seconds"
            )
        if self.base_delay_seconds < 0 or self.max_delay_seconds < 0:
            raise ValueError("retry delays must not be negative")
        if self.base_delay_seconds > MAX_REQUEST_SECONDS or self.max_delay_seconds > MAX_REQUEST_SECONDS:
            raise ValueError(f"retry delays must not exceed {MAX_REQUEST_SECONDS:g} seconds")
        if self.max_delay_seconds < self.base_delay_seconds:
            raise ValueError("max_delay_seconds must be at least base_delay_seconds")
        if not 0 <= self.jitter_ratio <= 1:
            raise ValueError("jitter_ratio must be between 0 and 1")


def policy_from_mapping(
    config: Mapping[str, str],
    *,
    request_timeout_seconds: float,
) -> RetryPolicy:
    """Load the unified provider retry knobs from an environment-like mapping."""

    raw_attempts = config.get(
        "PROVIDER_RETRY_MAX_ATTEMPTS",
        config.get("ALI_ASR_RETRY", str(DEFAULT_MAX_ATTEMPTS)),
    )
    try:
        attempts = int(raw_attempts)
        deadline = float(
            config.get(
                "PROVIDER_REQUEST_DEADLINE_SECONDS",
                str(DEFAULT_DEADLINE_SECONDS),
            )
        )
        base_delay = float(
            config.get(
                "PROVIDER_RETRY_BASE_SECONDS",
                str(DEFAULT_BASE_DELAY_SECONDS),
            )
        )
        max_delay = float(
            config.get(
                "PROVIDER_RETRY_MAX_SECONDS",
                str(DEFAULT_MAX_DELAY_SECONDS),
            )
        )
        jitter = float(
            config.get(
                "PROVIDER_RETRY_JITTER_RATIO",
                str(DEFAULT_JITTER_RATIO),
            )
        )
    except (TypeError, ValueError) as error:
        raise ValueError("provider retry configuration contains a non-numeric value") from error
    if str(attempts) != str(raw_attempts).strip():
        raise ValueError("PROVIDER_RETRY_MAX_ATTEMPTS must be an integer")
    return RetryPolicy(
        max_attempts=attempts,
        request_timeout_seconds=request_timeout_seconds,
        deadline_seconds=deadline,
        base_delay_seconds=base_delay,
        max_delay_seconds=max_delay,
        jitter_ratio=jitter,
    )


@dataclass(frozen=True)
class _RetryDecision:
    code: str
    reason: str
    status: int | None = None
    retry_after_seconds: float | None = None


class RetryError(RuntimeError):
    """A retryable provider request exhausted its attempts or total deadline."""

    def __init__(
        self,
        code: str,
        *,
        attempts: int,
        last_reason: str,
        last_status: int | None = None,
        safe_summary: str = "",
    ) -> None:
        self.code = code
        self.attempts = attempts
        self.last_reason = last_reason
        self.last_status = last_status
        self.safe_summary = safe_summary
        status_text = f", last_status={last_status}" if last_status is not None else ""
        summary_text = f": {safe_summary}" if safe_summary else ""
        super().__init__(
            f"[{code}] provider request failed after {attempts} attempts "
            f"(reason={last_reason}{status_text}){summary_text}"
        )


def _status_code(value: object) -> int | None:
    for field in ("status_code", "status"):
        raw = getattr(value, field, None)
        if isinstance(raw, int) and not isinstance(raw, bool):
            return raw
    return None


def _headers(value: object) -> Mapping[str, object]:
    raw = getattr(value, "headers", None)
    return raw if isinstance(raw, Mapping) else {}


def _header(headers: Mapping[str, object], name: str) -> str:
    lowered = name.casefold()
    for key, value in headers.items():
        if str(key).casefold() == lowered:
            return str(value).strip()
    return ""


def _retry_after_seconds(headers: Mapping[str, object], wall_clock: Callable[[], float]) -> float | None:
    raw = _header(headers, "Retry-After")
    if not raw:
        return None
    try:
        seconds = float(raw)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(raw)
        except (TypeError, ValueError, OverflowError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        seconds = parsed.timestamp() - wall_clock()
    if not math.isfinite(seconds) or seconds < 0:
        return None
    return seconds


def _http_decision(
    status: int | None,
    headers: Mapping[str, object],
    wall_clock: Callable[[], float],
) -> _RetryDecision | None:
    if status == 429:
        return _RetryDecision(
            code="RATE_LIMIT",
            reason="rate_limit",
            status=status,
            retry_after_seconds=_retry_after_seconds(headers, wall_clock),
        )
    if status in RETRYABLE_HTTP_STATUSES:
        return _RetryDecision(
            code="HTTP_SERVER_ERROR",
            reason="server_error",
            status=status,
        )
    return None


def _exception_decision(
    error: BaseException,
    wall_clock: Callable[[], float],
) -> _RetryDecision | None:
    if isinstance(error, urllib.error.HTTPError):
        return _http_decision(int(error.code), _headers(error), wall_clock)
    if isinstance(error, requests_exceptions.ConnectTimeout):
        return _RetryDecision("NETWORK_CONNECT_TIMEOUT", "connection_timeout")
    if isinstance(error, requests_exceptions.ReadTimeout):
        return _RetryDecision("NETWORK_READ_TIMEOUT", "read_timeout")
    if isinstance(error, requests_exceptions.ConnectionError):
        return _RetryDecision("NETWORK_CONNECTION_ERROR", "connection_error")
    if isinstance(error, urllib.error.URLError):
        reason = error.reason
        if isinstance(reason, (socket.timeout, TimeoutError)):
            return _RetryDecision("NETWORK_READ_TIMEOUT", "read_timeout")
        if isinstance(reason, OSError):
            return _RetryDecision("NETWORK_CONNECTION_ERROR", "connection_error")
    if isinstance(error, (socket.timeout, TimeoutError)):
        return _RetryDecision("NETWORK_READ_TIMEOUT", "read_timeout")
    status = _status_code(error)
    if status is not None and status > 0:
        return _http_decision(status, _headers(error), wall_clock)
    nested = getattr(error, "exception", None)
    if isinstance(nested, BaseException) and nested is not error:
        return _exception_decision(nested, wall_clock)
    return None


def _safe_summary(value: object, known_secrets: Sequence[str]) -> str:
    raw: object = ""
    if isinstance(value, urllib.error.HTTPError):
        try:
            raw = value.read()
        except (OSError, ValueError):
            raw = str(value)
    else:
        raw = getattr(value, "text", "") or getattr(value, "message", "") or str(value)
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    return redaction.scrub_text(
        raw,
        known_secrets=known_secrets,
        limit=ERROR_SUMMARY_LIMIT,
    )


def _close(value: object) -> None:
    close = getattr(value, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            return


def _backoff_seconds(
    policy: RetryPolicy,
    attempt: int,
    retry_after_seconds: float | None,
    random_value: Callable[[], float],
) -> float:
    if retry_after_seconds is not None:
        return retry_after_seconds
    base = min(
        float(policy.max_delay_seconds),
        float(policy.base_delay_seconds) * (2 ** (attempt - 1)),
    )
    sample = min(1.0, max(0.0, float(random_value())))
    factor = 1 + float(policy.jitter_ratio) * (2 * sample - 1)
    return min(float(policy.max_delay_seconds), max(0.0, base * factor))


def _deadline_error(
    attempts: int,
    decision: _RetryDecision,
    safe_summary: str,
) -> RetryError:
    return RetryError(
        "REQUEST_DEADLINE_EXCEEDED",
        attempts=attempts,
        last_reason=decision.reason,
        last_status=decision.status,
        safe_summary=safe_summary,
    )


def execute_http(
    operation: Callable[[float], T],
    policy: RetryPolicy,
    *,
    known_secrets: Sequence[str] = (),
    monotonic: Callable[[], float] = time.monotonic,
    wall_clock: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
    random_value: Callable[[], float] = random.random,
) -> T:
    """Execute one HTTP-like operation within a total attempts/deadline budget."""

    started = monotonic()
    for attempt in range(1, policy.max_attempts + 1):
        remaining = float(policy.deadline_seconds) - (monotonic() - started)
        if remaining <= 0:
            raise RetryError(
                "REQUEST_DEADLINE_EXCEEDED",
                attempts=attempt - 1,
                last_reason="deadline",
            )
        timeout = min(float(policy.request_timeout_seconds), remaining)
        response: object | None = None
        error: Exception | None = None
        try:
            response = operation(timeout)
            decision = _http_decision(
                _status_code(response),
                _headers(response),
                wall_clock,
            )
        except Exception as caught:
            error = caught
            decision = _exception_decision(caught, wall_clock)
            if decision is None:
                raise

        if decision is None:
            if monotonic() - started >= float(policy.deadline_seconds):
                _close(response)
                raise RetryError(
                    "REQUEST_DEADLINE_EXCEEDED",
                    attempts=attempt,
                    last_reason="deadline",
                )
            return response  # type: ignore[return-value]

        failed_value = error if error is not None else response
        safe_summary = _safe_summary(failed_value, known_secrets)
        remaining = float(policy.deadline_seconds) - (monotonic() - started)
        if remaining <= 0:
            _close(failed_value)
            raise _deadline_error(attempt, decision, safe_summary)
        if attempt >= policy.max_attempts:
            _close(failed_value)
            raise RetryError(
                decision.code,
                attempts=attempt,
                last_reason=decision.reason,
                last_status=decision.status,
                safe_summary=safe_summary,
            )

        delay = _backoff_seconds(
            policy,
            attempt,
            decision.retry_after_seconds,
            random_value,
        )
        if remaining <= 0 or delay >= remaining:
            _close(failed_value)
            raise _deadline_error(attempt, decision, safe_summary)
        _close(failed_value)
        sleep(delay)

    raise AssertionError("retry loop exhausted without returning or raising")
