#!/usr/bin/env python3
"""Deterministic cross-file evidence reference validation."""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
from typing import Any


EVIDENCE_INTEGRITY_SCHEMA_VERSION = 1
EVIDENCE_REPAIR_COMMAND = (
    "repair the listed JSON Pointer references and accepted evidence_index rows"
)
_TRANSCRIPT_FIELD_MARKERS = {
    "script_templates",
    "expression_dna",
    "judgment_heuristics",
    "anti_patterns",
    "script_style",
}
_METADATA_ROLE_PREFIXES = (
    "metadata:",
    "metadata/",
    "metadata_",
    "元数据:",
    "元数据：",
    "元数据/",
    "元数据_",
)


def _dict_items(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _video_id(record: Mapping[str, Any]) -> str:
    return str(record.get("platform_video_id") or record.get("video_id") or "").strip()


def _metadata_role(role: object) -> bool:
    normalized = str(role or "").strip().casefold().replace("-", "_")
    return normalized in {"metadata", "元数据"} or normalized.startswith(
        _METADATA_ROLE_PREFIXES
    )


def _evaluation_requires_transcript(fields: object) -> bool:
    if not isinstance(fields, list):
        return False
    normalized = "\n".join(str(field).casefold() for field in fields)
    return any(marker in normalized for marker in _TRANSCRIPT_FIELD_MARKERS)


def _collect_id_list(
    references: list[dict[str, Any]],
    duplicates: list[dict[str, Any]],
    value: object,
    *,
    artifact: str,
    pointer: str,
    reference_kind: str,
    required_type: str,
) -> list[str]:
    if not isinstance(value, list):
        return []
    first_pointers: dict[str, str] = {}
    unique_ids: list[str] = []
    for index, raw_video_id in enumerate(value):
        if not isinstance(raw_video_id, str) or not raw_video_id.strip():
            continue
        video_id = raw_video_id.strip()
        item_pointer = f"{pointer}/{index}"
        if video_id in first_pointers:
            duplicates.append(
                {
                    "artifact": artifact,
                    "pointer": item_pointer,
                    "first_pointer": first_pointers[video_id],
                    "video_id": video_id,
                    "reason": "duplicate_in_reference_list",
                }
            )
            continue
        first_pointers[video_id] = item_pointer
        unique_ids.append(video_id)
        references.append(
            {
                "artifact": artifact,
                "pointer": item_pointer,
                "video_id": video_id,
                "reference_kind": reference_kind,
                "required_type": required_type,
            }
        )
    return unique_ids


def _collect_document_references(
    persona_model: object,
    evaluation_suite: object,
    reverse_identification: object,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool, list[dict[str, Any]]]:
    references: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    topic_model_distinct = True
    anchors: list[dict[str, Any]] = []

    persona = persona_model if isinstance(persona_model, Mapping) else {}
    for index, topic in enumerate(_dict_items(persona.get("topic_models"))):
        unique_ids = _collect_id_list(
            references,
            duplicates,
            topic.get("evidence_ids"),
            artifact="persona_model",
            pointer=f"/topic_models/{index}/evidence_ids",
            reference_kind="topic_model",
            required_type="metadata",
        )
        if len(unique_ids) < 2:
            topic_model_distinct = False

    for index, script in enumerate(_dict_items(persona.get("script_templates"))):
        _collect_id_list(
            references,
            duplicates,
            script.get("evidence_ids"),
            artifact="persona_model",
            pointer=f"/script_templates/{index}/evidence_ids",
            reference_kind="script_template",
            required_type="transcript",
        )

    first_anchor_pointers: dict[str, str] = {}
    for index, anchor in enumerate(_dict_items(persona.get("evidence_anchors"))):
        raw_video_id = anchor.get("video_id")
        if not isinstance(raw_video_id, str) or not raw_video_id.strip():
            continue
        video_id = raw_video_id.strip()
        pointer = f"/evidence_anchors/{index}/video_id"
        required_type = "metadata" if _metadata_role(anchor.get("role")) else "transcript"
        anchor_reference = {
            "artifact": "persona_model",
            "pointer": pointer,
            "video_id": video_id,
            "reference_kind": "evidence_anchor",
            "required_type": required_type,
        }
        anchors.append(anchor_reference)
        if video_id in first_anchor_pointers:
            duplicates.append(
                {
                    "artifact": "persona_model",
                    "pointer": pointer,
                    "first_pointer": first_anchor_pointers[video_id],
                    "video_id": video_id,
                    "reason": "duplicate_evidence_anchor",
                }
            )
            continue
        first_anchor_pointers[video_id] = pointer
        references.append(anchor_reference)

    evaluation = evaluation_suite if isinstance(evaluation_suite, Mapping) else {}
    for index, case in enumerate(_dict_items(evaluation.get("cases"))):
        required_type = (
            "transcript"
            if _evaluation_requires_transcript(case.get("applied_persona_model_fields"))
            else "metadata"
        )
        _collect_id_list(
            references,
            duplicates,
            case.get("evidence_video_ids"),
            artifact="evaluation_suite",
            pointer=f"/cases/{index}/evidence_video_ids",
            reference_kind="evaluation_case",
            required_type=required_type,
        )

    reverse = reverse_identification if isinstance(reverse_identification, Mapping) else {}
    for index, row in enumerate(_dict_items(reverse.get("rows"))):
        _collect_id_list(
            references,
            duplicates,
            row.get("evidence_video_ids"),
            artifact="reverse_identification",
            pointer=f"/rows/{index}/evidence_video_ids",
            reference_kind="reverse_identification",
            required_type="transcript",
        )
    return references, duplicates, topic_model_distinct, anchors


def evaluate_evidence_integrity(
    corpus_index: object,
    evidence_index: object,
    persona_model: object,
    evaluation_suite: object,
    reverse_identification: object,
) -> dict[str, Any]:
    """Validate evidence identity and type links without reading or copying corpus text."""

    corpus = corpus_index if isinstance(corpus_index, Mapping) else {}
    parsed_evidence = evidence_index if isinstance(evidence_index, Mapping) else {}
    records = _dict_items(corpus.get("records"))
    corpus_by_id: dict[str, Mapping[str, Any]] = {}
    duplicate_references: list[dict[str, Any]] = []
    first_record_pointers: dict[str, str] = {}
    for index, record in enumerate(records):
        video_id = _video_id(record)
        if not video_id:
            continue
        pointer = f"/records/{index}/video_id"
        if video_id in first_record_pointers:
            duplicate_references.append(
                {
                    "artifact": "corpus_index",
                    "pointer": pointer,
                    "first_pointer": first_record_pointers[video_id],
                    "video_id": video_id,
                    "reason": "duplicate_corpus_video_id",
                }
            )
            continue
        first_record_pointers[video_id] = pointer
        corpus_by_id[video_id] = record

    accepted_ids = {
        str(video_id).strip()
        for video_id in parsed_evidence.get("accepted_ids", [])
        if str(video_id).strip()
    }
    invalid_evidence_decision_ids = {
        str(video_id).strip()
        for field in ("duplicate_ids", "conflicting_ids")
        for video_id in parsed_evidence.get(field, []) or []
        if str(video_id).strip()
    }
    usable_accepted_ids = accepted_ids - invalid_evidence_decision_ids
    references, document_duplicates, topic_model_distinct, anchors = (
        _collect_document_references(
            persona_model,
            evaluation_suite,
            reverse_identification,
        )
    )
    duplicate_references.extend(document_duplicates)
    for index, video_id in enumerate(parsed_evidence.get("duplicate_ids", []) or []):
        duplicate_references.append(
            {
                "artifact": "evidence_index",
                "pointer": f"/duplicate_ids/{index}",
                "first_pointer": "",
                "video_id": str(video_id),
                "reason": "duplicate_evidence_index_row",
            }
        )
    for index, video_id in enumerate(parsed_evidence.get("conflicting_ids", []) or []):
        duplicate_references.append(
            {
                "artifact": "evidence_index",
                "pointer": f"/conflicting_ids/{index}",
                "first_pointer": "",
                "video_id": str(video_id),
                "reason": "conflicting_evidence_decisions",
            }
        )

    orphan_references: list[dict[str, Any]] = []
    unknown_evidence_ids = {
        str(video_id).strip()
        for video_id in parsed_evidence.get("unknown_video_ids", []) or []
        if str(video_id).strip()
    }
    unknown_evidence_ids.update(accepted_ids - set(corpus_by_id))
    for index, video_id in enumerate(sorted(unknown_evidence_ids)):
        orphan_references.append(
            {
                "artifact": "evidence_index",
                "pointer": f"/unknown_video_ids/{index}",
                "video_id": video_id,
                "reason": "not_in_corpus",
            }
        )

    missing_references: list[dict[str, Any]] = []
    type_mismatches: list[dict[str, Any]] = []
    for reference in references:
        video_id = reference["video_id"]
        matched_record = corpus_by_id.get(video_id)
        if matched_record is None:
            orphan_references.append(
                {
                    **reference,
                    "reason": "not_in_corpus",
                }
            )
            continue
        if video_id not in usable_accepted_ids:
            missing_references.append(
                {
                    **reference,
                    "reason": (
                        "ambiguous_evidence_index_entry"
                        if video_id in invalid_evidence_decision_ids
                        else "not_in_accepted_evidence_index"
                    ),
                }
            )
        if reference["required_type"] == "transcript" and int(
            matched_record.get("transcript_chars") or 0
        ) <= 0:
            type_mismatches.append(
                {
                    **reference,
                    "available_type": "metadata",
                    "reason": "transcript_missing",
                }
            )

    duplicate_anchor_ids = {
        item["video_id"]
        for item in duplicate_references
        if item["reason"] == "duplicate_evidence_anchor"
    }
    anchor_mappings: list[dict[str, Any]] = []
    for anchor in anchors:
        video_id = anchor["video_id"]
        matched_record = corpus_by_id.get(video_id)
        has_transcript = bool(
            matched_record
            and int(matched_record.get("transcript_chars") or 0) > 0
        )
        evidence_type = "transcript" if has_transcript else "metadata"
        valid = bool(
            matched_record
            and video_id in usable_accepted_ids
            and video_id not in duplicate_anchor_ids
            and (anchor["required_type"] == "metadata" or has_transcript)
        )
        anchor_mappings.append(
            {
                **anchor,
                "in_metadata": matched_record is not None,
                "transcript_status": "available" if has_transcript else "missing",
                "in_evidence_index": video_id in usable_accepted_ids,
                "evidence_type": evidence_type,
                "valid": valid,
            }
        )

    valid_unique_anchor_ids = {
        item["video_id"] for item in anchor_mappings if item["valid"]
    }
    artifact_validity = {
        "corpus_index": bool(corpus_by_id),
        "evidence_index": parsed_evidence.get("source_status") == "parsed",
        "persona_model": True,
        "evaluation_suite": True,
        "reverse_identification": True,
    }
    for item in (
        orphan_references
        + missing_references
        + duplicate_references
        + type_mismatches
    ):
        artifact = item["artifact"]
        if artifact in artifact_validity:
            artifact_validity[artifact] = False
    evidence_anchor_minimum = len(valid_unique_anchor_ids) >= 15
    if not evidence_anchor_minimum or not topic_model_distinct:
        artifact_validity["persona_model"] = False

    checks = {
        "corpus_available": bool(corpus_by_id),
        "evidence_index_parsed": parsed_evidence.get("source_status") == "parsed",
        "all_references_in_corpus": not orphan_references,
        "all_references_in_evidence_index": not missing_references,
        "no_duplicate_references": not duplicate_references,
        "reference_types_match": not type_mismatches,
        "evidence_anchor_minimum": evidence_anchor_minimum,
        "topic_model_distinct_evidence": topic_model_distinct,
    }
    referenced_ids = {reference["video_id"] for reference in references}
    return {
        "schema_version": EVIDENCE_INTEGRITY_SCHEMA_VERSION,
        "valid": all(checks.values()),
        "checks": checks,
        "artifact_validity": artifact_validity,
        "counts": {
            "corpus_video_ids": len(corpus_by_id),
            "accepted_evidence_ids": len(accepted_ids & set(corpus_by_id)),
            "usable_accepted_evidence_ids": len(
                usable_accepted_ids & set(corpus_by_id)
            ),
            "referenced_video_ids": len(referenced_ids),
            "evidence_anchors": len(anchors),
            "valid_unique_evidence_anchors": len(valid_unique_anchor_ids),
            "orphan_references": len(orphan_references),
            "missing_references": len(missing_references),
            "duplicate_references": len(duplicate_references),
            "type_mismatches": len(type_mismatches),
        },
        "orphan_references": orphan_references,
        "missing_references": missing_references,
        "duplicate_references": duplicate_references,
        "type_mismatches": type_mismatches,
        "anchor_mappings": anchor_mappings,
        "repair": EVIDENCE_REPAIR_COMMAND,
    }


def _load_json_object(path: Path) -> tuple[object, str]:
    if not path.is_file():
        return {}, "missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}, "invalid_json"
    if not isinstance(payload, Mapping):
        return {}, "invalid_root_type"
    return payload, "loaded"


def evaluate_run_evidence_integrity(run_dir: Path) -> dict[str, Any]:
    """Evaluate current run inputs without trusting persisted corpus reports."""

    import refinement_coverage
    import refinement_signals

    root = Path(run_dir)
    try:
        corpus_index: object = refinement_signals.build_corpus_index(root)
        corpus_status = "loaded"
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError, KeyError):
        corpus_index = {"records": []}
        corpus_status = "invalid"
    corpus_records = (
        corpus_index.get("records", [])
        if isinstance(corpus_index, Mapping)
        else []
    )
    valid_video_ids = {
        _video_id(record)
        for record in _dict_items(corpus_records)
        if _video_id(record)
    }
    evidence_index = refinement_coverage.parse_evidence_index(
        root / "skill" / "references" / "evidence_index.md",
        valid_video_ids,
    )
    document_paths = {
        "persona_model": root / "skill" / "references" / "persona_model.json",
        "evaluation_suite": root / "research" / "reviews" / "evaluation_suite.json",
        "reverse_identification": root
        / "research"
        / "reviews"
        / "reverse_identification.json",
    }
    documents: dict[str, object] = {}
    document_status: dict[str, str] = {}
    for artifact, path in document_paths.items():
        documents[artifact], document_status[artifact] = _load_json_object(path)

    report = evaluate_evidence_integrity(
        corpus_index,
        evidence_index,
        documents["persona_model"],
        documents["evaluation_suite"],
        documents["reverse_identification"],
    )
    documents_loaded = all(status == "loaded" for status in document_status.values())
    report["checks"]["corpus_loaded"] = corpus_status == "loaded"
    report["checks"]["documents_loaded"] = documents_loaded
    report["valid"] = all(report["checks"].values())
    report["corpus_status"] = corpus_status
    report["document_status"] = document_status
    for artifact, status in document_status.items():
        if status != "loaded":
            report["artifact_validity"][artifact] = False
    if corpus_status != "loaded":
        report["artifact_validity"]["corpus_index"] = False
    return report
