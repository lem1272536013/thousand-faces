"""Cross-file evidence references must be real, distinct, and type-compatible."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import creator_pipeline
import evidence_model
import prepare_host_refinement
import run_diagnostics


VIDEO_IDS = [str(190000000000000300 + index) for index in range(20)]


def corpus(*, missing_transcripts: set[str] | None = None) -> dict[str, Any]:
    missing = missing_transcripts or set()
    return {
        "records": [
            {
                "video_id": video_id,
                "platform_video_id": video_id,
                "artifact_id": video_id,
                "transcript_chars": 0 if video_id in missing else 120,
            }
            for video_id in VIDEO_IDS
        ]
    }


def parsed_evidence(*ids: str, unknown: list[str] | None = None) -> dict[str, Any]:
    return {
        "source_status": "parsed",
        "accepted_ids": list(ids),
        "unknown_video_ids": unknown or [],
        "duplicate_ids": [],
        "conflicting_ids": [],
    }


def valid_documents() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    persona = {
        "topic_models": [{"evidence_ids": VIDEO_IDS[:2]}],
        "script_templates": [{"evidence_ids": [VIDEO_IDS[0]]}],
        "evidence_anchors": [
            {"video_id": video_id, "role": "metadata:title"}
            for video_id in VIDEO_IDS[:15]
        ],
    }
    evaluation = {
        "cases": [
            {
                "applied_persona_model_fields": ["script_templates", "expression_dna"],
                "evidence_video_ids": [VIDEO_IDS[0]],
            }
        ]
    }
    reverse = {"rows": [{"evidence_video_ids": [VIDEO_IDS[0]]}]}
    return persona, evaluation, reverse


def evaluate(
    *,
    corpus_index: dict[str, Any] | None = None,
    evidence_index: dict[str, Any] | None = None,
    persona: dict[str, Any] | None = None,
    evaluation: dict[str, Any] | None = None,
    reverse: dict[str, Any] | None = None,
) -> dict[str, Any]:
    default_persona, default_evaluation, default_reverse = valid_documents()
    return evidence_model.evaluate_evidence_integrity(
        corpus_index or corpus(),
        evidence_index or parsed_evidence(*VIDEO_IDS[:15]),
        persona if persona is not None else default_persona,
        evaluation if evaluation is not None else default_evaluation,
        reverse if reverse is not None else default_reverse,
    )


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def seed_run_documents(run_dir: Path) -> Path:
    persona, evaluation, reverse = valid_documents()
    write_json(
        run_dir / "input.json",
        {
            "run_format": run_diagnostics.RUN_FORMAT_NAME,
            "schema_version": run_diagnostics.RUN_FORMAT_SCHEMA_VERSION,
        },
    )
    write_json(run_dir / "config.snapshot.json", {"settings_schema_version": 2})
    write_json(run_dir / "workflow.plan.json", {"schema_version": 1})
    write_json(run_dir / "metadata" / "provenance.json", {"schema_version": 1})
    items = [
        {
            "platform_video_id": video_id,
            "artifact_id": video_id,
            "title": f"Synthetic evidence item {index}",
            "stats": {},
        }
        for index, video_id in enumerate(VIDEO_IDS)
    ]
    write_json(
        run_dir / "metadata" / "selected.compact.json",
        {
            "selected_count": len(items),
            "items": items,
        },
    )
    transcripts = run_dir / "transcripts"
    transcripts.mkdir(parents=True, exist_ok=True)
    for video_id in VIDEO_IDS:
        (transcripts / f"{video_id}.txt").write_text(
            "[00:00:00] Synthetic transcript evidence.\n",
            encoding="utf-8",
        )
    refs = run_dir / "skill" / "references"
    reviews = run_dir / "research" / "reviews"
    write_json(refs / "persona_model.json", persona)
    write_json(reviews / "evaluation_suite.json", evaluation)
    write_json(reviews / "reverse_identification.json", reverse)
    refs.mkdir(parents=True, exist_ok=True)
    refs.joinpath("evidence_index.md").write_text(
        "# Evidence Index\n\n"
        "| Video ID | Status | Reason | Finding |\n"
        "|---|---|---|---|\n"
        + "".join(
            f"| {video_id} | accepted | | traceable |\n"
            for video_id in VIDEO_IDS[:15]
        ),
        encoding="utf-8",
    )
    for name in ("persona.md", "topic_model.md", "script_style.md"):
        refs.joinpath(name).write_text(f"# {name}\n", encoding="utf-8")
    return run_dir / "skill"


def test_valid_cross_file_references_pass() -> None:
    report = evaluate()

    assert report["valid"] is True
    assert all(report["checks"].values())
    assert report["counts"]["valid_unique_evidence_anchors"] == 15
    assert report["artifact_validity"] == {
        "corpus_index": True,
        "evidence_index": True,
        "persona_model": True,
        "evaluation_suite": True,
        "reverse_identification": True,
    }
    for category in (
        "orphan_references",
        "missing_references",
        "duplicate_references",
        "type_mismatches",
    ):
        assert report[category] == []


def test_fifteen_forged_anchor_ids_do_not_satisfy_evidence_minimum() -> None:
    forged_ids = [str(999999999999999900 + index) for index in range(15)]
    persona, evaluation, reverse = valid_documents()
    persona["evidence_anchors"] = [
        {"video_id": video_id, "role": "metadata:title"}
        for video_id in forged_ids
    ]

    report = evaluate(
        evidence_index=parsed_evidence(unknown=forged_ids),
        persona=persona,
        evaluation=evaluation,
        reverse=reverse,
    )

    persona_orphans = {
        item["video_id"]
        for item in report["orphan_references"]
        if item["artifact"] == "persona_model"
    }
    assert persona_orphans == set(forged_ids)
    assert report["counts"]["valid_unique_evidence_anchors"] == 0
    assert report["checks"]["evidence_anchor_minimum"] is False
    assert report["artifact_validity"]["persona_model"] is False
    assert report["valid"] is False


def test_duplicate_topic_id_does_not_count_as_two_distinct_videos() -> None:
    persona, evaluation, reverse = valid_documents()
    persona["topic_models"][0]["evidence_ids"] = [VIDEO_IDS[0], VIDEO_IDS[0]]

    report = evaluate(persona=persona, evaluation=evaluation, reverse=reverse)

    assert report["checks"]["topic_model_distinct_evidence"] is False
    assert {
        (item["video_id"], item["pointer"], item["first_pointer"])
        for item in report["duplicate_references"]
    } == {
        (
            VIDEO_IDS[0],
            "/topic_models/0/evidence_ids/1",
            "/topic_models/0/evidence_ids/0",
        )
    }
    assert report["artifact_validity"]["persona_model"] is False
    assert report["valid"] is False


def test_metadata_only_video_cannot_support_script_expression_or_reverse_claims() -> None:
    persona, evaluation, reverse = valid_documents()
    persona["evidence_anchors"][1]["role"] = "title-derived script tone"
    report = evaluate(
        corpus_index=corpus(missing_transcripts={VIDEO_IDS[0], VIDEO_IDS[1]}),
        persona=persona,
        evaluation=evaluation,
        reverse=reverse,
    )

    mismatches = {
        (item["artifact"], item["pointer"], item["required_type"], item["available_type"])
        for item in report["type_mismatches"]
    }
    assert (
        "persona_model",
        "/script_templates/0/evidence_ids/0",
        "transcript",
        "metadata",
    ) in mismatches
    assert (
        "evaluation_suite",
        "/cases/0/evidence_video_ids/0",
        "transcript",
        "metadata",
    ) in mismatches
    assert (
        "reverse_identification",
        "/rows/0/evidence_video_ids/0",
        "transcript",
        "metadata",
    ) in mismatches
    assert not any(item["pointer"].startswith("/topic_models/") for item in report["type_mismatches"])
    anchor = next(
        item for item in report["anchor_mappings"] if item["video_id"] == VIDEO_IDS[0]
    )
    assert anchor["evidence_type"] == "metadata"
    assert anchor["valid"] is True
    ambiguous_anchor = next(
        item for item in report["anchor_mappings"] if item["video_id"] == VIDEO_IDS[1]
    )
    assert ambiguous_anchor["required_type"] == "transcript"
    assert ambiguous_anchor["valid"] is False
    assert any(
        item["pointer"] == "/evidence_anchors/1/video_id"
        for item in report["type_mismatches"]
    )
    assert report["checks"]["reference_types_match"] is False
    assert report["valid"] is False


def test_model_evaluation_and_reverse_ids_must_be_accepted_corpus_evidence() -> None:
    persona, evaluation, reverse = valid_documents()
    missing_id = VIDEO_IDS[14]
    forged_model_id = "999999999999999981"
    forged_reverse_id = "999999999999999982"
    persona["topic_models"][0]["evidence_ids"] = [VIDEO_IDS[0], forged_model_id]
    evaluation["cases"][0]["evidence_video_ids"] = [missing_id]
    reverse["rows"][0]["evidence_video_ids"] = [forged_reverse_id]
    accepted = VIDEO_IDS[:14]

    report = evaluate(
        evidence_index=parsed_evidence(*accepted),
        persona=persona,
        evaluation=evaluation,
        reverse=reverse,
    )

    assert {
        (item["artifact"], item["video_id"])
        for item in report["orphan_references"]
        if item["artifact"] != "evidence_index"
    } == {
        ("persona_model", forged_model_id),
        ("reverse_identification", forged_reverse_id),
    }
    assert {
        (item["artifact"], item["video_id"])
        for item in report["missing_references"]
    } >= {("evaluation_suite", missing_id)}
    assert report["checks"]["all_references_in_corpus"] is False
    assert report["checks"]["all_references_in_evidence_index"] is False
    assert report["artifact_validity"]["persona_model"] is False
    assert report["artifact_validity"]["evaluation_suite"] is False
    assert report["artifact_validity"]["reverse_identification"] is False
    assert report["valid"] is False


def test_evidence_index_duplicate_rows_are_reported(tmp_path: Path) -> None:
    evidence_path = tmp_path / "evidence_index.md"
    evidence_path.write_text(
        "| Video ID | Status | Finding |\n"
        "|---|---|---|\n"
        f"| {VIDEO_IDS[0]} | accepted | first |\n"
        f"| {VIDEO_IDS[0]} | accepted | duplicate |\n",
        encoding="utf-8",
    )

    parsed = prepare_host_refinement.parse_evidence_index(
        evidence_path,
        {VIDEO_IDS[0]},
    )

    assert parsed["accepted_ids"] == [VIDEO_IDS[0]]
    assert parsed["duplicate_ids"] == [VIDEO_IDS[0]]


def test_duplicate_evidence_index_entry_does_not_back_a_valid_anchor(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    skill_dir = seed_run_documents(run_dir)
    evidence_path = skill_dir / "references" / "evidence_index.md"
    evidence_path.write_text(
        evidence_path.read_text(encoding="utf-8")
        + f"| {VIDEO_IDS[0]} | accepted | | duplicate |\n",
        encoding="utf-8",
    )

    report = evidence_model.evaluate_run_evidence_integrity(run_dir)

    assert report["valid"] is False
    assert report["counts"]["duplicate_references"] == 1
    assert report["counts"]["valid_unique_evidence_anchors"] == 14
    duplicate_anchor = next(
        item for item in report["anchor_mappings"] if item["video_id"] == VIDEO_IDS[0]
    )
    assert duplicate_anchor["valid"] is False


def test_run_integrity_uses_current_metadata_transcripts_and_documents(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    seed_run_documents(run_dir)

    report = evidence_model.evaluate_run_evidence_integrity(run_dir)

    assert report["valid"] is True
    assert report["document_status"] == {
        "persona_model": "loaded",
        "evaluation_suite": "loaded",
        "reverse_identification": "loaded",
    }
    assert report["counts"]["corpus_video_ids"] == len(VIDEO_IDS)
    assert report["counts"]["valid_unique_evidence_anchors"] == 15


def test_content_readiness_exposes_cross_file_integrity_as_a_blocker(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    skill_dir = seed_run_documents(run_dir)
    persona_path = skill_dir / "references" / "persona_model.json"
    persona = json.loads(persona_path.read_text(encoding="utf-8"))
    forged_ids = [str(999999999999999700 + index) for index in range(15)]
    persona["evidence_anchors"] = [
        {"video_id": video_id, "role": "metadata:title"}
        for video_id in forged_ids
    ]
    write_json(persona_path, persona)

    readiness = creator_pipeline.creator_content_readiness(skill_dir, run_dir)

    assert readiness["checks"]["evidence_integrity_valid"] is False
    assert readiness["evidence_integrity"]["valid"] is False
    assert readiness["evidence_integrity"]["counts"]["valid_unique_evidence_anchors"] == 0
    assert readiness["persona_model"]["checks"]["evidence_anchors_min"] is False
    assert readiness["persona_model"]["counts"]["valid_unique_evidence_anchors"] == 0
    assert readiness["ready_for_use"] is False


def test_evaluation_and_reverse_integrity_are_explicit_host_checks(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    skill_dir = seed_run_documents(run_dir)
    evaluation_path = run_dir / "research" / "reviews" / "evaluation_suite.json"
    reverse_path = run_dir / "research" / "reviews" / "reverse_identification.json"
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    reverse = json.loads(reverse_path.read_text(encoding="utf-8"))
    evaluation["cases"][0]["evidence_video_ids"] = ["999999999999999961"]
    reverse["rows"][0]["evidence_video_ids"] = ["999999999999999962"]
    write_json(evaluation_path, evaluation)
    write_json(reverse_path, reverse)

    readiness = creator_pipeline.creator_content_readiness(skill_dir, run_dir)

    integrity = readiness["evidence_integrity"]
    assert integrity["artifact_validity"]["evaluation_suite"] is False
    assert integrity["artifact_validity"]["reverse_identification"] is False
    assert readiness["host_refinement"]["checks"]["evaluation_suite_evidence_integrity"] is False
    assert readiness["host_refinement"]["checks"]["reverse_identification_evidence_integrity"] is False


def test_quality_report_has_auditable_inputs_and_text_error_counts(
    tmp_path: Path,
    capsys: Any,
) -> None:
    run_dir = tmp_path / "run"
    seed_run_documents(run_dir)
    reverse_path = run_dir / "research" / "reviews" / "reverse_identification.json"
    reverse = json.loads(reverse_path.read_text(encoding="utf-8"))
    reverse["rows"][0]["evidence_video_ids"] = ["999999999999999951"]
    write_json(reverse_path, reverse)

    exit_code = creator_pipeline.command_quality_check(
        argparse.Namespace(run_dir=str(run_dir), json=False, report_only=True)
    )
    output = capsys.readouterr().out
    report = json.loads(
        (run_dir / "logs" / "creator_quality_report.json").read_text(
            encoding="utf-8"
        )
    )

    assert exit_code == 0
    assert "EVIDENCE_INTEGRITY INVALID" in output
    assert "REFERENCE_ERRORS orphan=1 missing=0 duplicate=0 type_mismatch=0" in output
    assert len(report["evidence_integrity"]["orphan_references"]) == 1
    input_roles = {
        item["role"] for item in report["evidence_integrity"]["computed_from"]
    }
    assert {
        "selected_metadata",
        "evidence_index",
        "persona_model",
        "evaluation_suite",
        "reverse_identification",
    } <= input_roles
    assert any(role.startswith("transcript:") for role in input_roles)
    assert str(run_dir) not in json.dumps(
        report["evidence_integrity"],
        ensure_ascii=False,
    )
