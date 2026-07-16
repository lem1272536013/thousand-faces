"""Structured run telemetry must be queryable, bounded, and secret-safe."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import pytest

import logging_utils
from asr_parsers import ASRParseError
from media_validation import MediaValidationError
from offline_scenarios import offline_subprocess_env, run_offline_scenario
from pipeline_models import PipelineResult, StepResult


@dataclass
class FakeClock:
    current: datetime = datetime(2026, 7, 16, 8, 0, tzinfo=timezone.utc)
    elapsed_seconds: float = 0.0
    advances: list[float] = field(default_factory=list)

    def now(self) -> datetime:
        return self.current

    def monotonic(self) -> float:
        return self.elapsed_seconds

    def advance(self, seconds: float) -> None:
        self.advances.append(seconds)
        self.current += timedelta(seconds=seconds)
        self.elapsed_seconds += seconds


def read_event_log(run_dir: Path) -> dict[str, object]:
    return json.loads(
        (run_dir / "logs" / "pipeline_events.json").read_text(encoding="utf-8")
    )


def test_step_events_share_one_model_for_json_and_human_console(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "project" / "run-synthetic"
    secret = "sk-synthetic-observability-secret-123456"
    signed_url = (
        "https://bucket.example.invalid/audio.mp3?"
        "OSSAccessKeyId=synthetic&Signature=signed-secret"
    )
    clock = FakeClock()
    console = io.StringIO()
    logger = logging_utils.StructuredRunLogger(
        run_dir,
        known_secrets=(secret,),
        utc_now=clock.now,
        monotonic=clock.monotonic,
        console=console,
    )

    logger.pipeline_started(message=f"source={signed_url}")
    timer = logger.step_started("download_videos", message="selected inputs are ready")
    clock.advance(1.25)
    result = StepResult.from_rows(
        "download_videos",
        [
            {"status": "downloaded", "path": "one.mp4"},
            {
                "status": "failed",
                "error": (
                    "[MEDIA_CONTENT_REJECTED] invalid media; "
                    f"Authorization Bearer {secret}"
                ),
            },
        ],
    )
    timed_result = logger.step_finished(timer, result)
    pipeline = PipelineResult.from_steps(
        str(run_dir),
        [timed_result],
        quality_passed=True,
    )
    logger.pipeline_finished(pipeline)

    payload = read_event_log(run_dir)
    events = payload["events"]
    assert payload["schema_version"] == 1
    assert payload["correlation_id"] == "run-synthetic"
    assert [event["event"] for event in events] == [
        "pipeline_started",
        "step_started",
        "step_finished",
        "pipeline_finished",
    ]
    terminal = events[2]
    assert terminal["step_id"] == "download_videos"
    assert terminal["status"] == "partial"
    assert terminal["started_at"] == "2026-07-16T08:00:00+00:00"
    assert terminal["completed_at"] == "2026-07-16T08:00:01.250000+00:00"
    assert terminal["duration_ms"] == 1250
    assert terminal["counts"] == {
        "input": 2,
        "succeeded": 1,
        "failed": 1,
        "skipped": 0,
    }
    assert terminal["error_codes"] == ["INVALID_MEDIA"]
    assert timed_result.duration_ms == 1250
    assert timed_result.error_codes == ("INVALID_MEDIA",)
    assert timed_result.started_at == terminal["started_at"]
    assert timed_result.completed_at == terminal["completed_at"]

    rendered_json = json.dumps(payload, ensure_ascii=False)
    rendered_console = console.getvalue()
    for rendered in (rendered_json, rendered_console):
        assert secret not in rendered
        assert "signed-secret" not in rendered
        assert "OSSAccessKeyId" not in rendered
    assert "event=step_finished" in rendered_console
    assert "step=download_videos" in rendered_console
    assert "duration_ms=1250" in rendered_console
    assert "failed=1" in rendered_console


def test_step_timing_survives_wall_clock_rollback(tmp_path: Path) -> None:
    run_dir = tmp_path / "project" / "run-clock-rollback"
    clock = FakeClock()
    logger = logging_utils.StructuredRunLogger(
        run_dir,
        utc_now=clock.now,
        monotonic=clock.monotonic,
        console=io.StringIO(),
    )

    timer = logger.step_started("quality_check")
    clock.current -= timedelta(seconds=1)
    clock.elapsed_seconds += 0.25

    result = logger.step_finished(
        timer,
        StepResult.succeeded("quality_check", input_count=1),
    )

    assert result.started_at == "2026-07-16T08:00:00+00:00"
    assert result.completed_at == "2026-07-16T08:00:00.250000+00:00"
    assert result.duration_ms == 250


def test_error_classifier_produces_stable_categories_and_recovery_flags() -> None:
    rate_limited = type("ProviderError", (RuntimeError,), {"code": "RATE_LIMIT"})(
        "provider limited the request"
    )

    assert logging_utils.classify_exception(rate_limited).error_code == "RATE_LIMIT"
    assert logging_utils.classify_exception(rate_limited).recoverable is True
    assert (
        logging_utils.classify_exception(requests.ReadTimeout("slow")).error_code
        == "NETWORK_TIMEOUT"
    )

    invalid_media = logging_utils.classify_exception(
        MediaValidationError("MEDIA_CONTENT_REJECTED", "not a video")
    )
    assert invalid_media.error_code == "INVALID_MEDIA"
    assert invalid_media.detail_code == "MEDIA_CONTENT_REJECTED"
    assert invalid_media.recoverable is False

    asr_parse = logging_utils.classify_exception(ASRParseError("unknown response"))
    assert asr_parse.error_code == "ASR_PARSE_FAILED"
    assert asr_parse.recoverable is False

    wrapped_rate_limit = logging_utils.classify_exception(
        SystemExit("[RATE_LIMIT] provider request failed after 3 attempts")
    )
    assert wrapped_rate_limit.error_code == "RATE_LIMIT"
    assert wrapped_rate_limit.detail_code == "RATE_LIMIT"

    stale = logging_utils.classify_exception(
        type("ArtifactStateError", (RuntimeError,), {"code": "STALE_ARTIFACT"})(
            "fingerprint mismatch"
        )
    )
    assert stale.error_code == "STALE_ARTIFACT"
    assert stale.recoverable is True


def test_unknown_error_summary_is_redacted_and_bounded() -> None:
    secret = "sk-synthetic-error-summary-secret-123456"
    error = RuntimeError(f"Authorization Bearer {secret}; " + "x" * 2_000)

    first = logging_utils.classify_exception(error, known_secrets=(secret,))
    second = logging_utils.classify_exception(error, known_secrets=(secret,))

    assert first.error_code == second.error_code == "UNEXPECTED_ERROR"
    assert first.detail_code == second.detail_code == "RUNTIME_ERROR"
    assert secret not in first.message
    assert len(first.message) <= 500


def test_event_log_rejects_a_different_correlation_id_for_the_same_run(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run-synthetic"
    first = logging_utils.StructuredRunLogger(run_dir, correlation_id="correlation-a")
    first.pipeline_started()

    try:
        logging_utils.StructuredRunLogger(run_dir, correlation_id="correlation-b")
    except logging_utils.StructuredLogError as error:
        assert "correlation" in str(error).lower()
    else:
        raise AssertionError("correlation mismatch was accepted")


@pytest.mark.parametrize(
    "events",
    [
        [
            {
                "schema_version": 1,
                "sequence": 2,
                "event": "pipeline_started",
                "correlation_id": "run-synthetic",
                "run_id": "run-synthetic",
            }
        ],
        [
            {
                "schema_version": 1,
                "sequence": 1,
                "event": "pipeline_started",
                "correlation_id": "run-synthetic",
                "run_id": "another-run",
            }
        ],
    ],
)
def test_event_log_rejects_broken_history_before_resume(
    tmp_path: Path,
    events: list[dict[str, object]],
) -> None:
    run_dir = tmp_path / "run-synthetic"
    log_path = run_dir / "logs" / "pipeline_events.json"
    log_path.parent.mkdir(parents=True)
    log_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "correlation_id": "run-synthetic",
                "run_id": "run-synthetic",
                "events": events,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(logging_utils.StructuredLogError, match="event"):
        logging_utils.StructuredRunLogger(run_dir)


def test_summary_derives_recovery_from_failed_step_without_top_level_exception(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "project" / "run-recoverable"
    (run_dir / "logs").mkdir(parents=True)
    (run_dir / "input.json").write_text(
        json.dumps({"project_name": "recoverable-project"}),
        encoding="utf-8",
    )
    failed = StepResult.failed(
        "fetch_creator_videos_with_tikhub",
        issues=("provider throttled the request",),
        error_codes=("RATE_LIMIT",),
    )
    pipeline = PipelineResult.from_steps(
        str(run_dir),
        [failed],
        quality_passed=None,
    )

    summary = logging_utils.build_execution_summary(
        run_dir,
        pipeline_result=pipeline,
    )

    assert summary["pipeline_error"] is None
    assert summary["next_action"]["recoverable"] is True
    assert "provider connectivity" in summary["next_action"]["reason"]
    assert "resume_creator_run.py" in summary["next_action"]["command"]


def test_pipeline_event_includes_top_level_error_code_without_a_failed_step(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run-top-level-error"
    logger = logging_utils.StructuredRunLogger(run_dir)
    logger.pipeline_started()
    pipeline = PipelineResult.from_steps(
        str(run_dir),
        [],
        quality_passed=None,
        error={
            "error_code": "RATE_LIMIT",
            "message": "provider throttled the request",
        },
    )

    logger.pipeline_finished(pipeline)

    terminal = read_event_log(run_dir)["events"][-1]
    assert terminal["error_codes"] == ["RATE_LIMIT"]
    assert terminal["recoverable"] is True


def test_pipeline_event_keeps_unexpected_top_level_error_code(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run-unexpected-error"
    logger = logging_utils.StructuredRunLogger(run_dir)
    logger.pipeline_started()
    pipeline = PipelineResult.from_steps(
        str(run_dir),
        [],
        quality_passed=None,
        error={"message": "an unknown subsystem failed"},
    )

    logger.pipeline_finished(pipeline)

    terminal = read_event_log(run_dir)["events"][-1]
    assert terminal["error_codes"] == ["UNEXPECTED_ERROR"]
    assert terminal["recoverable"] is False


def test_offline_run_summary_reports_step_counts_durations_and_slowest_step(
    project_root: Path,
    run_root: Path,
) -> None:
    result = run_offline_scenario(
        project_root,
        run_root / "structured-success",
        "happy",
    )
    assert result.returncode == 0
    assert result.run_dir is not None

    summary = json.loads((result.run_dir / "run_summary.json").read_text(encoding="utf-8"))
    execution = summary["execution"]
    steps = execution["steps"]
    assert execution["correlation_id"] == result.run_dir.name
    assert execution["pipeline_status"] == "succeeded"
    assert len(steps) == 10
    assert execution["failed_steps"] == []
    assert execution["total_duration_ms"] == sum(step["duration_ms"] for step in steps)
    assert execution["slowest_step"]["duration_ms"] == max(
        step["duration_ms"] for step in steps
    )
    assert execution["slowest_step"]["step_id"] in {
        step["step_id"] for step in steps
    }
    assert "prepare_host_refinement.py" in execution["next_action"]["command"]
    for step in steps:
        assert datetime.fromisoformat(step["started_at"])
        assert datetime.fromisoformat(step["completed_at"])
        assert step["duration_ms"] >= 0
        counts = step["counts"]
        assert counts["input"] == (
            counts["succeeded"] + counts["failed"] + counts["skipped"]
        )

    event_payload = read_event_log(result.run_dir)
    events = event_payload["events"]
    started = [event["step_id"] for event in events if event["event"] == "step_started"]
    finished = [event["step_id"] for event in events if event["event"] == "step_finished"]
    assert started == finished == [step["step_id"] for step in steps]
    assert events[-1]["event"] == "pipeline_finished"
    assert events[-1]["status"] == "succeeded"


def test_failed_offline_run_persists_stable_error_and_recovery_summary(
    project_root: Path,
    run_root: Path,
) -> None:
    result = run_offline_scenario(
        project_root,
        run_root / "structured-failure",
        "malformed_metadata",
    )
    assert result.returncode != 0
    assert result.run_dir is not None

    summary_path = result.run_dir / "run_summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    execution = summary["execution"]
    assert execution["pipeline_status"] == "failed"
    assert execution["pipeline_error"]["error_code"] == "INVALID_JSON"
    assert execution["failed_steps"][-1]["step_id"] == "select_recent_samples"
    assert execution["failed_steps"][-1]["error_codes"] == ["INVALID_JSON"]
    assert "resume_creator_run.py" in execution["next_action"]["command"]
    assert execution["next_action"]["recoverable"] is False

    event_payload = read_event_log(result.run_dir)
    terminal = event_payload["events"][-1]
    assert terminal["event"] == "pipeline_finished"
    assert terminal["status"] == "failed"
    assert terminal["error_codes"] == ["INVALID_JSON"]


def test_resume_appends_to_the_same_correlated_event_stream(
    project_root: Path,
    run_root: Path,
) -> None:
    initial = run_offline_scenario(
        project_root,
        run_root / "structured-resume",
        "malformed_metadata",
    )
    assert initial.run_dir is not None
    before = read_event_log(initial.run_dir)

    resumed = subprocess.run(
        [
            sys.executable,
            str(project_root / "scripts" / "resume_creator_run.py"),
            "--run-dir",
            str(initial.run_dir),
            "--project-name",
            "offline-malformed-metadata",
        ],
        cwd=project_root,
        env=offline_subprocess_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert resumed.returncode != 0
    after = read_event_log(initial.run_dir)
    assert after["correlation_id"] == before["correlation_id"] == initial.run_dir.name
    assert len(after["events"]) > len(before["events"])
    assert any(event["event"] == "pipeline_resumed" for event in after["events"])
    assert [event["sequence"] for event in after["events"]] == list(
        range(1, len(after["events"]) + 1)
    )

    summary = json.loads((initial.run_dir / "run_summary.json").read_text(encoding="utf-8"))
    assert summary["execution"]["correlation_id"] == initial.run_dir.name
    assert summary["execution"]["event_count"] == len(after["events"])
    assert all(step["started_at"] for step in summary["execution"]["steps"])
    assert all(step["completed_at"] for step in summary["execution"]["steps"])
