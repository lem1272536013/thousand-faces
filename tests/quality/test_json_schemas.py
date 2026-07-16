"""Runtime JSON Schema validation contracts for host-refinement artifacts."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

import prepare_host_refinement
import schema_validation
import creator_pipeline


SCHEMA_URI = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_VERSION = "1.1.0"
VIDEO_IDS = [str(10**15 + index) for index in range(20)]


def completed_persona_model() -> dict[str, Any]:
    return {
        "version": "1.0",
        "status": "completed",
        "creator": "Schema test creator",
        "core_identity": "以可验证的实验、清晰的机制解释和明确的能力边界帮助普通人判断工具价值。" * 2,
        "topic_models": [
            {
                "name": f"topic-{index}",
                "definition": f"definition-{index}",
                "use_cases": ["case"],
                "evidence_ids": VIDEO_IDS[index : index + 2],
                "failure_modes": ["insufficient evidence"],
            }
            for index in range(5)
        ],
        "script_templates": [
            {
                "name": f"script-{index}",
                "use_cases": ["case"],
                "hook": "show the surprising result",
                "body": "explain the mechanism",
                "ending": "state the boundary",
                "failure_modes": ["generic conclusion"],
                "evidence_ids": [VIDEO_IDS[index]],
            }
            for index in range(4)
        ],
        "judgment_heuristics": [f"heuristic-{index}" for index in range(6)],
        "expression_dna": [f"expression-{index}" for index in range(6)],
        "anti_patterns": [f"anti-pattern-{index}" for index in range(5)],
        "safety_boundaries": [f"boundary-{index}" for index in range(4)],
        "evidence_anchors": [
            {"video_id": VIDEO_IDS[index], "role": f"role-{index}"}
            for index in range(15)
        ],
        "generation_protocol": {
            "field_order": [f"field-{index}" for index in range(5)],
            "task_routing": [
                {"task": f"task-{index}", "use_fields": ["topic_models", "evidence_anchors"]}
                for index in range(4)
            ],
            "evidence_policy": "High-confidence claims need explicit evidence.",
            "confidence_policy": "Downgrade conclusions when evidence is incomplete.",
        },
        "evaluation_cases": [
            {
                "name": f"case-{index}",
                "task": f"task-{index}",
                "expected_fields": ["topic_models", "evidence_anchors"],
                "pass_criteria": ["specific", "traceable"],
            }
            for index in range(6)
        ],
    }


def completed_evaluation_suite() -> dict[str, Any]:
    return {
        "status": "completed",
        "cases": [
            {
                "name": f"case-{index}",
                "task": f"task-{index}",
                "input": "real input",
                "applied_persona_model_fields": ["topic_models", "evidence_anchors"],
                "output": "specific output",
                "evidence_video_ids": [VIDEO_IDS[index]],
                "safety_rule_ids": [],
                "generic_ai_markers": [],
                "confidence": "high",
                "passed": True,
            }
            for index in range(6)
        ],
        "scorecard": {
            "all_cases_completed": True,
            "persona_model_fields_cited": True,
            "evidence_or_rule_cited": True,
            "generic_ai_markers_reviewed": True,
            "passed": True,
            "remaining_gaps": [],
        },
    }


def completed_reverse_identification() -> dict[str, Any]:
    return {
        "status": "completed",
        "rows": [
            {
                "output_id": f"output-{index}",
                "creator_specific_markers": [f"specific-{index}"],
                "generic_ai_markers": [f"generic-{index}"],
                "persona_model_fields": ["expression_dna"],
                "evidence_video_ids": [VIDEO_IDS[index]],
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
            "remaining_gaps": [],
        },
    }


def schemas() -> dict[str, dict[str, Any]]:
    return {
        "persona_model": prepare_host_refinement.build_persona_model_schema(),
        "evaluation_suite": prepare_host_refinement.build_evaluation_suite_schema(),
        "reverse_identification": prepare_host_refinement.build_reverse_identification_schema(),
    }


def assert_all_object_schemas_are_strict(node: object) -> None:
    if isinstance(node, dict):
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False, node.get("title", node)
        for value in node.values():
            assert_all_object_schemas_are_strict(value)
    elif isinstance(node, list):
        for value in node:
            assert_all_object_schemas_are_strict(value)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def seed_schema_documents(
    run_dir: Path,
    *,
    persona: dict[str, Any],
    evaluation: dict[str, Any],
    reverse_identification: dict[str, Any],
) -> Path:
    skill_dir = run_dir / "skill"
    refs = skill_dir / "references"
    reviews = run_dir / "research" / "reviews"
    for name in ("persona.md", "topic_model.md", "script_style.md", "evidence_index.md"):
        path = refs / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {name}\n\nSchema validation test content.\n", encoding="utf-8")
    write_json(refs / "persona_model.schema.json", prepare_host_refinement.build_persona_model_schema())
    write_json(refs / "persona_model.json", persona)
    write_json(reviews / "evaluation_suite.schema.json", prepare_host_refinement.build_evaluation_suite_schema())
    write_json(reviews / "evaluation_suite.json", evaluation)
    write_json(
        reviews / "reverse_identification.schema.json",
        prepare_host_refinement.build_reverse_identification_schema(),
    )
    write_json(reviews / "reverse_identification.json", reverse_identification)
    return skill_dir


def test_generated_schemas_are_versioned_draft_2020_12_and_strict() -> None:
    for name, schema in schemas().items():
        Draft202012Validator.check_schema(schema)
        assert schema["$schema"] == SCHEMA_URI
        assert schema["x-schema-version"] == SCHEMA_VERSION
        assert schema["$id"].endswith(f"/{name}/{SCHEMA_VERSION}")
        assert_all_object_schemas_are_strict(schema)


def test_generated_draft_templates_validate_but_are_not_completed() -> None:
    documents = {
        "persona_model": prepare_host_refinement.build_persona_model_template({}),
        "evaluation_suite": prepare_host_refinement.build_evaluation_suite_json_template(),
        "reverse_identification": prepare_host_refinement.build_reverse_identification_json_template(),
    }

    for name, document in documents.items():
        result = schema_validation.validate_document(document, schemas()[name], artifact=name)
        assert result["valid"] is True, result
        assert document["status"] == "draft_template"


def test_completed_documents_validate_against_completed_branch() -> None:
    documents = {
        "persona_model": completed_persona_model(),
        "evaluation_suite": completed_evaluation_suite(),
        "reverse_identification": completed_reverse_identification(),
    }

    for name, document in documents.items():
        result = schema_validation.validate_document(document, schemas()[name], artifact=name)
        assert result["valid"] is True, result
        assert result["status"] == "completed"


def test_self_declared_scorecards_are_typed_declarations_not_schema_verdicts() -> None:
    evaluation = completed_evaluation_suite()
    for case in evaluation["cases"]:
        case["passed"] = False
    for field in (
        "all_cases_completed",
        "persona_model_fields_cited",
        "evidence_or_rule_cited",
        "generic_ai_markers_reviewed",
        "passed",
    ):
        evaluation["scorecard"][field] = False

    reverse = completed_reverse_identification()
    reverse["scorecard"].update(
        {
            "creator_specific_marker_count": 0,
            "generic_ai_marker_count": 0,
            "fields_traceable": False,
            "evidence_traceable": False,
            "passed": False,
        }
    )

    evaluation_result = schema_validation.validate_document(
        evaluation,
        prepare_host_refinement.build_evaluation_suite_schema(),
        artifact="evaluation_suite",
    )
    reverse_result = schema_validation.validate_document(
        reverse,
        prepare_host_refinement.build_reverse_identification_schema(),
        artifact="reverse_identification",
    )

    assert evaluation_result["valid"] is True, evaluation_result
    assert reverse_result["valid"] is True, reverse_result


@pytest.mark.parametrize(
    ("mutation", "expected_pointer"),
    [
        (lambda payload: payload.pop("core_identity"), "/core_identity"),
        (lambda payload: payload.__setitem__("status", 7), "/status"),
        (lambda payload: payload.__setitem__("unexpected", True), "/unexpected"),
        (lambda payload: payload.__setitem__("status", "ready"), "/status"),
    ],
    ids=["missing-field", "wrong-type", "extra-field", "illegal-status"],
)
def test_invalid_documents_fail_with_short_json_pointer_diagnostics(
    mutation: Any,
    expected_pointer: str,
) -> None:
    document = deepcopy(completed_persona_model())
    mutation(document)

    result = schema_validation.validate_document(
        document,
        prepare_host_refinement.build_persona_model_schema(),
        artifact="persona_model",
    )

    assert result["valid"] is False
    assert any(error["pointer"] == expected_pointer for error in result["errors"]), result
    assert all("\n" not in error["message"] and len(error["message"]) <= 240 for error in result["errors"])


def test_jsonschema_is_a_pinned_runtime_dependency(project_root: Path) -> None:
    runtime_requirements = (project_root / "requirements.txt").read_text(encoding="utf-8")

    assert "jsonschema>=4.23.0,<5.0.0" in runtime_requirements


def test_validation_messages_do_not_copy_invalid_document_values() -> None:
    document = completed_persona_model()
    document["core_identity"] = {"private": "SCHEMA_VALUE_MUST_NOT_BE_LOGGED"}

    result = schema_validation.validate_document(
        document,
        prepare_host_refinement.build_persona_model_schema(),
        artifact="persona_model",
    )

    assert result["valid"] is False
    assert any(error["pointer"] == "/core_identity" for error in result["errors"])
    assert "SCHEMA_VALUE_MUST_NOT_BE_LOGGED" not in json.dumps(result, ensure_ascii=False)


def test_schema_file_version_is_validated_instead_of_file_size(tmp_path: Path) -> None:
    schema = prepare_host_refinement.build_persona_model_schema()
    schema.pop("x-schema-version")
    schema["$comment"] = "large but stale schema " * 20
    schema_path = tmp_path / "persona_model.schema.json"
    model_path = tmp_path / "persona_model.json"
    write_json(schema_path, schema)
    write_json(model_path, completed_persona_model())

    result = schema_validation.validate_json_file(
        model_path,
        schema_path,
        artifact="persona_model",
    )

    assert schema_path.stat().st_size > 100
    assert result["schema_valid"] is False
    assert result["valid"] is False
    assert result["errors"] == [
        {
            "pointer": "/x-schema-version",
            "keyword": "schema_version",
            "message": f"schema version must be {SCHEMA_VERSION}",
        }
    ]


def test_content_readiness_reports_pointer_errors_for_all_three_documents(tmp_path: Path) -> None:
    persona = completed_persona_model()
    persona["unexpected"] = True
    evaluation = completed_evaluation_suite()
    evaluation["cases"][0]["passed"] = "yes"
    reverse_identification = completed_reverse_identification()
    reverse_identification["status"] = "ready"
    skill_dir = seed_schema_documents(
        tmp_path,
        persona=persona,
        evaluation=evaluation,
        reverse_identification=reverse_identification,
    )

    readiness = creator_pipeline.creator_content_readiness(skill_dir, tmp_path)

    validations = readiness["schema_validation"]
    assert validations["persona_model"]["valid"] is False
    assert any(error["pointer"] == "/unexpected" for error in validations["persona_model"]["errors"])
    assert validations["evaluation_suite"]["valid"] is False
    assert any(
        error["pointer"] == "/cases/0/passed"
        for error in validations["evaluation_suite"]["errors"]
    )
    assert validations["reverse_identification"]["valid"] is False
    assert any(
        error["pointer"] == "/status"
        for error in validations["reverse_identification"]["errors"]
    )
    assert readiness["persona_model"]["checks"]["model_schema_valid"] is False
    assert readiness["host_refinement"]["checks"]["evaluation_suite_json_schema_valid"] is False
    assert readiness["host_refinement"]["checks"]["reverse_identification_json_schema_valid"] is False
    assert readiness["ready_for_use"] is False


def test_valid_templates_are_schema_valid_but_cannot_be_ready(tmp_path: Path) -> None:
    skill_dir = seed_schema_documents(
        tmp_path,
        persona=prepare_host_refinement.build_persona_model_template({}),
        evaluation=prepare_host_refinement.build_evaluation_suite_json_template(),
        reverse_identification=prepare_host_refinement.build_reverse_identification_json_template(),
    )

    readiness = creator_pipeline.creator_content_readiness(skill_dir, tmp_path)

    assert all(result["valid"] for result in readiness["schema_validation"].values())
    assert readiness["persona_model"]["checks"]["not_template"] is False
    assert readiness["host_refinement"]["checks"]["evaluation_suite_json_filled"] is False
    assert readiness["host_refinement"]["checks"]["reverse_identification_json_filled"] is False
    assert readiness["ready_for_use"] is False
