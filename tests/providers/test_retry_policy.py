"""Bounded, classified retry behavior for provider HTTP requests."""

from __future__ import annotations

import argparse
import io
import json
import urllib.error
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pytest
import requests

import provider_adapters
import retry_policy


@dataclass
class FakeClock:
    monotonic_seconds: float = 0.0
    epoch_seconds: float = 1_700_000_000.0
    sleeps: list[float] = field(default_factory=list)

    def monotonic(self) -> float:
        return self.monotonic_seconds

    def time(self) -> float:
        return self.epoch_seconds

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.monotonic_seconds += seconds
        self.epoch_seconds += seconds


@dataclass
class FakeResponse:
    status_code: int
    headers: dict[str, str] = field(default_factory=dict)
    text: str = ""
    closed: bool = False

    def close(self) -> None:
        self.closed = True


def execute(
    operation: Callable[[float], Any],
    policy: retry_policy.RetryPolicy,
    clock: FakeClock,
    *,
    known_secrets: tuple[str, ...] = (),
    random_value: Callable[[], float] = lambda: 0.5,
) -> Any:
    return retry_policy.execute_http(
        operation,
        policy,
        known_secrets=known_secrets,
        monotonic=clock.monotonic,
        wall_clock=clock.time,
        sleep=clock.sleep,
        random_value=random_value,
    )


def test_429_honors_retry_after_and_clamps_each_attempt_to_remaining_deadline() -> None:
    clock = FakeClock()
    rate_limited = FakeResponse(429, {"Retry-After": "2"})
    success = FakeResponse(200)
    responses = iter((rate_limited, success))
    timeouts: list[float] = []
    policy = retry_policy.RetryPolicy(
        max_attempts=3,
        request_timeout_seconds=10,
        deadline_seconds=5,
        jitter_ratio=0,
    )

    result = execute(
        lambda timeout: (timeouts.append(timeout), next(responses))[1],
        policy,
        clock,
    )

    assert result is success
    assert clock.sleeps == [2.0]
    assert timeouts == [5.0, 3.0]
    assert rate_limited.closed is True


def test_retry_after_longer_than_remaining_deadline_fails_without_sleeping() -> None:
    clock = FakeClock()
    calls = 0

    def rate_limited(_timeout: float) -> FakeResponse:
        nonlocal calls
        calls += 1
        return FakeResponse(429, {"retry-after": "10"})

    with pytest.raises(retry_policy.RetryError) as caught:
        execute(
            rate_limited,
            retry_policy.RetryPolicy(
                max_attempts=4,
                request_timeout_seconds=5,
                deadline_seconds=5,
                jitter_ratio=0,
            ),
            clock,
        )

    assert caught.value.code == "REQUEST_DEADLINE_EXCEEDED"
    assert caught.value.attempts == 1
    assert caught.value.last_reason == "rate_limit"
    assert calls == 1
    assert clock.sleeps == []


def test_success_finishing_at_the_deadline_is_rejected_and_closed() -> None:
    clock = FakeClock()
    response = FakeResponse(200)

    def slow_success(_timeout: float) -> FakeResponse:
        clock.monotonic_seconds += 5
        return response

    with pytest.raises(retry_policy.RetryError) as caught:
        execute(
            slow_success,
            retry_policy.RetryPolicy(
                max_attempts=1,
                request_timeout_seconds=5,
                deadline_seconds=5,
            ),
            clock,
        )

    assert caught.value.code == "REQUEST_DEADLINE_EXCEEDED"
    assert caught.value.attempts == 1
    assert response.closed is True


def test_persistent_503_uses_exponential_backoff_and_records_attempt_count() -> None:
    clock = FakeClock()
    responses: list[FakeResponse] = []

    def unavailable(_timeout: float) -> FakeResponse:
        response = FakeResponse(503, text="provider unavailable")
        responses.append(response)
        return response

    with pytest.raises(retry_policy.RetryError) as caught:
        execute(
            unavailable,
            retry_policy.RetryPolicy(
                max_attempts=3,
                request_timeout_seconds=10,
                deadline_seconds=30,
                base_delay_seconds=1,
                max_delay_seconds=10,
                jitter_ratio=0,
            ),
            clock,
        )

    assert caught.value.code == "HTTP_SERVER_ERROR"
    assert caught.value.attempts == 3
    assert caught.value.last_status == 503
    assert "after 3 attempts" in str(caught.value)
    assert clock.sleeps == [1.0, 2.0]
    assert all(response.closed for response in responses)


def test_sdk_exception_with_retryable_http_status_is_classified() -> None:
    clock = FakeClock()
    calls = 0

    class SdkServerError(Exception):
        status = 503
        headers: dict[str, str] = {}

    def sdk_call(_timeout: float) -> FakeResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise SdkServerError("temporary SDK failure")
        return FakeResponse(200)

    result = execute(
        sdk_call,
        retry_policy.RetryPolicy(
            max_attempts=2,
            request_timeout_seconds=5,
            deadline_seconds=10,
            base_delay_seconds=0,
            max_delay_seconds=0,
            jitter_ratio=0,
        ),
        clock,
    )

    assert result.status_code == 200
    assert calls == 2


