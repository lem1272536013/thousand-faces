"""Chinese term and phrase signals are cross-video, source-grounded evidence."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import artifacts
import creator_pipeline
import prepare_host_refinement
import quality_engine
import run_diagnostics
import text_analysis
import topic_discovery
import pytest
from io_utils import atomic_write_json


@pytest.mark.parametrize("video_id", [" video-1", "video#part", "video\npart"])
def test_fragment_identity_rejects_ambiguous_or_controlled_video_ids(
    video_id: str,
) -> None:
    with pytest.raises(
        text_analysis.TextAnalysisError,
        match="stable fragment ID",
    ):
        text_analysis.analyze_documents(
            [text_analysis.TextDocument(video_id, "标题", "转写")]
        )


def test_chinese_sentence_is_segmented_into_terms_instead_of_one_token() -> None:
    sentence = "我今天想分享一个适合新手的番茄炒蛋做法"

    result = text_analysis.analyze_documents(
        [text_analysis.TextDocument("food-1", "", sentence)]
    )
    terms = [evidence["term"] for evidence in result["terms"]]

    assert sentence not in terms
    assert {"番茄", "炒蛋", "番茄炒蛋"} & set(terms)
    assert result["tokenizer_name"] == "jieba"
    assert result["tokenizer_mode"] == "precise_hmm_on"
    assert result["tokenizer_version"]
    assert result["stopword_version"]
    assert result["minimum_video_appearances"] == 2


def test_term_ranking_prefers_video_document_frequency_over_raw_repetition() -> None:
    result = text_analysis.analyze_documents(
        [
            text_analysis.TextDocument("repeat-1", "", "火候" * 20),
            text_analysis.TextDocument("food-1", "", "食材"),
            text_analysis.TextDocument("food-2", "", "食材"),
        ]
    )
    by_term = {evidence["term"]: evidence for evidence in result["terms"]}

    assert by_term["火候"]["total_frequency"] == 20
    assert by_term["火候"]["document_frequency"] == 1
    assert by_term["食材"]["total_frequency"] == 2
    assert by_term["食材"]["document_frequency"] == 2
    assert list(by_term).index("食材") < list(by_term).index("火候")


def test_repetition_inside_one_video_is_not_a_cross_video_phrase() -> None:
    repeated = "控制火候保持口感。" * 6

    result = text_analysis.analyze_documents(
        [
            text_analysis.TextDocument("food-1", "", repeated),
            text_analysis.TextDocument("walk-1", "", "观察城市建筑光影。"),
        ]
    )

    assert all(
        candidate["phrase"] != "控制火候保持口感"
        for candidate in result["repeated_phrases"]
    )


def test_cross_video_phrase_keeps_video_and_fragment_evidence() -> None:
    documents = [
        text_analysis.TextDocument(
            "food-1",
            "",
            "控制火候保持口感。控制火候保持口感。",
        ),
        text_analysis.TextDocument(
            "food-2",
            "",
            "控制火候保持口感。",
        ),
        text_analysis.TextDocument(
            "walk-1",
            "",
            "观察城市建筑光影。",
        ),
    ]

    result = text_analysis.analyze_documents(documents)
    reversed_result = text_analysis.analyze_documents(list(reversed(documents)))
    candidate = next(
        item
        for item in result["repeated_phrases"]
        if item["phrase"] == "控制火候保持口感"
    )

    assert result == reversed_result
    assert candidate["document_frequency"] == 2
    assert candidate["total_frequency"] == 3
    assert candidate["representative_video_ids"] == ["food-1", "food-2"]
    assert candidate["source_fragment_ids"] == [
        "food-1#transcript:0001",
        "food-1#transcript:0002",
        "food-2#transcript:0001",
    ]
    assert candidate["confidence"]["level"] in {"low", "medium", "high"}


def test_non_chinese_and_mixed_text_are_supported_without_special_cases() -> None:
    result = text_analysis.analyze_documents(
        [
            text_analysis.TextDocument(
                "mixed-1",
                "OpenAI API v2 性能调优",
                "Use cache 处理 latency，再检查 API response。",
            ),
            text_analysis.TextDocument(
                "english-1",
                "Practical contract review",
                "Compare delivery clauses and liability boundaries.",
            ),
        ]
    )
    terms = {evidence["term"] for evidence in result["terms"]}

    assert {"openai", "api", "cache", "latency"} & terms
    assert all(
        evidence["representative_video_ids"]
        and evidence["source_fragment_ids"]
        for evidence in result["terms"]
    )


def test_topic_candidates_publish_tokenizer_and_term_fragment_contract() -> None:
    result = topic_discovery.discover_topic_candidates(
        [
            topic_discovery.TopicDocument(
                "food-1",
                "番茄鸡蛋晚餐",
                "控制鸡蛋火候保持食材口感。",
            ),
            topic_discovery.TopicDocument(
                "food-2",
                "鸡蛋食材做法",
                "控制鸡蛋火候保持食材口感。",
            ),
        ]
    )

    assert result["tokenizer_name"] == text_analysis.TOKENIZER_NAME
    assert result["tokenizer_version"] == text_analysis.TOKENIZER_VERSION
    assert result["tokenizer_mode"] == text_analysis.TOKENIZER_MODE
    assert result["stopword_version"] == text_analysis.STOPWORD_VERSION
    assert result["minimum_video_appearances"] == 2
    assert all(
        evidence["source_fragment_ids"]
        and all("#" in fragment_id for fragment_id in evidence["source_fragment_ids"])
        for candidate in result["candidates"]
        for evidence in candidate["distinguishing_terms"]
    )


def test_host_signals_and_matrix_only_publish_cross_video_phrase_patterns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "phrase-run"
    (run_dir / "metadata").mkdir(parents=True)
    (run_dir / "transcripts").mkdir()
    atomic_write_json(
        run_dir / "input.json",
        {
            "run_format": run_diagnostics.RUN_FORMAT_NAME,
            "schema_version": run_diagnostics.RUN_FORMAT_SCHEMA_VERSION,
        },
    )
    atomic_write_json(run_dir / "config.snapshot.json", {"settings_schema_version": 2})
    atomic_write_json(run_dir / "workflow.plan.json", {"schema_version": 1})
    atomic_write_json(run_dir / "metadata" / "provenance.json", {"schema_version": 1})
    items = [
        {
            "platform_video_id": "food-1",
            "artifact_id": "food-1",
            "title": "鸡蛋火候",
            "published_at": "2026-01-01T00:00:00+00:00",
            "stats": {},
        },
        {
            "platform_video_id": "food-2",
            "artifact_id": "food-2",
            "title": "食材口感",
            "published_at": "2026-01-02T00:00:00+00:00",
            "stats": {},
        },
        {
            "platform_video_id": "walk-1",
            "artifact_id": "walk-1",
            "title": "城市散步",
            "published_at": "2026-01-03T00:00:00+00:00",
            "stats": {},
        },
    ]
    atomic_write_json(
        run_dir / "metadata" / "selected.compact.json",
        {
            "requested_count": 3,
            "selected_count": 3,
            "selection_strategy": "published_at_desc",
            "creator_profile": {},
            "items": items,
        },
    )
    (run_dir / "transcripts" / "food-1.txt").write_text(
        "控制火候保持口感。控制火候保持口感。",
        encoding="utf-8",
    )
    (run_dir / "transcripts" / "food-2.txt").write_text(
        "控制火候保持口感。",
        encoding="utf-8",
    )
    (run_dir / "transcripts" / "walk-1.txt").write_text(
        "观察城市建筑光影。观察城市建筑光影。",
        encoding="utf-8",
    )

    corpus = prepare_host_refinement.build_corpus_index(run_dir)
    signals = prepare_host_refinement.build_transcript_signals(run_dir, corpus)
    matrix = prepare_host_refinement.build_signal_matrix(run_dir, corpus)
    specs = quality_engine.refinement_artifact_specs(run_dir)
    phrase_analysis = signals["phrase_analysis"]
    candidate = next(
        item
        for item in phrase_analysis["candidates"]
        if item["phrase"] == "控制火候保持口感"
    )

    assert phrase_analysis["tokenizer_version"] == text_analysis.TOKENIZER_VERSION
    assert phrase_analysis["stopword_version"] == text_analysis.STOPWORD_VERSION
    assert phrase_analysis["minimum_video_appearances"] == 2
    assert candidate["representative_video_ids"] == ["food-1", "food-2"]
    assert candidate["source_fragment_ids"] == [
        "food-1#transcript:0001",
        "food-1#transcript:0002",
        "food-2#transcript:0001",
    ]
    reusable_by_video = {
        signal["video_id"]: signal["reusable_phrases"]
        for signal in signals["signals"]
    }
    assert "控制火候保持口感" in reusable_by_video["food-1"]
    assert "控制火候保持口感" in reusable_by_video["food-2"]
    assert reusable_by_video["walk-1"] == []
    assert f"Tokenizer version: {text_analysis.TOKENIZER_VERSION}" in matrix
    assert "| Phrase | Video DF | Total frequency | Confidence | Videos | Fragments |" in matrix
    assert prepare_host_refinement.markdown_data_inline(
        "food-1#transcript:0001"
    ) in matrix
    expected_text_config = {
        "text_analysis_algorithm_version": text_analysis.TEXT_ANALYSIS_VERSION,
        "tokenizer_name": text_analysis.TOKENIZER_NAME,
        "tokenizer_version": text_analysis.TOKENIZER_VERSION,
        "tokenizer_mode": text_analysis.TOKENIZER_MODE,
        "stopword_version": text_analysis.STOPWORD_VERSION,
        "minimum_video_appearances": text_analysis.MINIMUM_VIDEO_APPEARANCES,
    }
    for artifact_name in (
        "topic_candidates",
        "topic_candidates_markdown",
        "transcript_signal_matrix",
        "transcript_signals",
        "transcript_signals_markdown",
    ):
        assert expected_text_config.items() <= specs[artifact_name].config.items()

    monkeypatch.setattr(
        sys,
        "argv",
        ["prepare_host_refinement.py", "--run-dir", str(run_dir)],
    )
    prepare_host_refinement.main()
    signals_path = (
        run_dir / "research" / "host_refinement" / "transcript_signals.json"
    )
    persisted = json.loads(signals_path.read_text(encoding="utf-8"))
    persisted_specs = quality_engine.refinement_artifact_specs(run_dir)
    assert persisted["phrase_analysis"] == phrase_analysis
    assert artifacts.assess_artifact(
        signals_path,
        persisted_specs["transcript_signals"],
    ).reusable
    freshness = quality_engine.evaluate_refinement_freshness(run_dir)["freshness"]
    assert freshness["current"]["transcript_signals"]["phrase_analysis"] == {
        "algorithm_version": text_analysis.TEXT_ANALYSIS_VERSION,
        "tokenizer_name": text_analysis.TOKENIZER_NAME,
        "tokenizer_version": text_analysis.TOKENIZER_VERSION,
        "tokenizer_mode": text_analysis.TOKENIZER_MODE,
        "stopword_version": text_analysis.STOPWORD_VERSION,
        "minimum_video_appearances": text_analysis.MINIMUM_VIDEO_APPEARANCES,
        "candidate_count": phrase_analysis["candidate_count"],
    }
    assert creator_pipeline.host_refinement_stats(
        run_dir,
        freshness,
    )["checks"]["transcript_signals_present"] is True

    persisted.pop("phrase_analysis")
    atomic_write_json(signals_path, persisted)
    forced_freshness = {
        "fresh": True,
        "artifacts": {"transcript_signals": {"fresh": True}},
    }
    assert creator_pipeline.host_refinement_stats(
        run_dir,
        forced_freshness,
    )["checks"]["transcript_signals_present"] is False


def test_runtime_dependencies_use_the_real_tokenizer_not_unused_pinyin(
    project_root: Path,
) -> None:
    requirements = (project_root / "requirements.txt").read_text(encoding="utf-8")

    assert "jieba==0.42.1" in requirements
    assert "pypinyin" not in requirements.lower()
