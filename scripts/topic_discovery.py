#!/usr/bin/env python3
"""Deterministic, domain-neutral topic candidates with video-level evidence."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal, Sequence, TypedDict

import text_analysis


TOPIC_DISCOVERY_VERSION = "1.1.0"
STOPWORD_VERSION = text_analysis.STOPWORD_VERSION
DEFAULT_MAX_CANDIDATES = 12
DEFAULT_MAX_TERMS_PER_CANDIDATE = 6


class TopicDiscoveryError(ValueError):
    """Raised when topic discovery receives an invalid document contract."""


@dataclass(frozen=True)
class TopicDocument:
    """Minimal trusted identity plus untrusted title/transcript research data."""

    video_id: str
    title: str
    text: str


class Confidence(TypedDict):
    level: Literal["insufficient", "low", "medium", "high"]
    score: float
    reason: str


class TermEvidence(TypedDict):
    term: str
    document_frequency: int
    total_frequency: int
    title_document_frequency: int
    coverage_ratio: float
    source_fragment_ids: list[str]


class TopicCandidate(TypedDict):
    candidate_id: str
    provisional_label: str
    status: Literal["proposed"]
    not_final_conclusion: bool
    representative_video_ids: list[str]
    document_frequency: int
    coverage_ratio: float
    confidence: Confidence
    distinguishing_terms: list[TermEvidence]


class TopicDiscoveryResult(TypedDict):
    schema_version: int
    algorithm_version: str
    tokenizer_name: str
    tokenizer_version: str
    tokenizer_mode: str
    stopword_version: str
    minimum_video_appearances: int
    signals_used: list[str]
    classification_status: Literal["candidate_topics", "unclassified"]
    corpus_video_count: int
    analyzed_video_count: int
    minimum_document_frequency: int
    candidate_count: int
    represented_video_count: int
    overall_confidence: Confidence
    candidates: list[TopicCandidate]
    warnings: list[str]


class TopicReviewSource(TypedDict):
    algorithm_version: str
    candidate_ids: list[str]


class TopicReviewDecisionContract(TypedDict):
    required_fields: list[str]
    rename_field: str
    merge_field: str


class TopicReviewTemplate(TypedDict):
    schema_version: int
    source: TopicReviewSource
    allowed_decisions: list[str]
    decision_contract: TopicReviewDecisionContract
    decisions: list[dict[str, object]]


def _validated_documents(documents: Sequence[TopicDocument]) -> list[TopicDocument]:
    validated: list[TopicDocument] = []
    seen_ids: set[str] = set()
    for index, document in enumerate(documents):
        if not isinstance(document, TopicDocument):
            raise TopicDiscoveryError(
                f"document at index {index} must be a TopicDocument"
            )
        if not isinstance(document.video_id, str) or not document.video_id.strip():
            raise TopicDiscoveryError(f"document at index {index} has no video_id")
        if document.video_id != document.video_id.strip():
            raise TopicDiscoveryError(
                f"document video_id {document.video_id!r} has surrounding whitespace"
            )
        if document.video_id in seen_ids:
            raise TopicDiscoveryError(
                f"duplicate topic document video_id {document.video_id!r}"
            )
        if not isinstance(document.title, str) or not isinstance(document.text, str):
            raise TopicDiscoveryError(
                f"document {document.video_id!r} title and text must be strings"
            )
        seen_ids.add(document.video_id)
        validated.append(document)
    return validated


def _distinct_terms(
    terms: Sequence[str],
    *,
    limit: int,
) -> list[str]:
    selected: list[str] = []
    for term in terms:
        if any(term in existing or existing in term for existing in selected):
            continue
        selected.append(term)
        if len(selected) >= limit:
            break
    return selected


def _candidate_confidence(
    evidence_count: int,
    coverage_ratio: float,
    term_count: int,
) -> Confidence:
    raw_score = (
        min(evidence_count / 5, 1.0) * 0.35
        + coverage_ratio * 0.45
        + min(term_count / 4, 1.0) * 0.20
    )
    if evidence_count <= 1:
        return {
            "level": "low",
            "score": round(min(raw_score, 0.39), 3),
            "reason": "single_video_evidence",
        }
    if evidence_count >= 3 and coverage_ratio >= 0.5:
        return {
            "level": "high",
            "score": round(max(raw_score, 0.75), 3),
            "reason": "repeated_across_three_or_more_videos",
        }
    if coverage_ratio >= 0.25:
        return {
            "level": "medium",
            "score": round(min(max(raw_score, 0.4), 0.74), 3),
            "reason": "repeated_across_multiple_videos",
        }
    return {
        "level": "low",
        "score": round(min(raw_score, 0.39), 3),
        "reason": "low_corpus_coverage",
    }


def _candidate_id(terms: Sequence[str], video_ids: Sequence[str]) -> str:
    identity = "\n".join([*terms, "--", *video_ids]).encode("utf-8")
    return f"topic-{hashlib.sha256(identity).hexdigest()[:12]}"


def discover_topic_candidates(
    documents: Sequence[TopicDocument],
    *,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    max_terms_per_candidate: int = DEFAULT_MAX_TERMS_PER_CANDIDATE,
) -> TopicDiscoveryResult:
    """Discover provisional topic clusters without applying a domain taxonomy."""

    if max_candidates < 1:
        raise TopicDiscoveryError("max_candidates must be at least 1")
    if max_terms_per_candidate < 2:
        raise TopicDiscoveryError("max_terms_per_candidate must be at least 2")
    corpus = _validated_documents(documents)
    analyzed = [document for document in corpus if document.title or document.text]
    minimum_df = 1 if len(analyzed) <= 1 else 2
    analysis = text_analysis.analyze_documents(
        [
            text_analysis.TextDocument(
                video_id=document.video_id,
                title=document.title,
                text=document.text,
            )
            for document in analyzed
        ],
        phrase_limit=1,
    )
    by_term = {evidence["term"]: evidence for evidence in analysis["terms"]}
    term_documents = {
        term: set(evidence["representative_video_ids"])
        for term, evidence in by_term.items()
    }

    eligible = [
        term
        for term, video_ids in term_documents.items()
        if len(video_ids) >= minimum_df
    ]
    groups: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for term in eligible:
        groups[tuple(sorted(term_documents[term]))].append(term)

    ranked_groups = sorted(
        groups.items(),
        key=lambda item: (
            -len(item[0]),
            -sum(by_term[term]["total_frequency"] for term in item[1]),
            item[0],
        ),
    )
    candidates: list[TopicCandidate] = []
    for video_ids, group_terms in ranked_groups:
        terms = _distinct_terms(
            group_terms,
            limit=max_terms_per_candidate,
        )
        if len(terms) < 2:
            continue
        coverage_ratio = round(len(video_ids) / max(1, len(analyzed)), 4)
        evidence = [
            TermEvidence(
                term=term,
                document_frequency=by_term[term]["document_frequency"],
                total_frequency=by_term[term]["total_frequency"],
                title_document_frequency=by_term[term][
                    "title_document_frequency"
                ],
                coverage_ratio=by_term[term]["coverage_ratio"],
                source_fragment_ids=list(by_term[term]["source_fragment_ids"]),
            )
            for term in terms
        ]
        confidence = _candidate_confidence(
            len(video_ids),
            coverage_ratio,
            len(terms),
        )
        candidates.append(
            TopicCandidate(
                candidate_id=_candidate_id(terms, video_ids),
                provisional_label=" / ".join(terms[:3]),
                status="proposed",
                not_final_conclusion=True,
                representative_video_ids=list(video_ids),
                document_frequency=len(video_ids),
                coverage_ratio=coverage_ratio,
                confidence=confidence,
                distinguishing_terms=evidence,
            )
        )
        if len(candidates) >= max_candidates:
            break

    represented_ids = {
        video_id
        for candidate in candidates
        for video_id in candidate["representative_video_ids"]
    }
    confidence_levels = [candidate["confidence"]["level"] for candidate in candidates]
    if not candidates:
        overall = Confidence(
            level="insufficient",
            score=0.0,
            reason="no_distinctive_cross_document_terms",
        )
    else:
        strongest = max(
            candidates,
            key=lambda candidate: candidate["confidence"]["score"],
        )["confidence"]
        overall = Confidence(**strongest)
    classification_status: Literal["candidate_topics", "unclassified"] = (
        "candidate_topics"
        if any(level in {"medium", "high"} for level in confidence_levels)
        else "unclassified"
    )
    warnings: list[str] = []
    if not candidates:
        warnings.append("No evidence-backed topic candidate met the minimum signal rule.")
    elif classification_status == "unclassified":
        warnings.append(
            "All topic candidates remain low confidence and must not be treated as "
            "stable conclusions."
        )
    return {
        "schema_version": 1,
        "algorithm_version": TOPIC_DISCOVERY_VERSION,
        "tokenizer_name": analysis["tokenizer_name"],
        "tokenizer_version": analysis["tokenizer_version"],
        "tokenizer_mode": analysis["tokenizer_mode"],
        "stopword_version": STOPWORD_VERSION,
        "minimum_video_appearances": analysis["minimum_video_appearances"],
        "signals_used": [
            "title",
            "term_frequency",
            "document_frequency",
            "cooccurrence",
        ],
        "classification_status": classification_status,
        "corpus_video_count": len(corpus),
        "analyzed_video_count": len(analyzed),
        "minimum_document_frequency": minimum_df,
        "candidate_count": len(candidates),
        "represented_video_count": len(represented_ids),
        "overall_confidence": overall,
        "candidates": candidates,
        "warnings": warnings,
    }


def build_topic_review_template(
    discovery: TopicDiscoveryResult,
) -> TopicReviewTemplate:
    """Create a durable, human-editable decision ledger without auto-decisions."""

    return {
        "schema_version": 1,
        "source": {
            "algorithm_version": discovery["algorithm_version"],
            "candidate_ids": [
                candidate["candidate_id"]
                for candidate in discovery["candidates"]
            ],
        },
        "allowed_decisions": ["accepted", "renamed", "merged", "rejected"],
        "decision_contract": {
            "required_fields": [
                "candidate_id",
                "decision",
                "reason",
                "reviewed_by",
                "reviewed_at",
            ],
            "rename_field": "replacement_label",
            "merge_field": "merged_into_candidate_id",
        },
        "decisions": [],
    }
