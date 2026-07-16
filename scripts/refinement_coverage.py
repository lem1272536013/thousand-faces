"""Evidence and sample-coverage derivation for host refinement."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

import research_taxonomy
from refinement_common import clean_text


COVERAGE_THRESHOLDS = {
    "top_interaction_sample_count": 10,
    "top_transcript_sample_count": 10,
    "short_transcript_min_chars_exclusive": 0,
    "short_transcript_max_chars_exclusive": 800,
    "short_transcript_sample_count": 10,
    "boundary_or_risk_sample_count": 10,
}

COVERAGE_THRESHOLD_EXPLANATIONS = {
    "top_interaction_sample_count": "Score the ten videos with the highest weighted interaction.",
    "top_transcript_sample_count": "Score the ten videos with the longest available transcripts.",
    "short_transcript_min_chars_exclusive": "Ignore empty transcripts when selecting short-form evidence.",
    "short_transcript_max_chars_exclusive": "Treat non-empty transcripts shorter than 800 characters as short form.",
    "short_transcript_sample_count": "Score at most ten short-form videos.",
    "boundary_or_risk_sample_count": "Score at most ten videos flagged as boundary or risk samples.",
}

_VIDEO_ID_HEADERS = {
    "video_id",
    "videoid",
    "视频_id",
    "视频id",
    "证据视频_id",
    "证据视频id",
}
_STATUS_HEADERS = {"status", "decision", "状态", "结论"}
_REASON_HEADERS = {"reason", "rejection_reason", "拒绝理由", "理由", "原因"}
_ACCEPTED_EVIDENCE_STATUSES = {
    "accepted",
    "adopted",
    "covered",
    "included",
    "used",
    "接受",
    "采用",
    "已采用",
    "覆盖",
}
_REJECTED_EVIDENCE_STATUSES = {
    "excluded",
    "ignored",
    "rejected",
    "notused",
    "不采用",
    "已拒绝",
    "拒绝",
    "排除",
    "未采用",
}

def _markdown_table_cells(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|"):
        return []
    return [cell.strip().strip("`") for cell in stripped.strip("|").split("|")]


def _markdown_table_separator(cells: list[str]) -> bool:
    return bool(cells) and all(
        re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) is not None
        for cell in cells
    )


def _normalized_evidence_header(value: str) -> str:
    return re.sub(r"[\s-]+", "_", clean_text(value).casefold()).strip("_")


def _normalized_evidence_status(value: str) -> str:
    return re.sub(r"[\s_-]+", "", clean_text(value).casefold())


def parse_evidence_index(path: Path, valid_video_ids: set[str]) -> dict[str, Any]:
    """Parse explicit Markdown evidence tables without scanning prose for ID substrings."""

    if not path.is_file():
        return {
            "source_status": "missing",
            "structured_row_count": 0,
            "accepted_ids": [],
            "rejected_with_reason": [],
            "invalid_rejection_count": 0,
            "invalid_status_count": 0,
            "unknown_video_ids": [],
            "duplicate_ids": [],
            "conflicting_ids": [],
        }

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    decisions: dict[str, dict[str, list[str]]] = {}
    unknown_ids: set[str] = set()
    structured_row_count = 0
    invalid_rejection_count = 0
    invalid_status_count = 0
    line_index = 0

    while line_index + 1 < len(lines):
        headers = _markdown_table_cells(lines[line_index])
        normalized_headers = [_normalized_evidence_header(header) for header in headers]
        video_column = next(
            (index for index, header in enumerate(normalized_headers) if header in _VIDEO_ID_HEADERS),
            None,
        )
        separators = _markdown_table_cells(lines[line_index + 1])
        if video_column is None or not _markdown_table_separator(separators):
            line_index += 1
            continue

        status_column = next(
            (index for index, header in enumerate(normalized_headers) if header in _STATUS_HEADERS),
            None,
        )
        reason_column = next(
            (index for index, header in enumerate(normalized_headers) if header in _REASON_HEADERS),
            None,
        )
        row_index = line_index + 2
        while row_index < len(lines):
            cells = _markdown_table_cells(lines[row_index])
            if not cells:
                break
            if video_column >= len(cells):
                row_index += 1
                continue
            video_id = clean_text(cells[video_column])
            if not video_id:
                row_index += 1
                continue
            structured_row_count += 1
            if video_id not in valid_video_ids:
                unknown_ids.add(video_id)
                row_index += 1
                continue

            decision = decisions.setdefault(video_id, {"accepted": [], "rejected": []})
            if status_column is None:
                decision["accepted"].append("")
                row_index += 1
                continue

            raw_status = cells[status_column] if status_column < len(cells) else ""
            status = _normalized_evidence_status(raw_status)
            if status in _ACCEPTED_EVIDENCE_STATUSES:
                decision["accepted"].append("")
            elif status in _REJECTED_EVIDENCE_STATUSES:
                reason = clean_text(cells[reason_column]) if reason_column is not None and reason_column < len(cells) else ""
                if reason:
                    decision["rejected"].append(reason)
                else:
                    invalid_rejection_count += 1
            else:
                invalid_status_count += 1
            row_index += 1
        line_index = max(row_index, line_index + 1)

    conflicting_ids = sorted(
        video_id
        for video_id, decision in decisions.items()
        if decision["accepted"] and decision["rejected"]
    )
    duplicate_ids = sorted(
        video_id
        for video_id, decision in decisions.items()
        if len(decision["accepted"]) + len(decision["rejected"]) > 1
    )
    conflict_set = set(conflicting_ids)
    accepted_ids = sorted(
        video_id
        for video_id, decision in decisions.items()
        if decision["accepted"] and video_id not in conflict_set
    )
    rejected_with_reason = [
        {"video_id": video_id, "reason": decision["rejected"][-1]}
        for video_id, decision in sorted(decisions.items())
        if decision["rejected"] and video_id not in conflict_set
    ]
    return {
        "source_status": "parsed",
        "structured_row_count": structured_row_count,
        "accepted_ids": accepted_ids,
        "rejected_with_reason": rejected_with_reason,
        "invalid_rejection_count": invalid_rejection_count,
        "invalid_status_count": invalid_status_count,
        "unknown_video_ids": sorted(unknown_ids),
        "duplicate_ids": duplicate_ids,
        "conflicting_ids": conflicting_ids,
    }


def covered_video_ids(run_dir: Path, corpus_index: dict) -> set[str]:
    evidence_path = run_dir / "skill" / "references" / "evidence_index.md"
    valid_ids = {
        str(record.get("video_id", ""))
        for record in corpus_index.get("records", [])
        if record.get("video_id")
    }
    parsed = parse_evidence_index(evidence_path, valid_ids)
    return set(parsed["accepted_ids"])


def ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 1.0
    return round(numerator / denominator, 4)


def coverage_bucket(
    ids: list[str],
    covered: set[str],
    rejected_with_reason: dict[str, str] | None = None,
) -> dict:
    unique_ids = [video_id for video_id in dict.fromkeys(ids) if video_id]
    covered_ids = [video_id for video_id in unique_ids if video_id in covered]
    rejected = rejected_with_reason or {}
    rejected_items = [
        {"video_id": video_id, "reason": rejected[video_id]}
        for video_id in unique_ids
        if video_id in rejected and video_id not in covered
    ]
    if not unique_ids:
        return {
            "status": "not_applicable",
            "total": 0,
            "covered": 0,
            "ratio": None,
            "covered_ids": [],
            "missing_ids": [],
            "rejected_with_reason": [],
        }
    return {
        "status": "applicable",
        "total": len(unique_ids),
        "covered": len(covered_ids),
        "ratio": ratio(len(covered_ids), len(unique_ids)),
        "covered_ids": covered_ids,
        "missing_ids": [
            video_id
            for video_id in unique_ids
            if video_id not in covered and video_id not in rejected
        ],
        "rejected_with_reason": rejected_items,
    }


def _taxonomy_from_corpus(corpus_index: dict) -> research_taxonomy.TaxonomyPreset:
    identity = corpus_index.get("taxonomy") or {}
    name = identity.get("preset") if isinstance(identity, dict) else None
    version = identity.get("version") if isinstance(identity, dict) else None
    return research_taxonomy.get_taxonomy_preset(name, version)


def build_evidence_coverage(
    run_dir: Path,
    corpus_index: dict,
    signal_payload: dict,
    *,
    preset: research_taxonomy.TaxonomyPreset | None = None,
) -> dict:
    taxonomy = preset or _taxonomy_from_corpus(corpus_index)
    records = corpus_index.get("records", [])
    valid_ids = {
        str(record.get("video_id", ""))
        for record in records
        if record.get("video_id")
    }
    evidence_index = parse_evidence_index(
        run_dir / "skill" / "references" / "evidence_index.md",
        valid_ids,
    )
    covered = set(evidence_index["accepted_ids"])
    rejected = {
        item["video_id"]: item["reason"]
        for item in evidence_index["rejected_with_reason"]
    }
    by_score = sorted(records, key=lambda item: item["weighted_score"], reverse=True)
    by_length = sorted(records, key=lambda item: item["transcript_chars"], reverse=True)
    short_ids = [
        record["video_id"]
        for record in records
        if COVERAGE_THRESHOLDS["short_transcript_min_chars_exclusive"]
        < record["transcript_chars"]
        < COVERAGE_THRESHOLDS["short_transcript_max_chars_exclusive"]
    ]
    boundary_ids = [signal["video_id"] for signal in signal_payload["signals"] if signal["boundary_or_risk_sample"]]
    theme_buckets = {
        theme: [record["video_id"] for record in records if theme in (record.get("themes") or [])]
        for theme in taxonomy.theme_keywords
    }
    theme_coverage = {
        theme: coverage_bucket(ids, covered, rejected)
        for theme, ids in theme_buckets.items()
    }
    buckets = {
        "top_interaction": coverage_bucket(
            [
                record["video_id"]
                for record in by_score[: COVERAGE_THRESHOLDS["top_interaction_sample_count"]]
            ],
            covered,
            rejected,
        ),
        "top_transcript_length": coverage_bucket(
            [
                record["video_id"]
                for record in by_length[: COVERAGE_THRESHOLDS["top_transcript_sample_count"]]
            ],
            covered,
            rejected,
        ),
        "short_transcripts": coverage_bucket(
            short_ids[: COVERAGE_THRESHOLDS["short_transcript_sample_count"]],
            covered,
            rejected,
        ),
        "boundary_or_risk": coverage_bucket(
            boundary_ids[: COVERAGE_THRESHOLDS["boundary_or_risk_sample_count"]],
            covered,
            rejected,
        ),
    }
    applicable_theme_buckets = [
        bucket
        for bucket in theme_coverage.values()
        if bucket["status"] == "applicable"
    ]
    if applicable_theme_buckets:
        covered_theme_count = sum(
            1 for bucket in applicable_theme_buckets if bucket["covered"] > 0
        )
        theme_cluster_coverage = {
            "status": "applicable",
            "total": len(applicable_theme_buckets),
            "covered": covered_theme_count,
            "ratio": ratio(covered_theme_count, len(applicable_theme_buckets)),
        }
    else:
        theme_cluster_coverage = {
            "status": "not_applicable",
            "total": 0,
            "covered": 0,
            "ratio": None,
        }
    applicable_ratios = [
        bucket["ratio"]
        for bucket in buckets.values()
        if bucket["status"] == "applicable"
    ]
    if theme_cluster_coverage["status"] == "applicable":
        applicable_ratios.append(theme_cluster_coverage["ratio"])
    return {
        "taxonomy": taxonomy.identity(),
        "covered_video_count": len(covered),
        "covered_video_ids": sorted(covered),
        "rejected_video_count": len(rejected),
        "total_video_count": len(records),
        "buckets": buckets,
        "theme_coverage": theme_coverage,
        "theme_cluster_coverage": theme_cluster_coverage,
        "theme_cluster_ratio": theme_cluster_coverage["ratio"],
        "overall_status": "applicable" if applicable_ratios else "not_applicable",
        "applicable_metric_count": len(applicable_ratios),
        "overall_score": round(sum(applicable_ratios) / len(applicable_ratios), 4) if applicable_ratios else 0.0,
        "evidence_index": evidence_index,
        "configuration": {
            "thresholds": dict(COVERAGE_THRESHOLDS),
            "explanations": dict(COVERAGE_THRESHOLD_EXPLANATIONS),
        },
    }

def build_coverage_gaps(corpus_index: dict, signal_payload: dict, coverage: dict) -> dict:
    records = corpus_index.get("records", [])
    record_by_id = {record["video_id"]: record for record in records}
    signal_by_id = {signal["video_id"]: signal for signal in signal_payload.get("signals", [])}
    recommendations: dict[str, dict[str, Any]] = {}

    def add(video_id: str, reason: str, priority: int) -> None:
        if not video_id:
            return
        record = record_by_id.get(video_id, {})
        signal = signal_by_id.get(video_id, {})
        item = recommendations.setdefault(
            video_id,
            {
                "video_id": video_id,
                "priority": priority,
                "reasons": [],
                "title": record.get("title", ""),
                "published_at": record.get("published_at", ""),
                "weighted_score": record.get("weighted_score", 0),
                "transcript_chars": record.get("transcript_chars", 0),
                "themes": record.get("themes", []),
                "opener": signal.get("opener", ""),
                "ending": signal.get("ending", ""),
            },
        )
        item["priority"] = min(item["priority"], priority)
        if reason not in item["reasons"]:
            item["reasons"].append(reason)

    for bucket_name, bucket in coverage.get("buckets", {}).items():
        priority = 1 if bucket_name in {"top_interaction", "top_transcript_length"} else 2
        for video_id in bucket.get("missing_ids", [])[:10]:
            add(video_id, f"missing from {bucket_name} evidence bucket", priority)

    for theme, bucket in coverage.get("theme_coverage", {}).items():
        if bucket.get("covered", 0) == 0:
            for video_id in bucket.get("missing_ids", [])[:3]:
                add(video_id, f"theme cluster has no evidence: {theme}", 1)
        elif bucket.get("ratio", 0) < 0.3:
            for video_id in bucket.get("missing_ids", [])[:2]:
                add(video_id, f"theme cluster under-covered: {theme}", 3)

    top_items = sorted(
        recommendations.values(),
        key=lambda item: (item["priority"], -int(item.get("weighted_score") or 0), -int(item.get("transcript_chars") or 0)),
    )
    return {
        "status": "generated",
        "recommendation_count": len(top_items),
        "top_recommendations": top_items[:20],
        "summary": {
            "overall_score": coverage.get("overall_score", 0),
            "covered_video_count": coverage.get("covered_video_count", 0),
            "total_video_count": coverage.get("total_video_count", 0),
            "theme_cluster_ratio": coverage.get("theme_cluster_ratio", 0),
        },
        "usage": "Read these videos before rewriting persona/topic/script files. High priority items should either be accepted in the structured evidence_index.md table or rejected there with a non-empty reason.",
    }

def build_short_form_coverage(corpus_index: dict, signal_payload: dict) -> dict:
    records_by_id = {record["video_id"]: record for record in corpus_index.get("records", [])}
    signal_by_id = {signal["video_id"]: signal for signal in signal_payload.get("signals", [])}
    short_ids = [
        record["video_id"]
        for record in corpus_index.get("records", [])
        if 0 < record.get("transcript_chars", 0) < 800
    ]
    buckets: Counter[str] = Counter()
    rows = []
    for video_id in short_ids:
        record = records_by_id[video_id]
        signal = signal_by_id.get(video_id, {})
        hook = ", ".join(signal.get("hook_type") or [])
        ending = ", ".join(signal.get("ending_mode") or [])
        contribution = ", ".join(signal.get("contribution_types") or [])
        for label in signal.get("hook_type") or []:
            buckets[f"hook:{label}"] += 1
        for label in signal.get("ending_mode") or []:
            buckets[f"ending:{label}"] += 1
        rows.append(
            {
                "video_id": video_id,
                "title": record.get("title", ""),
                "chars": record.get("transcript_chars", 0),
                "score": record.get("weighted_score", 0),
                "hook_type": hook,
                "ending_mode": ending,
                "contribution_types": contribution,
                "evidence_strength": "weak" if record.get("transcript_chars", 0) < 300 else "medium",
            }
        )
    return {
        "short_form_count": len(short_ids),
        "analyzed_count": len(rows),
        "pattern_counts": dict(buckets.most_common()),
        "records": rows,
        "note": "Short-form records are useful for hook and ending patterns, but should usually be weak evidence for deep persona claims.",
    }

def build_timeline_shift(corpus_index: dict, signal_payload: dict) -> dict:
    records = sorted(corpus_index.get("records", []), key=lambda item: str(item.get("published_at", "")))
    if not records:
        return {"periods": [], "shift_score": 0.0, "notes": []}
    signal_by_id = {signal["video_id"]: signal for signal in signal_payload.get("signals", [])}
    period_count = min(3, len(records))
    periods: list[dict[str, Any]] = []
    for index in range(period_count):
        start = round(index * len(records) / period_count)
        end = round((index + 1) * len(records) / period_count)
        chunk = records[start:end]
        theme_counts = Counter(theme for record in chunk for theme in record.get("themes", []))
        hook_counts = Counter(
            label
            for record in chunk
            for label in (signal_by_id.get(record["video_id"], {}).get("hook_type") or [])
        )
        contribution_counts = Counter(
            label
            for record in chunk
            for label in (signal_by_id.get(record["video_id"], {}).get("contribution_types") or [])
        )
        periods.append(
            {
                "name": ["early", "middle", "recent"][index] if period_count == 3 else f"period_{index + 1}",
                "start_date": str(chunk[0].get("published_at", ""))[:10],
                "end_date": str(chunk[-1].get("published_at", ""))[:10],
                "count": len(chunk),
                "theme_counts": dict(theme_counts.most_common()),
                "hook_counts": dict(hook_counts.most_common()),
                "contribution_counts": dict(contribution_counts.most_common()),
                "top_video_ids": [record["video_id"] for record in sorted(chunk, key=lambda item: item["weighted_score"], reverse=True)[:5]],
            }
        )
    first_terms = set(periods[0].get("theme_counts", {}).keys()) | set(periods[0].get("contribution_counts", {}).keys())
    last_terms = set(periods[-1].get("theme_counts", {}).keys()) | set(periods[-1].get("contribution_counts", {}).keys())
    overlap = len(first_terms & last_terms)
    union = len(first_terms | last_terms)
    shift_score = round(1 - ratio(overlap, union), 4) if union else 0.0
    return {
        "periods": periods,
        "shift_score": shift_score,
        "notes": [
            "Higher shift_score means stronger topic or contribution drift across periods.",
            "Use this to avoid treating a recent platform trend as permanent persona core.",
        ],
    }
