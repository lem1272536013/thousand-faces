"""Run-level rights provenance must be explicit, auditable, and reference-only."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

import build_creator_skill
import creator_pipeline
from io_utils import atomic_write_json
from offline_scenarios import offline_subprocess_env


PRIVATE_AUTHORIZATION_TEXT = "PRIVATE-CONTRACT-CONTENT-MUST-NEVER-ENTER-RUN"


def run_args(run_root: Path, **overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "source_url": (
            "https://share.example.invalid/profile?page=1"
            "&token=private-source-token"
        ),
        "project_name": "rights-audit",
        "sample_count": 1,
        "metadata_fetch_limit": None,
        "run_root": str(run_root),
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def create_quality_shape(run_dir: Path, project_name: str = "rights-audit") -> None:
    metadata = run_dir / "metadata"
    transcripts = run_dir / "transcripts"
    research = run_dir / "research" / "merged"
    metadata.mkdir(parents=True, exist_ok=True)
    transcripts.mkdir(parents=True, exist_ok=True)
    research.mkdir(parents=True, exist_ok=True)
    atomic_write_json(metadata / "selected.json", {"selected_count": 1, "items": []})
    atomic_write_json(metadata / "selected.compact.json", {"selected_count": 1, "items": []})
    atomic_write_json(metadata / "creator_profile.json", {"platform": "douyin"})
    (transcripts / "video-001.txt").write_text("[00:00:01] synthetic transcript", encoding="utf-8")
    (research / "summary.md").write_text(
        "# Synthetic research summary\n\nA sufficiently long deterministic summary.",
        encoding="utf-8",
    )
    creator_pipeline.build_creator_skill(run_dir, project_name, overwrite=True)


def force_content_and_stage_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        creator_pipeline,
        "creator_content_readiness",
        lambda *_args, **_kwargs: {
            "ready_for_use": True,
            "checks": {},
            "schema_validation": {
                artifact: {"valid": True, "errors": []}
                for artifact in (
                    "persona_model",
                    "evaluation_suite",
                    "reverse_identification",
                )
            },
            "evidence_integrity": {
                "valid": True,
                "counts": {},
            },
            "evaluator_verdict": {
                "passed": True,
                "failed_blockers": [],
            },
            "advisory_checks": {},
        },
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
        creator_pipeline.quality_engine,
        "evaluate_refinement_freshness",
        lambda *_args, **_kwargs: {
            "computed_from": {},
            "freshness": {
                "fresh": True,
                "stale_artifacts": [],
                "artifacts": {},
                "current": {},
                "repair_command": "",
            },
        },
    )


def test_new_run_defaults_to_enumerated_unspecified_rights_basis(run_root: Path) -> None:
    run_dir = build_creator_skill.create_run(
        run_args(run_root),
        dict(build_creator_skill.DEFAULTS),
    )

    payload = read_json(run_dir / "input.json")
    provenance = read_json(run_dir / "metadata" / "provenance.json")

    assert payload["rights_basis"] == "unspecified"
    assert payload["retention_policy"] == "retain_media"
    assert payload["takedown_contact"] == "not_provided"
    assert payload["source_platform"] == "douyin"
    assert payload["source_url"] == "https://share.example.invalid/profile?page=1"
    assert datetime.fromisoformat(payload["source_collected_at"]).tzinfo is not None
    assert provenance["rights_basis"] == payload["rights_basis"]
    assert provenance["rights_declared"] is False
    assert provenance["authorization"] == {
        "reference_id": "",
        "note_path": "",
    }


def test_authorized_run_records_references_but_never_copies_private_material(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    note_path = Path("governance") / "authorization-note.md"
    note_path.parent.mkdir()
    note_path.write_text(PRIVATE_AUTHORIZATION_TEXT, encoding="utf-8")
    args = run_args(
        tmp_path / "runs",
        rights_basis="creator_authorized",
        authorization_reference_id="AUTH-2026-001",
        authorization_note_path=note_path.as_posix(),
        retention_policy="transcripts_only",
        takedown_contact="rights@example.invalid",
    )

    run_dir = build_creator_skill.create_run(args, dict(build_creator_skill.DEFAULTS))
    creator_pipeline.build_creator_skill(run_dir, "rights-audit", overwrite=True)
    payload = read_json(run_dir / "input.json")
    meta = read_json(run_dir / "skill" / "references" / "meta.json")
    skill_text = (run_dir / "skill" / "SKILL.md").read_text(encoding="utf-8")
    persisted = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in run_dir.rglob("*")
        if path.is_file()
    )

    assert payload["authorization"] == {
        "reference_id": "AUTH-2026-001",
        "note_path": "governance/authorization-note.md",
    }
    assert payload["retention_policy"] == "transcripts_only"
    assert meta["source_platform"] == "douyin"
    assert meta["rights_basis"] == "creator_authorized"
    assert meta["source_collected_at"] == payload["source_collected_at"]
    assert meta["takedown_contact"] == "rights@example.invalid"
    assert meta["usage_boundary"]
    assert "来源与使用边界" in skill_text
    assert "creator_authorized" in skill_text
    assert "rights@example.invalid" in skill_text
    assert PRIVATE_AUTHORIZATION_TEXT not in persisted


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"rights_basis": "self_declared"}, "rights_basis"),
        ({"retention_policy": "keep_everything_forever"}, "retention_policy"),
        ({"authorization_reference_id": "../private-contract"}, "authorization_reference_id"),
        ({"authorization_note_path": "../private/contract.md"}, "authorization_note_path"),
        ({"authorization_note_path": "C:/private/contract.md"}, "authorization_note_path"),
        ({"takedown_contact": "line-one\nline-two"}, "takedown_contact"),
    ],
)
def test_invalid_governance_input_fails_before_run_creation(
    tmp_path: Path,
    overrides: dict[str, object],
    expected: str,
) -> None:
    output_root = tmp_path / "runs"

    with pytest.raises(ValueError, match=expected):
        build_creator_skill.create_run(
            run_args(output_root, **overrides),
            dict(build_creator_skill.DEFAULTS),
        )

    assert not output_root.exists()


@pytest.mark.parametrize(
    ("overrides", "expected_ready", "expected_commercial"),
    [
        ({}, False, False),
        (
            {
                "rights_basis": "public_research",
                "takedown_contact": "rights@example.invalid",
            },
            True,
            False,
        ),
        (
            {
                "rights_basis": "creator_authorized",
                "authorization_reference_id": "AUTH-2026-002",
                "takedown_contact": "rights@example.invalid",
            },
            True,
            True,
        ),
    ],
)
def test_rights_governance_gates_ready_and_commercial_delivery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, object],
    expected_ready: bool,
    expected_commercial: bool,
) -> None:
    run_dir = build_creator_skill.create_run(
        run_args(tmp_path / "runs", **overrides),
        dict(build_creator_skill.DEFAULTS),
    )
    create_quality_shape(run_dir)
    force_content_and_stage_ready(monkeypatch)

    report = creator_pipeline.creator_quality_check(run_dir)

    assert report["passed"] is True
    assert report["ready_for_use"] is expected_ready
    assert report["commercial_delivery_ready"] is expected_commercial
    assert report["governance"]["checks"]["input_meta_consistent"] is True
    assert report["governance"]["rights_basis"] == (
        overrides.get("rights_basis") or "unspecified"
    )


def test_tampered_skill_meta_cannot_claim_a_different_rights_basis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = build_creator_skill.create_run(
        run_args(
            tmp_path / "runs",
            rights_basis="creator_authorized",
            authorization_reference_id="AUTH-2026-003",
            takedown_contact="rights@example.invalid",
        ),
        dict(build_creator_skill.DEFAULTS),
    )
    create_quality_shape(run_dir)
    meta_path = run_dir / "skill" / "references" / "meta.json"
    meta = read_json(meta_path)
    meta["rights_basis"] = "team_owned"
    atomic_write_json(meta_path, meta)
    force_content_and_stage_ready(monkeypatch)

    report = creator_pipeline.creator_quality_check(run_dir)

    assert report["passed"] is True
    assert report["governance"]["checks"]["input_meta_consistent"] is False
    assert report["ready_for_use"] is False
    assert report["commercial_delivery_ready"] is False


def test_public_build_cli_persists_governance_arguments(
    project_root: Path,
    run_root: Path,
) -> None:
    process = subprocess.run(
        [
            sys.executable,
            str(project_root / "scripts" / "build_creator_skill.py"),
            "--source-url",
            "https://share.example.invalid/profile",
            "--project-name",
            "governance-cli",
            "--sample-count",
            "1",
            "--run-root",
            str(run_root),
            "--rights-basis",
            "public_research",
            "--retention-policy",
            "final_skill_only",
            "--takedown-contact",
            "rights@example.invalid",
        ],
        cwd=project_root,
        env=offline_subprocess_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert process.returncode == 0
    runs = list((run_root / "governance-cli").iterdir())
    assert len(runs) == 1
    payload = read_json(runs[0] / "input.json")
    assert payload["rights_basis"] == "public_research"
    assert payload["retention_policy"] == "final_skill_only"
    assert payload["takedown_contact"] == "rights@example.invalid"


def test_ready_is_revoked_when_shipped_skill_loses_source_usage_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = build_creator_skill.create_run(
        run_args(
            tmp_path / "runs",
            rights_basis="team_owned",
            takedown_contact="rights@example.invalid",
        ),
        dict(build_creator_skill.DEFAULTS),
    )
    create_quality_shape(run_dir)
    skill_path = run_dir / "skill" / "SKILL.md"
    skill_text = skill_path.read_text(encoding="utf-8")
    skill_path.write_text(
        skill_text.replace("## 来源与使用边界", "## Removed Governance Boundary"),
        encoding="utf-8",
    )
    force_content_and_stage_ready(monkeypatch)

    report = creator_pipeline.creator_quality_check(run_dir)

    assert report["governance"]["checks"]["skill_usage_boundary_present"] is False
    assert report["ready_for_use"] is False
    assert report["commercial_delivery_ready"] is False