def test_401_is_returned_immediately_for_caller_handling_without_retry() -> None:
    clock = FakeClock()
    calls = 0
    unauthorized = FakeResponse(401, text="invalid credentials")

    def request(_timeout: float) -> FakeResponse:
        nonlocal calls
        calls += 1
        return unauthorized

    result = execute(
        request,
        retry_policy.RetryPolicy(
            max_attempts=5,
            request_timeout_seconds=5,
            deadline_seconds=30,
        ),
        clock,
    )

    assert result is unauthorized
    assert calls == 1
    assert clock.sleeps == []
    assert unauthorized.closed is False


@pytest.mark.parametrize(
    ("error", "expected_code", "expected_reason"),
    [
        (
            requests.ConnectTimeout("connect timed out"),
            "NETWORK_CONNECT_TIMEOUT",
            "connection_timeout",
        ),
        (
            requests.ReadTimeout("read timed out"),
            "NETWORK_READ_TIMEOUT",
            "read_timeout",
        ),
    ],
)
def test_connection_and_read_timeouts_have_distinct_failure_codes(
    error: Exception,
    expected_code: str,
    expected_reason: str,
) -> None:
    clock = FakeClock()

    with pytest.raises(retry_policy.RetryError) as caught:
        execute(
            lambda _timeout: (_ for _ in ()).throw(error),
            retry_policy.RetryPolicy(
                max_attempts=1,
                request_timeout_seconds=5,
                deadline_seconds=5,
            ),
            clock,
        )

    assert caught.value.code == expected_code
    assert caught.value.last_reason == expected_reason
    assert caught.value.attempts == 1


def test_exponential_backoff_supports_bounded_jitter() -> None:
    clock = FakeClock()
    responses = iter((FakeResponse(500), FakeResponse(200)))

    execute(
        lambda _timeout: next(responses),
        retry_policy.RetryPolicy(
            max_attempts=2,
            request_timeout_seconds=5,
            deadline_seconds=20,
            base_delay_seconds=2,
            max_delay_seconds=10,
            jitter_ratio=0.25,
        ),
        clock,
        random_value=lambda: 1.0,
    )

    assert clock.sleeps == [2.5]


def test_exhausted_error_summary_is_redacted_and_bounded() -> None:
    clock = FakeClock()
    secret = "sk-synthetic-secret-value-123456"
    body = (
        f"Authorization Bearer {secret}; token={secret}; "
        "C:\\Users\\Alice\\private\\.env; "
        + "x" * 2_000
    )

    with pytest.raises(retry_policy.RetryError) as caught:
        execute(
            lambda _timeout: FakeResponse(503, text=body),
            retry_policy.RetryPolicy(
                max_attempts=1,
                request_timeout_seconds=5,
                deadline_seconds=5,
            ),
            clock,
            known_secrets=(secret,),
        )

    rendered = str(caught.value)
    assert secret not in rendered
    assert "Alice" not in rendered
    assert "<redacted>" in rendered
    assert len(rendered) <= 800


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_attempts": 0},
        {"max_attempts": 21},
        {"request_timeout_seconds": 0},
        {"request_timeout_seconds": 3601},
        {"deadline_seconds": 0},
        {"deadline_seconds": 3601},
        {"base_delay_seconds": -1},
        {"max_delay_seconds": -1},
        {"max_delay_seconds": 3601},
        {"jitter_ratio": -0.1},
        {"jitter_ratio": 1.1},
        {"base_delay_seconds": 2, "max_delay_seconds": 1},
    ],
)
def test_invalid_retry_policy_is_rejected_at_the_boundary(
    kwargs: dict[str, float | int],
) -> None:
    with pytest.raises(ValueError):
        retry_policy.RetryPolicy(**kwargs)


def immediate_policy(*, attempts: int = 3) -> retry_policy.RetryPolicy:
    return retry_policy.RetryPolicy(
        max_attempts=attempts,
        request_timeout_seconds=5,
        deadline_seconds=20,
        base_delay_seconds=0,
        max_delay_seconds=0,
        jitter_ratio=0,
    )


def test_provider_json_request_retries_503_then_returns_decoded_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[float] = []

    class SuccessResponse:
        def __enter__(self) -> SuccessResponse:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"ok": true}'

    def open_url(*_args: object, timeout: float, **_kwargs: object) -> SuccessResponse:
        calls.append(timeout)
        if len(calls) == 1:
            raise urllib.error.HTTPError(
                "https://api.example.invalid/v1",
                503,
                "unavailable",
                {"Retry-After": "0"},
                io.BytesIO(b'{"error":"temporary"}'),
            )
        return SuccessResponse()

    monkeypatch.setattr(provider_adapters.network_policy, "open_url", open_url)

    payload = provider_adapters.read_json_url(
        "https://api.example.invalid/v1",
        timeout=5,
        retry=immediate_policy(),
    )

    assert payload == {"ok": True}
    assert calls == [5.0, 5.0]


