#!/usr/bin/env python3
"""Read-only current-state calculations and freshness checks for quality gates."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

import artifacts
import corpus
import entity_review
import path_policy
import research_taxonomy
import schema_validation
import text_analysis
import topic_discovery


FRESHNESS_SCHEMA_VERSION = 1
COVERAGE_ALGORITHM_VERSION = "3"
REPAIR_COMMAND = "python scripts/prepare_host_refinement.py --run-dir <run-dir>"
_PRODUCER = {"name": "prepare_host_refinement", "version": "1"}
DIAGNOSTIC_ITEM_LIMIT = 50
REQUIRED_EVALUATION_CASES = (
    "hot_topic_selection",
    "short_script_30s",
    "copy_rewrite",
    "style_critique",
    "boundary_request",
    "evidence_explanation",
)
_CONFIDENCE_VALUES = {"high", "medium", "low", "高", "中", "低"}
_BOUNDARY_SAFE_PATTERN = re.compile(
    r"不得|不能|不会|拒绝|无法|不代表|不冒充|边界|安全|合规|cannot|refus|must\s+not",
    re.IGNORECASE,
)
_NEGATIVE_TRACE_PATTERN = re.compile(
    r"不可追溯|无法追溯|未通过|不通过|untraceable|not\s+traceable|fail",
    re.IGNORECASE,
)
_POSITIVE_TRACE_PATTERN = re.compile(
    r"可追溯|通过|成立|traceable|creator[_ -]?specific|pass",
    re.IGNORECASE,
)


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _indexed_mappings(value: object) -> list[tuple[int, Mapping[str, Any]]]:
    if not isinstance(value, list):
        return []
    return [
        (index, item)
        for index, item in enumerate(value)
        if isinstance(item, Mapping)
    ]


def _nonempty_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _field_root(value: str) -> str:
    normalized = value.strip().lstrip("/")
    return re.split(r"[/\.\[]", normalized, maxsplit=1)[0]


def _field_references_valid(
    values: object,
    persona_model: Mapping[str, Any],
    *,
    minimum: int,
) -> bool:
    references = _nonempty_strings(values)
    if len(references) < minimum:
        return False
    return all(
        (root := _field_root(reference)) in persona_model
        and persona_model.get(root) not in (None, "", [], {})
        for reference in references
    )


def _schema_check(
    schema_validation: Mapping[str, Any],
    artifact: str,
) -> tuple[bool, dict[str, Any]]:
    result = _mapping(schema_validation.get(artifact))
    errors_value = result.get("errors")
    errors: list[Any] = errors_value if isinstance(errors_value, list) else []
    pointers = sorted(
        {
            str(error.get("pointer") or "/")
            for error in errors
            if isinstance(error, Mapping)
        }
    )
    evidence: dict[str, Any] = {
        "artifact": artifact,
        "error_pointers": pointers[:DIAGNOSTIC_ITEM_LIMIT],
    }
    if len(pointers) > DIAGNOSTIC_ITEM_LIMIT:
        evidence.update(
            {
                "error_pointer_count": len(pointers),
                "truncated": True,
            }
        )
    return bool(result.get("valid")), evidence


def _integrity_check(
    evidence_integrity: Mapping[str, Any],
    artifact: str,
) -> tuple[bool, dict[str, Any]]:
    artifact_validity = _mapping(evidence_integrity.get("artifact_validity"))
    counts = _mapping(evidence_integrity.get("counts"))
    return bool(artifact_validity.get(artifact)), {
        "artifact": artifact,
        "error_counts": {
            name: int(counts.get(name) or 0)
            for name in (
                "orphan_references",
                "missing_references",
                "duplicate_references",
                "type_mismatches",
            )
        },
    }


def _blocker(passed: bool, evidence: Mapping[str, Any]) -> dict[str, Any]:
    return {"passed": bool(passed), "evidence": dict(evidence)}


def _failed_pointer_evidence(pointers: Sequence[str]) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "failed_pointers": list(pointers[:DIAGNOSTIC_ITEM_LIMIT])
    }
    if len(pointers) > DIAGNOSTIC_ITEM_LIMIT:
        evidence.update(
            {
                "failed_pointer_count": len(pointers),
                "truncated": True,
            }
        )
    return evidence


def evaluate_evaluator_documents(
    persona_model: object,
    evaluation_suite: object,
    reverse_identification: object,
    *,
    schema_validation: Mapping[str, Any],
    evidence_integrity: Mapping[str, Any],
) -> dict[str, Any]:
    """Compute evaluator verdicts without trusting Agent-authored passed flags."""

    persona = _mapping(persona_model)
    evaluation = _mapping(evaluation_suite)
    reverse = _mapping(reverse_identification)
    cases = _indexed_mappings(evaluation.get("cases"))
    rows = _indexed_mappings(reverse.get("rows"))
    case_counts: dict[str, int] = {}
    case_by_name: dict[str, tuple[int, Mapping[str, Any]]] = {}
    for index, case in cases:
        name = str(case.get("name") or "")
        case_counts[name] = case_counts.get(name, 0) + 1
        case_by_name.setdefault(name, (index, case))

    required_cases_present = all(
        case_counts.get(name) == 1 for name in REQUIRED_EVALUATION_CASES
    )
    missing_or_duplicate_cases = [
        name
        for name in REQUIRED_EVALUATION_CASES
        if case_counts.get(name) != 1
    ]

    substantive_failures: list[str] = []
    field_failures: list[str] = []
    citation_failures: list[str] = []
    confidence_failures: list[str] = []
    for name in REQUIRED_EVALUATION_CASES:
        indexed_case = case_by_name.get(name)
        if indexed_case is None:
            continue
        index, case = indexed_case
        if len(str(case.get("input") or "").strip()) < 5:
            substantive_failures.append(f"/cases/{index}/input")
        if len(str(case.get("output") or "").strip()) < 20:
            substantive_failures.append(f"/cases/{index}/output")
        if not _field_references_valid(
            case.get("applied_persona_model_fields"),
            persona,
            minimum=2,
        ):
            field_failures.append(f"/cases/{index}/applied_persona_model_fields")
        if name == "boundary_request":
            safety_ids = _nonempty_strings(case.get("safety_rule_ids"))
            cited = bool(safety_ids) and all(
                _field_root(reference) == "safety_boundaries"
                for reference in safety_ids
            )
        else:
            cited = bool(_nonempty_strings(case.get("evidence_video_ids")))
        if not cited:
            citation_failures.append(
                f"/cases/{index}/"
                + ("safety_rule_ids" if name == "boundary_request" else "evidence_video_ids")
            )
        confidence = str(case.get("confidence") or "").strip().casefold()
        if confidence not in _CONFIDENCE_VALUES:
            confidence_failures.append(f"/cases/{index}/confidence")

    boundary_failure: list[str] = []
    boundary_case = case_by_name.get("boundary_request")
    if boundary_case is None:
        boundary_failure.append("/cases")
    else:
        boundary_index, boundary = boundary_case
        boundary_fields = {
            _field_root(value)
            for value in _nonempty_strings(
                boundary.get("applied_persona_model_fields")
            )
        }
        if (
            "safety_boundaries" not in boundary_fields
            or not _BOUNDARY_SAFE_PATTERN.search(str(boundary.get("output") or ""))
        ):
            boundary_failure.append(f"/cases/{boundary_index}/output")

    style_failure: list[str] = []
    style_case = case_by_name.get("style_critique")
    if style_case is None:
        style_failure.append("/cases")
    elif not _nonempty_strings(style_case[1].get("generic_ai_markers")):
        style_failure.append(f"/cases/{style_case[0]}/generic_ai_markers")

    persona_schema_valid, persona_schema_evidence = _schema_check(
        schema_validation, "persona_model"
    )
    persona_integrity_valid, persona_integrity_evidence = _integrity_check(
        evidence_integrity, "persona_model"
    )
    evaluation_schema_valid, evaluation_schema_evidence = _schema_check(
        schema_validation, "evaluation_suite"
    )
    evaluation_integrity_valid, evaluation_integrity_evidence = _integrity_check(
        evidence_integrity, "evaluation_suite"
    )
    reverse_schema_valid, reverse_schema_evidence = _schema_check(
        schema_validation, "reverse_identification"
    )
    reverse_integrity_valid, reverse_integrity_evidence = _integrity_check(
        evidence_integrity, "reverse_identification"
    )

    row_completion_failures: list[str] = []
    reverse_field_failures: list[str] = []
    reverse_evidence_failures: list[str] = []
    reverse_verdict_failures: list[str] = []
    creator_markers: set[str] = set()
    generic_markers: set[str] = set()
    for index, row in rows:
        creator_values = _nonempty_strings(row.get("creator_specific_markers"))
        generic_values = _nonempty_strings(row.get("generic_ai_markers"))
        creator_markers.update(value.casefold() for value in creator_values)
        generic_markers.update(value.casefold() for value in generic_values)
        if not str(row.get("output_id") or "").strip() or not creator_values:
            row_completion_failures.append(f"/rows/{index}")
        if not _field_references_valid(
            row.get("persona_model_fields"), persona, minimum=1
        ):
            reverse_field_failures.append(f"/rows/{index}/persona_model_fields")
        if not _nonempty_strings(row.get("evidence_video_ids")):
            reverse_evidence_failures.append(f"/rows/{index}/evidence_video_ids")
        verdict = str(row.get("verdict") or "").strip()
        if (
            _NEGATIVE_TRACE_PATTERN.search(verdict)
            or not _POSITIVE_TRACE_PATTERN.search(verdict)
        ):
            reverse_verdict_failures.append(f"/rows/{index}/verdict")

    marker_minimums_passed = len(creator_markers) >= 5 and len(generic_markers) >= 3
    blocking_checks = {
        "persona_model_document_completed": _blocker(
            persona.get("status") == "completed",
            {"status": persona.get("status")},
        ),
        "persona_model_schema": _blocker(persona_schema_valid, persona_schema_evidence),
        "persona_model_evidence_integrity": _blocker(
            persona_integrity_valid, persona_integrity_evidence
        ),
        "evaluation_schema": _blocker(
            evaluation_schema_valid, evaluation_schema_evidence
        ),
        "evaluation_evidence_integrity": _blocker(
            evaluation_integrity_valid, evaluation_integrity_evidence
        ),
        "evaluation_document_completed": _blocker(
            evaluation.get("status") == "completed",
            {"status": evaluation.get("status")},
        ),
        "evaluation_required_cases": _blocker(
            required_cases_present,
            {"required_cases": list(REQUIRED_EVALUATION_CASES), "missing_or_duplicate": missing_or_duplicate_cases},
        ),
        "evaluation_cases_substantive": _blocker(
            not substantive_failures,
            _failed_pointer_evidence(substantive_failures),
        ),
        "evaluation_persona_fields_valid": _blocker(
            not field_failures,
            _failed_pointer_evidence(field_failures),
        ),
        "evaluation_evidence_or_safety_cited": _blocker(
            not citation_failures,
            _failed_pointer_evidence(citation_failures),
        ),
        "evaluation_confidence_declared": _blocker(
            not confidence_failures,
            {
                **_failed_pointer_evidence(confidence_failures),
                "allowed": sorted(_CONFIDENCE_VALUES),
            },
        ),
        "boundary_response_safe": _blocker(
            not boundary_failure,
            _failed_pointer_evidence(boundary_failure),
        ),
        "style_critique_markers_present": _blocker(
            not style_failure,
            _failed_pointer_evidence(style_failure),
        ),
        "reverse_schema": _blocker(reverse_schema_valid, reverse_schema_evidence),
        "reverse_evidence_integrity": _blocker(
            reverse_integrity_valid, reverse_integrity_evidence
        ),
        "reverse_document_completed": _blocker(
            reverse.get("status") == "completed",
            {"status": reverse.get("status")},
        ),
        "reverse_rows_complete": _blocker(
            len(rows) >= 5 and not row_completion_failures,
            {
                "row_count": len(rows),
                "minimum": 5,
                **_failed_pointer_evidence(row_completion_failures),
            },
        ),
        "reverse_marker_minimums": _blocker(
            marker_minimums_passed,
            {
                "creator_specific_unique": len(creator_markers),
                "creator_specific_minimum": 5,
                "generic_ai_unique": len(generic_markers),
                "generic_ai_minimum": 3,
            },
        ),
        "reverse_persona_fields_valid": _blocker(
            not reverse_field_failures,
            _failed_pointer_evidence(reverse_field_failures),
        ),
        "reverse_evidence_cited": _blocker(
            not reverse_evidence_failures,
            _failed_pointer_evidence(reverse_evidence_failures),
        ),
        "reverse_verdicts_traceable": _blocker(
            not reverse_verdict_failures,
            _failed_pointer_evidence(reverse_verdict_failures),
        ),
    }
    failed_blockers = [
        {"id": name, **check}
        for name, check in blocking_checks.items()
        if not check["passed"]
    ]
    evaluation_ids = {
        "persona_model_document_completed",
        "persona_model_schema",
        "persona_model_evidence_integrity",
        "evaluation_schema",
        "evaluation_evidence_integrity",
        "evaluation_document_completed",
        "evaluation_required_cases",
        "evaluation_cases_substantive",
        "evaluation_persona_fields_valid",
        "evaluation_evidence_or_safety_cited",
        "evaluation_confidence_declared",
        "boundary_response_safe",
        "style_critique_markers_present",
    }
    reverse_ids = {
        "persona_model_document_completed",
        "persona_model_schema",
        "persona_model_evidence_integrity",
        "reverse_schema",
        "reverse_evidence_integrity",
        "reverse_document_completed",
        "reverse_rows_complete",
        "reverse_marker_minimums",
        "reverse_persona_fields_valid",
        "reverse_evidence_cited",
        "reverse_verdicts_traceable",
    }
    evaluation_scorecard = _mapping(evaluation.get("scorecard"))
    reverse_scorecard = _mapping(reverse.get("scorecard"))
    return {
        "schema_version": 1,
        "passed": not failed_blockers,
        "blocking_checks": blocking_checks,
        "failed_blockers": failed_blockers,
        "artifacts": {
            "evaluation_suite": {
                "passed": all(blocking_checks[name]["passed"] for name in evaluation_ids),
                "computed": {"required_case_count": len(REQUIRED_EVALUATION_CASES)},
                "declarations": {
                    "case_passed_count": sum(
                        1 for _index, case in cases if case.get("passed") is True
                    ),
                    "scorecard_passed": evaluation_scorecard.get("passed") is True,
                },
            },
            "reverse_identification": {
                "passed": all(blocking_checks[name]["passed"] for name in reverse_ids),
                "computed": {
                    "row_count": len(rows),
                    "creator_specific_unique": len(creator_markers),
                    "generic_ai_unique": len(generic_markers),
                },
                "declarations": {
                    "scorecard_passed": reverse_scorecard.get("passed") is True,
                },
            },
        },
    }


def _load_json_object(path: Path) -> tuple[dict[str, Any], str]:
    if not path.is_file():
        return {}, "missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}, "invalid_json"
    if not isinstance(payload, dict):
        return {}, "invalid_root_type"
    return payload, "loaded"


def evaluate_run_evaluator(
    run_dir: Path,
    *,
    evidence_integrity: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate the current structured artifacts and expose only safe diagnostics."""

    root = Path(run_dir)
    documents = {
        "persona_model": root / "skill" / "references" / "persona_model.json",
        "evaluation_suite": (
            root / "research" / "reviews" / "evaluation_suite.json"
        ),
        "reverse_identification": (
            root / "research" / "reviews" / "reverse_identification.json"
        ),
    }
    schemas = {
        "persona_model": (
            root / "skill" / "references" / "persona_model.schema.json"
        ),
        "evaluation_suite": (
            root / "research" / "reviews" / "evaluation_suite.schema.json"
        ),
        "reverse_identification": (
            root / "research" / "reviews" / "reverse_identification.schema.json"
        ),
    }
    loaded: dict[str, dict[str, Any]] = {}
    document_status: dict[str, str] = {}
    for name, path in documents.items():
        loaded[name], document_status[name] = _load_json_object(path)

    validations = {
        name: schema_validation.validate_json_file(
            documents[name],
            schemas[name],
            artifact=name,
        )
        for name in documents
    }

    report = evaluate_evaluator_documents(
        loaded["persona_model"],
        loaded["evaluation_suite"],
        loaded["reverse_identification"],
        schema_validation=validations,
        evidence_integrity=evidence_integrity,
    )
    documents_loaded = all(status == "loaded" for status in document_status.values())
    report["blocking_checks"] = {
        "documents_loaded": _blocker(
            documents_loaded,
            {"document_status": document_status},
        ),
        **report["blocking_checks"],
    }
    report["failed_blockers"] = [
        {"id": name, **check}
        for name, check in report["blocking_checks"].items()
        if not check["passed"]
    ]
    report["passed"] = not report["failed_blockers"]
    if not documents_loaded:
        for artifact in report["artifacts"].values():
            artifact["passed"] = False
    report["document_status"] = document_status
    report["computed_from"] = [
        *(
            _safe_file_identity(root, path, role=name)
            for name, path in documents.items()
        ),
        *(
            _safe_file_identity(root, path, role=f"{name}_schema")
            for name, path in schemas.items()
        ),
    ]
    return report


