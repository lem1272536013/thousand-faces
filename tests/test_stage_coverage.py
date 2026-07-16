"""Stage coverage contracts for online media and offline transcript runs."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

import build_creator_skill
import creator_pipeline
import run_diagnostics
from input_validation import InputValidationError, validate_stage_threshold_config
from io_utils import atomic_write_json
from stage_coverage import evaluate_stage_coverage


def write_run(
    run_dir: Path,
    video_count: int,
    *,
    mode: str,
    transcript_ids: tuple[str, ...] = (),
    config: dict[str, str] | None = None,
) -> list[str]:
    video_ids = [f"video-{index:03d}" for index in range(1, video_count + 1)]
    (run_dir / "metadata").mkdir(parents=True)
    (run_dir / "transcripts").mkdir(parents=True)
    (run_dir / "logs").mkdir(parents=True)
    atomic_write_json(
        run_dir / "input.json",
        {
            "run_format": run_diagnostics.RUN_FORMAT_NAME,
            "schema_version": run_diagnostics.RUN_FORMAT_SCHEMA_VERSION,
            "execution_mode": mode,
            "sample_count": video_count,
        },
    )
    atomic_write_json(
        run_dir / "config.snapshot.json",
        {
            "settings_schema_version": 2,
            **build_creator_skill.DEFAULTS,
            **(config or {}),
        },
    )
    atomic_write_json(run_dir / "workflow.plan.json", {"schema_version": 1})
    atomic_write_json(run_dir / "metadata" / "provenance.json", {"schema_version": 1})
    atomic_write_json(
        run_dir / "metadata" / "selected.json",
        {
            "selected_count": video_count,
            "items": [
                {
                    "platform_video_id": video_id,
                    "download_url": f"https://media.example.invalid/{video_id}.mp4",
                }
                for video_id in video_ids
            ],
        },
    )
    for video_id in transcript_ids:
        (run_dir / "transcripts" / f"{video_id}.txt").write_text("有效转写内容\n", encoding="utf-8")
    return video_ids


def test_selected_50_transcribed_1_fails_draft_coverage(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    video_ids = write_run(
        run_dir,
        50,
        mode="offline_transcripts",
        transcript_ids=("video-001",),
    )

    report = evaluate_stage_coverage(run_dir)

    assert report["stages"]["selected"]["count"] == 50
    assert report["stages"]["transcribed"]["count"] == 1
    assert report["stages"]["transcribed"]["ratio"] == 0.02
    assert report["stages"]["transcribed"]["draft_required_count"] == 40
    assert report["draft"]["passed"] is False
    assert len(report["issues"]) == 49
    assert {issue["video_id"] for issue in report["issues"]} == set(video_ids[1:])


def test_legitimate_offline_transcripts_are_not_hurt_by_media_coverage(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    video_ids = write_run(
        run_dir,
        2,
        mode="offline_transcripts",
        transcript_ids=("video-001", "video-002"),
    )

    report = evaluate_stage_coverage(run_dir)

    assert report["mode"] == "offline_transcripts"
    assert report["stages"]["downloaded"]["required"] is False
    assert report["stages"]["audio"]["required"] is False
    assert report["stages"]["transcribed"]["required"] is True
    assert report["draft"]["passed"] is True
    assert report["ready"]["passed"] is True
    assert report["issues"] == []
    assert all(
        video["stages"]["downloaded"]["status"] == "not_required"
        and video["stages"]["audio"]["status"] == "not_required"
        for video in report["videos"]
        if video["video_id"] in video_ids
    )


def test_online_uncovered_videos_have_stable_status_and_reason(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    video_ids = write_run(run_dir, 4, mode="online_media")
    selected_path = run_dir / "metadata" / "selected.json"
    selected = creator_pipeline.read_json(selected_path)
    selected["items"][0]["download_url"] = ""
    atomic_write_json(selected_path, selected)
    (run_dir / "media" / "videos").mkdir(parents=True)
    (run_dir / "media" / "audio").mkdir(parents=True)
    (run_dir / "media" / "videos" / f"{video_ids[2]}.mp4").write_bytes(b"video")
    (run_dir / "media" / "videos" / f"{video_ids[3]}.mp4").write_bytes(b"video")
    (run_dir / "media" / "videos" / f"{video_ids[1]}.mp4").write_bytes(b"stale-video")
    (run_dir / "media" / "audio" / f"{video_ids[2]}.mp3").write_bytes(b"stale-audio")
    (run_dir / "media" / "audio" / f"{video_ids[3]}.mp3").write_bytes(b"audio")
    atomic_write_json(
        run_dir / "logs" / "download_status.json",
        {
            "results": [
                {"video_id": video_ids[0], "status": "failed", "error": "missing download_url"},
                {"video_id": video_ids[1], "status": "failed", "error": "HTTP 403"},
                {"video_id": video_ids[2], "status": "downloaded"},
                {"video_id": video_ids[3], "status": "downloaded"},
            ]
        },
    )
    atomic_write_json(
        run_dir / "logs" / "audio_status.json",
        {
            "results": [
                {"video_id": video_ids[2], "status": "failed", "error": "ffmpeg exited 1"},
                {"video_id": video_ids[3], "status": "extracted"},
            ]
        },
    )
    atomic_write_json(
        run_dir / "logs" / "asr_status.json",
        {
            "results": [
                {
                    "audio": str(run_dir / "media" / "audio" / f"{video_ids[3]}.mp3"),
                    "status": "skipped",
                    "reason": "provider quota exhausted",
                }
            ]
        },
    )

    report = evaluate_stage_coverage(run_dir)

    issue_codes = {issue["code"] for issue in report["issues"]}
    assert {"DOWNLOAD_URL_MISSING", "DOWNLOAD_FAILED", "AUDIO_FAILED", "ASR_SKIPPED"} <= issue_codes
    assert report["draft"]["passed"] is False
    for video in report["videos"]:
        for stage in ("selected", "downloaded", "audio", "transcribed"):
            state = video["stages"][stage]
            assert state["status"] in {"covered", "failed", "blocked", "not_required"}
            assert state["reason"]


def test_small_samples_require_configured_absolute_count(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    write_run(
        run_dir,
        3,
        mode="offline_transcripts",
        transcript_ids=("video-001", "video-002"),
        config={"DRAFT_MIN_STAGE_COUNT": "3", "DRAFT_MIN_STAGE_RATIO": "0.50"},
    )

    report = evaluate_stage_coverage(run_dir)

    assert report["stages"]["transcribed"]["draft_required_count"] == 3
    assert report["draft"]["passed"] is False


def test_thresholds_are_configurable_within_safe_ordered_bounds(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    write_run(
        run_dir,
        10,
        mode="offline_transcripts",
        transcript_ids=tuple(f"video-{index:03d}" for index in range(1, 6)),
        config={
            "DRAFT_MIN_STAGE_COUNT": "1",
            "DRAFT_MIN_STAGE_RATIO": "0.50",
            "READY_MIN_STAGE_COUNT": "8",
            "READY_MIN_STAGE_RATIO": "0.90",
        },
    )

    report = evaluate_stage_coverage(run_dir)

    assert report["draft"]["passed"] is True
    assert report["ready"]["passed"] is False
    assert report["thresholds"]["draft"] == {"min_count": 1, "min_ratio": 0.5}
    with pytest.raises(InputValidationError, match="READY_MIN_STAGE_RATIO"):
        validate_stage_threshold_config(
            {
                "DRAFT_MIN_STAGE_COUNT": "2",
                "DRAFT_MIN_STAGE_RATIO": "0.90",
                "READY_MIN_STAGE_COUNT": "5",
                "READY_MIN_STAGE_RATIO": "0.80",
            }
        )


def test_quality_gate_and_summary_include_stage_coverage(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    write_run(
        run_dir,
        2,
        mode="offline_transcripts",
        transcript_ids=("video-001",),
    )

    quality = creator_pipeline.creator_quality_check(run_dir)
    summary_path = creator_pipeline.write_run_summary(run_dir, quality)
    summary = creator_pipeline.read_json(summary_path)

    assert quality["checks"]["stage_coverage_draft"] is False
    assert quality["passed"] is False
    assert quality["stage_coverage"]["stages"]["transcribed"]["count"] == 1
    assert summary["stage_coverage"] == quality["stage_coverage"]


def test_create_run_records_offline_execution_mode(run_root: Path) -> None:
    args = argparse.Namespace(
        source_url="https://share.example.invalid/profile",
        project_name="offline-mode",
        sample_count=2,
        metadata_fetch_limit=None,
        run_root=str(run_root),
        transcripts_dir=str(run_root / "input-transcripts"),
    )

    run_dir = build_creator_skill.create_run(args, dict(build_creator_skill.DEFAULTS))
    payload = creator_pipeline.read_json(run_dir / "input.json")

    assert payload["execution_mode"] == "offline_transcripts"
