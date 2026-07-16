"""Ready status must be computed from facts rather than self declarations."""

from __future__ import annotations

import json
import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import creator_pipeline
import quality_engine
import run_diagnostics


VIDEO_ID = "190000000000000401"
REQUIRED_CASES = (
    "hot_topic_selection",
    "short_script_30s",
    "copy_rewrite",
    "style_critique",
    "boundary_request",
    "evidence_explanation",
)


def persona_model() -> dict[str, Any]:
    return {
        "status": "completed",
        "topic_models": [{"name": "evidence-led topics"}],
        "script_templates": [{"name": "mechanism script"}],
        "judgment_heuristics": ["show evidence before conclusions"],
        "expression_dna": ["short mechanism-first sentences"],
        "anti_patterns": ["generic motivational ending"],
        "safety_boundaries": ["不得冒充创作者本人"],
        "evidence_anchors": [{"video_id": VIDEO_ID, "role": "transcript:structure"}],
    }


def evaluation_suite() -> dict[str, Any]:
    field_pairs = {
        "hot_topic_selection": ["topic_models", "evidence_anchors"],
        "short_script_30s": ["script_templates", "expression_dna"],
        "copy_rewrite": ["expression_dna", "anti_patterns"],
        "style_critique": ["expression_dna", "anti_patterns"],
        "boundary_request": ["safety_boundaries", "anti_patterns"],
        "evidence_explanation": ["evidence_anchors", "judgment_heuristics"],
    }
    cases = []
    for name in REQUIRED_CASES:
        boundary = name == "boundary_request"
        cases.append(
            {
                "name": name,
                "task": f"fixed task for {name}",
                "input": f"realistic input for {name}",
                "applied_persona_model_fields": field_pairs[name],
                "output": (
                    "不能冒充创作者本人；我可以提供不代表本人的安全改写建议。"
                    if boundary
                    else "This output applies the selected persona fields and explains its evidence."
                ),
                "evidence_video_ids": [] if boundary else [VIDEO_ID],
                "safety_rule_ids": ["/safety_boundaries/0"] if boundary else [],
                "generic_ai_markers": ["generic transition"]
                if name == "style_critique"
                else [],
                "confidence": "high",
                "passed": True,
            }
        )
    return {
        "status": "completed",
        "cases": cases,
        "scorecard": {
            "all_cases_completed": True,
            "persona_model_fields_cited": True,
            "evidence_or_rule_cited": True,
            "generic_ai_markers_reviewed": True,
            "passed": True,
        },
    }


def reverse_identification() -> dict[str, Any]:
    return {
        "status": "completed",
        "rows": [
            {
                "output_id": f"output-{index}",
                "creator_specific_markers": [f"creator-marker-{index}"],
                "generic_ai_markers": [f"generic-marker-{index}"] if index < 3 else [],
                "persona_model_fields": ["expression_dna"],
                "evidence_video_ids": [VIDEO_ID],
                "verdict": "traceable",
            }
            for index in range(5)
        ],
        "scorecard": {
            "creator_specific_marker_count": 5,
            "generic_ai_marker_count": 3,
            "fields_traceable": True,
            "evidence_traceable": True,
            "passed": True,
        },
    }


def schema_validation(*, valid: bool = True) -> dict[str, Any]:
    return {
        artifact: {
            "valid": valid,
            "schema_valid": True,
            "errors": []
            if valid
            else [{"pointer": "/status", "keyword": "const", "message": "invalid"}],
        }
        for artifact in (
            "persona_model",
            "evaluation_suite",
            "reverse_identification",
        )
    }


def evidence_integrity(*, valid: bool = True) -> dict[str, Any]:
    return {
        "valid": valid,
        "checks": {
            "corpus_available": valid,
            "all_references_in_corpus": valid,
        },
        "artifact_validity": {
            "persona_model": valid,
            "evaluation_suite": valid,
            "reverse_identification": valid,
        },
        "counts": {
            "orphan_references": 0 if valid else 1,
            "missing_references": 0,
            "duplicate_references": 0,
            "type_mismatches": 0,
        },
    }


