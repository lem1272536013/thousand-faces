"""Corpus, topic, entity, transcript-signal, and matrix derivation."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path

import corpus
import entity_review
import path_policy
import research_taxonomy
import text_analysis
import topic_discovery
from refinement_common import (
    clean_text,
    item_score,
    markdown_data_inline,
    markdown_data_join,
    read_json,
)
from refinement_coverage import _taxonomy_from_corpus


def build_asr_entity_review(
    run_dir: Path,
    corpus_index: dict,
    *,
    preset: research_taxonomy.TaxonomyPreset | None = None,
    corpus_snapshot: corpus.CorpusSnapshot | None = None,
) -> dict:
    taxonomy = preset or _taxonomy_from_corpus(corpus_index)
    if corpus_snapshot is not None:
        corpus_snapshot.assert_for_run(run_dir)
    transcript_dir = run_dir / "transcripts"
    documents = [
        entity_review.EntityDocument(
            video_id=record["video_id"],
            artifact_id=record["artifact_id"],
            title=record.get("title", ""),
            transcript=transcript_text(
                transcript_dir,
                record["artifact_id"],
                corpus_snapshot=corpus_snapshot,
            ),
        )
        for record in corpus_index.get("records", [])
    ]
    return entity_review.build_entity_review(
        documents,
        taxonomy=taxonomy.identity(),
        preset_entities=taxonomy.entity_patterns,
        project_dictionary_path=entity_review.project_dictionary_path(run_dir),
    )

def sentence_like_count(text: str) -> int:
    return len(re.findall(r"[。！？!?]", text))


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？!?])\s*", text)
    return [part.strip() for part in parts if part.strip()]


def keyword_labels(
    text: str,
    groups: Mapping[str, Sequence[str]],
) -> list[str]:
    lowered = text.lower()
    labels = []
    for label, keywords in groups.items():
        if any(keyword.lower() in lowered for keyword in keywords):
            labels.append(label)
    return labels


def first_matching_sentence(sentences: list[str], keywords: list[str]) -> str:
    for sentence in sentences:
        if any(keyword.lower() in sentence.lower() for keyword in keywords):
            return sentence[:180]
    return sentences[0][:180] if sentences else ""


def reusable_phrase_candidates(text: str, limit: int = 6) -> list[str]:
    """Return no cross-video claim when only one video's text is available."""

    return []


def contribution_types(
    title: str,
    text: str,
    themes: list[str],
    *,
    preset: research_taxonomy.TaxonomyPreset,
) -> list[str]:
    combined = f"{title}\n{text}"
    labels = [
        contribution
        for theme in themes
        for contribution in preset.theme_contributions.get(theme, ())
    ]
    if re.search(r"机制|原理|本质|为什么|背后", combined):
        labels.append("judgment_heuristic:mechanism_explanation")
    if re.search(r"未来|趋势|生态|平台|产业|全球|中国", combined):
        labels.append("topic_model:industry_context")
    return labels or ["evidence:general_style"]


def transcript_text(
    transcript_dir: Path,
    artifact_id: str,
    *,
    corpus_snapshot: corpus.CorpusSnapshot | None = None,
) -> str:
    if corpus_snapshot is not None:
        return corpus_snapshot.text_for(artifact_id)
    try:
        path = path_policy.artifact_path(transcript_dir, artifact_id, ".txt")
    except (path_policy.VideoIdError, path_policy.PathContainmentError):
        return ""
    if not path.exists():
        return ""
    return clean_text(path.read_text(encoding="utf-8-sig", errors="replace"))


