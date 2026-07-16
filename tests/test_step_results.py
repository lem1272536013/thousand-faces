"""Structured step and pipeline results are stable machine-readable contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import creator_pipeline
import run_creator_skill_build
from pipeline_models import PipelineResult, StepResult, write_pipeline_result


def test_step_result_aggregates_success_partial_failure_and_verified_cache() -> None:
    succeeded = StepResult.from_rows(
        "download_videos",
        [
            {"status": "downloaded", "path": "one.mp4"},
            {"status": "skipped", "path": "two.mp4", "cache_status": "verified"},
        ],
    )
    partial = StepResult.from_rows(
        "extract_audio_with_ffmpeg",
        [
            {"status": "extracted", "path": "one.wav"},
            {"status": "failed", "error": "ffmpeg failed"},
        ],
    )
    failed = StepResult.from_rows(
        "transcribe_with_aliyun_asr",
        [{"status": "failed", "error": "provider failed"}],
    )
    skipped = StepResult.from_rows("download_videos", [])

    assert succeeded.status == "succeeded"
    assert succeeded.counts == {"input": 2, "succeeded": 2, "failed": 0, "skipped": 0}
    assert partial.status == "partial"
    assert partial.counts == {"input": 2, "succeeded": 1, "failed": 1, "skipped": 0}
    assert partial.issues == ("ffmpeg failed",)
    assert failed.status == "failed"
    assert failed.failed_count == 1
    assert skipped.status == "skipped"


def test_step_result_rejects_inconsistent_counts() -> None:
    with pytest.raises(ValueError, match="counts"):
        StepResult(
            step_id="invalid",
            status="succeeded",
            input_count=1,
            succeeded_count=2,
        )


def test_step_result_rejects_error_codes_without_failed_items() -> None:
    with pytest.raises(ValueError, match="error_codes"):
        StepResult(
            step_id="invalid",
            status="succeeded",
            input_count=1,
            succeeded_count=1,
            error_codes=("RATE_LIMIT",),
        )


def test_pipeline_result_exit_code_matches_terminal_status_and_round_trips(tmp_path: Path) -> None:
    success_step = StepResult.succeeded("build_creator_skill", output_paths=("skill/SKILL.md",))
    failed_quality = StepResult.failed("quality_check", issues=("has_transcripts=false",))

    succeeded = PipelineResult.from_steps("run-ok", [success_step], quality_passed=True)
    failed = PipelineResult.from_steps(
        "run-failed",
        [success_step, failed_quality],
        quality_passed=False,
    )
    output_path = tmp_path / "pipeline_result.json"
    write_pipeline_result(output_path, failed)
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert succeeded.status == "succeeded"
    assert succeeded.exit_code == 0
    assert failed.status == "failed"
    assert failed.exit_code != 0
    assert payload["status"] == "failed"
    assert payload["exit_code"] == failed.exit_code
    assert payload["quality_passed"] is False
    assert payload["steps"][1]["step_id"] == "quality_check"


def test_partial_pipeline_is_nonzero_even_when_quality_gate_passes() -> None:
    partial = StepResult.from_rows(
        "download_videos",
        [
            {"status": "downloaded", "path": "one.mp4"},
            {"status": "failed", "error": "one failed"},
        ],
    )

    result = PipelineResult.from_steps("run-partial", [partial], quality_passed=True)

    assert result.status == "partial"
    assert result.exit_code != 0


def test_pipeline_without_quality_conclusion_fails_closed() -> None:
    result = PipelineResult.from_steps(
        "run-no-quality",
        [StepResult.succeeded("build_creator_skill")],
        quality_passed=None,
    )

    assert result.status == "failed"
    assert result.exit_code != 0


def test_all_required_pipeline_step_wrappers_return_structured_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "metadata").mkdir(parents=True)
    (run_dir / "media" / "videos").mkdir(parents=True)
    (run_dir / "transcripts").mkdir(parents=True)
    selected_path = run_dir / "metadata" / "selected.json"
    creator_pipeline.write_json(selected_path, {"items": []})
    monkeypatch.setattr(creator_pipeline, "ffmpeg_version", lambda _: "ffmpeg version test")

    download = creator_pipeline.download_videos_step(
        selected_path,
        run_dir / "media" / "videos",
        run_dir / "logs",
    )
    audio = creator_pipeline.extract_audio_step(
        run_dir / "media" / "videos",
        run_dir / "media" / "audio",
    )
    monkeypatch.setattr(
        run_creator_skill_build,
        "transcribe_audio_files",
        lambda *_: [{"status": "transcribed", "transcript": "one.txt"}],
    )
    asr = run_creator_skill_build.transcribe_audio_files_step(run_dir, None, False)
    research = creator_pipeline.summarize_transcripts_step(
        run_dir / "transcripts",
        run_dir / "research" / "merged",
        overwrite=False,
    )
    build = creator_pipeline.build_creator_skill_step(run_dir, "structured", overwrite=False)
    quality, report = creator_pipeline.creator_quality_check_step(run_dir)

    assert [result.step_id for result in (download, audio, asr, research, build, quality)] == [
        "download_videos",
        "extract_audio_with_ffmpeg",
        "transcribe_with_aliyun_asr",
        "research_creator_style",
        "build_creator_skill",
        "quality_check",
    ]
    assert download.status == "skipped"
    assert audio.status == "skipped"
    assert asr.status == "succeeded"
    assert research.status == "succeeded"
    assert build.status == "succeeded"
    assert quality.status == "failed"
    assert report["passed"] is False
