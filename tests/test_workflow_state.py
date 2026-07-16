"""Versioned workflow state must remain observable and recoverable."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import pytest

import build_creator_skill
import creator_pipeline


def create_run(run_root: Path) -> Path:
    args = argparse.Namespace(
        source_url="https://share.example.invalid/profile",
        project_name="workflow-state",
        sample_count=2,
        metadata_fetch_limit=None,
        run_root=str(run_root),
    )
    return build_creator_skill.create_run(args, dict(build_creator_skill.DEFAULTS))


def read_workflow(run_dir: Path) -> dict[str, object]:
    return json.loads((run_dir / "workflow.plan.json").read_text(encoding="utf-8"))


def test_new_workflow_contains_versioned_lifecycle_fields(run_root: Path) -> None:
    workflow = read_workflow(create_run(run_root))

    assert workflow["schema_version"] == 1
    assert workflow["status"] == "planned"
    assert workflow["final_status"] == "pending"
    assert datetime.fromisoformat(str(workflow["created_at"]))
    assert workflow["updated_at"] == workflow["created_at"]


def test_workflow_update_derives_pending_and_completed_final_status(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    creator_pipeline.write_json(
        run_dir / "workflow.plan.json",
        {
            "schema_version": 1,
            "workflow_id": "test",
            "status": "planned",
            "final_status": "pending",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "steps": [
                {"step_id": "first", "status": "pending"},
                {"step_id": "second", "status": "pending"},
            ],
        },
    )

    creator_pipeline.update_workflow_state(run_dir, "first", "completed")
    in_progress = read_workflow(run_dir)
    assert in_progress["status"] == "running"
    assert in_progress["final_status"] == "pending"

    creator_pipeline.update_workflow_state(run_dir, "second", "skipped", "not required")
    completed = read_workflow(run_dir)
    assert completed["status"] == "completed"
    assert completed["final_status"] == "succeeded"
    assert completed["steps"][0]["status"] == "succeeded"
    assert completed["updated_at"] != "2026-01-01T00:00:00+00:00"


def test_failed_step_sets_terminal_workflow_status(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    creator_pipeline.write_json(
        run_dir / "workflow.plan.json",
        {"workflow_id": "test", "status": "planned", "steps": [{"step_id": "fetch", "status": "pending"}]},
    )

    creator_pipeline.update_workflow_state(run_dir, "fetch", "failed", "provider unavailable")

    workflow = read_workflow(run_dir)
    assert workflow["status"] == "failed"
    assert workflow["final_status"] == "failed"
    assert workflow["schema_version"] == 1
    assert workflow["created_at"]


def test_corrupt_workflow_is_preserved_and_records_recovery_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    workflow_path = run_dir / "workflow.plan.json"
    corrupt_document = '{"steps": ['
    workflow_path.write_text(corrupt_document, encoding="utf-8")

    with pytest.raises(creator_pipeline.WorkflowStateError, match="cannot read workflow state"):
        creator_pipeline.update_workflow_state(run_dir, "normalize_transcripts", "running")

    assert workflow_path.read_text(encoding="utf-8") == corrupt_document
    assert "cannot read workflow state" in capsys.readouterr().err
    recovery = json.loads(
        (run_dir / "logs" / "workflow_recovery_error.json").read_text(encoding="utf-8")
    )
    assert recovery["schema_version"] == 1
    assert recovery["operation"] == {"step_id": "normalize_transcripts", "status": "running"}
    assert recovery["error"]["type"] == "JSONDecodeError"


def test_missing_workflow_fails_loudly_and_records_recovery_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    with pytest.raises(creator_pipeline.WorkflowStateError, match="workflow state file does not exist"):
        creator_pipeline.update_workflow_state(run_dir, "download_videos", "completed")

    assert "workflow state file does not exist" in capsys.readouterr().err
    recovery = json.loads(
        (run_dir / "logs" / "workflow_recovery_error.json").read_text(encoding="utf-8")
    )
    assert recovery["operation"] == {"step_id": "download_videos", "status": "completed"}
    assert recovery["error"]["type"] == "FileNotFoundError"