def transcript_record(
    item: dict,
    transcript_dir: Path,
    *,
    preset: research_taxonomy.TaxonomyPreset | None = None,
    corpus_snapshot: corpus.CorpusSnapshot | None = None,
) -> dict:
    taxonomy = preset or research_taxonomy.get_taxonomy_preset()
    platform_video_id = path_policy.validate_platform_video_id(item.get("platform_video_id") or "video")
    artifact_id = path_policy.artifact_id_for_item(item)
    text = transcript_text(
        transcript_dir,
        artifact_id,
        corpus_snapshot=corpus_snapshot,
    )
    title = clean_text(str(item.get("title", "")))
    stats = item.get("stats") or {}
    themes = [
        theme
        for theme, keywords in taxonomy.theme_keywords.items()
        if any(keyword.lower() in title.lower() for keyword in keywords)
    ]
    return {
        "video_id": platform_video_id,
        "platform_video_id": platform_video_id,
        "artifact_id": artifact_id,
        "published_at": item.get("published_at", ""),
        "title": title,
        "duration": item.get("duration"),
        "stats": stats,
        "weighted_score": item_score(item),
        "transcript_chars": len(text),
        "sentence_like_breaks": sentence_like_count(text),
        "themes": themes,
        "opener": text[:180],
        "ending": text[-180:] if text else "",
    }


def transcript_signal(
    record: dict,
    transcript_dir: Path,
    *,
    preset: research_taxonomy.TaxonomyPreset | None = None,
    corpus_snapshot: corpus.CorpusSnapshot | None = None,
) -> dict:
    taxonomy = preset or research_taxonomy.get_taxonomy_preset()
    video_id = record["video_id"]
    artifact_id = record["artifact_id"]
    text = transcript_text(
        transcript_dir,
        artifact_id,
        corpus_snapshot=corpus_snapshot,
    )
    sentences = split_sentences(text)
    title = record["title"]
    themes = record.get("themes") or []
    combined = f"{title}\n{text}"
    hook_labels = keyword_labels(
        " ".join(sentences[:3]) or title,
        taxonomy.hook_keywords,
    )
    argument_labels = keyword_labels(combined, taxonomy.argument_keywords)
    ending_labels = keyword_labels(
        " ".join(sentences[-3:]) if sentences else title,
        taxonomy.ending_keywords,
    )
    judgment_markers = [
        keyword
        for keyword in taxonomy.judgment_keywords
        if keyword.lower() in combined.lower()
    ]
    boundary_sample = any(
        theme in themes for theme in taxonomy.boundary_themes
    ) or any(
        keyword.lower() in combined.lower()
        for keyword in taxonomy.boundary_keywords
    )
    return {
        "video_id": video_id,
        "platform_video_id": video_id,
        "artifact_id": artifact_id,
        "title": title,
        "published_at": record.get("published_at", ""),
        "weighted_score": record.get("weighted_score", 0),
        "transcript_chars": record.get("transcript_chars", 0),
        "themes": themes,
        "hook_type": hook_labels or ["未显式命中"],
        "core_question_candidate": first_matching_sentence(
            sentences,
            ["到底", "为什么", "怎么", "如何", "能不能", "是不是", "意味着"],
        ),
        "conflict_or_turning_point": first_matching_sentence(
            sentences,
            ["但是", "没想到", "结果", "问题是", "真正", "其实", "反而"],
        ),
        "argument_mode": argument_labels or ["未显式命中"],
        "ending_mode": ending_labels or ["未显式命中"],
        "value_judgment_markers": judgment_markers,
        "reusable_phrases": reusable_phrase_candidates(text),
        "boundary_or_risk_sample": boundary_sample,
        "contribution_types": contribution_types(
            title,
            text,
            themes,
            preset=taxonomy,
        ),
    }