def evaluate_documents(
    *,
    evaluation: dict[str, Any] | None = None,
    reverse: dict[str, Any] | None = None,
    schemas: dict[str, Any] | None = None,
    integrity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return quality_engine.evaluate_evaluator_documents(
        persona_model(),
        evaluation or evaluation_suite(),
        reverse or reverse_identification(),
        schema_validation=schemas or schema_validation(),
        evidence_integrity=integrity or evidence_integrity(),
    )


def ready_inputs() -> dict[str, Any]:
    return {
        "deterministic_checks": {"required_files": True, "stage_coverage_draft": True},
        "content_readiness": {"ready_for_use": True, "checks": {}},
        "stage_coverage": {"ready": {"passed": True, "failed_stages": []}},
        "governance": {
            "ready_for_use": True,
            "commercial_delivery_ready": True,
            "checks": {},
        },
        "freshness": {"fresh": True, "stale_artifacts": []},
        "schema_validation": schema_validation(),
        "evidence_integrity": evidence_integrity(),
        "evaluator_verdict": {"passed": True, "failed_blockers": []},
        "advisory_checks": {
            "reviewer_recommends_ready": {
                "passed": True,
                "evidence": {"source": "reviewer_findings.md"},
            }
        },
    }


def seed_deterministic_run(run_dir: Path) -> None:
    skill = run_dir / "skill"
    refs = skill / "references"
    metadata = run_dir / "metadata"
    research = run_dir / "research" / "merged"
    transcripts = run_dir / "transcripts"
    for directory in (refs, metadata, research, transcripts):
        directory.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        "# Skill\n\n免责声明：不代表创作者本人。\n\n安全边界：不得冒充或克隆。\n",
        encoding="utf-8",
    )
    for name in ("persona.md", "topic_model.md", "script_style.md", "research_summary.md"):
        (refs / name).write_text(
            f"# {name}\n\nSynthetic deterministic quality content.\n",
            encoding="utf-8",
        )
    (refs / "persona.md").write_text(
        "# Persona\n\n免责声明：不代表创作者本人。安全边界：不得冒充或克隆。\n",
        encoding="utf-8",
    )
    (refs / "evidence_index.md").write_text(
        "# Evidence\n\n| Video ID | Finding |\n|---|---|\n| 190000000000000401 | fact |\n",
        encoding="utf-8",
    )
    (refs / "meta.json").write_text("{}\n", encoding="utf-8")
    write_json(
        run_dir / "input.json",
        {
            "run_format": run_diagnostics.RUN_FORMAT_NAME,
            "schema_version": run_diagnostics.RUN_FORMAT_SCHEMA_VERSION,
        },
    )
    write_json(run_dir / "config.snapshot.json", {"settings_schema_version": 2})
    write_json(run_dir / "workflow.plan.json", {"schema_version": 1})
    write_json(metadata / "provenance.json", {"schema_version": 1})
    for path in (
        metadata / "selected.json",
        metadata / "selected.compact.json",
        metadata / "creator_profile.json",
    ):
        path.write_text("{}\n", encoding="utf-8")
    (research / "summary.md").write_text(
        "# Research summary\n\nSynthetic deterministic summary.\n",
        encoding="utf-8",
    )
    (transcripts / "video-001.txt").write_text(
        "[00:00:00] Synthetic transcript.\n",
        encoding="utf-8",
    )


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def force_non_content_gates_ready(monkeypatch: pytest.MonkeyPatch) -> None:
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
    monkeypatch.setattr(
        creator_pipeline,
        "evaluate_stage_coverage",
        lambda *_args, **_kwargs: {
            "draft": {"passed": True},
            "ready": {"passed": True, "failed_stages": []},
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


def forced_content_readiness(
    *,
    schemas: dict[str, Any] | None = None,
    integrity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "ready_for_use": True,
        "checks": {},
        "schema_validation": schemas or schema_validation(),
        "evidence_integrity": integrity or evidence_integrity(),
        "evaluator_verdict": {"passed": True, "failed_blockers": []},
        "advisory_checks": {
            "reviewer_recommends_ready": {
                "passed": True,
                "evidence": {"source": "reviewer_findings.md"},
            }
        },
    }


def test_complete_factual_evaluation_passes_without_using_scorecard_as_verdict() -> None:
    evaluation = evaluation_suite()
    evaluation["scorecard"]["passed"] = False
    for case in evaluation["cases"]:
        case["passed"] = False

    report = evaluate_documents(evaluation=evaluation)

    assert report["passed"] is True
    assert all(check["passed"] for check in report["blocking_checks"].values())
    assert report["artifacts"]["evaluation_suite"]["declarations"] == {
        "case_passed_count": 0,
        "scorecard_passed": False,
    }


def test_setting_every_self_declared_passed_flag_cannot_complete_blank_cases() -> None:
    evaluation = evaluation_suite()
    for case in evaluation["cases"]:
        case["input"] = ""
        case["output"] = ""
        case["applied_persona_model_fields"] = []
        case["evidence_video_ids"] = []
        case["safety_rule_ids"] = []
        case["generic_ai_markers"] = []
        case["confidence"] = ""
        case["passed"] = True
    evaluation["scorecard"]["passed"] = True

    report = evaluate_documents(evaluation=evaluation)

    assert report["passed"] is False
    assert report["artifacts"]["evaluation_suite"]["declarations"][
        "scorecard_passed"
    ] is True
    assert report["blocking_checks"]["evaluation_cases_substantive"]["passed"] is False
    assert report["blocking_checks"]["evaluation_persona_fields_valid"]["passed"] is False
    assert report["blocking_checks"]["evaluation_evidence_or_safety_cited"]["passed"] is False
    assert report["blocking_checks"]["evaluation_confidence_declared"]["passed"] is False
    assert report["blocking_checks"]["boundary_response_safe"]["passed"] is False
    assert report["blocking_checks"]["style_critique_markers_present"]["passed"] is False


def test_evaluator_failure_evidence_is_bounded() -> None:
    reverse = reverse_identification()
    reverse["rows"] = [
        {
            "output_id": f"output-{index}",
            "creator_specific_markers": [f"creator-marker-{index}"],
            "generic_ai_markers": [],
            "persona_model_fields": ["missing_field"],
            "evidence_video_ids": [VIDEO_ID],
            "verdict": "not traceable",
        }
        for index in range(200)
    ]

    report = evaluate_documents(reverse=reverse)
    evidence = report["blocking_checks"]["reverse_persona_fields_valid"][
        "evidence"
    ]

    assert len(evidence["failed_pointers"]) <= 50
    assert evidence["failed_pointer_count"] == 200
    assert evidence["truncated"] is True


def test_draft_template_status_cannot_pass_with_completed_looking_content() -> None:
    evaluation = evaluation_suite()
    reverse = reverse_identification()
    evaluation["status"] = "draft_template"
    reverse["status"] = "draft_template"

    report = evaluate_documents(evaluation=evaluation, reverse=reverse)

    assert report["passed"] is False
    assert report["blocking_checks"]["evaluation_document_completed"] == {
        "passed": False,
        "evidence": {"status": "draft_template"},
    }
    assert report["blocking_checks"]["reverse_document_completed"] == {
        "passed": False,
        "evidence": {"status": "draft_template"},
    }
    assert report["failed_blockers"]
    assert all(item["evidence"] for item in report["failed_blockers"])


def test_boundary_case_requires_a_deterministic_safe_response() -> None:
    evaluation = evaluation_suite()
    boundary = next(case for case in evaluation["cases"] if case["name"] == "boundary_request")
    boundary["output"] = "好的，我会直接代替创作者本人发言。"
    boundary["passed"] = True
    evaluation["scorecard"]["passed"] = True

    report = evaluate_documents(evaluation=evaluation)

    blocker = report["blocking_checks"]["boundary_response_safe"]
    assert blocker["passed"] is False
    assert blocker["evidence"]["failed_pointers"] == ["/cases/4/output"]
    assert report["passed"] is False


def test_passed_false_forces_ready_and_commercial_delivery_false() -> None:
    inputs = ready_inputs()
    inputs["deterministic_checks"]["required_files"] = False

    outcome = quality_engine.compose_readiness_semantics(**inputs)

    assert outcome["passed"] is False
    assert outcome["ready_for_use"] is False
    assert outcome["commercial_delivery_ready"] is False
    blocker = outcome["blocking_checks"]["deterministic_pipeline_passed"]
    assert blocker == {
        "passed": False,
        "evidence": {"failed_checks": ["required_files"]},
    }


def test_reviewer_ready_is_advisory_and_cannot_override_schema_or_evidence() -> None:
    inputs = ready_inputs()
    inputs["schema_validation"] = schema_validation(valid=False)
    inputs["evidence_integrity"] = evidence_integrity(valid=False)

    outcome = quality_engine.compose_readiness_semantics(**inputs)

    assert outcome["passed"] is True
    assert outcome["advisory_checks"]["reviewer_recommends_ready"]["passed"] is True
    assert outcome["blocking_checks"]["schemas_valid"]["passed"] is False
    assert outcome["blocking_checks"]["evidence_integrity_valid"]["passed"] is False
    assert outcome["blocking_checks"]["evidence_integrity_valid"]["evidence"] == {
        "failed_checks": ["all_references_in_corpus", "corpus_available"],
        "error_counts": {
            "orphan_references": 1,
            "missing_references": 0,
            "duplicate_references": 0,
            "type_mismatches": 0,
        },
    }
    assert outcome["ready_for_use"] is False
    assert outcome["commercial_delivery_ready"] is False
    assert outcome["blocking_checks"]["schemas_valid"]["evidence"] == {
        "invalid_artifacts": [
            "evaluation_suite",
            "persona_model",
            "reverse_identification",
        ],
        "error_pointers": {
            "evaluation_suite": ["/status"],
            "persona_model": ["/status"],
            "reverse_identification": ["/status"],
        },
    }


def test_top_level_schema_blocker_evidence_is_bounded() -> None:
    inputs = ready_inputs()
    inputs["schema_validation"]["evaluation_suite"] = {
        "valid": False,
        "errors": [
            {"pointer": f"/cases/{index}/output"}
            for index in range(200)
        ],
    }

    outcome = quality_engine.compose_readiness_semantics(**inputs)
    evidence = outcome["blocking_checks"]["schemas_valid"]["evidence"]

    assert len(evidence["error_pointers"]["evaluation_suite"]) <= 50
    assert evidence["error_pointer_counts"] == {"evaluation_suite": 200}
    assert evidence["truncated_artifacts"] == ["evaluation_suite"]


def test_creator_quality_report_enforces_ready_implies_passed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    seed_deterministic_run(run_dir)
    (run_dir / "skill" / "SKILL.md").unlink()
    force_non_content_gates_ready(monkeypatch)
    monkeypatch.setattr(
        creator_pipeline,
        "creator_content_readiness",
        lambda *_args, **_kwargs: forced_content_readiness(),
    )

    report = creator_pipeline.creator_quality_check(run_dir)

    assert report["passed"] is False
    assert report["ready_for_use"] is False
    assert report["commercial_delivery_ready"] is False
    assert report["blocking_checks"]["deterministic_pipeline_passed"] == {
        "passed": False,
        "evidence": {"failed_checks": ["required_files"]},
    }


def test_creator_quality_report_keeps_reviewer_advisory_below_hard_blockers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    seed_deterministic_run(run_dir)
    force_non_content_gates_ready(monkeypatch)
    monkeypatch.setattr(
        creator_pipeline,
        "creator_content_readiness",
        lambda *_args, **_kwargs: forced_content_readiness(
            schemas=schema_validation(valid=False),
            integrity=evidence_integrity(valid=False),
        ),
    )

    report = creator_pipeline.creator_quality_check(run_dir)
    persisted = json.loads(
        (run_dir / "logs" / "creator_quality_report.json").read_text(
            encoding="utf-8"
        )
    )

    assert report["passed"] is True
    assert report["advisory_checks"]["reviewer_recommends_ready"]["passed"] is True
    assert report["blocking_checks"]["schemas_valid"]["passed"] is False
    assert report["blocking_checks"]["evidence_integrity_valid"]["passed"] is False
    assert report["ready_for_use"] is False
    assert report["commercial_delivery_ready"] is False
    assert persisted["failed_blockers"] == report["failed_blockers"]


def test_run_evaluator_reads_current_documents_without_copying_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    seed_deterministic_run(run_dir)
    write_json(run_dir / "skill" / "references" / "persona_model.json", persona_model())
    write_json(
        run_dir / "research" / "reviews" / "evaluation_suite.json",
        evaluation_suite(),
    )
    write_json(
        run_dir / "research" / "reviews" / "reverse_identification.json",
        reverse_identification(),
    )

    monkeypatch.setattr(
        quality_engine.schema_validation,
        "validate_json_file",
        lambda _document, _schema, *, artifact: schema_validation()[artifact],
    )
    report = quality_engine.evaluate_run_evaluator(
        run_dir,
        evidence_integrity=evidence_integrity(),
    )

    assert report["passed"] is True
    assert report["document_status"] == {
        "persona_model": "loaded",
        "evaluation_suite": "loaded",
        "reverse_identification": "loaded",
    }
    assert {
        "persona_model",
        "persona_model_schema",
        "evaluation_suite",
        "evaluation_suite_schema",
        "reverse_identification",
        "reverse_identification_schema",
    } <= {item["role"] for item in report["computed_from"]}
    serialized = json.dumps(report, ensure_ascii=False)
    assert "This output applies the selected persona fields" not in serialized
    assert str(run_dir) not in serialized


def test_run_evaluator_accepts_utf8_bom_like_runtime_schema_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    documents = {
        run_dir / "skill" / "references" / "persona_model.json": persona_model(),
        run_dir / "research" / "reviews" / "evaluation_suite.json": evaluation_suite(),
        run_dir
        / "research"
        / "reviews"
        / "reverse_identification.json": reverse_identification(),
    }
    for path, payload in documents.items():
        write_json(path, payload)
        path.write_text(
            "\ufeff" + path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    monkeypatch.setattr(
        quality_engine.schema_validation,
        "validate_json_file",
        lambda _document, _schema, *, artifact: schema_validation()[artifact],
    )
    report = quality_engine.evaluate_run_evaluator(
        run_dir,
        evidence_integrity=evidence_integrity(),
    )

    assert report["passed"] is True
    assert set(report["document_status"].values()) == {"loaded"}


def test_run_evaluator_has_no_external_schema_verdict_override() -> None:
    assert "schema_validation_report" not in inspect.signature(
        quality_engine.evaluate_run_evaluator
    ).parameters


def test_missing_freshness_proof_is_a_host_refinement_blocker(
    tmp_path: Path,
) -> None:
    stats = creator_pipeline.host_refinement_stats(tmp_path)

    assert stats["checks"]["derived_artifacts_fresh"] is False


def test_reviewer_and_audit_recommendations_are_advisory_signals(
    tmp_path: Path,
) -> None:
    reviews = tmp_path / "research" / "reviews"
    reviews.mkdir(parents=True)
    reviewer_text = (
        "# Reviewer Findings\n\n"
        "所有 high / medium 问题均已逐项记录并处理。\n"
        "- 是否处理全部 high / medium 问题：是\n"
        "- 是否建议进入 `ready_for_use=true`：否\n\n"
        + "已完成复核记录。" * 80
    )
    audit_text = (
        "# Refinement Audit\n\n"
        "审计人：offline-reviewer\n审计时间：2026-07-15\n"
        "覆盖、深度、成品和安全项目均已逐项完成。\n"
        "- 是否建议 `ready_for_use=true`：否\n"
        "- 仍需补强：人工复核建议，不覆盖自动结果。\n\n"
        + "已完成审计记录。" * 80
    )
    (reviews / "reviewer_findings.md").write_text(reviewer_text, encoding="utf-8")
    (reviews / "refinement_audit.md").write_text(audit_text, encoding="utf-8")
    (reviews / "usage_probe.md").write_text(
        (
            "# Usage Probe\n\n"
            "输入候选：真实候选\n改写结果：真实改写\n"
            "待批评片段：真实片段\n选题：真实选题\n"
            "使用的 persona_model 字段：topic_models, expression_dna\n"
            "是否通过反向生成测试：否\n\n"
            + "已完成探针记录。" * 100
        ),
        encoding="utf-8",
    )

    stats = creator_pipeline.host_refinement_stats(
        tmp_path,
        evidence_integrity=evidence_integrity(),
        evaluator_verdict={
            "artifacts": {
                "evaluation_suite": {"passed": False},
                "reverse_identification": {"passed": False},
            }
        },
    )

    assert stats["checks"]["reviewer_findings_filled"] is True
    assert stats["checks"]["refinement_audit_filled"] is True
    assert stats["checks"]["usage_probe_filled"] is True
    assert stats["advisory_checks"]["usage_probe_declares_passed"] == {
        "passed": False,
        "evidence": {"source": "research/reviews/usage_probe.md"},
    }
    assert stats["advisory_checks"]["reviewer_recommends_ready"] == {
        "passed": False,
        "evidence": {"source": "research/reviews/reviewer_findings.md"},
    }
    assert stats["advisory_checks"]["audit_recommends_ready"] == {
        "passed": False,
        "evidence": {"source": "research/reviews/refinement_audit.md"},
    }


def test_text_quality_report_explains_blockers_and_advisories(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = {
        "passed": True,
        "ready_for_use": False,
        "commercial_delivery_ready": False,
        "checks": {"required_files": True},
        "content_readiness": {"checks": {"evaluator_verdict_passed": False}},
        "governance": {"checks": {}},
        "evidence_integrity": {"valid": True, "counts": {}},
        "freshness": {"fresh": True},
        "evaluator_verdict": {
            "passed": False,
            "failed_blockers": [{"id": "evaluation_cases_substantive"}],
        },
        "blocking_checks": {
            "schemas_valid": {
                "passed": False,
                "evidence": {
                    "invalid_artifacts": {
                        "evaluation_suite": ["/cases/0/output"]
                    }
                },
            }
        },
        "advisory_checks": {
            "reviewer_recommends_ready": {
                "passed": False,
                "evidence": {"source": "research/reviews/reviewer_findings.md"},
            }
        },
    }
    monkeypatch.setattr(creator_pipeline, "creator_quality_check", lambda _run: report)

    exit_code = creator_pipeline.command_quality_check(
        SimpleNamespace(run_dir="run", json=False, report_only=True)
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "EVALUATOR FAIL" in output
    assert "BLOCKING FAIL schemas_valid" in output
    assert "/cases/0/output" in output
    assert "ADVISORY WARN reviewer_recommends_ready" in output
    assert "research/reviews/reviewer_findings.md" in output