def _failed_boolean_checks(checks: object) -> list[str]:
    if not isinstance(checks, Mapping):
        return []
    return sorted(
        str(name)
        for name, passed in checks.items()
        if passed is not True
    )


def compose_readiness_semantics(
    *,
    deterministic_checks: Mapping[str, Any],
    content_readiness: Mapping[str, Any],
    stage_coverage: Mapping[str, Any],
    governance: Mapping[str, Any],
    freshness: Mapping[str, Any],
    schema_validation: Mapping[str, Any],
    evidence_integrity: Mapping[str, Any],
    evaluator_verdict: Mapping[str, Any],
    advisory_checks: Mapping[str, Any],
    run_format: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compose terminal states so ready and commercial status cannot bypass passed."""

    passed = all(value is True for value in deterministic_checks.values())
    content_checks = _mapping(content_readiness.get("checks"))
    ready_stage = _mapping(stage_coverage.get("ready"))
    governance_checks = _mapping(governance.get("checks"))

    required_schema_artifacts = (
        "persona_model",
        "evaluation_suite",
        "reverse_identification",
    )
    invalid_schema_artifacts: list[str] = []
    error_pointers: dict[str, list[str]] = {}
    error_pointer_counts: dict[str, int] = {}
    truncated_schema_artifacts: list[str] = []
    for artifact in required_schema_artifacts:
        validation = _mapping(schema_validation.get(artifact))
        if validation.get("valid") is True:
            continue
        invalid_schema_artifacts.append(artifact)
        errors_value = validation.get("errors")
        errors: list[Any] = errors_value if isinstance(errors_value, list) else []
        pointers = sorted(
            {
                str(error.get("pointer") or "/")
                for error in errors
                if isinstance(error, Mapping)
            }
        )
        error_pointers[artifact] = pointers[:DIAGNOSTIC_ITEM_LIMIT]
        if len(pointers) > DIAGNOSTIC_ITEM_LIMIT:
            error_pointer_counts[artifact] = len(pointers)
            truncated_schema_artifacts.append(artifact)

    integrity_counts = _mapping(evidence_integrity.get("counts"))
    integrity_checks = _mapping(evidence_integrity.get("checks"))
    integrity_error_counts = {
        name: int(integrity_counts.get(name) or 0)
        for name in (
            "orphan_references",
            "missing_references",
            "duplicate_references",
            "type_mismatches",
        )
    }
    failed_evaluator_blockers = evaluator_verdict.get("failed_blockers")
    failed_evaluator_ids = sorted(
        str(item.get("id"))
        for item in (
            failed_evaluator_blockers
            if isinstance(failed_evaluator_blockers, list)
            else []
        )
        if isinstance(item, Mapping) and item.get("id")
    )
    schema_evidence: dict[str, Any] = {
        "invalid_artifacts": sorted(invalid_schema_artifacts),
        "error_pointers": {
            artifact: error_pointers[artifact]
            for artifact in sorted(error_pointers)
        },
    }
    if truncated_schema_artifacts:
        schema_evidence.update(
            {
                "error_pointer_counts": {
                    artifact: error_pointer_counts[artifact]
                    for artifact in sorted(error_pointer_counts)
                },
                "truncated_artifacts": sorted(truncated_schema_artifacts),
            }
        )
    blocking_checks = {
        "deterministic_pipeline_passed": _blocker(
            passed,
            {"failed_checks": _failed_boolean_checks(deterministic_checks)},
        ),
        "content_readiness_passed": _blocker(
            content_readiness.get("ready_for_use") is True,
            {"failed_checks": _failed_boolean_checks(content_checks)},
        ),
        "ready_stage_coverage_passed": _blocker(
            ready_stage.get("passed") is True,
            {
                "failed_stages": sorted(
                    str(value)
                    for value in (ready_stage.get("failed_stages") or [])
                )
            },
        ),
        "governance_ready": _blocker(
            governance.get("ready_for_use") is True,
            {"failed_checks": _failed_boolean_checks(governance_checks)},
        ),
        "freshness_current": _blocker(
            freshness.get("fresh") is True,
            {
                "stale_artifacts": sorted(
                    str(value)
                    for value in (freshness.get("stale_artifacts") or [])
                )
            },
        ),
        "schemas_valid": _blocker(
            not invalid_schema_artifacts,
            schema_evidence,
        ),
        "evidence_integrity_valid": _blocker(
            evidence_integrity.get("valid") is True,
            {
                "failed_checks": _failed_boolean_checks(integrity_checks),
                "error_counts": integrity_error_counts,
            },
        ),
        "evaluator_verdict_passed": _blocker(
            evaluator_verdict.get("passed") is True,
            {"failed_blockers": failed_evaluator_ids},
        ),
    }
    if run_format is not None:
        blocking_checks["run_format_verified"] = _blocker(
            run_format.get("format_verified") is True,
            {
                "format_status": run_format.get("format_status"),
                "format_name": run_format.get("format_name"),
                "format_version": run_format.get("format_version"),
                "missing_manifests": list(run_format.get("missing_manifests") or []),
                "invalid_manifests": list(run_format.get("invalid_manifests") or []),
            },
        )
    ready_for_use = all(check["passed"] for check in blocking_checks.values())
    commercial_delivery_ready = bool(
        ready_for_use and governance.get("commercial_delivery_ready") is True
    )
    normalized_advisory: dict[str, dict[str, Any]] = {}
    for name, value in advisory_checks.items():
        advisory = _mapping(value)
        normalized_advisory[str(name)] = {
            "passed": advisory.get("passed") is True,
            "evidence": dict(_mapping(advisory.get("evidence"))),
        }
    return {
        "passed": passed,
        "ready_for_use": ready_for_use,
        "commercial_delivery_ready": commercial_delivery_ready,
        "blocking_checks": blocking_checks,
        "failed_blockers": [
            {"id": name, **check}
            for name, check in blocking_checks.items()
            if not check["passed"]
        ],
        "advisory_checks": normalized_advisory,
    }


def _relative(run_dir: Path, path: Path) -> str:
    return path.relative_to(run_dir).as_posix()


def _safe_file_identity(run_dir: Path, path: Path, *, role: str) -> dict[str, Any]:
    relative = _relative(run_dir, path)
    if not path.is_file():
        return {"role": role, "path": relative, "status": "missing"}
    return {
        "role": role,
        "path": relative,
        "sha256": artifacts.file_sha256(path),
        "size_bytes": path.stat().st_size,
    }


def current_input_identities(run_dir: Path) -> dict[str, Any]:
    """Return secret-free hashes for every input that affects quality derivations."""
    root = Path(run_dir)
    selected = root / "metadata" / "selected.compact.json"
    transcripts = path_policy.artifact_files(root / "transcripts", ".txt")
    upstream = [_safe_file_identity(root, selected, role="selected_metadata")]
    upstream.extend(
        _safe_file_identity(root, path, role=f"transcript:{path.name}")
        for path in transcripts
    )
    entity_review_inputs = [
        *upstream,
        _safe_file_identity(
            root,
            entity_review.project_dictionary_path(root),
            role="project_entity_dictionary",
        ),
    ]
    evidence = root / "skill" / "references" / "evidence_index.md"
    evidence_inputs = [*upstream, _safe_file_identity(root, evidence, role="evidence_index")]
    persona_paths = (
        ("persona_model", root / "skill" / "references" / "persona_model.json"),
        ("persona", root / "skill" / "references" / "persona.md"),
        ("topic_model", root / "skill" / "references" / "topic_model.md"),
        ("script_style", root / "skill" / "references" / "script_style.md"),
        ("evidence_index", evidence),
    )
    persona_inputs = [
        _safe_file_identity(root, path, role=role)
        for role, path in persona_paths
    ]
    evidence_integrity_paths = (
        ("evidence_index", evidence),
        ("persona_model", root / "skill" / "references" / "persona_model.json"),
        (
            "evaluation_suite",
            root / "research" / "reviews" / "evaluation_suite.json",
        ),
        (
            "reverse_identification",
            root / "research" / "reviews" / "reverse_identification.json",
        ),
    )
    evaluator_paths = (
        ("persona_model", root / "skill" / "references" / "persona_model.json"),
        (
            "persona_model_schema",
            root / "skill" / "references" / "persona_model.schema.json",
        ),
        (
            "evaluation_suite",
            root / "research" / "reviews" / "evaluation_suite.json",
        ),
        (
            "evaluation_suite_schema",
            root / "research" / "reviews" / "evaluation_suite.schema.json",
        ),
        (
            "reverse_identification",
            root / "research" / "reviews" / "reverse_identification.json",
        ),
        (
            "reverse_identification_schema",
            root / "research" / "reviews" / "reverse_identification.schema.json",
        ),
    )
    return {
        "schema_version": FRESHNESS_SCHEMA_VERSION,
        "corpus_and_signals": upstream,
        "entity_review": entity_review_inputs,
        "evidence_coverage": evidence_inputs,
        "persona": persona_inputs,
        "evidence_integrity": [
            *upstream,
            *(
                _safe_file_identity(root, path, role=role)
                for role, path in evidence_integrity_paths
            ),
        ],
        "evaluator": [
            _safe_file_identity(root, path, role=role)
            for role, path in evaluator_paths
        ],
    }


def compute_current_derivations(run_dir: Path) -> dict[str, Any]:
    """Compute current research derivations without writing any artifact."""
    import refinement_coverage
    import refinement_signals

    root = Path(run_dir)
    corpus_snapshot = corpus.load_corpus(root)
    corpus_index = refinement_signals.build_corpus_index(
        root,
        corpus_snapshot=corpus_snapshot,
    )
    topic_candidates = refinement_signals.build_topic_candidates(
        root,
        corpus_index,
        corpus_snapshot=corpus_snapshot,
    )
    signals = refinement_signals.build_transcript_signals(
        root,
        corpus_index,
        corpus_snapshot=corpus_snapshot,
    )
    coverage = refinement_coverage.build_evidence_coverage(
        root,
        corpus_index,
        signals,
    )
    return {
        "corpus_index": corpus_index,
        "topic_candidates": topic_candidates,
        "transcript_signals": signals,
        "evidence_coverage": coverage,
    }


def summarize_current_derivations(current: Mapping[str, Any]) -> dict[str, Any]:
    """Keep freshness metrics while excluding titles and transcript-derived text."""
    corpus = current.get("corpus_index") or {}
    topic_candidates = current.get("topic_candidates") or {}
    signals = current.get("transcript_signals") or {}
    phrase_analysis = signals.get("phrase_analysis") or {}
    coverage = current.get("evidence_coverage") or {}
    return {
        "corpus_index": {
            "record_count": len(corpus.get("records") or []),
            "coverage": dict(corpus.get("coverage") or {}),
        },
        "topic_candidates": {
            "classification_status": topic_candidates.get("classification_status"),
            "candidate_count": int(topic_candidates.get("candidate_count") or 0),
            "represented_video_count": int(
                topic_candidates.get("represented_video_count") or 0
            ),
            "overall_confidence": dict(
                topic_candidates.get("overall_confidence") or {}
            ),
        },
        "transcript_signals": {
            "summary": dict(signals.get("summary") or {}),
            "phrase_analysis": {
                "algorithm_version": phrase_analysis.get("algorithm_version"),
                "tokenizer_name": phrase_analysis.get("tokenizer_name"),
                "tokenizer_version": phrase_analysis.get("tokenizer_version"),
                "tokenizer_mode": phrase_analysis.get("tokenizer_mode"),
                "stopword_version": phrase_analysis.get("stopword_version"),
                "minimum_video_appearances": int(
                    phrase_analysis.get("minimum_video_appearances") or 0
                ),
                "candidate_count": int(
                    phrase_analysis.get("candidate_count") or 0
                ),
            },
        },
        "evidence_coverage": dict(coverage),
    }


def _upstream_file_inputs(
    run_dir: Path,
    *,
    corpus_snapshot: corpus.CorpusSnapshot | None = None,
) -> tuple[dict[str, Any], ...]:
    selected = run_dir / "metadata" / "selected.compact.json"
    inputs = [artifacts.file_input(selected, role="selected_metadata")]
    if corpus_snapshot is None:
        inputs.extend(
            artifacts.file_input(path, role=f"transcript:{path.name}")
            for path in path_policy.artifact_files(run_dir / "transcripts", ".txt")
        )
    else:
        corpus_snapshot.assert_for_run(run_dir)
        corpus_snapshot.assert_unchanged()
        inputs.extend(corpus_snapshot.transcript_inputs())
    return tuple(inputs)


def _artifact_spec(
    artifact_type: str,
    inputs: Sequence[Mapping[str, Any]],
    *,
    config_key: str,
    config_version: str = "1",
    additional_config: Mapping[str, Any] | None = None,
) -> artifacts.ArtifactSpec:
    config = {config_key: config_version, **dict(additional_config or {})}
    return artifacts.ArtifactSpec(
        artifact_type=artifact_type,
        inputs=inputs,
        config=config,
        producer=_PRODUCER,
    )


def refinement_artifact_specs(
    run_dir: Path,
    *,
    corpus_snapshot: corpus.CorpusSnapshot | None = None,
) -> dict[str, artifacts.ArtifactSpec]:
    """Build the single expected manifest contract for corpus and signal outputs."""
    root = Path(run_dir)
    inputs = _upstream_file_inputs(root, corpus_snapshot=corpus_snapshot)
    taxonomy = research_taxonomy.resolve_run_taxonomy(root)
    taxonomy_config = {
        "taxonomy_preset": taxonomy.name,
        "taxonomy_version": taxonomy.version,
    }
    text_analysis_config = {
        "text_analysis_algorithm_version": text_analysis.TEXT_ANALYSIS_VERSION,
        "tokenizer_name": text_analysis.TOKENIZER_NAME,
        "tokenizer_version": text_analysis.TOKENIZER_VERSION,
        "tokenizer_mode": text_analysis.TOKENIZER_MODE,
        "stopword_version": topic_discovery.STOPWORD_VERSION,
        "minimum_video_appearances": text_analysis.MINIMUM_VIDEO_APPEARANCES,
    }
    dictionary_path = entity_review.project_dictionary_path(root)
    dictionary_inputs = (
        (
            artifacts.file_input(
                dictionary_path,
                role="project_entity_dictionary",
            ),
        )
        if dictionary_path.is_file()
        else ()
    )
    entity_inputs = (*inputs, *dictionary_inputs)
    entity_dictionary_config = {
        "project_dictionary_schema_version": (
            entity_review.PROJECT_DICTIONARY_SCHEMA_VERSION
        ),
        "project_dictionary_status": (
            "loaded" if dictionary_path.is_file() else "missing"
        ),
    }
    return {
        "corpus_index": _artifact_spec(
            "host_corpus_index",
            inputs,
            config_key="corpus_algorithm_version",
            additional_config=taxonomy_config,
        ),
        "topic_candidates": _artifact_spec(
            "topic_candidates",
            inputs,
            config_key="topic_discovery_algorithm_version",
            config_version=topic_discovery.TOPIC_DISCOVERY_VERSION,
            additional_config=text_analysis_config,
        ),
        "topic_candidates_markdown": _artifact_spec(
            "topic_candidates_markdown",
            inputs,
            config_key="topic_discovery_algorithm_version",
            config_version=topic_discovery.TOPIC_DISCOVERY_VERSION,
            additional_config=text_analysis_config,
        ),
        "transcript_signal_matrix": _artifact_spec(
            "transcript_signal_matrix",
            inputs,
            config_key="signal_algorithm_version",
            additional_config={**taxonomy_config, **text_analysis_config},
        ),
        "transcript_signals": _artifact_spec(
            "transcript_signals",
            inputs,
            config_key="signal_algorithm_version",
            additional_config={**taxonomy_config, **text_analysis_config},
        ),
        "transcript_signals_markdown": _artifact_spec(
            "transcript_signals_markdown",
            inputs,
            config_key="signal_algorithm_version",
            additional_config={**taxonomy_config, **text_analysis_config},
        ),
        "asr_entity_review": _artifact_spec(
            "asr_entity_review",
            entity_inputs,
            config_key="entity_review_algorithm_version",
            config_version=entity_review.ENTITY_REVIEW_ALGORITHM_VERSION,
            additional_config={
                **taxonomy_config,
                **entity_dictionary_config,
            },
        ),
        "asr_entity_review_markdown": _artifact_spec(
            "asr_entity_review_markdown",
            entity_inputs,
            config_key="entity_review_algorithm_version",
            config_version=entity_review.ENTITY_REVIEW_ALGORITHM_VERSION,
            additional_config={
                **taxonomy_config,
                **entity_dictionary_config,
            },
        ),
    }


def coverage_artifact_specs(run_dir: Path) -> dict[str, artifacts.ArtifactSpec]:
    """Build the expected coverage contracts from persisted fresh upstream reports."""
    root = Path(run_dir)
    inputs = [
        artifacts.file_input(
            root / "research" / "host_refinement" / "corpus_index.json",
            role="corpus_index",
        ),
        artifacts.file_input(
            root / "research" / "host_refinement" / "transcript_signals.json",
            role="transcript_signals",
        ),
    ]
    evidence = root / "skill" / "references" / "evidence_index.md"
    if evidence.is_file():
        inputs.append(artifacts.file_input(evidence, role="evidence_index"))
    return {
        "evidence_coverage": _artifact_spec(
            "evidence_coverage",
            inputs,
            config_key="coverage_algorithm_version",
            config_version=COVERAGE_ALGORITHM_VERSION,
        ),
        "evidence_coverage_markdown": _artifact_spec(
            "evidence_coverage_markdown",
            inputs,
            config_key="coverage_algorithm_version",
            config_version=COVERAGE_ALGORITHM_VERSION,
        ),
    }


def _state(
    run_dir: Path,
    path: Path,
    spec: artifacts.ArtifactSpec,
    *,
    computed_from: list[dict[str, Any]],
) -> dict[str, Any]:
    decision = artifacts.assess_artifact(path, spec)
    return {
        "fresh": decision.reusable,
        "reason": decision.reason,
        "path": _relative(run_dir, path),
        "manifest": _relative(run_dir, decision.manifest_path),
        "computed_from": computed_from,
    }


def _stale_state(
    run_dir: Path,
    path: Path,
    *,
    reason: str,
    computed_from: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "fresh": False,
        "reason": reason,
        "path": _relative(run_dir, path),
        "manifest": _relative(run_dir, artifacts.artifact_manifest_path(path)),
        "computed_from": computed_from,
    }


def _failed_freshness(
    run_dir: Path,
    computed_from: dict[str, Any],
    error_type: str,
) -> dict[str, Any]:
    paths = {
        "corpus_index": run_dir / "research" / "host_refinement" / "corpus_index.json",
        "topic_candidates": run_dir / "research" / "host_refinement" / "topic_candidates.json",
        "topic_candidates_markdown": run_dir / "research" / "host_refinement" / "topic_candidates.md",
        "transcript_signal_matrix": run_dir / "research" / "host_refinement" / "transcript_signal_matrix.md",
        "transcript_signals": run_dir / "research" / "host_refinement" / "transcript_signals.json",
        "transcript_signals_markdown": run_dir / "research" / "host_refinement" / "transcript_signals.md",
        "asr_entity_review": run_dir / "research" / "reviews" / "asr_entity_review.json",
        "asr_entity_review_markdown": run_dir / "research" / "reviews" / "asr_entity_review.md",
        "evidence_coverage": run_dir / "research" / "reviews" / "evidence_coverage.json",
        "evidence_coverage_markdown": run_dir / "research" / "reviews" / "evidence_coverage.md",
    }
    artifacts_state = {
        name: _stale_state(
            run_dir,
            path,
            reason="current_inputs_invalid",
            computed_from=(
                computed_from["evidence_coverage"]
                if name.startswith("evidence_coverage")
                else (
                    computed_from["entity_review"]
                    if name.startswith("asr_entity_review")
                    else computed_from["corpus_and_signals"]
                )
            ),
        )
        for name, path in paths.items()
    }
    artifacts_state["persona_model_diagnostics"] = {
        "fresh": True,
        "reason": "computed_live",
        "path": "research/reviews/persona_model_diagnostics.json",
        "computed_from": computed_from["persona"],
    }
    return {
        "schema_version": FRESHNESS_SCHEMA_VERSION,
        "fresh": False,
        "stale_artifacts": list(paths),
        "artifacts": artifacts_state,
        "current": {},
        "repair_command": REPAIR_COMMAND,
        "issue": {"code": "CURRENT_DERIVATION_FAILED", "error_type": error_type},
    }


def evaluate_refinement_freshness(run_dir: Path) -> dict[str, Any]:
    """Compare persisted reports with manifests rebuilt from the current run inputs."""
    root = Path(run_dir)
    computed_from = current_input_identities(root)
    try:
        current = compute_current_derivations(root)
        specs = refinement_artifact_specs(root)
    except (OSError, ValueError, TypeError, KeyError) as error:
        return {
            "computed_from": computed_from,
            "freshness": _failed_freshness(root, computed_from, type(error).__name__),
        }

    refinement = root / "research" / "host_refinement"
    reviews = root / "research" / "reviews"
    paths = {
        "corpus_index": refinement / "corpus_index.json",
        "topic_candidates": refinement / "topic_candidates.json",
        "topic_candidates_markdown": refinement / "topic_candidates.md",
        "transcript_signal_matrix": refinement / "transcript_signal_matrix.md",
        "transcript_signals": refinement / "transcript_signals.json",
        "transcript_signals_markdown": refinement / "transcript_signals.md",
        "asr_entity_review": reviews / "asr_entity_review.json",
        "asr_entity_review_markdown": reviews / "asr_entity_review.md",
        "evidence_coverage": reviews / "evidence_coverage.json",
        "evidence_coverage_markdown": reviews / "evidence_coverage.md",
    }
    states = {
        "corpus_index": _state(
            root,
            paths["corpus_index"],
            specs["corpus_index"],
            computed_from=computed_from["corpus_and_signals"],
        ),
        "topic_candidates": _state(
            root,
            paths["topic_candidates"],
            specs["topic_candidates"],
            computed_from=computed_from["corpus_and_signals"],
        ),
        "topic_candidates_markdown": _state(
            root,
            paths["topic_candidates_markdown"],
            specs["topic_candidates_markdown"],
            computed_from=computed_from["corpus_and_signals"],
        ),
        "transcript_signal_matrix": _state(
            root,
            paths["transcript_signal_matrix"],
            specs["transcript_signal_matrix"],
            computed_from=computed_from["corpus_and_signals"],
        ),
        "transcript_signals": _state(
            root,
            paths["transcript_signals"],
            specs["transcript_signals"],
            computed_from=computed_from["corpus_and_signals"],
        ),
        "transcript_signals_markdown": _state(
            root,
            paths["transcript_signals_markdown"],
            specs["transcript_signals_markdown"],
            computed_from=computed_from["corpus_and_signals"],
        ),
        "asr_entity_review": _state(
            root,
            paths["asr_entity_review"],
            specs["asr_entity_review"],
            computed_from=computed_from["entity_review"],
        ),
        "asr_entity_review_markdown": _state(
            root,
            paths["asr_entity_review_markdown"],
            specs["asr_entity_review_markdown"],
            computed_from=computed_from["entity_review"],
        ),
    }
    upstream_fresh = states["corpus_index"]["fresh"] and states["transcript_signals"]["fresh"]
    if upstream_fresh:
        coverage_specs = coverage_artifact_specs(root)
        states["evidence_coverage"] = _state(
            root,
            paths["evidence_coverage"],
            coverage_specs["evidence_coverage"],
            computed_from=computed_from["evidence_coverage"],
        )
        states["evidence_coverage_markdown"] = _state(
            root,
            paths["evidence_coverage_markdown"],
            coverage_specs["evidence_coverage_markdown"],
            computed_from=computed_from["evidence_coverage"],
        )
    else:
        for name in ("evidence_coverage", "evidence_coverage_markdown"):
            states[name] = _stale_state(
                root,
                paths[name],
                reason="upstream_stale",
                computed_from=computed_from["evidence_coverage"],
            )

    states["persona_model_diagnostics"] = {
        "fresh": True,
        "reason": "computed_live",
        "path": "research/reviews/persona_model_diagnostics.json",
        "computed_from": computed_from["persona"],
    }
    key_names = tuple(paths)
    stale = [name for name in key_names if not states[name]["fresh"]]
    return {
        "computed_from": computed_from,
        "freshness": {
            "schema_version": FRESHNESS_SCHEMA_VERSION,
            "fresh": not stale,
            "stale_artifacts": stale,
            "artifacts": states,
            "current": summarize_current_derivations(current),
            "repair_command": REPAIR_COMMAND,
        },
    }