def build_corpus_index(
    run_dir: Path,
    *,
    preset: research_taxonomy.TaxonomyPreset | None = None,
    corpus_snapshot: corpus.CorpusSnapshot | None = None,
) -> dict:
    taxonomy = preset or research_taxonomy.resolve_run_taxonomy(run_dir)
    if corpus_snapshot is not None:
        corpus_snapshot.assert_for_run(run_dir)
    selected = read_json(run_dir / "metadata" / "selected.compact.json")
    transcript_dir = run_dir / "transcripts"
    records = [
        transcript_record(
            item,
            transcript_dir,
            preset=taxonomy,
            corpus_snapshot=corpus_snapshot,
        )
        for item in selected.get("items", [])
    ]
    records_by_score = sorted(records, key=lambda item: item["weighted_score"], reverse=True)
    records_by_length = sorted(records, key=lambda item: item["transcript_chars"], reverse=True)
    return {
        "taxonomy": taxonomy.identity(),
        "creator_profile": selected.get("creator_profile") or {},
        "requested_count": selected.get("requested_count"),
        "selected_count": selected.get("selected_count"),
        "selection_strategy": selected.get("selection_strategy"),
        "video_id_map": [
            {
                "platform_video_id": record["platform_video_id"],
                "artifact_id": record["artifact_id"],
            }
            for record in records
        ],
        "coverage": {
            "transcript_count": sum(1 for record in records if record["transcript_chars"] > 0),
            "total_transcript_chars": sum(record["transcript_chars"] for record in records),
            "long_transcripts_over_5000_chars": sum(1 for record in records if record["transcript_chars"] >= 5000),
            "short_transcripts_under_800_chars": sum(1 for record in records if 0 < record["transcript_chars"] < 800),
        },
        "top_by_weighted_score": [record["video_id"] for record in records_by_score[:30]],
        "top_by_transcript_length": [record["video_id"] for record in records_by_length[:30]],
        "records": records,
    }


def build_topic_candidates(
    run_dir: Path,
    corpus_index: dict,
    *,
    corpus_snapshot: corpus.CorpusSnapshot | None = None,
) -> topic_discovery.TopicDiscoveryResult:
    """Discover domain-neutral research leads from the current corpus."""

    if corpus_snapshot is not None:
        corpus_snapshot.assert_for_run(run_dir)
    transcript_dir = run_dir / "transcripts"
    documents = [
        topic_discovery.TopicDocument(
            video_id=record["video_id"],
            title=record.get("title", ""),
            text=transcript_text(
                transcript_dir,
                record["artifact_id"],
                corpus_snapshot=corpus_snapshot,
            ),
        )
        for record in corpus_index.get("records", [])
    ]
    return topic_discovery.discover_topic_candidates(documents)


def _text_analysis_documents(
    run_dir: Path,
    corpus_index: dict,
    *,
    corpus_snapshot: corpus.CorpusSnapshot | None = None,
) -> list[text_analysis.TextDocument]:
    transcript_dir = run_dir / "transcripts"
    return [
        text_analysis.TextDocument(
            video_id=record["video_id"],
            title=record.get("title", ""),
            text=transcript_text(
                transcript_dir,
                record["artifact_id"],
                corpus_snapshot=corpus_snapshot,
            ),
        )
        for record in corpus_index.get("records", [])
    ]


def _phrase_analysis_payload(
    analysis: text_analysis.TextAnalysisResult,
) -> dict[str, object]:
    return {
        "schema_version": analysis["schema_version"],
        "algorithm_version": analysis["algorithm_version"],
        "tokenizer_name": analysis["tokenizer_name"],
        "tokenizer_version": analysis["tokenizer_version"],
        "tokenizer_mode": analysis["tokenizer_mode"],
        "stopword_version": analysis["stopword_version"],
        "minimum_video_appearances": analysis["minimum_video_appearances"],
        "document_count": analysis["document_count"],
        "fragment_count": analysis["fragment_count"],
        "candidate_count": len(analysis["repeated_phrases"]),
        "candidates": analysis["repeated_phrases"],
    }


