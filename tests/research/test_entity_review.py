"""ASR entity review must be extensible, stateful, and source traceable."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import artifacts
import creator_pipeline
import entity_review
import prepare_host_refinement
import quality_engine
import run_diagnostics
from io_utils import atomic_write_json


VIDEO_ID = "190000000000000701"


def write_project_dictionary(path: Path, entities: list[dict[str, object]]) -> None:
    payload = entity_review.build_project_dictionary_template()
    payload["entities"] = entities
    atomic_write_json(path, payload)


def document(
    transcript: str,
    *,
    video_id: str = VIDEO_ID,
    title: str = "",
) -> entity_review.EntityDocument:
    return entity_review.EntityDocument(
        video_id=video_id,
        artifact_id=video_id,
        title=title,
        transcript=transcript,
    )


def build_report(
    tmp_path: Path,
    transcript: str,
    entities: list[dict[str, object]],
) -> dict:
    dictionary_path = tmp_path / "research" / "entity_dictionary.json"
    dictionary_path.parent.mkdir(parents=True, exist_ok=True)
    write_project_dictionary(dictionary_path, entities)
    return entity_review.build_entity_review(
        [document(transcript)],
        taxonomy={"preset": "generic_zh_creator", "version": "1.0.0"},
        preset_entities=(),
        project_dictionary_path=dictionary_path,
    )


def test_preset_and_project_dictionary_support_alias_case_and_mixed_writing(
    tmp_path: Path,
) -> None:
    dictionary_path = tmp_path / "research" / "entity_dictionary.json"
    dictionary_path.parent.mkdir(parents=True)
    write_project_dictionary(
        dictionary_path,
        [
            {
                "canonical_term": "Nike",
                "aliases": ["耐克", "耐克 Nike"],
                "category": "brand",
                "impact": "high",
                "note": "运动品牌",
            },
            {
                "canonical_term": "张小龙",
                "aliases": [],
                "category": "person",
                "impact": "high",
                "note": "人物姓名",
            },
            {
                "canonical_term": "心房颤动",
                "aliases": ["房颤"],
                "category": "professional_term",
                "impact": "high",
                "note": "医学术语",
            },
        ],
    )

    report = entity_review.build_entity_review(
        [
            document(
                "OPEN AI 的发布与耐 克 Nike 联名无关，张小龙也谈到房颤。",
                title="OpenAI 与耐克 NIKE",
            )
        ],
        taxonomy={"preset": "custom", "version": "1.0.0"},
        preset_entities=("OpenAI",),
        project_dictionary_path=dictionary_path,
    )
    candidates = {
        candidate["canonical_term"]: candidate
        for candidate in report["candidates"]
        if candidate["registry_source"] != "detected"
    }

    assert {"OpenAI", "Nike", "张小龙", "心房颤动"} <= set(candidates)
    assert candidates["OpenAI"]["registry_source"] == "preset"
    assert candidates["OpenAI"]["confidence"] == {
        "level": "high",
        "score": 0.95,
        "reason": "registered_dictionary_match",
    }
    assert {form.casefold() for form in candidates["OpenAI"]["observed_forms"]} == {
        "open ai",
        "openai",
    }
    assert candidates["Nike"]["category"] == "brand"
    assert candidates["Nike"]["impact"] == "high"
    assert candidates["Nike"]["occurrence_count"] == 2
    assert candidates["张小龙"]["category"] == "person"
    assert candidates["心房颤动"]["category"] == "professional_term"
    assert report["dictionary"]["project"]["path"] == "research/entity_dictionary.json"


def test_all_unresolved_review_cannot_be_reported_as_complete(tmp_path: Path) -> None:
    report = build_report(
        tmp_path,
        "这次只讨论耐克的产品设计。",
        [
            {
                "canonical_term": "耐克",
                "aliases": [],
                "category": "brand",
                "impact": "high",
                "note": "高影响品牌",
            }
        ],
    )
    ledger = entity_review.build_entity_decision_ledger(report)
    assessment = entity_review.evaluate_entity_review(report, ledger, run_dir=tmp_path)

    candidate = report["candidates"][0]
    assert report["review_required"] is True
    assert candidate["status"] == "unresolved"
    assert candidate["treatment_note"] == ""
    assert ledger["decisions"][0]["status"] == "unresolved"
    assert assessment["valid"] is True
    assert assessment["complete"] is False
    assert assessment["processed_count"] == 0
    assert assessment["unresolved_high_impact_candidate_ids"] == [
        candidate["candidate_id"]
    ]
    assert "unresolved_high_impact_entities" in assessment["blocking_reasons"]

    contradictory_ledger = json.loads(json.dumps(ledger, ensure_ascii=False))
    contradictory_ledger["decisions"][0]["treatment_note"] = "写了说明但仍标未处理"
    contradictory = entity_review.evaluate_entity_review(
        report,
        contradictory_ledger,
        run_dir=tmp_path,
    )
    assert contradictory["valid"] is False
    assert "invalid_or_incomplete_decisions" in contradictory["blocking_reasons"]

    tampered = json.loads(json.dumps(report, ensure_ascii=False))
    tampered["review_required"] = False
    tampered_assessment = entity_review.evaluate_entity_review(
        tampered,
        ledger,
        run_dir=tmp_path,
    )
    assert tampered_assessment["valid"] is False
    assert "review_contract_invalid" in tampered_assessment["blocking_reasons"]

    tampered_confidence = json.loads(json.dumps(report, ensure_ascii=False))
    tampered_confidence["candidates"][0]["confidence"]["score"] = 1.0
    confidence_assessment = entity_review.evaluate_entity_review(
        tampered_confidence,
        ledger,
        run_dir=tmp_path,
    )
    assert confidence_assessment["valid"] is False
    assert "review_contract_invalid" in confidence_assessment["blocking_reasons"]


def test_correction_layer_maps_raw_asr_to_final_skill_without_rewriting_source(
    tmp_path: Path,
) -> None:
    transcript_path = tmp_path / "transcripts" / f"{VIDEO_ID}.txt"
    transcript_path.parent.mkdir(parents=True)
    raw_asr = "这次合作方的名字被识别成耐克。"
    transcript_path.write_text(raw_asr, encoding="utf-8")
    report = build_report(
        tmp_path,
        raw_asr,
        [
            {
                "canonical_term": "耐克",
                "aliases": [],
                "category": "brand",
                "impact": "high",
                "note": "高影响品牌",
            }
        ],
    )
    ledger = entity_review.build_entity_decision_ledger(report)
    decision = ledger["decisions"][0]
    decision.update(
        {
            "status": "corrected",
            "treatment_note": "依据品牌官网写法统一为 NIKE。",
            "corrected_term": "NIKE",
            "final_references": [
                {
                    "path": "skill/references/persona.md",
                    "locator": "品牌案例段",
                }
            ],
            "reviewed_by": "host-agent",
            "reviewed_at": "2026-07-16T12:00:00+08:00",
        }
    )

    missing_final = entity_review.evaluate_entity_review(
        report,
        ledger,
        run_dir=tmp_path,
    )
    assert missing_final["complete"] is False
    assert "invalid_or_incomplete_decisions" in missing_final["blocking_reasons"]

    final_path = tmp_path / "skill" / "references" / "persona.md"
    final_path.parent.mkdir(parents=True)
    final_path.write_text("# Persona\n\n品牌案例段使用 NIKE。\n", encoding="utf-8")
    assessment = entity_review.evaluate_entity_review(report, ledger, run_dir=tmp_path)

    assert assessment["complete"] is True
    assert assessment["status_counts"] == {
        "unresolved": 0,
        "confirmed": 0,
        "corrected": 1,
        "ignored": 0,
    }
    assert assessment["correction_mappings"] == [
        {
            "candidate_id": report["candidates"][0]["candidate_id"],
            "original_term": "耐克",
            "corrected_term": "NIKE",
            "source_references": report["candidates"][0]["source_references"],
            "final_references": decision["final_references"],
            "treatment_note": "依据品牌官网写法统一为 NIKE。",
        }
    ]
    assert report["candidates"][0]["raw_asr_references"] == [
        f"transcripts/{VIDEO_ID}.txt"
    ]
    assert transcript_path.read_text(encoding="utf-8") == raw_asr


def test_non_high_unresolved_items_remain_explainable_warnings_after_audit_starts(
    tmp_path: Path,
) -> None:
    report = build_report(
        tmp_path,
        "耐克与 ExampleTool 同时出现。",
        [
            {
                "canonical_term": "耐克",
                "aliases": [],
                "category": "brand",
                "impact": "high",
                "note": "高影响品牌",
            }
        ],
    )
    ledger = entity_review.build_entity_decision_ledger(report)
    high_candidate = next(
        candidate for candidate in report["candidates"] if candidate["impact"] == "high"
    )
    high_decision = next(
        decision
        for decision in ledger["decisions"]
        if decision["candidate_id"] == high_candidate["candidate_id"]
    )
    high_decision.update(
        {
            "status": "confirmed",
            "treatment_note": "已与品牌正式写法核对。",
            "reviewed_by": "host-agent",
            "reviewed_at": "2026-07-16T12:00:00+08:00",
        }
    )

    assessment = entity_review.evaluate_entity_review(report, ledger, run_dir=tmp_path)

    warning_candidates = [
        candidate
        for candidate in report["candidates"]
        if candidate["status"] == "unresolved" and candidate["impact"] != "high"
    ]
    assert warning_candidates
    detected = next(
        candidate
        for candidate in warning_candidates
        if candidate["registry_source"] == "detected"
    )
    assert detected["confidence"] == {
        "level": "low",
        "score": 0.3,
        "reason": "detected_single_video_signal",
    }
    assert detected["source_references"]
    assert assessment["complete"] is True
    assert assessment["warning_count"] == len(warning_candidates)
    assert assessment["unresolved_warning_candidate_ids"] == [
        candidate["candidate_id"] for candidate in warning_candidates
    ]


def test_host_readiness_uses_decision_state_instead_of_file_existence(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path
    reviews = run_dir / "research" / "reviews"
    reviews.mkdir(parents=True)
    report = build_report(
        run_dir,
        "这次只讨论耐克的产品设计。",
        [
            {
                "canonical_term": "耐克",
                "aliases": [],
                "category": "brand",
                "impact": "high",
                "note": "高影响品牌",
            }
        ],
    )
    ledger = entity_review.build_entity_decision_ledger(report)
    atomic_write_json(reviews / "asr_entity_review.json", report)
    atomic_write_json(reviews / "asr_entity_decisions.json", ledger)
    freshness = {
        "fresh": True,
        "artifacts": {"asr_entity_review": {"fresh": True}},
    }

    unresolved = creator_pipeline.host_refinement_stats(run_dir, freshness)

    assert unresolved["checks"]["asr_entity_review_present"] is True
    assert unresolved["checks"]["asr_entity_review_complete"] is False
    assert unresolved["entity_review"]["processed_count"] == 0
    assert unresolved["entity_review"]["blocker_count"] == 1

    ledger["decisions"][0].update(
        {
            "status": "confirmed",
            "treatment_note": "已人工核对品牌写法。",
            "reviewed_by": "host-agent",
            "reviewed_at": "2026-07-16T12:00:00+08:00",
        }
    )
    atomic_write_json(reviews / "asr_entity_decisions.json", ledger)
    resolved = creator_pipeline.host_refinement_stats(run_dir, freshness)

    assert resolved["checks"]["asr_entity_review_complete"] is True
    assert resolved["entity_review"]["status_counts"]["confirmed"] == 1
    assert resolved["files"]["asr_entity_decisions"].replace("\\", "/").endswith(
        "research/reviews/asr_entity_decisions.json"
    )


def test_project_dictionary_rejects_alias_collisions(tmp_path: Path) -> None:
    dictionary_path = tmp_path / "entity_dictionary.json"
    write_project_dictionary(
        dictionary_path,
        [
            {
                "canonical_term": "品牌甲",
                "aliases": ["共同别名"],
                "category": "brand",
                "impact": "high",
                "note": "甲",
            },
            {
                "canonical_term": "品牌乙",
                "aliases": ["共同 别名"],
                "category": "brand",
                "impact": "medium",
                "note": "乙",
            },
        ],
    )

    try:
        entity_review.build_entity_review(
            [document("共同别名")],
            taxonomy={"preset": "generic_zh_creator", "version": "1.0.0"},
            preset_entities=(),
            project_dictionary_path=dictionary_path,
        )
    except entity_review.EntityReviewError as error:
        assert "alias collision" in str(error)
    else:
        raise AssertionError("project dictionary alias collision was accepted")


def test_project_dictionary_content_is_bounded_and_markdown_encoded(
    tmp_path: Path,
) -> None:
    dictionary_path = tmp_path / "entity_dictionary.json"
    write_project_dictionary(
        dictionary_path,
        [
            {
                "canonical_term": "<b>Nike</b>",
                "aliases": ["Nike"],
                "category": "brand",
                "impact": "high",
                "note": "不可信 Markdown 测试",
            }
        ],
    )
    report = entity_review.build_entity_review(
        [document("Nike")],
        taxonomy={"preset": "generic_zh_creator", "version": "1.0.0"},
        preset_entities=(),
        project_dictionary_path=dictionary_path,
    )
    markdown = entity_review.build_entity_review_markdown(report)
    assert "<b>Nike</b>" not in markdown
    assert "&#60;b&#62;Nike&#60;/b&#62;" in markdown
    assert "| Confidence |" in markdown

    oversized = entity_review.build_project_dictionary_template()
    oversized["entities"] = [
        {
            "canonical_term": "Nike",
            "aliases": [f"alias-{index}" for index in range(51)],
            "category": "brand",
            "impact": "high",
            "note": "too many aliases",
        }
    ]
    atomic_write_json(dictionary_path, oversized)
    try:
        entity_review.build_entity_review(
            [document("Nike")],
            taxonomy={"preset": "generic_zh_creator", "version": "1.0.0"},
            preset_entities=(),
            project_dictionary_path=dictionary_path,
        )
    except entity_review.EntityReviewError as error:
        assert "cannot exceed 50" in str(error)
    else:
        raise AssertionError("oversized alias list was accepted")


def test_prepare_persists_decisions_and_dictionary_changes_invalidate_report(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "run"
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
    atomic_write_json(
        run_dir / "metadata" / "selected.compact.json",
        {
            "requested_count": 1,
            "selected_count": 1,
            "selection_strategy": "published_at_desc",
            "creator_profile": {},
            "items": [
                {
                    "platform_video_id": VIDEO_ID,
                    "artifact_id": VIDEO_ID,
                    "title": "耐克产品设计",
                    "published_at": "2026-07-16T00:00:00+08:00",
                    "stats": {},
                }
            ],
        },
    )
    transcript_path = run_dir / "transcripts" / f"{VIDEO_ID}.txt"
    transcript_path.write_text("这次只讨论耐克的产品设计。", encoding="utf-8")
    dictionary_path = entity_review.project_dictionary_path(run_dir)
    dictionary_path.parent.mkdir(parents=True)
    entities = [
        {
            "canonical_term": "耐克",
            "aliases": [],
            "category": "brand",
            "impact": "high",
            "note": "高影响品牌",
        }
    ]
    write_project_dictionary(dictionary_path, entities)
    monkeypatch.setattr(
        sys,
        "argv",
        ["prepare_host_refinement.py", "--run-dir", str(run_dir)],
    )

    prepare_host_refinement.main()

    reviews = run_dir / "research" / "reviews"
    report_path = reviews / "asr_entity_review.json"
    markdown_path = reviews / "asr_entity_review.md"
    decisions_path = reviews / "asr_entity_decisions.json"
    ledger = json.loads(decisions_path.read_text(encoding="utf-8"))
    specs = quality_engine.refinement_artifact_specs(run_dir)
    assert artifacts.assess_artifact(report_path, specs["asr_entity_review"]).reusable
    assert artifacts.assess_artifact(
        markdown_path,
        specs["asr_entity_review_markdown"],
    ).reusable

    ledger["decisions"][0].update(
        {
            "status": "confirmed",
            "treatment_note": "已核对品牌正式写法。",
            "reviewed_by": "host-agent",
            "reviewed_at": "2026-07-16T12:00:00+08:00",
        }
    )
    atomic_write_json(decisions_path, ledger)
    prepare_host_refinement.main()
    preserved = json.loads(decisions_path.read_text(encoding="utf-8"))
    assert preserved["decisions"][0]["status"] == "confirmed"
    assert transcript_path.read_text(encoding="utf-8") == "这次只讨论耐克的产品设计。"

    entities.append(
        {
            "canonical_term": "阿迪达斯",
            "aliases": ["Adidas"],
            "category": "brand",
            "impact": "medium",
            "note": "新增品牌",
        }
    )
    write_project_dictionary(dictionary_path, entities)
    freshness = quality_engine.evaluate_refinement_freshness(run_dir)["freshness"]
    assert freshness["artifacts"]["asr_entity_review"]["fresh"] is False
    assert freshness["artifacts"]["asr_entity_review"]["reason"] == "fingerprint_mismatch"
    assert freshness["artifacts"]["corpus_index"]["fresh"] is True
