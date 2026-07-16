#!/usr/bin/env python3
"""Reusable, credential-free scenarios for the offline self-test and pytest."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import build_creator_skill
from io_utils import atomic_write_json as write_json


ScenarioName = Literal[
    "happy",
    "partial_transcript",
    "no_transcript",
    "empty_metadata",
    "malformed_metadata",
]

FIRST_VIDEO_ID = "190000000000000101"
SECOND_VIDEO_ID = "190000000000000102"


@dataclass(frozen=True)
class OfflineRunResult:
    """Captured state from one deterministic runner invocation."""

    scenario: str
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    run_dir: Path | None
    quality: dict[str, Any]
    summary: dict[str, Any]
    workflow: dict[str, Any]
    selected: dict[str, Any]
    compact: dict[str, Any]
    creator_profile: dict[str, Any]


@dataclass(frozen=True)
class HostRefinementResult:
    """Captured outputs from host-refinement preparation and quality recheck."""

    prepare_returncode: int
    quality_returncode: int
    stdout: str
    stderr: str
    quality: dict[str, Any]
    persona_schema: dict[str, Any]
    persona_model: dict[str, Any]
    evaluation_schema: dict[str, Any]
    reverse_identification_schema: dict[str, Any]


@dataclass(frozen=True)
class OfflineSelfTestResult:
    """Complete happy-path result shared by the CLI and integration test."""

    baseline: OfflineRunResult
    refinement: HostRefinementResult


class OfflineScenarioError(RuntimeError):
    """Raised when the reusable offline self-test contract is violated."""


HOST_REFINEMENT_ARTIFACTS = (
    "research/host_refinement/brief.md",
    "research/host_refinement/corpus_index.json",
    "research/host_refinement/transcript_signal_matrix.md",
    "research/host_refinement/transcript_signals.json",
    "research/host_refinement/transcript_signals.md",
    "research/reviews/evidence_coverage.json",
    "research/reviews/evidence_coverage.md",
    "research/reviews/coverage_gaps.json",
    "research/reviews/coverage_gaps.md",
    "research/reviews/short_form_coverage.json",
    "research/reviews/short_form_coverage.md",
    "research/reviews/timeline_shift.json",
    "research/reviews/timeline_shift.md",
    "research/entity_dictionary.json",
    "research/reviews/asr_entity_review.json",
    "research/reviews/asr_entity_review.md",
    "research/reviews/asr_entity_decisions.json",
    "research/reviews/usage_probe.md",
    "research/reviews/evaluation_suite.md",
    "research/reviews/evaluation_suite.schema.json",
    "research/reviews/evaluation_suite.json",
    "research/reviews/reverse_identification.md",
    "research/reviews/reverse_identification.schema.json",
    "research/reviews/reverse_identification.json",
    "research/reviews/reviewer_findings.md",
    "research/reviews/refinement_audit.md",
    "skill/references/persona_model.schema.json",
    "skill/references/persona_model.json",
)


def read_json_if_present(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def synthetic_metadata() -> dict[str, Any]:
    author = {
        "nickname": "离线测试创作者",
        "unique_id": "offline-synthetic",
        "uid": "author-synthetic-001",
        "sec_uid": "sec-synthetic-001",
    }
    return {
        "data": {
            "aweme_list": [
                {
                    "aweme_id": FIRST_VIDEO_ID,
                    "desc": "人工样本：把复杂任务拆成可以验证的小步骤",
                    "create_time": 1767312000,
                    "statistics": {
                        "digg_count": 10,
                        "collect_count": 2,
                        "share_count": 1,
                        "comment_count": 3,
                    },
                    "video": {
                        "play_addr": {
                            "url_list": ["https://media.example.invalid/video/offline-101.mp4"]
                        }
                    },
                    "share_url": "https://share.example.invalid/offline-101",
                    "author": author,
                },
                {
                    "aweme_id": SECOND_VIDEO_ID,
                    "desc": "人工样本：用反例检查结论是否真的成立",
                    "create_time": 1767225600,
                    "statistics": {
                        "digg_count": 8,
                        "collect_count": 1,
                        "share_count": 2,
                        "comment_count": 4,
                    },
                    "video": {
                        "play_addr": {
                            "url_list": ["https://media.example.invalid/video/offline-102.mp4"]
                        }
                    },
                    "share_url": "https://share.example.invalid/offline-102",
                    "author": author,
                },
            ]
        }
    }


def synthetic_transcripts() -> dict[str, str]:
    return {
        FIRST_VIDEO_ID: "\n".join(
            [
                "[00:00:00] 这是人工构造的离线测试语料，先把目标拆成可以观察的结果。",
                "[00:00:05] 接着一次只改变一个条件，并记录每一步的输入与输出。",
                "[00:00:11] 如果结果与预期不同，就回到证据，而不是用一句看起来合理的话掩盖问题。",
            ]
        )
        + "\n",
        SECOND_VIDEO_ID: "\n".join(
            [
                "[00:00:00] 第二段也是人工构造的短文本，用来验证部分转写与完整转写的差异。",
                "[00:00:06] 一个结论至少要经得起反例检查，还要说明哪些材料没有覆盖。",
                "[00:00:12] 当证据不足时，应降低置信度并保留后续补充入口。",
            ]
        )
        + "\n",
    }


def offline_subprocess_env() -> dict[str, str]:
    """Return a deterministic environment without provider credentials."""

    env = os.environ.copy()
    for key in build_creator_skill.CONFIG_KEYS:
        env.pop(key, None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def prepare_scenario_inputs(work_root: Path, scenario: ScenarioName) -> tuple[Path, Path | None]:
    input_dir = work_root / "input"
    raw_metadata = input_dir / "raw.json"
    transcript_dir = input_dir / "transcripts"
    input_dir.mkdir(parents=True, exist_ok=True)

    if scenario == "malformed_metadata":
        raw_metadata.write_text('{"data": {"aweme_list": [', encoding="utf-8")
        return raw_metadata, None
    if scenario == "empty_metadata":
        write_json(raw_metadata, {"data": {"aweme_list": []}})
        return raw_metadata, None

    write_json(raw_metadata, synthetic_metadata())
    transcripts = synthetic_transcripts()
    selected_ids: tuple[str, ...]
    if scenario == "happy":
        selected_ids = (FIRST_VIDEO_ID, SECOND_VIDEO_ID)
    elif scenario == "partial_transcript":
        selected_ids = (FIRST_VIDEO_ID,)
    else:
        selected_ids = ()

    for video_id in selected_ids:
        path = transcript_dir / f"{video_id}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(transcripts[video_id], encoding="utf-8")
    return raw_metadata, transcript_dir if selected_ids else None


def _run_offline_inputs(
    project_root: Path,
    work_root: Path,
    *,
    scenario: str,
    raw_metadata: Path,
    transcript_dir: Path | None,
    project_name: str,
    sample_count: int,
    source_url: str,
    taxonomy_preset: str | None = None,
) -> OfflineRunResult:
    """Run the canonical offline process for already prepared local inputs."""

    work_root.mkdir(parents=True, exist_ok=True)
    run_root = work_root / "runs"
    runner = project_root / "scripts" / "run_creator_skill_build.py"
    command = [
        sys.executable,
        str(runner),
        "--source-url",
        source_url,
        "--project-name",
        project_name,
        "--sample-count",
        str(sample_count),
        "--raw-metadata",
        str(raw_metadata),
        "--skip-download",
        "--skip-audio",
        "--skip-asr",
        "--skip-llm-research",
        "--run-root",
        str(run_root),
    ]
    if transcript_dir is not None:
        command.extend(["--transcripts-dir", str(transcript_dir)])
    if taxonomy_preset is not None:
        command.extend(["--taxonomy-preset", taxonomy_preset])

    process = subprocess.run(
        command,
        cwd=project_root,
        env=offline_subprocess_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    project_run_root = run_root / build_creator_skill.slugify(project_name)
    run_dirs = sorted(path for path in project_run_root.iterdir() if path.is_dir()) if project_run_root.exists() else []
    run_dir = run_dirs[-1] if run_dirs else None
    if run_dir is None:
        return OfflineRunResult(
            scenario=scenario,
            command=tuple(command),
            returncode=process.returncode,
            stdout=process.stdout,
            stderr=process.stderr,
            run_dir=None,
            quality={},
            summary={},
            workflow={},
            selected={},
            compact={},
            creator_profile={},
        )

    return OfflineRunResult(
        scenario=scenario,
        command=tuple(command),
        returncode=process.returncode,
        stdout=process.stdout,
        stderr=process.stderr,
        run_dir=run_dir,
        quality=read_json_if_present(run_dir / "logs" / "creator_quality_report.json"),
        summary=read_json_if_present(run_dir / "run_summary.json"),
        workflow=read_json_if_present(run_dir / "workflow.plan.json"),
        selected=read_json_if_present(run_dir / "metadata" / "selected.json"),
        compact=read_json_if_present(run_dir / "metadata" / "selected.compact.json"),
        creator_profile=read_json_if_present(run_dir / "metadata" / "creator_profile.json"),
    )


def run_offline_scenario(
    project_root: Path,
    work_root: Path,
    scenario: ScenarioName,
) -> OfflineRunResult:
    """Run one built-in offline scenario and capture its durable outputs."""

    work_root.mkdir(parents=True, exist_ok=True)
    raw_metadata, transcript_dir = prepare_scenario_inputs(work_root, scenario)
    return _run_offline_inputs(
        project_root,
        work_root,
        scenario=scenario,
        raw_metadata=raw_metadata,
        transcript_dir=transcript_dir,
        project_name=f"offline-{scenario.replace('_', '-')}",
        sample_count=2,
        source_url="https://share.example.invalid/offline-profile",
    )


def run_offline_corpus(
    project_root: Path,
    work_root: Path,
    *,
    corpus_name: str,
    raw_metadata: Path,
    transcript_dir: Path,
    taxonomy_preset: str,
    sample_count: int,
) -> OfflineRunResult:
    """Run a named synthetic corpus through the same credential-free pipeline."""

    return _run_offline_inputs(
        project_root,
        work_root,
        scenario=f"corpus:{corpus_name}",
        raw_metadata=raw_metadata,
        transcript_dir=transcript_dir,
        project_name=f"cross-domain-{corpus_name}",
        sample_count=sample_count,
        source_url=f"https://share.example.invalid/{corpus_name}-synthetic",
        taxonomy_preset=taxonomy_preset,
    )


def run_host_refinement(project_root: Path, baseline: OfflineRunResult) -> HostRefinementResult:
    """Prepare deterministic host artifacts and rerun quality for a baseline run."""

    if baseline.run_dir is None:
        raise OfflineScenarioError("offline baseline did not create a run directory")

    prepare = subprocess.run(
        [
            sys.executable,
            str(project_root / "scripts" / "prepare_host_refinement.py"),
            "--run-dir",
            str(baseline.run_dir),
        ],
        cwd=project_root,
        env=offline_subprocess_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    quality = subprocess.run(
        [
            sys.executable,
            str(project_root / "scripts" / "creator_pipeline.py"),
            "quality-check",
            "--run-dir",
            str(baseline.run_dir),
        ],
        cwd=project_root,
        env=offline_subprocess_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    refs = baseline.run_dir / "skill" / "references"
    reviews = baseline.run_dir / "research" / "reviews"
    return HostRefinementResult(
        prepare_returncode=prepare.returncode,
        quality_returncode=quality.returncode,
        stdout=prepare.stdout + quality.stdout,
        stderr=prepare.stderr + quality.stderr,
        quality=read_json_if_present(baseline.run_dir / "logs" / "creator_quality_report.json"),
        persona_schema=read_json_if_present(refs / "persona_model.schema.json"),
        persona_model=read_json_if_present(refs / "persona_model.json"),
        evaluation_schema=read_json_if_present(reviews / "evaluation_suite.schema.json"),
        reverse_identification_schema=read_json_if_present(reviews / "reverse_identification.schema.json"),
    )


def require(condition: object, message: str) -> None:
    if not condition:
        raise OfflineScenarioError(message)


def validate_happy_baseline(result: OfflineRunResult) -> None:
    """Validate the durable baseline state used by both pytest and the CLI."""

    require(result.returncode == 0, f"runner exited {result.returncode}: {result.stderr[-1000:]}")
    require(result.run_dir is not None, "no run directory generated")
    require(result.quality.get("passed") is True, f"quality gate failed: {result.quality}")
    require("ready_for_use" in result.quality, "quality report missing ready_for_use")
    require(result.quality.get("ready_for_use") is False, "deterministic draft must not be ready_for_use")
    require(result.quality.get("transcript_count") == 2, "happy scenario must copy two transcripts")
    require(result.workflow.get("workflow_id") == "creator_skill_build_v1_skill_first", "workflow ID drifted")
    require(result.workflow.get("status") == "completed", f"workflow not completed: {result.workflow}")
    require(result.workflow.get("final_status") == "succeeded", f"workflow final status drifted: {result.workflow}")

    artifacts = result.summary.get("artifacts") or {}
    require(artifacts.get("skill") is True, "skill artifact missing")
    require(artifacts.get("transcripts") == 2, "run summary transcript count is wrong")
    require(artifacts.get("videos") == 0 and artifacts.get("audio") == 0, "offline run created media")
    require(result.selected.get("selected_count") == 2, "selected metadata count is wrong")
    require(result.selected.get("selection_strategy") == "published_at_desc", "selection strategy missing")
    require(
        result.selected.get("items", [{}])[0].get("download_url")
        == "https://media.example.invalid/video/offline-101.mp4",
        "download_url was not normalized",
    )
    require("raw" not in json.dumps(result.compact, ensure_ascii=False), "compact metadata leaked raw payload")
    compact_items = result.compact.get("items") or []
    require(
        compact_items and compact_items[0].get("platform_video_id") == FIRST_VIDEO_ID,
        "compact metadata is malformed",
    )
    require(result.creator_profile.get("platform") == "douyin", "creator profile is malformed")


def validate_host_refinement(baseline: OfflineRunResult, result: HostRefinementResult) -> None:
    """Validate that preparation creates a recoverable draft, never a false-ready result."""

    require(result.prepare_returncode == 0, f"host refinement failed: {result.stderr[-1000:]}")
    require(result.quality_returncode == 0, f"quality recheck failed: {result.stderr[-1000:]}")
    require(baseline.run_dir is not None, "baseline run directory missing")
    if baseline.run_dir is None:
        return
    for relative in HOST_REFINEMENT_ARTIFACTS:
        require((baseline.run_dir / relative).is_file(), f"host refinement artifact missing: {relative}")

    require(result.quality.get("passed") is True, "base quality must remain passed after preparation")
    require(result.quality.get("ready_for_use") is False, "blank refinement templates must not be ready")
    host_checks = result.quality.get("content_readiness", {}).get("host_refinement", {}).get("checks", {})
    for name in (
        "brief_present",
        "corpus_index_present",
        "transcript_signals_present",
        "coverage_gaps_present",
        "short_form_coverage_present",
        "timeline_shift_present",
        "asr_entity_review_present",
        "evaluation_suite_schema_valid",
        "evaluation_suite_json_schema_valid",
        "evaluation_suite_evidence_integrity",
        "reverse_identification_schema_valid",
        "reverse_identification_json_schema_valid",
        "reverse_identification_evidence_integrity",
    ):
        require(host_checks.get(name) is True, f"host refinement check missing: {name}")
    for name in (
        "refinement_audit_filled",
        "usage_probe_filled",
        "evaluation_suite_filled",
        "evaluation_suite_json_filled",
        "reverse_identification_filled",
        "reverse_identification_json_filled",
        "reviewer_findings_filled",
    ):
        require(host_checks.get(name) is False, f"blank host artifact incorrectly passed: {name}")

    persona_checks = result.quality.get("content_readiness", {}).get("persona_model", {}).get("checks", {})
    require(persona_checks.get("schema_file_present") is True, "persona schema check missing")
    require(persona_checks.get("schema_valid") is True, "persona schema must be valid")
    require(persona_checks.get("model_file_present") is True, "persona model check missing")
    require(persona_checks.get("model_schema_valid") is True, "persona draft must match its schema")
    require(persona_checks.get("not_template") is False, "draft persona model must remain a template")
    require(persona_checks.get("evidence_anchors_min") is False, "blank anchors must not satisfy integrity")
    schema_uri = "https://json-schema.org/draft/2020-12/schema"
    schema_version = "1.1.0"
    require(result.persona_schema.get("$schema") == schema_uri, "persona schema draft version drifted")
    require(result.persona_schema.get("x-schema-version") == schema_version, "persona schema version drifted")
    require(result.persona_model.get("version") == "1.0", "persona model version drifted")
    require(result.persona_model.get("status") == "draft_template", "persona model status drifted")
    require(result.evaluation_schema.get("$schema") == schema_uri, "evaluation schema draft version drifted")
    require(result.evaluation_schema.get("x-schema-version") == schema_version, "evaluation schema version drifted")
    require(
        result.reverse_identification_schema.get("$schema") == schema_uri,
        "reverse-identification schema draft version drifted",
    )
    require(
        result.reverse_identification_schema.get("x-schema-version") == schema_version,
        "reverse-identification schema version drifted",
    )
    validations = result.quality.get("schema_validation") or {}
    for artifact in ("persona_model", "evaluation_suite", "reverse_identification"):
        require(validations.get(artifact, {}).get("valid") is True, f"draft schema validation failed: {artifact}")
        require(
            validations.get(artifact, {}).get("status") == "draft_template",
            f"draft schema status drifted: {artifact}",
        )
    evidence_integrity = result.quality.get("evidence_integrity") or {}
    require(evidence_integrity.get("valid") is False, "blank evidence template must not be valid")
    require(
        (evidence_integrity.get("counts") or {}).get("valid_unique_evidence_anchors") == 0,
        "blank evidence anchors must not be counted",
    )


def run_and_validate_offline_happy_path(
    project_root: Path,
    work_root: Path,
) -> OfflineSelfTestResult:
    """Run and validate the complete scenario shared by pytest and the CLI."""

    baseline = run_offline_scenario(project_root, work_root, "happy")
    validate_happy_baseline(baseline)
    refinement = run_host_refinement(project_root, baseline)
    validate_host_refinement(baseline, refinement)
    return OfflineSelfTestResult(baseline=baseline, refinement=refinement)