def build_transcript_signals(
    run_dir: Path,
    corpus_index: dict,
    *,
    preset: research_taxonomy.TaxonomyPreset | None = None,
    corpus_snapshot: corpus.CorpusSnapshot | None = None,
) -> dict:
    taxonomy = preset or _taxonomy_from_corpus(corpus_index)
    if corpus_snapshot is not None:
        corpus_snapshot.assert_for_run(run_dir)
    transcript_dir = run_dir / "transcripts"
    signals = [
        transcript_signal(
            record,
            transcript_dir,
            preset=taxonomy,
            corpus_snapshot=corpus_snapshot,
        )
        for record in corpus_index["records"]
    ]
    analysis = text_analysis.analyze_documents(
        _text_analysis_documents(
            run_dir,
            corpus_index,
            corpus_snapshot=corpus_snapshot,
        ),
    )
    phrases_by_video: dict[str, list[str]] = {
        signal["video_id"]: [] for signal in signals
    }
    for candidate in analysis["repeated_phrases"]:
        for video_id in candidate["representative_video_ids"]:
            phrases_by_video.setdefault(video_id, []).append(candidate["phrase"])
    for signal in signals:
        signal["reusable_phrases"] = phrases_by_video.get(signal["video_id"], [])
    by_contribution = Counter(label for signal in signals for label in signal["contribution_types"])
    by_hook = Counter(label for signal in signals for label in signal["hook_type"])
    by_argument = Counter(label for signal in signals for label in signal["argument_mode"])
    return {
        "taxonomy": taxonomy.identity(),
        "phrase_analysis": _phrase_analysis_payload(analysis),
        "summary": {
            "signal_count": len(signals),
            "boundary_or_risk_count": sum(1 for signal in signals if signal["boundary_or_risk_sample"]),
            "contribution_counts": dict(by_contribution.most_common()),
            "hook_counts": dict(by_hook.most_common()),
            "argument_counts": dict(by_argument.most_common()),
        },
        "signals": signals,
    }

def top_terms_for_text(text: str, limit: int = 30) -> list[tuple[str, int]]:
    analysis = text_analysis.analyze_documents(
        [text_analysis.TextDocument("local-video", "", text)],
        term_limit=max(1, limit),
        phrase_limit=1,
    )
    return [
        (evidence["term"], evidence["total_frequency"])
        for evidence in analysis["terms"]
    ]


def common_phrase_candidates(texts: list[str], limit: int = 40) -> list[tuple[str, int]]:
    analysis = text_analysis.analyze_documents(
        [
            text_analysis.TextDocument(f"local-{index:04d}", "", text)
            for index, text in enumerate(texts, start=1)
        ],
        term_limit=1,
        phrase_limit=max(1, limit),
    )
    return [
        (candidate["phrase"], candidate["total_frequency"])
        for candidate in analysis["repeated_phrases"]
    ]


