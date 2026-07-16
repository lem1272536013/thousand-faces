"""Local retention must be inspectable, explicit, and confined to one run."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

import build_creator_skill
import creator_pipeline


def retention() -> Any:
    return importlib.import_module("retention")


def seed_run(tmp_path: Path, policy: str) -> Path:
    args = argparse.Namespace(
        source_url="https://share.example.invalid/profile",
        project_name=f"retention-{policy}",
        sample_count=1,
        metadata_fetch_limit=None,
        run_root=str(tmp_path / "runs"),
        rights_basis="team_owned",
        retention_policy=policy,
        takedown_contact="rights@example.invalid",
    )
    run_dir = build_creator_skill.create_run(args, dict(build_creator_skill.DEFAULTS))
    creator_pipeline.build_creator_skill(run_dir, args.project_name, overwrite=True)
    files = {
        "media/videos/video-001.mp4": b"synthetic video",
        "media/audio/video-001.mp3": b"synthetic audio",
        "transcripts/raw_json/video-001.result.json": b'{"text":"raw"}',
        "transcripts/raw_json/video-001.chunks.manifest.json": b'{"status":"complete"}',
        "transcripts/raw_json/video-001.chunk-001.result.json": b'{"text":"chunk raw"}',
        "transcripts/raw_json/video-001.chunk-001.txt": b"chunk transcript",
        "transcripts/raw_json/chunks/video-001.chunk-000.mp3": b"audio chunk",
        "transcripts/video-001.txt": b"normalized transcript",
        "transcripts/video-001.txt.artifact.json": b'{"schema_version":1}',
        "metadata/raw.json": b'{"provider":"synthetic"}',
        "metadata/selected.json": b'{"items":[]}',
        "metadata/selected.compact.json": b'{"items":[]}',
        "metadata/creator_profile.json": b'{"platform":"douyin"}',
        "metadata/video_id_map.json": b'{"records":[]}',
        "metadata/selected.video_id_map.json": b'{"records":[]}',
        "research/raw/note.md": b"synthetic research note",
        "research/merged/summary.md": b"synthetic summary",
        "research/reviews/audit.md": b"synthetic audit",
        "logs/asr_status.json": b'{"results":[]}',
    }
    for relative, content in files.items():
        path = run_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return run_dir


def test_retain_media_dry_run_lists_nothing_and_has_no_side_effects(tmp_path: Path) -> None:
    run_dir = seed_run(tmp_path, "retain_media")
    before = sorted(path.relative_to(run_dir).as_posix() for path in run_dir.rglob("*") if path.is_file())

    plan = retention().build_retention_plan(run_dir)

    after = sorted(path.relative_to(run_dir).as_posix() for path in run_dir.rglob("*") if path.is_file())
    assert plan.policy == "retain_media"
    assert plan.delete_paths == ()
    assert plan.delete_bytes == 0
    assert before == after
    assert not (run_dir / "logs" / "retention.json").exists()


def test_transcripts_only_dry_run_lists_sensitive_intermediates_but_keeps_outputs(
    tmp_path: Path,
) -> None:
    run_dir = seed_run(tmp_path, "transcripts_only")

    plan = retention().build_retention_plan(run_dir)

    deleted = set(plan.delete_paths)
    assert {
        "media/videos/video-001.mp4",
        "media/audio/video-001.mp3",
        "transcripts/raw_json/video-001.result.json",
        "transcripts/raw_json/video-001.chunks.manifest.json",
        "transcripts/raw_json/video-001.chunk-001.result.json",
        "transcripts/raw_json/video-001.chunk-001.txt",
        "transcripts/raw_json/chunks/video-001.chunk-000.mp3",
        "metadata/raw.json",
        "metadata/selected.json",
        "research/raw/note.md",
        "research/merged/summary.md",
        "logs/asr_status.json",
        "config.snapshot.json",
    } <= deleted
    for kept in (
        "input.json",
        "metadata/provenance.json",
        "metadata/selected.compact.json",
        "metadata/creator_profile.json",
        "transcripts/video-001.txt",
        "transcripts/video-001.txt.artifact.json",
        "skill/SKILL.md",
        "skill/references/meta.json",
    ):
        assert kept not in deleted
        assert (run_dir / kept).is_file()
    assert not (run_dir / "logs" / "retention.json").exists()


def test_final_skill_only_dry_run_lists_transcripts_and_compact_metadata(
    tmp_path: Path,
) -> None:
    run_dir = seed_run(tmp_path, "final_skill_only")

    plan = retention().build_retention_plan(run_dir)

    assert "transcripts/video-001.txt" in plan.delete_paths
    assert "metadata/selected.compact.json" in plan.delete_paths
    assert "metadata/creator_profile.json" in plan.delete_paths
    assert "input.json" not in plan.delete_paths
    assert "metadata/provenance.json" not in plan.delete_paths
    assert "skill/SKILL.md" not in plan.delete_paths
    assert all(not Path(path).is_absolute() for path in plan.delete_paths)


def test_apply_final_skill_only_deletes_exact_plan_and_writes_audit_receipt(
    tmp_path: Path,
) -> None:
    run_dir = seed_run(tmp_path, "final_skill_only")
    module = retention()
    plan = module.build_retention_plan(run_dir)

    receipt = module.apply_retention_plan(run_dir, plan)

    assert receipt["status"] == "applied"
    assert receipt["policy"] == "final_skill_only"
    assert receipt["deleted_paths"] == list(plan.delete_paths)
    assert receipt["failed"] == []
    assert all(not (run_dir / relative).exists() for relative in plan.delete_paths)
    assert (run_dir / "input.json").is_file()
    assert (run_dir / "metadata" / "provenance.json").is_file()
    assert (run_dir / "skill" / "SKILL.md").is_file()
    receipt_path = run_dir / "logs" / "retention.json"
    assert json.loads(receipt_path.read_text(encoding="utf-8")) == receipt

    second_plan = module.build_retention_plan(run_dir)
    assert second_plan.delete_paths == ()


def test_cli_defaults_to_dry_run_and_lists_without_deleting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_dir = seed_run(tmp_path, "final_skill_only")
    media = run_dir / "media" / "videos" / "video-001.mp4"
    module = retention()
    monkeypatch.setattr(
        sys,
        "argv",
        ["retention.py", "--run-dir", str(run_dir)],
    )

    exit_code = module.main()
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["dry_run"] is True
    assert "media/videos/video-001.mp4" in output["delete_paths"]
    assert media.is_file()
    assert not (run_dir / "logs" / "retention.json").exists()


def test_retention_rejects_non_run_directory_before_listing_or_deleting(
    tmp_path: Path,
) -> None:
    ordinary_directory = tmp_path / "ordinary"
    ordinary_directory.mkdir()
    marker = ordinary_directory / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="run directory"):
        retention().build_retention_plan(ordinary_directory, policy="final_skill_only")

    assert marker.read_text(encoding="utf-8") == "keep"


def test_apply_refuses_a_stale_plan_when_run_contents_changed(tmp_path: Path) -> None:
    run_dir = seed_run(tmp_path, "final_skill_only")
    module = retention()
    plan = module.build_retention_plan(run_dir)
    added = run_dir / "research" / "raw" / "added-after-dry-run.md"
    added.write_text("new sensitive artifact", encoding="utf-8")

    with pytest.raises(ValueError, match="stale"):
        module.apply_retention_plan(run_dir, plan)

    assert added.is_file()
    assert (run_dir / "media" / "videos" / "video-001.mp4").is_file()


def test_retention_rejects_policy_tampering_between_input_and_provenance(
    tmp_path: Path,
) -> None:
    run_dir = seed_run(tmp_path, "retain_media")
    input_path = run_dir / "input.json"
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    payload["retention_policy"] = "final_skill_only"
    input_path.write_text(json.dumps(payload), encoding="utf-8")
    marker = run_dir / "media" / "videos" / "video-001.mp4"

    with pytest.raises(ValueError, match="provenance manifest"):
        retention().build_retention_plan(run_dir)

    assert marker.is_file()


def test_apply_rejects_a_forged_parent_traversal_plan_before_deleting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = seed_run(tmp_path, "final_skill_only")
    module = retention()
    valid_plan = module.build_retention_plan(run_dir)
    outside = run_dir.parent / "outside.txt"
    outside.write_text("must survive", encoding="utf-8")
    forged_plan = replace(
        valid_plan,
        delete_paths=("../outside.txt",),
        delete_bytes=outside.stat().st_size,
    )
    monkeypatch.setattr(module, "build_retention_plan", lambda *_args, **_kwargs: forged_plan)

    with pytest.raises(ValueError, match="outside|relative|unsafe|escape"):
        module.apply_retention_plan(run_dir, forged_plan)

    assert outside.read_text(encoding="utf-8") == "must survive"
    assert not (run_dir / "logs" / "retention.json").exists()


def test_parent_directory_swap_is_rechecked_immediately_before_unlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = seed_run(tmp_path, "final_skill_only")
    module = retention()
    video_dir = run_dir / "media" / "videos"
    saved_video_dir = run_dir / "media" / "videos-original"
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_video = outside_dir / "video-001.mp4"
    outside_video.write_bytes(b"outside must survive")
    valid_plan = module.build_retention_plan(run_dir)
    focused_plan = replace(
        valid_plan,
        delete_paths=("media/videos/video-001.mp4",),
        delete_bytes=(video_dir / "video-001.mp4").stat().st_size,
    )
    monkeypatch.setattr(module, "build_retention_plan", lambda *_args, **_kwargs: focused_plan)
    original_validate = module._validated_delete_candidates
    swapped = False

    def validate_then_swap(root: Path, paths: tuple[str, ...]) -> Any:
        nonlocal swapped
        candidates = original_validate(root, paths)
        if not swapped:
            video_dir.rename(saved_video_dir)
            try:
                video_dir.symlink_to(outside_dir, target_is_directory=True)
            except OSError:
                saved_video_dir.rename(video_dir)
                pytest.skip("directory symlinks are unavailable in this Windows environment")
            swapped = True
        return candidates

    monkeypatch.setattr(module, "_validated_delete_candidates", validate_then_swap)
    try:
        receipt = module.apply_retention_plan(run_dir, focused_plan)
    finally:
        if video_dir.is_symlink():
            video_dir.unlink()
        if saved_video_dir.exists():
            saved_video_dir.rename(video_dir)

    assert outside_video.read_bytes() == b"outside must survive"
    assert receipt["status"] == "partial"
    assert receipt["deleted_paths"] == []
    assert receipt["failed"][0]["path"] == "media/videos/video-001.mp4"
    assert "escapes" in receipt["failed"][0]["error"]
    assert json.loads(
        (run_dir / "logs" / "retention.json").read_text(encoding="utf-8")
    ) == receipt
