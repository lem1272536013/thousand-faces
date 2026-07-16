"""DashScope task polling must terminate on success, failure, unknown state, or deadline."""

from __future__ import annotations

import argparse
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import provider_adapters


@dataclass
class FakeClock:
    now: float = 0.0
    sleeps: list[float] = field(default_factory=list)

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def response(status: str, *, message: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        status_code=200,
        message=message,
        output=SimpleNamespace(task_status=status),
    )


def install_fake_dashscope(
    monkeypatch: pytest.MonkeyPatch,
    transcription: type[Any],
) -> None:
    dashscope_module = types.ModuleType("dashscope")
    audio_module = types.ModuleType("dashscope.audio")
    asr_module = types.ModuleType("dashscope.audio.asr")
    asr_module.Transcription = transcription  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "dashscope", dashscope_module)
    monkeypatch.setitem(sys.modules, "dashscope.audio", audio_module)
    monkeypatch.setitem(sys.modules, "dashscope.audio.asr", asr_module)


def test_poll_returns_after_known_nonterminal_states_reach_success() -> None:
    clock = FakeClock()
    responses = iter((response("PENDING"), response("RUNNING"), response("SUCCEEDED")))
    calls: list[str] = []

    result = provider_adapters.poll_dashscope_task(
        task_id="task-synthetic",
        fetch=lambda task_id: (calls.append(task_id), next(responses))[1],
        poll_seconds=2,
        deadline_seconds=10,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert result.output.task_status == "SUCCEEDED"
    assert calls == ["task-synthetic"] * 3
    assert clock.sleeps == [2.0, 2.0]


def test_failed_status_raises_immediately_with_redacted_summary() -> None:
    clock = FakeClock()
    secret = "sk-synthetic-poll-secret-123456"

    with pytest.raises(provider_adapters.DashScopePollingError) as caught:
        provider_adapters.poll_dashscope_task(
            task_id="task-synthetic",
            fetch=lambda _task_id: response(
                "FAILED",
                message=f"Authorization Bearer {secret}",
            ),
            poll_seconds=2,
            deadline_seconds=10,
            known_secrets=(secret,),
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )

    assert caught.value.code == "ASR_TASK_FAILED"
    assert caught.value.poll_count == 1
    assert secret not in str(caught.value)
    assert clock.sleeps == []


def test_unknown_status_fails_closed_instead_of_polling_forever() -> None:
    clock = FakeClock()

    with pytest.raises(provider_adapters.DashScopePollingError) as caught:
        provider_adapters.poll_dashscope_task(
            task_id="task-synthetic",
            fetch=lambda _task_id: response("MYSTERY_STATE"),
            poll_seconds=1,
            deadline_seconds=10,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )

    assert caught.value.code == "ASR_TASK_STATUS_UNKNOWN"
    assert caught.value.poll_count == 1
    assert "MYSTERY_STATE" in str(caught.value)
    assert clock.sleeps == []


def test_running_status_cannot_exceed_total_poll_deadline() -> None:
    clock = FakeClock()
    calls = 0

    def running(_task_id: str) -> Any:
        nonlocal calls
        calls += 1
        return response("RUNNING")

    with pytest.raises(provider_adapters.DashScopePollingError) as caught:
        provider_adapters.poll_dashscope_task(
            task_id="task-synthetic",
            fetch=running,
            poll_seconds=2,
            deadline_seconds=5,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )

    assert caught.value.code == "ASR_POLL_DEADLINE_EXCEEDED"
    assert caught.value.poll_count == 3
    assert calls == 3
    assert clock.sleeps == [2.0, 2.0]
    assert clock.now == 4.0


def test_success_arriving_at_the_deadline_is_still_too_late() -> None:
    clock = FakeClock()

    def slow_success(_task_id: str) -> SimpleNamespace:
        clock.now += 5
        return response("SUCCEEDED")

    with pytest.raises(provider_adapters.DashScopePollingError) as caught:
        provider_adapters.poll_dashscope_task(
            task_id="task-synthetic",
            fetch=slow_success,
            poll_seconds=1,
            deadline_seconds=5,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )

    assert caught.value.code == "ASR_POLL_DEADLINE_EXCEEDED"
    assert caught.value.poll_count == 1


@pytest.mark.parametrize(
    ("poll_seconds", "deadline_seconds"),
    [
        (0, 10),
        (-1, 10),
        (float("nan"), 10),
        (1, 0),
        (1, -1),
        (1, float("inf")),
    ],
)
def test_invalid_poll_timing_is_rejected_before_fetch(
    poll_seconds: float,
    deadline_seconds: float,
) -> None:
    with pytest.raises(ValueError):
        provider_adapters.poll_dashscope_task(
            task_id="task-synthetic",
            fetch=lambda _task_id: pytest.fail("invalid config reached fetch"),
            poll_seconds=poll_seconds,
            deadline_seconds=deadline_seconds,
        )


def test_legacy_wait_mode_uses_the_same_bounded_local_polling() -> None:
    calls: list[str] = []

    class FakeTranscription:
        @classmethod
        def fetch(cls, *, task: str) -> SimpleNamespace:
            calls.append(task)
            return response("SUCCEEDED")

    result = provider_adapters.await_dashscope_task(
        FakeTranscription,
        task_id="task-synthetic",
        wait_mode="wait",
        poll_seconds=2,
        deadline_seconds=7,
    )

    assert result.output.task_status == "SUCCEEDED"
    assert calls == ["task-synthetic"]


def test_aliyun_adapter_failed_task_is_redacted_and_writes_no_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "sk-synthetic-dashscope-secret-123456"
    output = tmp_path / "task.json"

    class FakeTranscription:
        @classmethod
        def async_call(cls, **kwargs: object) -> SimpleNamespace:
            assert 0 < float(kwargs["request_timeout"]) <= 5.0
            return SimpleNamespace(
                status_code=200,
                output=SimpleNamespace(task_id="task-synthetic"),
            )

        @classmethod
        def fetch(cls, **kwargs: object) -> SimpleNamespace:
            assert kwargs["task"] == "task-synthetic"
            assert 0 < float(kwargs["request_timeout"]) <= 5.0
            return response("FAILED", message=f"Authorization Bearer {secret}")

    install_fake_dashscope(monkeypatch, FakeTranscription)
    monkeypatch.setattr(
        provider_adapters.network_policy,
        "validate_url",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setenv("DASHSCOPE_API_KEY", secret)
    monkeypatch.setenv("PROVIDER_RETRY_MAX_ATTEMPTS", "1")
    monkeypatch.setenv("PROVIDER_REQUEST_DEADLINE_SECONDS", "5")
    monkeypatch.setenv("ALI_ASR_POLL_SECONDS", "1")
    monkeypatch.setenv("ALI_ASR_POLL_DEADLINE_SECONDS", "5")

    with pytest.raises(SystemExit) as caught:
        provider_adapters.transcribe_aliyun_file_url(
            argparse.Namespace(
                file_url="https://media.example.invalid/synthetic.mp3",
                output=str(output),
                result_json=None,
                timeout=5,
            )
        )

    assert "ASR_TASK_FAILED" in str(caught.value)
    assert secret not in str(caught.value)
    assert not output.exists()


def test_aliyun_adapter_redacts_nonretry_sdk_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "sk-synthetic-dashscope-exception-123456"

    class FakeTranscription:
        @classmethod
        def async_call(cls, **_kwargs: object) -> SimpleNamespace:
            raise RuntimeError(f"Authorization Bearer {secret}")

    install_fake_dashscope(monkeypatch, FakeTranscription)
    monkeypatch.setattr(
        provider_adapters.network_policy,
        "validate_url",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setenv("DASHSCOPE_API_KEY", secret)
    monkeypatch.setenv("PROVIDER_RETRY_MAX_ATTEMPTS", "1")
    monkeypatch.setenv("PROVIDER_REQUEST_DEADLINE_SECONDS", "5")
    output = tmp_path / "task.json"

    with pytest.raises(SystemExit) as caught:
        provider_adapters.transcribe_aliyun_file_url(
            argparse.Namespace(
                file_url="https://media.example.invalid/synthetic.mp3",
                output=str(output),
                result_json=None,
                timeout=5,
            )
        )

    assert "DashScope task submission failed" in str(caught.value)
    assert secret not in str(caught.value)
    assert not output.exists()