def build_signal_matrix(
    run_dir: Path,
    corpus_index: dict,
    *,
    corpus_snapshot: corpus.CorpusSnapshot | None = None,
) -> str:
    if corpus_snapshot is not None:
        corpus_snapshot.assert_for_run(run_dir)
    records = corpus_index["records"]
    analysis = text_analysis.analyze_documents(
        _text_analysis_documents(
            run_dir,
            corpus_index,
            corpus_snapshot=corpus_snapshot,
        ),
        term_limit=40,
        phrase_limit=40,
    )
    opener_analysis = text_analysis.analyze_documents(
        [
            text_analysis.TextDocument(record["video_id"], "", record["opener"])
            for record in records
        ],
        term_limit=25,
        phrase_limit=1,
    )
    ending_analysis = text_analysis.analyze_documents(
        [
            text_analysis.TextDocument(record["video_id"], "", record["ending"])
            for record in records
        ],
        term_limit=25,
        phrase_limit=1,
    )
    theme_counts = Counter(theme for record in records for theme in record.get("themes", []))

    lines = [
        "# Transcript Signal Matrix",
        "",
        "该文件由脚本确定性生成，用于帮助宿主 agent 做全量覆盖。它不是最终研究结论，只是研究线索。",
        "",
        "## Coverage",
        "",
        f"- Taxonomy: {markdown_data_inline(corpus_index.get('taxonomy', {}).get('preset', ''))} "
        f"{markdown_data_inline(corpus_index.get('taxonomy', {}).get('version', ''))}",
        f"- Text analysis algorithm: {analysis['algorithm_version']}",
        f"- Tokenizer: {analysis['tokenizer_name']} ({analysis['tokenizer_mode']})",
        f"- Tokenizer version: {analysis['tokenizer_version']}",
        f"- Stopword version: {analysis['stopword_version']}",
        f"- Minimum cross-video appearances: {analysis['minimum_video_appearances']}",
        f"- Transcript count: {corpus_index['coverage']['transcript_count']}",
        f"- Total transcript chars: {corpus_index['coverage']['total_transcript_chars']}",
        f"- Long transcripts >= 5000 chars: {corpus_index['coverage']['long_transcripts_over_5000_chars']}",
        f"- Short transcripts < 800 chars: {corpus_index['coverage']['short_transcripts_under_800_chars']}",
        "",
        "## Theme Counts",
        "",
    ]
    for theme, count in theme_counts.most_common():
        lines.append(f"- {markdown_data_inline(theme)}: {count}")

    lines.extend(["", "## Corpus Terms", ""])
    lines.append("| Term | Video DF | Total frequency | Videos | Fragments |")
    lines.append("|---|---:|---:|---|---|")
    for evidence in analysis["terms"]:
        lines.append(
            f"| {markdown_data_inline(evidence['term'])} | "
            f"{evidence['document_frequency']} | {evidence['total_frequency']} | "
            f"{markdown_data_join(evidence['representative_video_ids'])} | "
            f"{markdown_data_join(evidence['source_fragment_ids'])} |"
        )

    lines.extend(["", "## Opener Terms", ""])
    lines.append("| Term | Video DF | Total frequency | Videos |")
    lines.append("|---|---:|---:|---|")
    for evidence in opener_analysis["terms"]:
        lines.append(
            f"| {markdown_data_inline(evidence['term'])} | "
            f"{evidence['document_frequency']} | {evidence['total_frequency']} | "
            f"{markdown_data_join(evidence['representative_video_ids'])} |"
        )

    lines.extend(["", "## Ending Terms", ""])
    lines.append("| Term | Video DF | Total frequency | Videos |")
    lines.append("|---|---:|---:|---|")
    for evidence in ending_analysis["terms"]:
        lines.append(
            f"| {markdown_data_inline(evidence['term'])} | "
            f"{evidence['document_frequency']} | {evidence['total_frequency']} | "
            f"{markdown_data_join(evidence['representative_video_ids'])} |"
        )

    lines.extend(["", "## Repeated Phrase Candidates", ""])
    lines.append(
        "| Phrase | Video DF | Total frequency | Confidence | Videos | Fragments |"
    )
    lines.append("|---|---:|---:|---|---|---|")
    for candidate in analysis["repeated_phrases"]:
        confidence = candidate["confidence"]
        lines.append(
            f"| {markdown_data_inline(candidate['phrase'])} | "
            f"{candidate['document_frequency']} | {candidate['total_frequency']} | "
            f"{confidence['level']} ({confidence['score']}) | "
            f"{markdown_data_join(candidate['representative_video_ids'])} | "
            f"{markdown_data_join(candidate['source_fragment_ids'])} |"
        )

    lines.extend(["", "## Per-Video Signals", ""])
    lines.append("| Video ID | Date | Chars | Sentences | Score | Themes | Title |")
    lines.append("|---|---|---:|---:|---:|---|---|")
    for record in records:
        title = markdown_data_inline(record["title"])
        themes = markdown_data_join(record.get("themes") or [])
        lines.append(
            f"| {markdown_data_inline(record['video_id'])} | "
            f"{markdown_data_inline(str(record['published_at'])[:10])} | {record['transcript_chars']} | "
            f"{record['sentence_like_breaks']} | {record['weighted_score']} | {themes} | {title} |"
        )
    return "\n".join(lines).rstrip() + "\n"
