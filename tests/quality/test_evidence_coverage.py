"""Evidence coverage must be conservative, structured, and denominator-safe."""

from __future__ import annotations

from pathlib import Path

import prepare_host_refinement
import quality_engine


def record(
    video_id: str,
    *,
    score: int,
    chars: int = 1_000,
    themes: list[str] | None = None,
) -> dict:
    return {
        "video_id": video_id,
        "weighted_score": score,
        "transcript_chars": chars,
        "themes": themes or [],
    }


def signals(*boundary_ids: str) -> dict:
    return {
        "signals": [
            {"video_id": video_id, "boundary_or_risk_sample": True}
            for video_id in boundary_ids
        ]
    }


def write_evidence(run_dir: Path, text: str) -> None:
    path = run_dir / "skill" / "references" / "evidence_index.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build(run_dir: Path, records: list[dict], signal_payload: dict | None = None) -> dict:
    return prepare_host_refinement.build_evidence_coverage(
        run_dir,
        {"records": records},
        signal_payload or signals(),
    )


def test_zero_evidence_scores_zero_and_empty_buckets_are_not_applicable(tmp_path: Path) -> None:
    records = [record("video-1", score=20), record("video-2", score=10, chars=1_200)]
    write_evidence(tmp_path, "# Evidence Index\n\nNo evidence selected yet.\n")

    coverage = build(tmp_path, records)

    assert coverage["covered_video_count"] == 0
    assert coverage["overall_score"] == 0.0
    assert coverage["overall_status"] == "applicable"
    assert coverage["applicable_metric_count"] == 2
    assert coverage["buckets"]["short_transcripts"] == {
        "status": "not_applicable",
        "total": 0,
        "covered": 0,
        "ratio": None,
        "covered_ids": [],
        "missing_ids": [],
        "rejected_with_reason": [],
    }
    assert coverage["buckets"]["boundary_or_risk"]["status"] == "not_applicable"
    assert all(
        bucket["status"] == "not_applicable"
        for bucket in coverage["theme_coverage"].values()
    )
    assert coverage["theme_cluster_coverage"]["status"] == "not_applicable"


def test_overall_score_averages_only_applicable_metrics(tmp_path: Path) -> None:
    records = [record("video-1", score=20), record("video-2", score=10, chars=1_200)]
    write_evidence(
        tmp_path,
        "# Evidence Index\n\n| Video ID | Finding |\n|---|---|\n| video-1 | repeated hook |\n",
    )

    coverage = build(tmp_path, records)

    assert coverage["buckets"]["top_interaction"]["ratio"] == 0.5
    assert coverage["buckets"]["top_transcript_length"]["ratio"] == 0.5
    assert coverage["applicable_metric_count"] == 2
    assert coverage["overall_score"] == 0.5


def test_only_structured_rows_count_and_ids_do_not_match_by_substring(tmp_path: Path) -> None:
    records = [record("123", score=20), record("1234", score=10)]
    write_evidence(
        tmp_path,
        """# Evidence Index

The prose mentions exact ID 123, but prose is not evidence.

| Video ID | Finding |
|---|---|
| 1234 | structured evidence |
""",
    )

    coverage = build(tmp_path, records)

    assert coverage["covered_video_ids"] == ["1234"]
    assert coverage["covered_video_count"] == 1
    assert coverage["buckets"]["top_interaction"]["missing_ids"] == ["123"]


def test_rejection_with_reason_closes_gap_without_counting_as_evidence(tmp_path: Path) -> None:
    records = [record("noisy", score=20), record("unresolved", score=10)]
    write_evidence(
        tmp_path,
        """# Evidence Index

| Video ID | Status | Reason | Finding |
|---|---|---|---|
| noisy | rejected | ASR is mostly music | none |
| unresolved | rejected | | none |
""",
    )

    coverage = build(tmp_path, records)
    bucket = coverage["buckets"]["top_interaction"]
    gaps = prepare_host_refinement.build_coverage_gaps(
        {"records": records},
        signals(),
        coverage,
    )

    assert coverage["covered_video_count"] == 0
    assert bucket["ratio"] == 0.0
    assert bucket["rejected_with_reason"] == [
        {"video_id": "noisy", "reason": "ASR is mostly music"}
    ]
    assert bucket["missing_ids"] == ["unresolved"]
    assert coverage["evidence_index"]["invalid_rejection_count"] == 1
    assert {item["video_id"] for item in gaps["top_recommendations"]} == {"unresolved"}


def test_markdown_and_manifest_expose_na_rejections_and_named_thresholds(tmp_path: Path) -> None:
    records = [record("noisy", score=20)]
    write_evidence(
        tmp_path,
        """# Evidence Index

| 视频 ID | 状态 | 理由 |
|---|---|---|
| noisy | 拒绝 | 重复样本 |
""",
    )

    coverage = build(tmp_path, records)
    markdown = prepare_host_refinement.build_evidence_coverage_markdown(coverage)
    refinement = tmp_path / "research" / "host_refinement"
    refinement.mkdir(parents=True)
    (refinement / "corpus_index.json").write_text("{}\n", encoding="utf-8")
    (refinement / "transcript_signals.json").write_text("{}\n", encoding="utf-8")
    specs = quality_engine.coverage_artifact_specs(tmp_path)

    assert "N/A" in markdown
    assert "rejected_with_reason" in markdown
    assert "noisy" in markdown and "重复样本" in markdown
    thresholds = coverage["configuration"]["thresholds"]
    explanations = coverage["configuration"]["explanations"]
    assert thresholds["top_interaction_sample_count"] == 10
    assert thresholds["short_transcript_max_chars_exclusive"] == 800
    assert set(thresholds) == set(explanations)
    assert all(explanations.values())
    assert specs["evidence_coverage"].config["coverage_algorithm_version"] == "3"