def test_douyin_resolution_retries_a_transient_server_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    class SuccessResponse:
        def __enter__(self) -> SuccessResponse:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def geturl(self) -> str:
            return "https://www.douyin.com/user/sec-retried"

    def open_url(*_args: object, **_kwargs: object) -> SuccessResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise urllib.error.HTTPError(
                "https://v.douyin.com/retried/",
                503,
                "unavailable",
                {},
                io.BytesIO(b"temporary"),
            )
        return SuccessResponse()

    monkeypatch.setattr(provider_adapters.network_policy, "open_url", open_url)

    resolved = provider_adapters.resolve_douyin_url(
        "https://v.douyin.com/retried/",
        timeout=5,
        retry=immediate_policy(),
    )

    assert resolved == "sec-retried"
    assert calls == 2


def test_compatible_asr_401_is_not_retried_even_with_larger_budget(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio = tmp_path / "sample.mp3"
    audio.write_bytes(b"synthetic audio")
    output = tmp_path / "result.json"
    calls = 0

    class UnauthorizedResponse(FakeResponse):
        def __init__(self) -> None:
            super().__init__(401, text='{"error":"unauthorized"}')

        def json(self) -> dict[str, str]:
            return {"error": "unauthorized"}

    def post(*_args: object, **_kwargs: object) -> UnauthorizedResponse:
        nonlocal calls
        calls += 1
        return UnauthorizedResponse()

    monkeypatch.setenv("ALI_ASR_API_KEY", "synthetic-key")
    monkeypatch.setenv("ALI_ASR_ENDPOINT", "https://api.example.invalid/v1")
    monkeypatch.setattr(provider_adapters.network_policy, "validate_url", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(provider_adapters.network_policy, "reject_requests_redirect", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(requests, "post", post)

    with pytest.raises(SystemExit, match="compatible ASR failed: 401"):
        provider_adapters.transcribe_compatible_audio_chat(
            argparse.Namespace(input=str(audio), output=str(output)),
            retry=immediate_policy(attempts=5),
        )

    assert calls == 1
    assert not output.exists()


def test_compatible_asr_persistent_503_records_attempts_and_redacts_body(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio = tmp_path / "sample.mp3"
    audio.write_bytes(b"synthetic audio")
    output = tmp_path / "result.json"
    secret = "sk-synthetic-provider-secret-123456"
    calls = 0

    class UnavailableResponse(FakeResponse):
        def __init__(self) -> None:
            super().__init__(503, text=f"Authorization Bearer {secret}")

        def json(self) -> dict[str, str]:
            return {"error": self.text}

    def post(*_args: object, **_kwargs: object) -> UnavailableResponse:
        nonlocal calls
        calls += 1
        return UnavailableResponse()

    monkeypatch.setenv("ALI_ASR_API_KEY", secret)
    monkeypatch.setenv("ALI_ASR_ENDPOINT", "https://api.example.invalid/v1")
    monkeypatch.setattr(provider_adapters.network_policy, "validate_url", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(provider_adapters.network_policy, "reject_requests_redirect", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(requests, "post", post)

    with pytest.raises(SystemExit) as caught:
        provider_adapters.transcribe_compatible_audio_chat(
            argparse.Namespace(input=str(audio), output=str(output)),
            retry=immediate_policy(attempts=3),
        )

    assert calls == 3
    assert "after 3 attempts" in str(caught.value)
    assert secret not in str(caught.value)
    assert not output.exists()


def test_multipart_retry_reopens_file_for_each_attempt(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio = tmp_path / "sample.mp3"
    audio.write_bytes(b"synthetic audio bytes")
    output = tmp_path / "result.json"
    uploaded: list[bytes] = []

    class MultipartResponse(FakeResponse):
        def json(self) -> dict[str, object]:
            return {"status": self.status_code}

    def post(*_args: object, **kwargs: object) -> MultipartResponse:
        handle = kwargs["files"]["file"][1]
        uploaded.append(handle.read())
        return MultipartResponse(503 if len(uploaded) == 1 else 200)

    monkeypatch.setenv("ALI_ASR_API_KEY", "synthetic-key")
    monkeypatch.setenv("ALI_ASR_ENDPOINT", "https://api.example.invalid/v1")
    monkeypatch.setattr(provider_adapters.network_policy, "validate_url", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(provider_adapters.network_policy, "reject_requests_redirect", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(requests, "post", post)

    provider_adapters.transcribe_compatible_audio_transcriptions(
        argparse.Namespace(input=str(audio), output=str(output)),
        retry=immediate_policy(),
    )

    assert uploaded == [b"synthetic audio bytes", b"synthetic audio bytes"]
    assert json.loads(output.read_text(encoding="utf-8")) == {"status": 200}
