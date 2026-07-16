"""Creator-specific quality diagnostics built on the shared quality engine."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import artifacts
import content_safety
import entity_review
import evidence_model
import path_policy
import provenance
import quality_engine
import run_diagnostics
import schema_validation
import text_analysis
from creator_metadata import read_json
from io_utils import atomic_write_json as write_json
from pipeline_models import StepResult
from stage_coverage import evaluate_stage_coverage


def markdown_nonempty_bullets(text: str) -> int:
    return len(re.findall(r"(?m)^\s*[-*]\s+\S", text))


def markdown_heading_count(text: str) -> int:
    return len(re.findall(r"(?m)^#{2,4}\s+\S", text))


def markdown_table_rows(text: str) -> int:
    return len(re.findall(r"(?m)^\|[^|\n]+\|", text))


def has_mojibake(text: str) -> bool:
    return not content_safety.analyze_text_encoding(text)["passed"]


GENERIC_AI_PHRASES = [
    "引发共鸣",
    "层层递进",
    "通俗易懂",
    "深入浅出",
    "既专业又亲切",
    "用通俗语言解释复杂问题",
    "生动形象",
    "干货满满",
    "娓娓道来",
    "逻辑清晰",
    "观点鲜明",
    "贴近生活",
    "真实自然",
    "情绪价值",
    "爆款",
]


def generic_template_stats(text: str) -> dict:
    hits: list[dict[str, Any]] = []
    for phrase in GENERIC_AI_PHRASES:
        count = text.count(phrase)
        if count:
            hits.append({"phrase": phrase, "count": count})
    total_hits = sum(item["count"] for item in hits)
    return {
        "hit_count": total_hits,
        "unique_hit_count": len(hits),
        "hits": hits,
        "passed": total_hits <= 6 and len(hits) <= 4,
    }


def extract_video_ids_from_value(value: Any) -> set[str]:
    if isinstance(value, str):
        return set(re.findall(r"\b\d{16,20}\b", value))
    ids: set[str] = set()
    if isinstance(value, dict):
        for nested in value.values():
            ids.update(extract_video_ids_from_value(nested))
        return ids
    if isinstance(value, list):
        for nested in value:
            ids.update(extract_video_ids_from_value(nested))
        return ids
    return ids


def nonempty_items(value: Any) -> list[Any]:
    if not isinstance(value, list):
        return []
    return [item for item in value if item not in (None, "", [], {})]


def compute_persona_model_stats(
    run_dir: Path,
    skill_dir: Path,
    markdown_texts: dict[str, str],
    *,
    computed_from: list[dict[str, Any]] | None = None,
    evidence_integrity: dict[str, Any] | None = None,
) -> dict:
    refs = skill_dir / "references"
    schema_path = refs / "persona_model.schema.json"
    model_path = refs / "persona_model.json"
    diagnostics_path = run_dir / "research" / "reviews" / "persona_model_diagnostics.json"
    persona_schema_validation = schema_validation.validate_json_file(
        model_path,
        schema_path,
        artifact="persona_model",
    )
    integrity = evidence_integrity or evidence_model.evaluate_run_evidence_integrity(
        run_dir
    )
    integrity_counts = integrity.get("counts") or {}
    integrity_by_artifact = integrity.get("artifact_validity") or {}
    evidence_text = markdown_texts.get("evidence", "")
    topic_text = markdown_texts.get("topic", "")
    script_text = markdown_texts.get("script", "")
    persona_text = markdown_texts.get("persona", "")
    combined_md = "\n\n".join([persona_text, topic_text, script_text, evidence_text])

    model: dict[str, Any] = {}
    issues: list[dict[str, str]] = []
    if model_path.exists():
        try:
            loaded = read_json(model_path)
            if isinstance(loaded, dict):
                model = loaded
            else:
                issues.append({"severity": "high", "issue": "persona_model.json is not a JSON object"})
        except (OSError, json.JSONDecodeError) as exc:
            issues.append({"severity": "high", "issue": f"persona_model.json cannot be parsed: {exc}"})
    else:
        issues.append({"severity": "high", "issue": "persona_model.json missing"})

    required_fields = [
        "version",
        "core_identity",
        "topic_models",
        "script_templates",
        "judgment_heuristics",
        "expression_dna",
        "anti_patterns",
        "safety_boundaries",
        "evidence_anchors",
        "generation_protocol",
        "evaluation_cases",
    ]
    missing_fields = [field for field in required_fields if field not in model]
    if missing_fields:
        issues.append({"severity": "high", "issue": "missing required fields: " + ", ".join(missing_fields)})

    topic_models = nonempty_items(model.get("topic_models"))
    script_templates = nonempty_items(model.get("script_templates"))
    judgment_heuristics = nonempty_items(model.get("judgment_heuristics"))
    expression_dna = nonempty_items(model.get("expression_dna"))
    anti_patterns = nonempty_items(model.get("anti_patterns"))
    safety_boundaries = nonempty_items(model.get("safety_boundaries"))
    evidence_anchors = nonempty_items(model.get("evidence_anchors"))
    generation_protocol_value = model.get("generation_protocol")
    generation_protocol: dict[str, Any] = (
        generation_protocol_value if isinstance(generation_protocol_value, dict) else {}
    )
    evaluation_cases = nonempty_items(model.get("evaluation_cases"))

    topic_models_complete = len(topic_models) >= 5 and all(
        isinstance(item, dict)
        and item.get("name")
        and item.get("definition")
        and len(nonempty_items(item.get("use_cases"))) >= 1
        and len(extract_video_ids_from_value(item.get("evidence_ids", []))) >= 2
        and len(nonempty_items(item.get("failure_modes"))) >= 1
        for item in topic_models
    )
    script_templates_complete = len(script_templates) >= 4 and all(
        isinstance(item, dict)
        and item.get("name")
        and len(nonempty_items(item.get("use_cases"))) >= 1
        and item.get("hook")
        and item.get("body")
        and item.get("ending")
        and len(nonempty_items(item.get("failure_modes"))) >= 1
        and len(extract_video_ids_from_value(item.get("evidence_ids", []))) >= 1
        for item in script_templates
    )
    model_ids = extract_video_ids_from_value(model)
    persona_reference_issues = [
        item
        for category in (
            "orphan_references",
            "missing_references",
            "duplicate_references",
            "type_mismatches",
        )
        for item in integrity.get(category, [])
        if item.get("artifact") == "persona_model"
    ]
    missing_from_evidence_index = [
        item
        for item in persona_reference_issues
        if item.get("reason")
        in {
            "not_in_corpus",
            "not_in_accepted_evidence_index",
            "ambiguous_evidence_index_entry",
        }
    ]
    topic_names = [str(item.get("name", "")) for item in topic_models if isinstance(item, dict)]
    topic_name_hits = sum(1 for name in topic_names if name and name in topic_text)
    script_names = [str(item.get("name", "")) for item in script_templates if isinstance(item, dict)]
    script_name_hits = sum(1 for name in script_names if name and name in script_text)
    safety_text = "\n".join(str(item) for item in safety_boundaries)
    safety_complete = all(term in safety_text for term in ["冒充", "本人"]) and bool(re.search(r"声音|形象|克隆", safety_text))
    generation_protocol_complete = (
        len(nonempty_items(generation_protocol.get("field_order"))) >= 5
        and len(nonempty_items(generation_protocol.get("task_routing"))) >= 4
        and bool(generation_protocol.get("evidence_policy"))
        and bool(generation_protocol.get("confidence_policy"))
    )
    evaluation_cases_complete = len(evaluation_cases) >= 6 and all(
        isinstance(item, dict)
        and item.get("name")
        and item.get("task")
        and len(nonempty_items(item.get("expected_fields"))) >= 2
        and len(nonempty_items(item.get("pass_criteria"))) >= 2
        for item in evaluation_cases
    )

    checks = {
        "schema_file_present": schema_path.is_file(),
        "schema_valid": bool(persona_schema_validation["schema_valid"]),
        "model_file_present": model_path.exists() and model_path.stat().st_size > 100,
        "model_schema_valid": bool(persona_schema_validation["valid"]),
        "not_template": model.get("status") != "draft_template",
        "required_top_fields": not missing_fields,
        "core_identity_present": isinstance(model.get("core_identity"), str) and len(model.get("core_identity", "")) >= 40,
        "topic_models_complete": topic_models_complete,
        "script_templates_complete": script_templates_complete,
        "judgment_heuristics_min": len(judgment_heuristics) >= 6,
        "expression_dna_min": len(expression_dna) >= 6,
        "anti_patterns_min": len(anti_patterns) >= 5,
        "safety_boundaries_complete": safety_complete,
        "evidence_anchors_min": int(
            integrity_counts.get("valid_unique_evidence_anchors") or 0
        )
        >= 15,
        "generation_protocol_complete": generation_protocol_complete,
        "evaluation_cases_complete": evaluation_cases_complete,
        "evidence_ids_in_evidence_index": not missing_from_evidence_index,
        "evidence_integrity_valid": bool(
            integrity_by_artifact.get("persona_model")
        ),
        "markdown_alignment": topic_name_hits >= min(5, len(topic_names)) and script_name_hits >= min(3, len(script_names)),
        "no_mojibake": not has_mojibake(json.dumps(model, ensure_ascii=False)) and not has_mojibake(combined_md),
    }
    if not checks["not_template"]:
        issues.append({"severity": "high", "issue": "persona_model.json is still the draft template"})
    for error in persona_schema_validation["errors"]:
        pointer = error["pointer"] or "/"
        issues.append(
            {
                "severity": "high",
                "issue": f"persona_model schema error at {pointer}: {error['message']}",
            }
        )
    if missing_from_evidence_index:
        issues.append(
            {
                "severity": "high",
                "issue": "persona_model has orphan or unaccepted evidence references",
            }
        )
    for reference_issue in persona_reference_issues[:20]:
        pointer = reference_issue.get("pointer") or "/"
        issues.append(
            {
                "severity": "high",
                "issue": (
                    f"persona_model evidence error at {pointer}: "
                    f"{reference_issue.get('reason', 'invalid_reference')} "
                    f"({reference_issue.get('video_id', '')})"
                ),
            }
        )
    if not checks["markdown_alignment"]:
        issues.append({"severity": "medium", "issue": "persona_model names do not align with Markdown topic/script files"})

    diagnostics = {
        "ready": all(checks.values()),
        "computed_from": computed_from or [],
        "freshness": {"fresh": True, "reason": "computed_live"},
        "schema_validation": persona_schema_validation,
        "checks": checks,
        "counts": {
            "topic_models": len(topic_models),
            "script_templates": len(script_templates),
            "judgment_heuristics": len(judgment_heuristics),
            "expression_dna": len(expression_dna),
            "anti_patterns": len(anti_patterns),
            "safety_boundaries": len(safety_boundaries),
            "evidence_anchors": len(evidence_anchors),
            "valid_unique_evidence_anchors": int(
                integrity_counts.get("valid_unique_evidence_anchors") or 0
            ),
            "task_routing": len(nonempty_items(generation_protocol.get("task_routing"))),
            "evaluation_cases": len(evaluation_cases),
            "referenced_video_ids": len(model_ids),
            "topic_name_hits": topic_name_hits,
            "script_name_hits": script_name_hits,
        },
        "issues": issues,
        "files": {
            "schema": str(schema_path.relative_to(run_dir)) if schema_path.exists() else "",
            "model": str(model_path.relative_to(run_dir)) if model_path.exists() else "",
            "diagnostics": str(diagnostics_path.relative_to(run_dir)),
        },
    }
    return diagnostics


def persona_model_stats(
    run_dir: Path,
    skill_dir: Path,
    markdown_texts: dict[str, str],
    *,
    computed_from: list[dict[str, Any]] | None = None,
    evidence_integrity: dict[str, Any] | None = None,
) -> dict:
    """Compute current diagnostics, then atomically persist the quality evidence."""
    diagnostics = compute_persona_model_stats(
        run_dir,
        skill_dir,
        markdown_texts,
        computed_from=computed_from,
        evidence_integrity=evidence_integrity,
    )
    diagnostics_path = (
        run_dir / "research" / "reviews" / "persona_model_diagnostics.json"
    )
    diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(diagnostics_path, diagnostics)
    return diagnostics


def creator_content_readiness(
    skill_dir: Path,
    run_dir: Path | None = None,
    *,
    freshness_report: dict[str, Any] | None = None,
) -> dict:
    persona = skill_dir / "references" / "persona.md"
    topic = skill_dir / "references" / "topic_model.md"
    script = skill_dir / "references" / "script_style.md"
    evidence = skill_dir / "references" / "evidence_index.md"

    persona_text = persona.read_text(encoding="utf-8", errors="replace") if persona.exists() else ""
    topic_text = topic.read_text(encoding="utf-8", errors="replace") if topic.exists() else ""
    script_text = script.read_text(encoding="utf-8", errors="replace") if script.exists() else ""
    evidence_text = evidence.read_text(encoding="utf-8", errors="replace") if evidence.exists() else ""
    combined = "\n\n".join([persona_text, topic_text, script_text, evidence_text])
    evidence_integrity: dict[str, Any] = (
        evidence_model.evaluate_run_evidence_integrity(run_dir)
        if run_dir
        else {"valid": False, "checks": {}, "artifact_validity": {}}
    )
    if run_dir:
        integrity_inputs = (
            (freshness_report or {})
            .get("computed_from", {})
            .get("evidence_integrity")
        )
        if not isinstance(integrity_inputs, list):
            integrity_inputs = quality_engine.current_input_identities(run_dir).get(
                "evidence_integrity", []
            )
        evidence_integrity["computed_from"] = integrity_inputs
    evaluator_verdict: dict[str, Any] = (
        quality_engine.evaluate_run_evaluator(
            run_dir,
            evidence_integrity=evidence_integrity,
        )
        if run_dir
        else {
            "passed": False,
            "blocking_checks": {},
            "failed_blockers": [],
            "artifacts": {},
            "computed_from": [],
        }
    )
    generic_stats = generic_template_stats(combined)
    raw_stats: dict[str, Any] = (
        raw_research_note_stats(run_dir) if run_dir else {"count": 0, "substantial_count": 0, "files": []}
    )
    refinement_stats = (
        host_refinement_stats(
            run_dir,
            (freshness_report or {}).get("freshness"),
            evidence_integrity=evidence_integrity,
            evaluator_verdict=evaluator_verdict,
        )
        if run_dir
        else {"checks": {}, "ready": False, "advisory_checks": {}}
    )
    persona_stats = (
        persona_model_stats(
            run_dir,
            skill_dir,
            {"persona": persona_text, "topic": topic_text, "script": script_text, "evidence": evidence_text},
            computed_from=(freshness_report or {})
            .get("computed_from", {})
            .get("persona", []),
            evidence_integrity=evidence_integrity,
        )
        if run_dir
        else {"ready": False, "checks": {}}
    )
    schema_results: dict[str, Any] = {}
    persona_schema_result = persona_stats.get("schema_validation")
    if isinstance(persona_schema_result, dict):
        schema_results["persona_model"] = persona_schema_result
    refinement_schema_results = refinement_stats.get("schema_validation")
    if isinstance(refinement_schema_results, dict):
        schema_results.update(refinement_schema_results)

    checks = {
        "host_refinement_package_ready": refinement_stats["ready"],
        "persona_model_ready": persona_stats["ready"],
        "raw_research_notes_present": raw_stats["substantial_count"] >= 5,
        "persona_min_density": len(persona_text) >= 3500
        and markdown_heading_count(persona_text) >= 8
        and bool(re.search(r"表达\s*DNA|Agent\s*使用协议|反模式|安全边界", persona_text, re.IGNORECASE)),
        "topic_models_present": len(re.findall(r"(?m)^#{2,4}\s*.*模型|模型[一二三四五六七八九十\d]", topic_text)) >= 5
        and bool(re.search(r"证据|锚点", topic_text))
        and bool(re.search(r"失败模式|不适合|低匹配", topic_text)),
        "script_templates_present": (
            len(re.findall(r"(?m)^#{2,4}\s+", script_text)) >= 8
            or len(re.findall(r"(?m)^#{2,4}\s*.*(?:模板|Hook)|模板[:：]", script_text)) >= 4
        )
        and len(set(re.findall(r"实验|教程|现场|产业|灰区|风险|工具|产品", script_text))) >= 4,
        "evidence_entries_present": markdown_table_rows(evidence_text) >= 15
        or markdown_nonempty_bullets(evidence_text) >= 15,
        "evidence_integrity_valid": bool(evidence_integrity.get("valid")),
        "evaluator_verdict_passed": bool(evaluator_verdict.get("passed")),
        "anti_template_pass": generic_stats["passed"],
        "no_mojibake": not has_mojibake(combined),
    }
    return {
        "ready_for_use": all(checks.values()),
        "checks": checks,
        "raw_research_notes": raw_stats,
        "host_refinement": refinement_stats,
        "persona_model": persona_stats,
        "evidence_integrity": evidence_integrity,
        "evaluator_verdict": evaluator_verdict,
        "advisory_checks": refinement_stats.get("advisory_checks", {}),
        "schema_validation": schema_results,
        "generic_template_phrases": generic_stats,
        "note": (
            "ready_for_use=false means the deterministic pipeline produced a recoverable draft "
            "or the host-agent refinement is still too thin. Generate research/host_refinement/brief.md, "
            "corpus_index.json, transcript_signal_matrix.md, and transcript_signals.json; write at least five "
            "substantial research/raw notes; fill persona_model.json, evidence_coverage, usage_probe, "
            "evaluation_suite.md/json, reverse_identification.md/json, reviewer_findings, and refinement_audit; then rewrite the Creator Skill."
        ),
    }


def _unverified_run_quality_report(run_format: dict[str, Any]) -> dict[str, Any]:
    blocker = {
        "passed": False,
        "evidence": {
            "format_status": run_format.get("format_status"),
            "format_name": run_format.get("format_name"),
            "format_version": run_format.get("format_version"),
            "missing_manifests": list(run_format.get("missing_manifests") or []),
            "invalid_manifests": list(run_format.get("invalid_manifests") or []),
        },
    }
    return {
        "passed": False,
        "ready_for_use": False,
        "commercial_delivery_ready": False,
        "checks": {"run_format_verified": False},
        "blocking_checks": {"run_format_verified": blocker},
        "failed_blockers": [{"id": "run_format_verified", **blocker}],
        "advisory_checks": {},
        "run_format": run_format,
        "content_readiness": {"ready_for_use": False, "checks": {}},
        "content_safety": {
            "passed": False,
            "copyright_overlap": {
                "passed": False,
                "longest_overlap_chars": 0,
                "overall_copied_ratio": 0.0,
                "failed_files": [],
            },
            "encoding": {"passed": False, "failed_files": []},
        },
        "evidence_integrity": {"valid": False, "counts": {}},
        "evaluator_verdict": {"passed": False},
        "schema_validation": {},
        "computed_from": {},
        "freshness": {
            "fresh": False,
            "stale_artifacts": [],
            "repair_command": run_format["recommended_action"]["command"],
        },
        "governance": {
            "ready_for_use": False,
            "commercial_delivery_ready": False,
            "checks": {},
        },
        "stage_coverage": {},
        "missing_files": [],
        "transcript_count": 0,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "note": (
            "Quality evaluation was not executed because the run format is not verified. "
            "The legacy run was not modified."
        ),
    }


def creator_quality_check(
    run_dir: Path,
    *,
    content_readiness_fn: Callable[..., dict[str, Any]] | None = None,
    stage_coverage_fn: Callable[[Path], dict[str, Any]] | None = None,
) -> dict:
    run_format = run_diagnostics.inspect_run_structure(run_dir)
    if not run_format["format_verified"]:
        return _unverified_run_quality_report(run_format)

    skill_dir = run_dir / "skill"
    required_files = [
        skill_dir / "SKILL.md",
        skill_dir / "references" / "persona.md",
        skill_dir / "references" / "topic_model.md",
        skill_dir / "references" / "script_style.md",
        skill_dir / "references" / "research_summary.md",
        skill_dir / "references" / "evidence_index.md",
        skill_dir / "references" / "meta.json",
    ]
    missing_files = [str(path.relative_to(run_dir)) for path in required_files if not path.exists()]
    text_blobs = []
    for path in required_files:
        if path.exists() and path.suffix.lower() in {".md", ".txt"}:
            text_blobs.append(path.read_text(encoding="utf-8", errors="replace"))
    combined = "\n\n".join(text_blobs)
    transcript_files = path_policy.artifact_files(run_dir / "transcripts", ".txt")
    content_safety_report = content_safety.evaluate_run_content_safety(
        run_dir,
        transcript_paths=transcript_files,
    )
    config_snapshot = run_dir / "config.snapshot.json"
    selected_metadata = run_dir / "metadata" / "selected.json"
    selected_compact = run_dir / "metadata" / "selected.compact.json"
    creator_profile = run_dir / "metadata" / "creator_profile.json"
    research_summary = run_dir / "research" / "merged" / "summary.md"
    freshness_report = quality_engine.evaluate_refinement_freshness(run_dir)
    readiness_impl = content_readiness_fn or creator_content_readiness
    readiness = readiness_impl(
        skill_dir,
        run_dir,
        freshness_report=freshness_report,
    )
    stage_coverage = (stage_coverage_fn or evaluate_stage_coverage)(run_dir)
    governance = provenance.evaluate_run_governance(run_dir)

    checks = {
        "content_safety_passed": content_safety_report["passed"] is True,
        "required_files": not missing_files,
        "has_disclaimer": bool(re.search(r"disclaimer|does not represent|不代表|免责声明", combined, re.IGNORECASE)),
        "has_safety_boundary": bool(re.search(r"safety|identity deception|冒充|clone|克隆|边界", combined, re.IGNORECASE)),
        "has_evidence_index": (skill_dir / "references" / "evidence_index.md").exists()
        and (skill_dir / "references" / "evidence_index.md").stat().st_size > 20,
        "no_transcript_dump": bool(
            content_safety_report["copyright_overlap"].get("passed")
        ),
        "has_transcripts": bool(transcript_files),
        "has_config_snapshot": config_snapshot.exists(),
        "has_selected_metadata": selected_metadata.exists(),
        "has_selected_compact_metadata": selected_compact.exists(),
        "has_creator_profile": creator_profile.exists(),
        "has_research_summary": research_summary.exists() and research_summary.stat().st_size > 20,
        "no_mojibake": bool(content_safety_report["encoding"].get("passed")),
        "stage_coverage_draft": stage_coverage["draft"]["passed"],
    }
    outcome = quality_engine.compose_readiness_semantics(
        deterministic_checks=checks,
        content_readiness=readiness,
        stage_coverage=stage_coverage,
        governance=governance,
        freshness=freshness_report["freshness"],
        schema_validation=readiness.get("schema_validation", {}),
        evidence_integrity=readiness.get("evidence_integrity", {}),
        evaluator_verdict=readiness.get("evaluator_verdict", {}),
        advisory_checks=readiness.get("advisory_checks", {}),
        run_format=run_format,
    )
    report_computed_from = {
        **freshness_report["computed_from"],
        "content_safety": content_safety_report["computed_from"],
    }
    report = {
        **outcome,
        "checks": checks,
        "content_readiness": readiness,
        "content_safety": content_safety_report,
        "evidence_integrity": readiness.get("evidence_integrity", {}),
        "evaluator_verdict": readiness.get("evaluator_verdict", {}),
        "schema_validation": readiness.get("schema_validation", {}),
        "run_format": run_format,
        "computed_from": report_computed_from,
        "freshness": freshness_report["freshness"],
        "governance": governance,
        "stage_coverage": stage_coverage,
        "missing_files": missing_files,
        "transcript_count": len(transcript_files),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json(run_dir / "logs" / "creator_quality_report.json", report)
    return report


def creator_quality_check_step(run_dir: Path) -> tuple[StepResult, dict]:
    started = time.monotonic()
    report = creator_quality_check(run_dir)
    duration_ms = round((time.monotonic() - started) * 1000)
    output_path = run_dir / "logs" / "creator_quality_report.json"
    output_paths = (str(output_path),) if output_path.exists() else ()
    if report.get("passed"):
        result = StepResult.succeeded(
            "quality_check",
            duration_ms=duration_ms,
            output_paths=output_paths,
        )
    else:
        issues = tuple(f"{name}=false" for name, passed in report.get("checks", {}).items() if not passed)
        result = StepResult.failed(
            "quality_check",
            duration_ms=duration_ms,
            output_paths=output_paths,
            issues=issues,
        )
    return result, report
def raw_research_note_stats(run_dir: Path) -> dict:
    raw_dir = run_dir / "research" / "raw"
    notes = sorted(raw_dir.glob("*.md")) if raw_dir.exists() else []
    substantial = [path for path in notes if path.stat().st_size >= 1200]
    return {
        "count": len(notes),
        "substantial_count": len(substantial),
        "files": [str(path.relative_to(run_dir)) for path in notes],
    }


def _valid_transcript_phrase_contract(payload: dict[str, Any]) -> bool:
    phrase_analysis = payload.get("phrase_analysis")
    signals = payload.get("signals")
    if not isinstance(phrase_analysis, dict) or not isinstance(signals, list):
        return False
    if not (
        phrase_analysis.get("schema_version") == 1
        and phrase_analysis.get("algorithm_version")
        == text_analysis.TEXT_ANALYSIS_VERSION
        and phrase_analysis.get("tokenizer_name") == text_analysis.TOKENIZER_NAME
        and phrase_analysis.get("tokenizer_version")
        == text_analysis.TOKENIZER_VERSION
        and phrase_analysis.get("tokenizer_mode") == text_analysis.TOKENIZER_MODE
        and phrase_analysis.get("stopword_version")
        == text_analysis.STOPWORD_VERSION
        and phrase_analysis.get("minimum_video_appearances")
        == text_analysis.MINIMUM_VIDEO_APPEARANCES
    ):
        return False
    candidates = phrase_analysis.get("candidates")
    if not isinstance(candidates, list) or phrase_analysis.get(
        "candidate_count"
    ) != len(candidates):
        return False
    phrases_by_video: dict[str, set[str]] = {}
    seen_phrases: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            return False
        phrase = candidate.get("phrase")
        video_ids = candidate.get("representative_video_ids")
        fragments = candidate.get("source_fragment_ids")
        document_frequency = candidate.get("document_frequency")
        total_frequency = candidate.get("total_frequency")
        confidence = candidate.get("confidence")
        if not (
            isinstance(phrase, str)
            and phrase.strip()
            and phrase not in seen_phrases
            and isinstance(video_ids, list)
            and all(isinstance(video_id, str) and video_id for video_id in video_ids)
            and len(video_ids) == len(set(video_ids))
            and isinstance(document_frequency, int)
            and not isinstance(document_frequency, bool)
            and document_frequency == len(video_ids)
            and document_frequency >= text_analysis.MINIMUM_VIDEO_APPEARANCES
            and isinstance(total_frequency, int)
            and not isinstance(total_frequency, bool)
            and total_frequency >= document_frequency
            and isinstance(fragments, list)
            and bool(fragments)
            and all(
                isinstance(fragment, str)
                and any(fragment.startswith(f"{video_id}#") for video_id in video_ids)
                for fragment in fragments
            )
            and all(
                any(fragment.startswith(f"{video_id}#") for fragment in fragments)
                for video_id in video_ids
            )
            and isinstance(confidence, dict)
            and confidence.get("level") in {"low", "medium", "high"}
        ):
            return False
        seen_phrases.add(phrase)
        for video_id in video_ids:
            phrases_by_video.setdefault(video_id, set()).add(phrase)
    for signal in signals:
        if not isinstance(signal, dict):
            return False
        video_id = signal.get("video_id")
        reusable_phrases = signal.get("reusable_phrases")
        if not (
            isinstance(video_id, str)
            and isinstance(reusable_phrases, list)
            and all(isinstance(phrase, str) for phrase in reusable_phrases)
            and set(reusable_phrases) == phrases_by_video.get(video_id, set())
        ):
            return False
    return True


def host_refinement_stats(
    run_dir: Path,
    freshness: dict[str, Any] | None = None,
    *,
    evidence_integrity: dict[str, Any] | None = None,
    evaluator_verdict: dict[str, Any] | None = None,
) -> dict:
    refinement_dir = run_dir / "research" / "host_refinement"
    reviews_dir = run_dir / "research" / "reviews"
    brief = refinement_dir / "brief.md"
    corpus_index = refinement_dir / "corpus_index.json"
    topic_candidates_report = refinement_dir / "topic_candidates.json"
    signal_matrix = refinement_dir / "transcript_signal_matrix.md"
    transcript_signals = refinement_dir / "transcript_signals.json"
    coverage_report = reviews_dir / "evidence_coverage.json"
    coverage_gaps_report = reviews_dir / "coverage_gaps.json"
    short_form_report = reviews_dir / "short_form_coverage.json"
    timeline_report = reviews_dir / "timeline_shift.json"
    entity_report = reviews_dir / "asr_entity_review.json"
    entity_decisions_report = reviews_dir / "asr_entity_decisions.json"
    topic_decisions_report = reviews_dir / "topic_candidate_decisions.json"
    audit = reviews_dir / "refinement_audit.md"
    usage_probe = reviews_dir / "usage_probe.md"
    evaluation_suite = reviews_dir / "evaluation_suite.md"
    evaluation_suite_json = reviews_dir / "evaluation_suite.json"
    evaluation_suite_schema = reviews_dir / "evaluation_suite.schema.json"
    reverse_identification = reviews_dir / "reverse_identification.md"
    reverse_identification_json = reviews_dir / "reverse_identification.json"
    reverse_identification_schema = reviews_dir / "reverse_identification.schema.json"
    reviewer_findings = reviews_dir / "reviewer_findings.md"
    evaluation_schema_validation = schema_validation.validate_json_file(
        evaluation_suite_json,
        evaluation_suite_schema,
        artifact="evaluation_suite",
    )
    reverse_schema_validation = schema_validation.validate_json_file(
        reverse_identification_json,
        reverse_identification_schema,
        artifact="reverse_identification",
    )
    integrity_by_artifact = (evidence_integrity or {}).get("artifact_validity") or {}

    freshness_artifacts = (freshness or {}).get("artifacts") or {}

    def derived_is_fresh(name: str, path: Path) -> bool:
        state = freshness_artifacts.get(name)
        if isinstance(state, dict):
            return bool(state.get("fresh"))
        return artifacts.inspect_artifact(path).reusable

    corpus_record_count = 0
    corpus_transcript_count = 0
    if corpus_index.exists():
        try:
            corpus = read_json(corpus_index)
            corpus_record_count = len(corpus.get("records") or [])
            corpus_transcript_count = int((corpus.get("coverage") or {}).get("transcript_count") or 0)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            corpus_record_count = 0
            corpus_transcript_count = 0

    transcript_signal_count = 0
    transcript_signals_valid = False
    if transcript_signals.exists():
        try:
            signal_payload = read_json(transcript_signals)
            transcript_signal_count = int((signal_payload.get("summary") or {}).get("signal_count") or 0)
            transcript_signals_valid = _valid_transcript_phrase_contract(
                signal_payload
            )
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            transcript_signal_count = 0
            transcript_signals_valid = False

    topic_candidates_valid = False
    topic_candidate_ids: list[str] = []
    topic_algorithm_version = ""
    if topic_candidates_report.exists():
        try:
            topic_payload = read_json(topic_candidates_report)
            raw_candidates = topic_payload.get("candidates")
            topic_candidate_ids = [
                str(candidate.get("candidate_id"))
                for candidate in raw_candidates
                if isinstance(candidate, dict) and candidate.get("candidate_id")
            ]
            topic_algorithm_version = str(
                topic_payload.get("algorithm_version") or ""
            )
            topic_candidates_valid = bool(
                isinstance(raw_candidates, list)
                and len(topic_candidate_ids) == len(raw_candidates)
                and int(topic_payload.get("candidate_count") or 0)
                == len(raw_candidates)
                and topic_payload.get("classification_status")
                in {"candidate_topics", "unclassified"}
                and isinstance(topic_payload.get("overall_confidence"), dict)
                and topic_algorithm_version
            )
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            topic_candidates_valid = False
            topic_candidate_ids = []
            topic_algorithm_version = ""

    topic_decisions_valid = False
    if topic_decisions_report.exists():
        try:
            decisions_payload = read_json(topic_decisions_report)
            source = decisions_payload.get("source") or {}
            allowed = decisions_payload.get("allowed_decisions")
            decisions = decisions_payload.get("decisions")
            allowed_set = {"accepted", "renamed", "merged", "rejected"}
            topic_decisions_valid = bool(
                isinstance(source, dict)
                and source.get("algorithm_version") == topic_algorithm_version
                and source.get("candidate_ids") == topic_candidate_ids
                and isinstance(allowed, list)
                and set(allowed) == allowed_set
                and isinstance(decisions, list)
                and all(
                    isinstance(decision, dict)
                    and decision.get("candidate_id") in topic_candidate_ids
                    and decision.get("decision") in allowed_set
                    and all(
                        str(decision.get(field) or "").strip()
                        for field in ("reason", "reviewed_by", "reviewed_at")
                    )
                    and (
                        decision.get("decision") != "renamed"
                        or bool(str(decision.get("replacement_label") or "").strip())
                    )
                    and (
                        decision.get("decision") != "merged"
                        or (
                            decision.get("merged_into_candidate_id")
                            in topic_candidate_ids
                            and decision.get("merged_into_candidate_id")
                            != decision.get("candidate_id")
                        )
                    )
                    for decision in decisions
                )
            )
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            topic_decisions_valid = False

    coverage_score = 0.0
    covered_video_count = 0
    coverage_gap_count = 0
    if coverage_report.exists():
        try:
            coverage_payload = read_json(coverage_report)
            coverage_score = float(coverage_payload.get("overall_score") or 0.0)
            covered_video_count = int(coverage_payload.get("covered_video_count") or 0)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            coverage_score = 0.0
            covered_video_count = 0
    if coverage_gaps_report.exists():
        try:
            coverage_gaps_payload = read_json(coverage_gaps_report)
            coverage_gap_count = int(coverage_gaps_payload.get("recommendation_count") or 0)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            coverage_gap_count = 0

    current = (freshness or {}).get("current") or {}
    current_corpus = current.get("corpus_index") or {}
    current_signals = current.get("transcript_signals") or {}
    current_coverage = current.get("evidence_coverage") or {}
    if current_corpus:
        current_corpus_coverage = current_corpus.get("coverage") or {}
        corpus_record_count = int(
            current_corpus.get("record_count")
            or len(current_corpus.get("records") or [])
        )
        corpus_transcript_count = int(
            current_corpus_coverage.get("transcript_count") or 0
        )
    if current_signals:
        transcript_signal_count = int(
            (current_signals.get("summary") or {}).get("signal_count") or 0
        )
    if current_coverage:
        coverage_score = float(current_coverage.get("overall_score") or 0.0)
        covered_video_count = int(
            current_coverage.get("covered_video_count") or 0
        )

    short_form_count = 0
    if short_form_report.exists():
        try:
            short_form_payload = read_json(short_form_report)
            short_form_count = int(short_form_payload.get("short_form_count") or 0)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            short_form_count = 0

    timeline_period_count = 0
    if timeline_report.exists():
        try:
            timeline_payload = read_json(timeline_report)
            timeline_period_count = len(timeline_payload.get("periods") or [])
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            timeline_period_count = 0

    entity_candidate_count = 0
    entity_review_required = False
    entity_report_valid = False
    entity_review_assessment: dict[str, Any] = {
        "valid": False,
        "complete": False,
        "review_required": False,
        "candidate_count": 0,
        "processed_count": 0,
        "status_counts": {status: 0 for status in entity_review.ALLOWED_STATUSES},
        "blocker_count": 1,
        "warning_count": 0,
        "blocking_reasons": ["entity_review_artifacts_missing"],
        "warnings": [],
        "decision_errors": [],
        "unresolved_high_impact_candidate_ids": [],
        "unresolved_warning_candidate_ids": [],
        "correction_mappings": [],
    }
    if entity_report.exists() and entity_decisions_report.exists():
        try:
            entity_payload = read_json(entity_report)
            entity_decisions_payload = read_json(entity_decisions_report)
            entity_review_assessment = entity_review.evaluate_entity_review(
                entity_payload,
                entity_decisions_payload,
                run_dir=run_dir,
            )
            entity_report_valid = bool(entity_review_assessment.get("valid"))
            entity_review_required = bool(
                entity_review_assessment.get("review_required")
            )
            raw_entity_candidate_count = entity_review_assessment.get(
                "candidate_count"
            )
            entity_candidate_count = (
                raw_entity_candidate_count
                if isinstance(raw_entity_candidate_count, int)
                else 0
            )
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            entity_candidate_count = 0
            entity_review_required = False
            entity_report_valid = False

    signal_text = signal_matrix.read_text(encoding="utf-8", errors="replace") if signal_matrix.exists() else ""
    audit_text = audit.read_text(encoding="utf-8", errors="replace") if audit.exists() else ""
    usage_text = usage_probe.read_text(encoding="utf-8", errors="replace") if usage_probe.exists() else ""
    evaluation_text = evaluation_suite.read_text(encoding="utf-8", errors="replace") if evaluation_suite.exists() else ""
    reverse_text = (
        reverse_identification.read_text(encoding="utf-8", errors="replace")
        if reverse_identification.exists()
        else ""
    )
    reviewer_text = reviewer_findings.read_text(encoding="utf-8", errors="replace") if reviewer_findings.exists() else ""
    audit_recommends_ready = bool(
        re.search(r"是否建议\s*`?ready_for_use=true`?\s*[：:]\s*(是|yes|true)", audit_text, re.IGNORECASE)
    )
    audit_template_unfilled = "- [ ]" in audit_text or bool(
        re.search(r"审计人\s*[：:]\s*$|审计时间\s*[：:]\s*$|仍需补强\s*[：:]\s*$", audit_text, re.MULTILINE)
    )
    usage_probe_passed = bool(re.search(r"是否通过反向生成测试\s*[：:]\s*(是|yes|true)", usage_text, re.IGNORECASE))
    usage_probe_template_unfilled = bool(
        re.search(
            r"输入候选\s*[：:]\s*$|改写结果\s*[：:]\s*$|待批评片段\s*[：:]\s*$|选题\s*[：:]\s*$|使用的 persona_model 字段\s*[：:]\s*$",
            usage_text,
            re.MULTILINE,
        )
    )
    evaluation_suite_passed = bool(re.search(r"是否通过评测集\s*[：:]\s*(是|yes|true)", evaluation_text, re.IGNORECASE))
    evaluation_suite_template_unfilled = bool(
        re.search(r"输入候选\s*[：:]\s*$|输入选题\s*[：:]\s*$|原始文案\s*[：:]\s*$|待评估文本\s*[：:]\s*$", evaluation_text, re.MULTILINE)
    ) or bool(re.search(r"6 个 case 是否全部完成\s*[：:]\s*(否|no|false)", evaluation_text, re.IGNORECASE))
    reverse_identification_passed = bool(
        re.search(r"是否通过反向识别测试\s*[：:]\s*(是|yes|true)", reverse_text, re.IGNORECASE)
    )
    reverse_identification_template_unfilled = "|  |  |  |  |  |  |" in reverse_text or bool(
        re.search(r"至少识别 5 个 creator-specific marker\s*[：:]\s*(否|no|false)", reverse_text, re.IGNORECASE)
    )
    evaluator_artifacts = (evaluator_verdict or {}).get("artifacts") or {}
    evaluation_artifact = evaluator_artifacts.get("evaluation_suite") or {}
    reverse_artifact = evaluator_artifacts.get("reverse_identification") or {}
    evaluation_suite_json_ready = evaluation_artifact.get("passed") is True
    reverse_identification_json_ready = reverse_artifact.get("passed") is True
    reviewer_recommends_ready = bool(
        re.search(r"是否建议进入\s*`?ready_for_use=true`?\s*[：:]\s*(是|yes|true)", reviewer_text, re.IGNORECASE)
    )
    reviewer_template_unfilled = "|  |  |  |  |  |  |" in reviewer_text or bool(
        re.search(r"是否处理全部 high / medium 问题\s*[：:]\s*$", reviewer_text, re.MULTILINE)
    )

    checks = {
        "brief_present": brief.exists() and brief.stat().st_size >= 1000,
        "derived_artifacts_fresh": bool(
            freshness is not None and freshness.get("fresh") is True
        ),
        "corpus_index_present": corpus_record_count > 0
        and corpus_transcript_count > 0
        and derived_is_fresh("corpus_index", corpus_index),
        "topic_candidates_present": topic_candidates_report.exists()
        and topic_candidates_report.stat().st_size > 100
        and topic_candidates_valid
        and derived_is_fresh("topic_candidates", topic_candidates_report),
        "topic_candidate_decisions_present": topic_decisions_report.exists()
        and topic_decisions_report.stat().st_size > 100
        and topic_decisions_valid,
        "signal_matrix_present": signal_matrix.exists()
        and signal_matrix.stat().st_size >= 1000
        and derived_is_fresh("transcript_signal_matrix", signal_matrix)
        and "Per-Video Signals" in signal_text,
        "transcript_signals_present": transcript_signal_count > 0
        and transcript_signals_valid
        and derived_is_fresh("transcript_signals", transcript_signals),
        "evidence_coverage_present": coverage_report.exists()
        and derived_is_fresh("evidence_coverage", coverage_report)
        and covered_video_count >= min(15, max(1, corpus_record_count))
        and coverage_score >= 0.45,
        "coverage_gaps_present": coverage_gaps_report.exists()
        and coverage_gaps_report.stat().st_size > 100
        and coverage_gap_count >= 0,
        "short_form_coverage_present": short_form_report.exists() and short_form_report.stat().st_size > 100,
        "timeline_shift_present": timeline_report.exists()
        and timeline_report.stat().st_size > 100
        and timeline_period_count >= min(2, max(1, corpus_record_count)),
        "asr_entity_review_present": entity_report.exists()
        and entity_decisions_report.exists()
        and entity_report.stat().st_size > 100
        and entity_decisions_report.stat().st_size > 100
        and entity_report_valid
        and derived_is_fresh("asr_entity_review", entity_report),
        "asr_entity_review_complete": bool(
            entity_review_assessment.get("complete")
        ),
        "usage_probe_filled": usage_probe.exists()
        and usage_probe.stat().st_size >= 700
        and not usage_probe_template_unfilled,
        "evaluation_suite_filled": evaluation_suite.exists()
        and evaluation_suite.stat().st_size >= 900
        and evaluation_suite_schema.exists()
        and evaluation_suite_json.exists()
        and not evaluation_suite_template_unfilled,
        "evaluation_suite_json_filled": evaluation_suite_json_ready,
        "evaluation_suite_schema_valid": bool(evaluation_schema_validation["schema_valid"]),
        "evaluation_suite_json_schema_valid": bool(evaluation_schema_validation["valid"]),
        "evaluation_suite_evidence_integrity": bool(
            integrity_by_artifact.get("evaluation_suite")
        ),
        "reverse_identification_filled": reverse_identification.exists()
        and reverse_identification.stat().st_size >= 700
        and reverse_identification_schema.exists()
        and reverse_identification_json.exists()
        and not reverse_identification_template_unfilled,
        "reverse_identification_json_filled": reverse_identification_json_ready,
        "reverse_identification_schema_valid": bool(reverse_schema_validation["schema_valid"]),
        "reverse_identification_json_schema_valid": bool(reverse_schema_validation["valid"]),
        "reverse_identification_evidence_integrity": bool(
            integrity_by_artifact.get("reverse_identification")
        ),
        "reviewer_findings_filled": reviewer_findings.exists()
        and reviewer_findings.stat().st_size >= 500
        and not reviewer_template_unfilled,
        "refinement_audit_filled": audit.exists()
        and audit.stat().st_size >= 500
        and not audit_template_unfilled,
    }
    evaluation_declarations = evaluation_artifact.get("declarations") or {}
    reverse_declarations = reverse_artifact.get("declarations") or {}
    advisory_checks = {
        "usage_probe_declares_passed": {
            "passed": usage_probe_passed,
            "evidence": {"source": "research/reviews/usage_probe.md"},
        },
        "evaluation_markdown_declares_passed": {
            "passed": evaluation_suite_passed,
            "evidence": {"source": "research/reviews/evaluation_suite.md"},
        },
        "evaluation_scorecard_declares_passed": {
            "passed": evaluation_declarations.get("scorecard_passed") is True,
            "evidence": {"source": "research/reviews/evaluation_suite.json"},
        },
        "reverse_markdown_declares_passed": {
            "passed": reverse_identification_passed,
            "evidence": {"source": "research/reviews/reverse_identification.md"},
        },
        "reverse_scorecard_declares_passed": {
            "passed": reverse_declarations.get("scorecard_passed") is True,
            "evidence": {
                "source": "research/reviews/reverse_identification.json"
            },
        },
        "reviewer_recommends_ready": {
            "passed": reviewer_recommends_ready,
            "evidence": {"source": "research/reviews/reviewer_findings.md"},
        },
        "audit_recommends_ready": {
            "passed": audit_recommends_ready,
            "evidence": {"source": "research/reviews/refinement_audit.md"},
        },
    }
    return {
        "checks": checks,
        "ready": all(checks.values()),
        "advisory_checks": advisory_checks,
        "schema_validation": {
            "evaluation_suite": evaluation_schema_validation,
            "reverse_identification": reverse_schema_validation,
        },
        "files": {
            "brief": str(brief.relative_to(run_dir)) if brief.exists() else "",
            "corpus_index": str(corpus_index.relative_to(run_dir)) if corpus_index.exists() else "",
            "topic_candidates": str(topic_candidates_report.relative_to(run_dir))
            if topic_candidates_report.exists()
            else "",
            "topic_candidate_decisions": str(
                topic_decisions_report.relative_to(run_dir)
            )
            if topic_decisions_report.exists()
            else "",
            "signal_matrix": str(signal_matrix.relative_to(run_dir)) if signal_matrix.exists() else "",
            "transcript_signals": str(transcript_signals.relative_to(run_dir)) if transcript_signals.exists() else "",
            "evidence_coverage": str(coverage_report.relative_to(run_dir)) if coverage_report.exists() else "",
            "coverage_gaps": str(coverage_gaps_report.relative_to(run_dir)) if coverage_gaps_report.exists() else "",
            "short_form_coverage": str(short_form_report.relative_to(run_dir)) if short_form_report.exists() else "",
            "timeline_shift": str(timeline_report.relative_to(run_dir)) if timeline_report.exists() else "",
            "asr_entity_review": str(entity_report.relative_to(run_dir)) if entity_report.exists() else "",
            "asr_entity_decisions": str(
                entity_decisions_report.relative_to(run_dir)
            )
            if entity_decisions_report.exists()
            else "",
            "audit": str(audit.relative_to(run_dir)) if audit.exists() else "",
            "usage_probe": str(usage_probe.relative_to(run_dir)) if usage_probe.exists() else "",
            "evaluation_suite": str(evaluation_suite.relative_to(run_dir)) if evaluation_suite.exists() else "",
            "evaluation_suite_json": str(evaluation_suite_json.relative_to(run_dir)) if evaluation_suite_json.exists() else "",
            "reverse_identification": str(reverse_identification.relative_to(run_dir)) if reverse_identification.exists() else "",
            "reverse_identification_json": str(reverse_identification_json.relative_to(run_dir)) if reverse_identification_json.exists() else "",
            "reviewer_findings": str(reviewer_findings.relative_to(run_dir)) if reviewer_findings.exists() else "",
        },
        "corpus_record_count": corpus_record_count,
        "corpus_transcript_count": corpus_transcript_count,
        "transcript_signal_count": transcript_signal_count,
        "topic_candidate_count": len(topic_candidate_ids),
        "covered_video_count": covered_video_count,
        "coverage_score": coverage_score,
        "coverage_gap_count": coverage_gap_count,
        "short_form_count": short_form_count,
        "timeline_period_count": timeline_period_count,
        "entity_candidate_count": entity_candidate_count,
        "entity_review_required": entity_review_required,
        "entity_review": entity_review_assessment,
        "freshness": freshness or {},
    }
