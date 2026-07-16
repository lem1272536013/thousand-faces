"""Versioned run diagnosis and conservative legacy-run compatibility contracts."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from offline_scenarios import offline_subprocess_env


RUN_FORMAT = "thousand-faces.creator-run"
RUN_FORMAT_VERSION = 1


def run_command(
    project_root: Path,
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *arguments],
        cwd=project_root,
        env=offline_subprocess_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def creator_pipeline_command(project_root: Path, *arguments: str) -> tuple[str, ...]:
    return (str(project_root / "scripts" / "creator_pipeline.py"), *arguments)


def copy_legacy_run(tmp_path: Path, fixture_root: Path) -> Path:
    target = tmp_path / "legacy-v0"
    shutil.copytree(fixture_root / "runs" / "legacy_v0", target)
    return target


def snapshot_tree(root: Path) -> tuple[tuple[str, ...], dict[str, bytes]]:
    directories = tuple(
        sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_dir())
    )
    files = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }
    return directories, files


def inspect_json(project_root: Path, run_dir: Path) -> tuple[subprocess.CompletedProcess[str], dict]:
    process = run_command(
        project_root,
        *creator_pipeline_command(
            project_root,
            "inspect-run",
            "--run-dir",
            str(run_dir),
            "--json",
        ),
    )
    return process, json.loads(process.stdout)


def test_legacy_run_is_diagnosed_without_mutation_or_ready_claim(
    project_root: Path,
    fixture_root: Path,
    tmp_path: Path,
) -> None:
    run_dir = copy_legacy_run(tmp_path, fixture_root)
    before = snapshot_tree(run_dir)

    process, report = inspect_json(project_root, run_dir)

    assert process.returncode == 1
    assert report["format_status"] == "legacy_unverified"
    assert report["format_version"] is None
    assert report["format_verified"] is False
    assert report["ready_for_use"] is False
    assert report["quality"] == {
        "status": "ignored_unverified",
        "declared_ready_for_use": False,
        "format_verified": False,
    }
    assert report["missing_manifests"] == [
        "config.snapshot.json",
        "metadata/provenance.json",
    ]
    assert report["recommended_action"]["code"] == "CREATE_NEW_RUN"
    assert "build_creator_skill.py" in report["recommended_action"]["command"]
    assert snapshot_tree(run_dir) == before


def test_quality_check_reports_legacy_format_blocker_without_writing(
    project_root: Path,
    fixture_root: Path,
    tmp_path: Path,
) -> None:
    run_dir = copy_legacy_run(tmp_path, fixture_root)
    before = snapshot_tree(run_dir)

    process = run_command(
        project_root,
        *creator_pipeline_command(
            project_root,
            "quality-check",
            "--run-dir",
            str(run_dir),
            "--json",
            "--report-only",
        ),
    )
    report = json.loads(process.stdout)

    assert process.returncode == 0
    assert report["run_format"]["format_status"] == "legacy_unverified"
    assert report["run_format"]["format_verified"] is False
    assert report["blocking_checks"]["run_format_verified"]["passed"] is False
    assert report["ready_for_use"] is False
    assert report["commercial_delivery_ready"] is False
    persisted_legacy = json.loads(
        (run_dir / "logs" / "creator_quality_report.json").read_text(encoding="utf-8")
    )
    assert persisted_legacy["ready_for_use"] is True
    assert snapshot_tree(run_dir) == before


@pytest.mark.parametrize(
    ("script_name", "arguments"),
    [
        (
            "creator_pipeline.py",
            ["build-skill", "--project-name", "legacy-synthetic"],
        ),
        ("creator_pipeline.py", ["run-summary"]),
        ("resume_creator_run.py", ["--project-name", "legacy-synthetic"]),
        ("prepare_host_refinement.py", []),
        ("retention.py", ["--apply"]),
        (
            "provider_adapters.py",
            ["oss-upload", "--input", "synthetic.wav", "--video-id", "video-001"],
        ),
        ("provider_adapters.py", ["oss-cleanup"]),
    ],
)
def test_mutating_entrypoints_reject_legacy_run_before_writing(
    project_root: Path,
    fixture_root: Path,
    tmp_path: Path,
    script_name: str,
    arguments: list[str],
) -> None:
    run_dir = copy_legacy_run(tmp_path, fixture_root)
    before = snapshot_tree(run_dir)

    has_subcommand = script_name in {"creator_pipeline.py", "provider_adapters.py"}
    process = run_command(
        project_root,
        str(project_root / "scripts" / script_name),
        *(arguments[:1] if has_subcommand else []),
        "--run-dir",
        str(run_dir),
        *(arguments[1:] if has_subcommand else arguments),
    )

    assert process.returncode != 0
    assert "RUN_FORMAT_UNVERIFIED" in process.stderr
    assert "inspect-run" in process.stderr
    assert snapshot_tree(run_dir) == before


def test_new_run_declares_supported_format_and_inspects_conservatively(
    project_root: Path,
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "runs"
    process = run_command(
        project_root,
        str(project_root / "scripts" / "build_creator_skill.py"),
        "--source-url",
        "https://share.example.invalid/profile",
        "--project-name",
        "format-current",
        "--sample-count",
        "1",
        "--run-root",
        str(run_root),
    )
    assert process.returncode == 0, process.stderr
    runs = list((run_root / "format-current").iterdir())
    assert len(runs) == 1
    run_dir = runs[0]

    descriptor = json.loads((run_dir / "input.json").read_text(encoding="utf-8"))
    assert descriptor["run_format"] == RUN_FORMAT
    assert descriptor["schema_version"] == RUN_FORMAT_VERSION

    inspect_process, report = inspect_json(project_root, run_dir)

    assert inspect_process.returncode == 0
    assert report["format_status"] == "current_verified"
    assert report["format_name"] == RUN_FORMAT
    assert report["format_version"] == RUN_FORMAT_VERSION
    assert report["format_verified"] is True
    assert report["missing_manifests"] == []
    assert report["invalid_manifests"] == []
    assert report["quality"]["status"] == "missing"
    assert report["ready_for_use"] is False


@pytest.mark.parametrize(
    ("mutation", "expected_status", "expected_path"),
    [
        ("missing_workflow", "current_incomplete", "workflow.plan.json"),
        ("invalid_config", "invalid", "config.snapshot.json"),
        ("future_version", "unsupported", None),
    ],
)
def test_incomplete_invalid_and_future_runs_are_not_verified(
    project_root: Path,
    tmp_path: Path,
    mutation: str,
    expected_status: str,
    expected_path: str | None,
) -> None:
    run_dir = tmp_path / mutation
    (run_dir / "metadata").mkdir(parents=True)
    (run_dir / "input.json").write_text(
        json.dumps(
            {
                "run_format": RUN_FORMAT,
                "schema_version": 999 if mutation == "future_version" else RUN_FORMAT_VERSION,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "config.snapshot.json").write_text(
        "not-json" if mutation == "invalid_config" else '{"settings_schema_version": 2}',
        encoding="utf-8",
    )
    if mutation != "missing_workflow":
        (run_dir / "workflow.plan.json").write_text('{"schema_version": 1}', encoding="utf-8")
    (run_dir / "metadata" / "provenance.json").write_text(
        '{"schema_version": 1}', encoding="utf-8"
    )

    process, report = inspect_json(project_root, run_dir)

    assert process.returncode == 1
    assert report["format_status"] == expected_status
    assert report["format_verified"] is False
    assert report["ready_for_use"] is False
    if mutation == "missing_workflow":
        assert expected_path in report["missing_manifests"]
    elif mutation == "invalid_config":
        assert expected_path in report["invalid_manifests"]


def test_missing_run_has_stable_nonzero_diagnosis(
    project_root: Path,
    tmp_path: Path,
) -> None:
    process, report = inspect_json(project_root, tmp_path / "does-not-exist")

    assert process.returncode == 1
    assert report["format_status"] == "not_found"
    assert report["format_verified"] is False
    assert report["ready_for_use"] is False
