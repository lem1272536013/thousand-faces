"""CLI exit codes, workflow state, and persisted results must agree."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from offline_scenarios import offline_subprocess_env, run_offline_scenario


def read_pipeline_result(run_dir: Path) -> dict[str, object]:
    return json.loads((run_dir / "logs" / "pipeline_result.json").read_text(encoding="utf-8"))


def test_successful_runner_has_zero_exit_and_matching_succeeded_final_status(
    project_root: Path,
    run_root: Path,
) -> None:
    result = run_offline_scenario(project_root, run_root / "success", "happy")
    assert result.run_dir is not None
    pipeline = read_pipeline_result(result.run_dir)

    assert result.returncode == 0
    assert result.workflow["final_status"] == "succeeded"
    assert pipeline["status"] == "succeeded"
    assert pipeline["exit_code"] == result.returncode
    assert pipeline["quality_passed"] is True


@pytest.mark.parametrize("scenario", ["no_transcript", "empty_metadata"])
def test_failed_draft_has_nonzero_exit_and_matching_failed_final_status(
    project_root: Path,
    run_root: Path,
    scenario: str,
) -> None:
    result = run_offline_scenario(project_root, run_root / scenario, scenario)
    assert result.run_dir is not None
    pipeline = read_pipeline_result(result.run_dir)

    assert result.quality["passed"] is False
    assert result.returncode != 0
    assert result.workflow["final_status"] == "failed"
    assert pipeline["status"] == "failed"
    assert pipeline["exit_code"] == result.returncode
    assert pipeline["quality_passed"] is False


def test_exception_records_failed_workflow_and_pipeline_before_process_exits(
    project_root: Path,
    run_root: Path,
) -> None:
    result = run_offline_scenario(project_root, run_root / "malformed", "malformed_metadata")
    assert result.run_dir is not None
    pipeline = read_pipeline_result(result.run_dir)

    assert result.returncode != 0
    assert result.workflow["final_status"] == "failed"
    assert pipeline["status"] == "failed"
    assert pipeline["exit_code"] == result.returncode
    assert pipeline["error"]["type"] == "JSONDecodeError"


def run_creator_quality_cli(project_root: Path, run_dir: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(project_root / "scripts" / "creator_pipeline.py"),
            "quality-check",
            "--run-dir",
            str(run_dir),
            "--json",
            *extra,
        ],
        cwd=project_root,
        env=offline_subprocess_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def test_creator_quality_check_is_strict_by_default_and_report_only_is_explicit(
    project_root: Path,
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "empty-run"
    run_dir.mkdir()

    strict = run_creator_quality_cli(project_root, run_dir)
    report_only = run_creator_quality_cli(project_root, run_dir, "--report-only")

    assert json.loads(strict.stdout)["passed"] is False
    assert strict.returncode != 0
    assert json.loads(report_only.stdout)["passed"] is False
    assert report_only.returncode == 0


def test_research_quality_check_is_strict_by_default_and_report_only_is_explicit(
    project_root: Path,
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "empty-run"
    run_dir.mkdir()
    base_command = [
        sys.executable,
        str(project_root / "scripts" / "research" / "quality_check.py"),
        str(run_dir),
        "--json",
    ]
    strict = subprocess.run(
        base_command,
        cwd=project_root,
        env=offline_subprocess_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    report_only = subprocess.run(
        [*base_command, "--report-only"],
        cwd=project_root,
        env=offline_subprocess_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert json.loads(strict.stdout)["passed"] is False
    assert strict.returncode != 0
    assert "DEPRECATED" in strict.stderr
    assert "creator_pipeline.py quality-check" in strict.stderr
    assert json.loads(report_only.stdout)["passed"] is False
    assert report_only.returncode == 0
