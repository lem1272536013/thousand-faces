"""Offline end-to-end proof that research defaults generalize across domains."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from offline_scenarios import (
    HOST_REFINEMENT_ARTIFACTS,
    run_host_refinement,
    run_offline_corpus,
)


@dataclass(frozen=True)
class CorpusCase:
    domain: str
    taxonomy_preset: str
    expected_topic_terms: frozenset[str]
    expected_theme: str
    expected_phrase_terms: frozenset[str]


CASES = (
    CorpusCase(
        domain="tech",
        taxonomy_preset="tech_creator",
        expected_topic_terms=frozenset({"模型", "提示"}),
        expected_theme="AI / Agent / 模型",
        expected_phrase_terms=frozenset({"模型", "提示词"}),
    ),
    CorpusCase(
        domain="food",
        taxonomy_preset="generic_zh_creator",
        expected_topic_terms=frozenset({"火候", "口感"}),
        expected_theme="教程 / 方法",
        expected_phrase_terms=frozenset({"火候", "口感"}),
    ),
    CorpusCase(
        domain="parenting",
        taxonomy_preset="generic_zh_creator",
        expected_topic_terms=frozenset({"情绪", "选择"}),
        expected_theme="教程 / 方法",
        expected_phrase_terms=frozenset({"情绪", "选择"}),
    ),
)

TECH_THEME_LABELS = {
    "AI / Agent / 模型",
    "工具教程 / 低门槛",
    "比赛 / 实验 / 模拟",
    "硬件 / 机器人 / 汽车",
    "现场 / 发布会 / 探访",
    "教育 / 高考 / 学习",
    "风险 / 灰区 / 安全",
}
TOPIC_SIGNAL_CONTRACT = {
    "title",
    "term_frequency",
    "document_frequency",
    "cooccurrence",
}
EXTRA_REFINEMENT_ARTIFACTS = {
    "research/host_refinement/topic_candidates.json",
    "research/host_refinement/topic_candidates.md",
    "research/reviews/topic_candidate_decisions.json",
}


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def corpus_paths(fixture_root: Path, case: CorpusCase) -> tuple[Path, Path]:
    root = fixture_root / "corpora" / case.domain
    return root / "metadata.json", root / "transcripts"


def fixture_items(fixture_root: Path, case: CorpusCase) -> list[dict[str, Any]]:
    metadata_path, _ = corpus_paths(fixture_root, case)
    items = read_json(metadata_path)["data"]["aweme_list"]
    assert isinstance(items, list)
    return items


def run_corpus(
    project_root: Path,
    fixture_root: Path,
    work_root: Path,
    case: CorpusCase,
) -> dict[str, Any]:
    metadata_path, transcript_dir = corpus_paths(fixture_root, case)
    baseline = run_offline_corpus(
        project_root,
        work_root,
        corpus_name=case.domain,
        raw_metadata=metadata_path,
        transcript_dir=transcript_dir,
        taxonomy_preset=case.taxonomy_preset,
        sample_count=3,
    )
    assert baseline.run_dir is not None, baseline.stderr
    run_dir = baseline.run_dir
    refinement = run_host_refinement(project_root, baseline)
    return {
        "run_dir": run_dir,
        "baseline": baseline,
        "refinement": refinement,
        "input": read_json(run_dir / "input.json"),
        "summary": read_json(run_dir / "run_summary.json"),
        "quality": refinement.quality,
        "corpus": read_json(run_dir / "research" / "host_refinement" / "corpus_index.json"),
        "topics": read_json(run_dir / "research" / "host_refinement" / "topic_candidates.json"),
        "signals": read_json(run_dir / "research" / "host_refinement" / "transcript_signals.json"),
        "coverage": read_json(run_dir / "research" / "reviews" / "evidence_coverage.json"),
        "entities": read_json(run_dir / "research" / "reviews" / "asr_entity_review.json"),
    }


@pytest.fixture(scope="module")
def cross_domain_runs(
    project_root: Path,
    fixture_root: Path,
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, dict[str, Any]]:
    work_root = tmp_path_factory.mktemp("cross_domain_pipeline")
    return {
        case.domain: run_corpus(project_root, fixture_root, work_root / case.domain, case)
        for case in CASES
    }


def test_short_sanitized_cross_domain_fixture_contract(fixture_root: Path) -> None:
    for case in CASES:
        _, transcript_dir = corpus_paths(fixture_root, case)
        items = fixture_items(fixture_root, case)
        transcript_paths = sorted(transcript_dir.glob("*.txt"))

        assert len(items) == 3
        assert {item["aweme_id"] for item in items} == {path.stem for path in transcript_paths}
        assert all(item["fixture_domain"] == case.domain for item in items)
        for path in transcript_paths:
            transcript = path.read_text(encoding="utf-8")
            assert "人工构造" in transcript
            assert 80 <= len(transcript) <= 600


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.domain)
def test_each_corpus_builds_complete_draft_and_refinement_package(
    cross_domain_runs: dict[str, dict[str, Any]],
    case: CorpusCase,
) -> None:
    result = cross_domain_runs[case.domain]
    run_dir = result["run_dir"]

    assert result["baseline"].returncode == 0, result["baseline"].stderr[-1500:]
    assert result["refinement"].prepare_returncode == 0, result["refinement"].stderr[-1500:]
    assert result["refinement"].quality_returncode == 0, result["refinement"].stderr[-1500:]
    assert result["summary"]["artifacts"]["transcripts"] == 3
    assert result["summary"]["artifacts"]["skill"] is True
    assert result["quality"]["passed"] is True
    assert result["quality"]["ready_for_use"] is False
    for relative in set(HOST_REFINEMENT_ARTIFACTS) | EXTRA_REFINEMENT_ARTIFACTS:
        assert (run_dir / relative).is_file(), relative


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.domain)
def test_domain_topics_and_structural_signals_match_fixture_design(
    cross_domain_runs: dict[str, dict[str, Any]],
    case: CorpusCase,
) -> None:
    result = cross_domain_runs[case.domain]
    identity = {"preset": case.taxonomy_preset, "version": "1.0.0"}

    assert result["input"]["taxonomy_preset"] == case.taxonomy_preset
    assert result["corpus"]["taxonomy"] == identity
    assert result["signals"]["taxonomy"] == identity
    assert result["coverage"]["taxonomy"] == identity
    assert result["entities"]["taxonomy"] == identity

    topics = result["topics"]
    assert topics["classification_status"] == "candidate_topics"
    assert set(topics["signals_used"]) == TOPIC_SIGNAL_CONTRACT
    assert topics["candidates"][0]["confidence"]["level"] == "high"
    main_terms = {
        term["term"] for term in topics["candidates"][0]["distinguishing_terms"]
    }
    assert case.expected_topic_terms <= main_terms
    for term in topics["candidates"][0]["distinguishing_terms"]:
        assert term["document_frequency"] >= 2
        assert term["source_fragment_ids"]

    records = result["corpus"]["records"]
    signals = result["signals"]["signals"]
    assert len(records) == len(signals) == 3
    assert all(case.expected_theme in record["themes"] for record in records)
    assert all(signal["hook_type"] != ["未显式命中"] for signal in signals)
    assert all(signal["argument_mode"] != ["未显式命中"] for signal in signals)
    assert all(signal["contribution_types"] for signal in signals)
    assert any(signal["boundary_or_risk_sample"] is True for signal in signals)


def test_nontech_defaults_do_not_emit_technology_taxonomy_labels(
    cross_domain_runs: dict[str, dict[str, Any]],
) -> None:
    for domain in ("food", "parenting"):
        result = cross_domain_runs[domain]
        emitted_themes = {
            theme
            for record in result["corpus"]["records"]
            for theme in record["themes"]
        }
        assert emitted_themes.isdisjoint(TECH_THEME_LABELS)
        assert result["entities"]["known_entities"] == {}
        assert result["entities"]["dictionary"]["preset_entity_count"] == 0


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.domain)
def test_discovery_and_readiness_keep_evidence_and_confidence_explicit(
    cross_domain_runs: dict[str, dict[str, Any]],
    case: CorpusCase,
) -> None:
    result = cross_domain_runs[case.domain]
    phrase_candidates = result["signals"]["phrase_analysis"]["candidates"]
    matching_phrases = [
        phrase
        for phrase in phrase_candidates
        if all(term in phrase["phrase"] for term in case.expected_phrase_terms)
    ]
    assert matching_phrases
    assert matching_phrases[0]["confidence"]["level"] == "high"
    assert matching_phrases[0]["document_frequency"] == 3
    assert matching_phrases[0]["source_fragment_ids"]

    coverage = result["coverage"]
    assert coverage["total_video_count"] == 3
    assert coverage["covered_video_count"] == 0
    assert coverage["overall_score"] == 0.0
    readiness = result["quality"]["content_readiness"]["host_refinement"]
    assert readiness["checks"]["topic_candidates_present"] is True
    assert readiness["checks"]["transcript_signals_present"] is True
    assert readiness["checks"]["evidence_coverage_present"] is False

    if case.domain == "tech":
        assert {"OpenAI", "Agent"} <= set(result["entities"]["known_entities"])
        for entity in result["entities"]["candidates"]:
            assert entity["confidence"]["level"] in {"low", "medium", "high"}
            assert entity["source_references"]
    else:
        main_label = result["topics"]["candidates"][0]["provisional_label"]
        assert any(term in main_label for term in case.expected_topic_terms)
