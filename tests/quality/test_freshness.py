"""Quality checks must never trust derived reports computed from stale inputs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

import build_creator_skill
import creator_pipeline
import prepare_host_refinement
import quality_engine
from io_utils import atomic_write_json


FIRST_VIDEO_ID = "190000000000000201"
SECOND_VIDEO_ID = "190000000000000202"
REPAIR_COMMAND = "python scripts/prepare_host_refinement.py --run-dir <run-dir>"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def seed_run(tmp_path: Path) -> Path:
    args = argparse.Namespace(
        source_url="https://share.example.invalid/freshness-profile",
        project_name="freshness-audit",
        sample_count=2,
        metadata_fetch_limit=None,
        run_root=str(tmp_path / "runs"),
        rights_basis="team_owned",
        retention_policy="retain_media",
        takedown_contact="rights@example.invalid",
    )
    run_dir = build_creator_skill.create_run(args, dict(build_creator_skill.DEFAULTS))
    items = [
        {
            "platform_video_id": FIRST_VIDEO_ID,
            "artifact_id": FIRST_VIDEO_ID,
            "title": "第一条人工新鲜度样本",
            "published_at": "2026-01-02T00:00:00+00:00",
            "duration": 30,
            "stats": {"like": 10, "favorite": 2, "share": 1, "comment": 3},
            "source_url": "https://share.example.invalid/video-201",
        },
        {
            "platform_video_id": SECOND_VIDEO_ID,
            "artifact_id": SECOND_VIDEO_ID,
            "title": "第二条人工新鲜度样本",
            "published_at": "2026-01-01T00:00:00+00:00",
            "duration": 40,
            "stats": {"like": 8, "favorite": 1, "share": 2, "comment": 2},
            "source_url": "https://share.example.invalid/video-202",
        },
    ]
    metadata = run_dir / "metadata"
    transcripts = run_dir / "transcripts"
    research = run_dir / "research" / "merged"
    atomic_write_json(
        metadata / "selected.json",
        {
            "requested_count": 2,
            "selected_count": 2,
            "selection_strategy": "published_at_desc",
            "items": items,
        },
    )
    atomic_write_json(
        metadata / "selected.compact.json",
        {
            "requested_count": 2,
            "selected_count": 2,
            "selection_strategy": "published_at_desc",
            "creator_profile": {"nickname": "新鲜度测试创作者"},
            "items": items,
        },
    )
    atomic_write_json(metadata / "creator_profile.json", {"platform": "douyin"})
    transcripts.mkdir(parents=True, exist_ok=True)
    (transcripts / f"{FIRST_VIDEO_ID}.txt").write_text(
        "[00:00:00] 第一条人工转写用于验证证据覆盖和派生产物哈希。\n",
        encoding="utf-8",
    )
    (transcripts / f"{SECOND_VIDEO_ID}.txt").write_text(
        "[00:00:00] 第二条人工转写用于验证修改后旧信号必须失效。\n",
        encoding="utf-8",
    )
    research.mkdir(parents=True, exist_ok=True)
    (research / "summary.md").write_text(
        "# Synthetic summary\n\nDeterministic freshness test material.\n",
        encoding="utf-8",
    )
    creator_pipeline.build_creator_skill(run_dir, args.project_name, overwrite=True)
    (run_dir / "skill" / "references" / "evidence_index.md").write_text(
        "# Evidence Index\n\nNo evidence selected yet.\n",
        encoding="utf-8",
    )
    return run_dir


def run_prepare(monkeypatch: pytest.MonkeyPatch, run_dir: Path) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["prepare_host_refinement.py", "--run-dir", str(run_dir)],
    )
    prepare_host_refinement.main()


def persona_input_sha(report: dict, role: str) -> str:
    item = next(
        value
        for value in report["computed_from"]["persona"]
        if value["role"] == role
    )
    return str(item["sha256"])


def test_evidence_edit_is_recomputed_live_and_invalidates_persisted_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = seed_run(tmp_path)
    run_prepare(monkeypatch, run_dir)
    baseline = creator_pipeline.creator_quality_check(run_dir)
    persisted_coverage = run_dir / "research" / "reviews" / "evidence_coverage.json"

    assert baseline["freshness"]["fresh"] is True
    assert baseline["freshness"]["current"]["evidence_coverage"]["covered_video_count"] == 0
    (run_dir / "skill" / "references" / "evidence_index.md").write_text(
        f"# Evidence Index\n\n| Video ID | Finding |\n|---|---|\n| {FIRST_VIDEO_ID} | current evidence |\n",
        encoding="utf-8",
    )

    report = creator_pipeline.creator_quality_check(run_dir)

    assert report["freshness"]["fresh"] is False
    assert report["freshness"]["artifacts"]["evidence_coverage"]["fresh"] is False
    assert report["freshness"]["artifacts"]["evidence_coverage"]["reason"] == "fingerprint_mismatch"
    assert report["freshness"]["current"]["evidence_coverage"]["covered_video_count"] == 1
    assert report["content_readiness"]["host_refinement"]["covered_video_count"] == 1
    assert read_json(persisted_coverage)["covered_video_count"] == 0
    assert report["ready_for_use"] is False
    assert report["freshness"]["repair_command"] == REPAIR_COMMAND


def test_transcript_edit_marks_corpus_signals_and_coverage_stale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = seed_run(tmp_path)
    run_prepare(monkeypatch, run_dir)
    baseline = creator_pipeline.creator_quality_check(run_dir)
    transcript = run_dir / "transcripts" / f"{FIRST_VIDEO_ID}.txt"
    baseline_chars = baseline["freshness"]["current"]["corpus_index"]["coverage"][
        "total_transcript_chars"
    ]
    transcript.write_text(
        transcript.read_text(encoding="utf-8")
        + "[00:00:05] 这是质量检查之后新增且必须进入当前计算的转写内容。\n",
        encoding="utf-8",
    )

    report = creator_pipeline.creator_quality_check(run_dir)

    assert report["freshness"]["fresh"] is False
    assert {
        "corpus_index",
        "transcript_signal_matrix",
        "transcript_signals",
        "transcript_signals_markdown",
        "evidence_coverage",
        "evidence_coverage_markdown",
    } <= set(report["freshness"]["stale_artifacts"])
    assert report["freshness"]["artifacts"]["corpus_index"]["reason"] == "fingerprint_mismatch"
    assert report["freshness"]["artifacts"]["transcript_signals"]["reason"] == "fingerprint_mismatch"
    assert report["freshness"]["artifacts"]["evidence_coverage"]["reason"] == "upstream_stale"
    assert (
        report["freshness"]["current"]["corpus_index"]["coverage"]["total_transcript_chars"]
        > baseline_chars
    )
    assert report["content_readiness"]["host_refinement"]["checks"][
        "derived_artifacts_fresh"
    ] is False
    assert report["ready_for_use"] is False
    assert report["freshness"]["repair_command"] == REPAIR_COMMAND


def test_prepare_command_repairs_stale_reports_without_overwriting_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = seed_run(tmp_path)
    run_prepare(monkeypatch, run_dir)
    evidence = run_dir / "skill" / "references" / "evidence_index.md"
    evidence.write_text(
        (
            "# Evidence Index\n\n"
            "| Video ID | Finding |\n"
            "|---|---|\n"
            f"| {FIRST_VIDEO_ID} | retained human evidence |\n"
        ),
        encoding="utf-8",
    )
    assert creator_pipeline.creator_quality_check(run_dir)["freshness"]["fresh"] is False

    run_prepare(monkeypatch, run_dir)
    repaired = creator_pipeline.creator_quality_check(run_dir)

    assert repaired["freshness"]["fresh"] is True
    assert repaired["freshness"]["stale_artifacts"] == []
    assert repaired["freshness"]["current"]["evidence_coverage"]["covered_video_count"] == 1
    assert FIRST_VIDEO_ID in evidence.read_text(encoding="utf-8")


def test_persona_diagnostics_are_recomputed_from_current_model_on_every_quality_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = seed_run(tmp_path)
    run_prepare(monkeypatch, run_dir)
    baseline = creator_pipeline.creator_quality_check(run_dir)
    model_path = run_dir / "skill" / "references" / "persona_model.json"
    model = read_json(model_path)
    old_sha = persona_input_sha(baseline, "persona_model")
    model["status"] = "refined"
    model["topic_models"] = [{"name": "current-persona-model"}]
    atomic_write_json(model_path, model)

    report = creator_pipeline.creator_quality_check(run_dir)
    diagnostics = read_json(
        run_dir / "research" / "reviews" / "persona_model_diagnostics.json"
    )

    assert persona_input_sha(report, "persona_model") != old_sha
    assert report["freshness"]["artifacts"]["persona_model_diagnostics"] == {
        "fresh": True,
        "reason": "computed_live",
        "path": "research/reviews/persona_model_diagnostics.json",
        "computed_from": report["computed_from"]["persona"],
    }
    assert report["content_readiness"]["persona_model"]["counts"]["topic_models"] == 1
    assert diagnostics["counts"]["topic_models"] == 1
    assert diagnostics["freshness"] == {"fresh": True, "reason": "computed_live"}
    assert diagnostics["computed_from"] == report["computed_from"]["persona"]


def test_current_derivation_entry_is_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = seed_run(tmp_path)
    run_prepare(monkeypatch, run_dir)
    before = {
        path.relative_to(run_dir).as_posix(): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in run_dir.rglob("*")
        if path.is_file()
    }

    current = quality_engine.compute_current_derivations(run_dir)

    after = {
        path.relative_to(run_dir).as_posix(): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in run_dir.rglob("*")
        if path.is_file()
    }
    assert current["corpus_index"]["coverage"]["transcript_count"] == 2
    assert current["transcript_signals"]["summary"]["signal_count"] == 2
    assert current["evidence_coverage"]["covered_video_count"] == 0
    assert after == before


def test_persona_diagnostics_calculation_entry_is_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = seed_run(tmp_path)
    run_prepare(monkeypatch, run_dir)
    refs = run_dir / "skill" / "references"
    diagnostics_path = run_dir / "research" / "reviews" / "persona_model_diagnostics.json"
    diagnostics_path.unlink(missing_ok=True)
    markdown_texts = {
        "persona": (refs / "persona.md").read_text(encoding="utf-8"),
        "topic": (refs / "topic_model.md").read_text(encoding="utf-8"),
        "script": (refs / "script_style.md").read_text(encoding="utf-8"),
        "evidence": (refs / "evidence_index.md").read_text(encoding="utf-8"),
    }

    diagnostics = creator_pipeline.compute_persona_model_stats(
        run_dir,
        run_dir / "skill",
        markdown_texts,
        computed_from=quality_engine.current_input_identities(run_dir)["persona"],
    )

    assert diagnostics["freshness"] == {"fresh": True, "reason": "computed_live"}
    assert diagnostics["counts"]["topic_models"] == len(
        read_json(refs / "persona_model.json")["topic_models"]
    )
    assert not diagnostics_path.exists()


def test_text_quality_output_lists_stale_artifacts_and_shortest_repair_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_dir = seed_run(tmp_path)
    run_prepare(monkeypatch, run_dir)
    (run_dir / "transcripts" / f"{SECOND_VIDEO_ID}.txt").write_text(
        "[00:00:00] changed after prepare\n",
        encoding="utf-8",
    )

    exit_code = creator_pipeline.command_quality_check(
        argparse.Namespace(run_dir=str(run_dir), json=False, report_only=True)
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "FRESHNESS STALE" in output
    assert "STALE_ARTIFACTS corpus_index" in output
    assert f"REPAIR {REPAIR_COMMAND}" in output


def test_stale_derivations_are_an_explicit_final_ready_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = seed_run(tmp_path)
    run_prepare(monkeypatch, run_dir)
    transcript = run_dir / "transcripts" / f"{FIRST_VIDEO_ID}.txt"
    transcript.write_text(
        transcript.read_text(encoding="utf-8") + "changed after prepare\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        creator_pipeline,
        "creator_content_readiness",
        lambda *_args, **_kwargs: {"ready_for_use": True, "checks": {}},
    )
    monkeypatch.setattr(
        creator_pipeline,
        "evaluate_stage_coverage",
        lambda *_args, **_kwargs: {
            "draft": {"passed": True},
            "ready": {"passed": True},
        },
    )
    monkeypatch.setattr(
        creator_pipeline.provenance,
        "evaluate_run_governance",
        lambda *_args, **_kwargs: {
            "ready_for_use": True,
            "commercial_delivery_ready": True,
            "checks": {},
        },
    )

    report = creator_pipeline.creator_quality_check(run_dir)

    assert report["freshness"]["fresh"] is False
    assert report["ready_for_use"] is False
    assert report["commercial_delivery_ready"] is False


def test_freshness_report_keeps_hashes_and_metrics_without_copying_corpus_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = seed_run(tmp_path)
    run_prepare(monkeypatch, run_dir)

    report = creator_pipeline.creator_quality_check(run_dir)
    persisted = json.dumps(report, ensure_ascii=False)

    assert report["computed_from"]["corpus_and_signals"][0]["sha256"]
    assert report["freshness"]["current"]["corpus_index"]["coverage"][
        "transcript_count"
    ] == 2
    assert "第一条人工转写用于验证证据覆盖" not in persisted
    assert "第一条人工新鲜度样本" not in persisted
    assert str(run_dir) not in persisted
