"""Domain-neutral topic discovery emits evidence-backed research leads."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import artifacts
import creator_pipeline
import prepare_host_refinement
import quality_engine
import run_diagnostics
import topic_discovery
from io_utils import atomic_write_json


@pytest.mark.parametrize(
    ("fixture_name", "expected_terms"),
    [
        ("food", {"黄瓜", "鸡蛋", "食材", "火候", "晚餐"}),
        ("legal", {"合同", "签约", "条款", "责任", "交付"}),
        ("parenting", {"孩子", "玩具", "选择", "步骤", "积木"}),
    ],
)
def test_non_technology_fixtures_produce_source_grounded_low_confidence_topics(
    project_root: Path,
    fixture_name: str,
    expected_terms: set[str],
) -> None:
    fixture_dir = project_root / "tests" / "fixtures" / "corpora" / fixture_name
    metadata = json.loads(
        (fixture_dir / "metadata.json").read_text(encoding="utf-8")
    )
    item = metadata["data"]["aweme_list"][0]
    video_id = item["aweme_id"]
    transcript = (fixture_dir / "transcripts" / f"{video_id}.txt").read_text(
        encoding="utf-8"
    )
    document = topic_discovery.TopicDocument(
        video_id=video_id,
        title=item["desc"],
        text=transcript,
    )

    result = topic_discovery.discover_topic_candidates([document])

    discovered_terms = {
        evidence["term"]
        for candidate in result["candidates"]
        for evidence in candidate["distinguishing_terms"]
    }
    assert discovered_terms & expected_terms
    assert result["classification_status"] == "unclassified"
    assert result["overall_confidence"]["level"] == "low"
    assert result["signals_used"] == [
        "title",
        "term_frequency",
        "document_frequency",
        "cooccurrence",
    ]
    assert all(
        candidate["representative_video_ids"] == [video_id]
        and candidate["document_frequency"] == 1
        and candidate["coverage_ratio"] == 1.0
        and candidate["confidence"]["level"] == "low"
        and candidate["status"] == "proposed"
        and candidate["not_final_conclusion"] is True
        for candidate in result["candidates"]
    )


def test_empty_or_stopword_only_corpus_stays_unclassified_without_candidates() -> None:
    empty = topic_discovery.discover_topic_candidates([])
    stopword_only = topic_discovery.discover_topic_candidates(
        [
            topic_discovery.TopicDocument(
                video_id="stopword-video",
                title="今天我们可以这样",
                text="这是一个视频，然后大家可以这样，所以就是这样。",
            )
        ]
    )

    for result in (empty, stopword_only):
        assert result["classification_status"] == "unclassified"
        assert result["candidates"] == []
        assert result["overall_confidence"] == {
            "level": "insufficient",
            "score": 0.0,
            "reason": "no_distinctive_cross_document_terms",
        }


def test_cross_video_cooccurrence_produces_stable_high_confidence_evidence() -> None:
    documents = [
        topic_discovery.TopicDocument(
            video_id="food-001",
            title="黄瓜鸡蛋晚餐",
            text="鸡蛋和食材都要注意火候，黄瓜保持清脆。",
        ),
        topic_discovery.TopicDocument(
            video_id="food-002",
            title="番茄鸡蛋家常菜",
            text="这份食材的关键仍是鸡蛋火候。",
        ),
        topic_discovery.TopicDocument(
            video_id="food-003",
            title="三种食材做晚餐",
            text="处理鸡蛋时控制火候，食材口感会更稳定。",
        ),
        topic_discovery.TopicDocument(
            video_id="walk-001",
            title="城市散步观察建筑",
            text="记录街道光影和老建筑的细节。",
        ),
    ]

    result = topic_discovery.discover_topic_candidates(documents)
    reversed_result = topic_discovery.discover_topic_candidates(
        list(reversed(documents))
    )
    food_candidate = next(
        candidate
        for candidate in result["candidates"]
        if {"鸡蛋", "食材", "火候"}
        <= {term["term"] for term in candidate["distinguishing_terms"]}
    )

    assert result == reversed_result
    assert result["classification_status"] == "candidate_topics"
    assert food_candidate["representative_video_ids"] == [
        "food-001",
        "food-002",
        "food-003",
    ]
    assert food_candidate["document_frequency"] == 3
    assert food_candidate["coverage_ratio"] == 0.75
    assert food_candidate["confidence"]["level"] == "high"
    assert all(
        term["document_frequency"] == 3
        for term in food_candidate["distinguishing_terms"]
    )
    sources = {
        document.video_id: f"{document.title}\n{document.text}".lower()
        for document in documents
    }
    assert all(
        evidence["term"].lower() in sources[video_id]
        for evidence in food_candidate["distinguishing_terms"]
        for video_id in food_candidate["representative_video_ids"]
    )


def test_three_videos_do_not_claim_high_confidence_in_a_large_sparse_corpus() -> None:
    food_documents = [
        topic_discovery.TopicDocument(
            video_id=f"food-{index}",
            title="鸡蛋食材火候",
            text="鸡蛋食材火候",
        )
        for index in range(3)
    ]
    unrelated_documents = [
        topic_discovery.TopicDocument(
            video_id=f"noise-{index}",
            title=f"unique{index}",
            text=f"isolated{index}",
        )
        for index in range(17)
    ]

    result = topic_discovery.discover_topic_candidates(
        [*food_documents, *unrelated_documents]
    )
    food_candidate = next(
        candidate
        for candidate in result["candidates"]
        if "鸡蛋" in {
            evidence["term"]
            for evidence in candidate["distinguishing_terms"]
        }
    )

    assert food_candidate["document_frequency"] == 3
    assert food_candidate["coverage_ratio"] == 0.15
    assert food_candidate["confidence"]["level"] == "low"
    assert food_candidate["confidence"]["reason"] == "low_corpus_coverage"
    assert result["warnings"] == [
        "All topic candidates remain low confidence and must not be treated as "
        "stable conclusions."
    ]


def test_topic_document_ids_are_unique_and_review_contract_is_auditable() -> None:
    duplicate = topic_discovery.TopicDocument(
        video_id="duplicate-id",
        title="合同条款",
        text="合同条款需要核对。",
    )
    with pytest.raises(
        topic_discovery.TopicDiscoveryError,
        match="duplicate topic document video_id",
    ):
        topic_discovery.discover_topic_candidates([duplicate, duplicate])

    discovery = topic_discovery.discover_topic_candidates([duplicate])
    review = topic_discovery.build_topic_review_template(discovery)

    assert review["source"] == {
        "algorithm_version": discovery["algorithm_version"],
        "candidate_ids": [
            candidate["candidate_id"] for candidate in discovery["candidates"]
        ],
    }
    assert review["allowed_decisions"] == [
        "accepted",
        "renamed",
        "merged",
        "rejected",
    ]
    assert review["decisions"] == []


def test_markdown_summary_table_contains_every_candidate_before_term_details() -> None:
    discovery = topic_discovery.discover_topic_candidates(
        [
            topic_discovery.TopicDocument("food-1", "鸡蛋食材", "鸡蛋食材火候"),
            topic_discovery.TopicDocument("food-2", "食材火候", "鸡蛋食材火候"),
            topic_discovery.TopicDocument("walk-1", "城市建筑", "城市建筑光影"),
            topic_discovery.TopicDocument("walk-2", "建筑光影", "城市建筑光影"),
        ]
    )
    assert discovery["candidate_count"] >= 2

    markdown = prepare_host_refinement.build_topic_candidates_markdown(discovery)
    summary_table = markdown.split("\n### ", maxsplit=1)[0]

    assert all(
        candidate["candidate_id"] in summary_table
        for candidate in discovery["candidates"]
    )


def test_prepare_persists_fresh_candidates_and_preserves_host_decisions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "topic-run"
    (run_dir / "metadata").mkdir(parents=True)
    (run_dir / "transcripts").mkdir()
    atomic_write_json(
        run_dir / "input.json",
        {
            "run_format": run_diagnostics.RUN_FORMAT_NAME,
            "schema_version": run_diagnostics.RUN_FORMAT_SCHEMA_VERSION,
            "taxonomy_preset": "generic_zh_creator",
            "taxonomy_version": "1.0.0",
        },
    )
    atomic_write_json(run_dir / "config.snapshot.json", {"settings_schema_version": 2})
    atomic_write_json(run_dir / "workflow.plan.json", {"schema_version": 1})
    atomic_write_json(run_dir / "metadata" / "provenance.json", {"schema_version": 1})
    items = [
        {
            "platform_video_id": "food-001",
            "artifact_id": "food-001",
            "title": "黄瓜鸡蛋晚餐",
            "published_at": "2026-01-01T00:00:00+00:00",
            "stats": {},
        },
        {
            "platform_video_id": "food-002",
            "artifact_id": "food-002",
            "title": "番茄鸡蛋家常菜",
            "published_at": "2026-01-02T00:00:00+00:00",
            "stats": {},
        },
        {
            "platform_video_id": "food-003",
            "artifact_id": "food-003",
            "title": "三种食材做晚餐",
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
    for item in items:
        (run_dir / "transcripts" / f"{item['artifact_id']}.txt").write_text(
            "鸡蛋和食材需要控制火候，最后根据口感调整。",
            encoding="utf-8",
        )

    monkeypatch.setattr(
        sys,
        "argv",
        ["prepare_host_refinement.py", "--run-dir", str(run_dir)],
    )
    prepare_host_refinement.main()

    candidates_path = run_dir / "research" / "host_refinement" / "topic_candidates.json"
    candidates_markdown = candidates_path.with_suffix(".md")
    decisions_path = run_dir / "research" / "reviews" / "topic_candidate_decisions.json"
    candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
    decisions = json.loads(decisions_path.read_text(encoding="utf-8"))
    specs = quality_engine.refinement_artifact_specs(run_dir)

    assert candidates["classification_status"] == "candidate_topics"
    assert candidates["candidate_count"] > 0
    assert "Topic Candidates" in candidates_markdown.read_text(encoding="utf-8")
    assert decisions == topic_discovery.build_topic_review_template(candidates)
    assert artifacts.assess_artifact(
        candidates_path,
        specs["topic_candidates"],
    ).reusable
    assert artifacts.assess_artifact(
        candidates_markdown,
        specs["topic_candidates_markdown"],
    ).reusable

    decisions["decisions"].append(
        {
            "candidate_id": candidates["candidates"][0]["candidate_id"],
            "decision": "rejected",
            "reason": "与另一个候选重复",
            "reviewed_by": "host-agent",
            "reviewed_at": "2026-07-16T00:00:00+08:00",
        }
    )
    atomic_write_json(decisions_path, decisions)
    prepare_host_refinement.main()

    assert json.loads(decisions_path.read_text(encoding="utf-8")) == decisions
    freshness = quality_engine.evaluate_refinement_freshness(run_dir)["freshness"]
    assert freshness["artifacts"]["topic_candidates"]["fresh"] is True
    assert freshness["artifacts"]["topic_candidates_markdown"]["fresh"] is True
    assert freshness["current"]["topic_candidates"] == {
        "classification_status": "candidate_topics",
        "candidate_count": candidates["candidate_count"],
        "represented_video_count": candidates["represented_video_count"],
        "overall_confidence": candidates["overall_confidence"],
    }
    refinement = creator_pipeline.host_refinement_stats(
        run_dir,
        freshness,
    )
    assert refinement["checks"]["topic_candidates_present"] is True
    assert refinement["checks"]["topic_candidate_decisions_present"] is True
    assert refinement["files"]["topic_candidates"].replace("\\", "/").endswith(
        "research/host_refinement/topic_candidates.json"
    )
    assert refinement["files"]["topic_candidate_decisions"].replace(
        "\\", "/"
    ).endswith(
        "research/reviews/topic_candidate_decisions.json"
    )

    invalid_rename = json.loads(json.dumps(decisions, ensure_ascii=False))
    invalid_rename["decisions"][0]["decision"] = "renamed"
    atomic_write_json(decisions_path, invalid_rename)
    assert creator_pipeline.host_refinement_stats(
        run_dir,
        freshness,
    )["checks"]["topic_candidate_decisions_present"] is False
    atomic_write_json(decisions_path, decisions)

    transcript = run_dir / "transcripts" / "food-001.txt"
    transcript.write_text(
        transcript.read_text(encoding="utf-8") + "补充新的食材处理方法。",
        encoding="utf-8",
    )
    stale = quality_engine.evaluate_refinement_freshness(run_dir)["freshness"]
    assert stale["artifacts"]["topic_candidates"]["fresh"] is False
    assert stale["artifacts"]["topic_candidates"]["reason"] == "fingerprint_mismatch"
    assert stale["artifacts"]["topic_candidates_markdown"]["fresh"] is False
