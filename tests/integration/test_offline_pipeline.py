"""Offline end-to-end contracts shared with the user-facing self-test."""

from __future__ import annotations

from pathlib import Path

from offline_scenarios import run_and_validate_offline_happy_path, run_offline_scenario


def test_happy_path_builds_assertable_draft_and_refinement_package(
    project_root: Path,
    run_root: Path,
) -> None:
    result = run_and_validate_offline_happy_path(project_root, run_root / "happy")
    baseline = result.baseline
    refinement = result.refinement

    assert baseline.returncode == 0
    assert baseline.run_dir is not None
    assert baseline.workflow["workflow_id"] == "creator_skill_build_v1_skill_first"
    assert baseline.workflow["status"] == "completed"
    assert baseline.workflow["final_status"] == "succeeded"
    assert baseline.quality["passed"] is True
    assert baseline.quality["ready_for_use"] is False
    assert baseline.quality["transcript_count"] == 2
    assert baseline.summary["artifacts"] == {
        "raw_metadata": True,
        "selected_metadata": True,
        "selected_compact_metadata": True,
        "creator_profile": True,
        "videos": 0,
        "audio": 0,
        "transcripts": 2,
        "asr_raw_json": 0,
        "research_summary": True,
        "skill": True,
    }
    assert baseline.selected["requested_count"] == 2
    assert baseline.selected["selected_count"] == 2
    assert baseline.selected["selection_strategy"] == "published_at_desc"
    assert all("raw" not in item for item in baseline.compact["items"])
    assert baseline.creator_profile["platform"] == "douyin"

    assert refinement.prepare_returncode == 0
    assert refinement.quality_returncode == 0
    assert refinement.quality["passed"] is True
    assert refinement.quality["ready_for_use"] is False
    assert refinement.persona_schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert refinement.persona_schema["x-schema-version"] == "1.1.0"
    assert refinement.persona_model["version"] == "1.0"
    assert refinement.persona_model["status"] == "draft_template"
    assert refinement.evaluation_schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert refinement.evaluation_schema["x-schema-version"] == "1.1.0"
    assert refinement.reverse_identification_schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert refinement.reverse_identification_schema["x-schema-version"] == "1.1.0"
    assert {
        name: (validation["valid"], validation["status"])
        for name, validation in refinement.quality["schema_validation"].items()
    } == {
        "persona_model": (True, "draft_template"),
        "evaluation_suite": (True, "draft_template"),
        "reverse_identification": (True, "draft_template"),
    }
    assert refinement.quality["evidence_integrity"]["valid"] is False
    assert refinement.quality["evidence_integrity"]["counts"][
        "valid_unique_evidence_anchors"
    ] == 0
    assert refinement.quality["content_readiness"]["checks"][
        "evidence_integrity_valid"
    ] is False


def test_partial_transcript_is_not_reported_as_complete(
    project_root: Path,
    run_root: Path,
) -> None:
    result = run_offline_scenario(project_root, run_root / "partial", "partial_transcript")

    assert result.selected["selected_count"] == 2
    assert result.quality["transcript_count"] == 1
    assert result.summary["artifacts"]["transcripts"] == 1
    assert result.quality["passed"] is False
    assert result.quality["checks"]["stage_coverage_draft"] is False
    assert result.quality["stage_coverage"]["stages"]["transcribed"]["count"] == 1
    assert result.quality["stage_coverage"]["draft"]["failed_stages"] == ["transcribed"]
    assert result.workflow["status"] == "failed"
    assert result.returncode != 0


def test_no_transcript_marks_quality_and_workflow_failed(
    project_root: Path,
    run_root: Path,
) -> None:
    result = run_offline_scenario(project_root, run_root / "no-transcript", "no_transcript")

    assert result.selected["selected_count"] == 2
    assert result.quality["transcript_count"] == 0
    assert "artifacts" in result.summary, {
        "returncode": result.returncode,
        "summary": result.summary,
        "stdout_tail": result.stdout[-4000:],
        "stderr_tail": result.stderr[-4000:],
    }
    assert result.summary["artifacts"]["transcripts"] == 0
    assert result.quality["passed"] is False
    assert result.summary["quality"]["passed"] is False
    assert result.workflow["status"] == "failed"
    quality_step = next(step for step in result.workflow["steps"] if step["step_id"] == "quality_check")
    assert quality_step["status"] == "failed"


def test_failed_quality_gate_returns_nonzero_exit_code(
    project_root: Path,
    run_root: Path,
) -> None:
    result = run_offline_scenario(project_root, run_root / "quality-exit", "no_transcript")

    assert result.quality["passed"] is False
    assert result.returncode != 0


def test_empty_metadata_produces_an_explicit_failed_draft(
    project_root: Path,
    run_root: Path,
) -> None:
    result = run_offline_scenario(project_root, run_root / "empty", "empty_metadata")

    assert result.selected["selected_count"] == 0
    assert result.compact["items"] == []
    assert result.quality["passed"] is False
    assert result.quality["transcript_count"] == 0
    assert result.summary["artifacts"]["skill"] is True
    assert result.workflow["status"] == "failed"


def test_malformed_metadata_returns_nonzero_and_records_failed_step(
    project_root: Path,
    run_root: Path,
) -> None:
    result = run_offline_scenario(project_root, run_root / "malformed", "malformed_metadata")

    assert result.returncode != 0
    assert result.quality == {}
    assert result.summary["execution"]["pipeline_status"] == "failed"
    assert result.summary["execution"]["pipeline_error"]["error_code"] == "INVALID_JSON"
    assert "resume_creator_run.py" in result.summary["execution"]["next_action"]["command"]
    assert result.workflow["status"] == "failed"
    select_step = next(step for step in result.workflow["steps"] if step["step_id"] == "select_recent_samples")
    assert select_step["status"] == "failed"
    assert "JSON" in result.stderr or "decode" in result.stderr.lower()
