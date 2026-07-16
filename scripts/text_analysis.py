#!/usr/bin/env python3
"""Deterministic Chinese term and cross-video phrase evidence."""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Literal, Sequence, TypedDict

import jieba


TEXT_ANALYSIS_VERSION = "1.0.0"
TOKENIZER_NAME = "jieba"
TOKENIZER_MODE = "precise_hmm_on"
TOKENIZER_VERSION = f"{getattr(jieba, '__version__', '0.42.1')}-default-dictionary"
STOPWORD_VERSION = "generic-zh-v2"
MINIMUM_VIDEO_APPEARANCES = 2
DEFAULT_PHRASE_LIMIT = 40


class TextAnalysisError(ValueError):
    """Raised when text analysis receives an invalid public input contract."""


@dataclass(frozen=True)
class TextDocument:
    """Stable video identity plus untrusted title and transcript text."""

    video_id: str
    title: str
    text: str


@dataclass(frozen=True)
class _Fragment:
    fragment_id: str
    video_id: str
    kind: Literal["title", "transcript"]
    text: str


class SignalConfidence(TypedDict):
    level: Literal["low", "medium", "high"]
    score: float
    reason: str


class TermEvidence(TypedDict):
    term: str
    document_frequency: int
    total_frequency: int
    title_document_frequency: int
    coverage_ratio: float
    representative_video_ids: list[str]
    source_fragment_ids: list[str]


class PhraseEvidence(TypedDict):
    phrase_id: str
    phrase: str
    document_frequency: int
    total_frequency: int
    coverage_ratio: float
    representative_video_ids: list[str]
    source_fragment_ids: list[str]
    confidence: SignalConfidence


class TextAnalysisResult(TypedDict):
    schema_version: int
    algorithm_version: str
    tokenizer_name: str
    tokenizer_version: str
    tokenizer_mode: str
    stopword_version: str
    minimum_video_appearances: int
    document_count: int
    fragment_count: int
    terms: list[TermEvidence]
    repeated_phrases: list[PhraseEvidence]


_STOPWORDS = frozenset(
    {
        "的", "了", "是", "在", "和", "与", "也", "都", "就", "而", "或",
        "把", "被", "让", "给", "再", "并", "及", "时", "到", "从", "向",
        "对", "中", "上", "下", "里", "后", "前", "会", "要", "还", "为",
        "以", "这", "那", "其", "它", "我", "你", "他", "她", "们", "个",
        "这是", "这个", "那个", "一个", "一些", "一种", "我们", "你们", "他们",
        "大家", "今天", "现在", "然后", "所以", "但是", "因为", "如果", "例如",
        "比如", "可以", "需要", "应该", "可能", "已经", "就是", "这样", "怎么",
        "如何", "为什么", "首先", "最后", "接着", "人工", "构造", "测试", "语料",
        "视频", "内容", "the", "and", "for", "with", "this", "that", "use",
    }
)
_FUNCTION_CHARS = frozenset(
    "的一了是在和与也都就而或把被让给再并及时到从向对中上下里后前这那个们"
)
_TIMESTAMP = re.compile(r"\[?\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?\]?")
_SENTENCE = re.compile(r"[^。！？!?；;\r\n]+(?:[。！？!?；;]+|$)")
_CJK_TOKEN = re.compile(r"[\u4e00-\u9fff]+")
_ASCII_TOKEN = re.compile(r"[a-z][a-z0-9_+.-]*")
_TOKENIZER = jieba.Tokenizer()


def _validated_documents(documents: Sequence[TextDocument]) -> list[TextDocument]:
    validated: list[TextDocument] = []
    seen_ids: set[str] = set()
    for index, document in enumerate(documents):
        if not isinstance(document, TextDocument):
            raise TextAnalysisError(
                f"document at index {index} must be a TextDocument"
            )
        video_id = document.video_id
        if not isinstance(video_id, str) or not video_id.strip():
            raise TextAnalysisError(f"document at index {index} has no video_id")
        if (
            video_id != video_id.strip()
            or "#" in video_id
            or not video_id.isprintable()
        ):
            raise TextAnalysisError(
                f"document video_id {video_id!r} cannot form a stable fragment ID"
            )
        if video_id in seen_ids:
            raise TextAnalysisError(f"duplicate text document video_id {video_id!r}")
        if not isinstance(document.title, str) or not isinstance(document.text, str):
            raise TextAnalysisError(
                f"document {video_id!r} title and text must be strings"
            )
        seen_ids.add(video_id)
        validated.append(document)
    return sorted(validated, key=lambda document: document.video_id)


def _clean_fragment(text: str) -> str:
    return re.sub(r"\s+", " ", _TIMESTAMP.sub(" ", text)).strip()


def _fragments(documents: Sequence[TextDocument]) -> list[_Fragment]:
    fragments: list[_Fragment] = []
    for document in documents:
        title = _clean_fragment(document.title)
        if title:
            fragments.append(
                _Fragment(
                    fragment_id=f"{document.video_id}#title",
                    video_id=document.video_id,
                    kind="title",
                    text=title,
                )
            )
        transcript_index = 0
        for match in _SENTENCE.finditer(document.text):
            text = _clean_fragment(match.group(0).rstrip("。！？!?；;"))
            if not text:
                continue
            transcript_index += 1
            fragments.append(
                _Fragment(
                    fragment_id=(
                        f"{document.video_id}#transcript:{transcript_index:04d}"
                    ),
                    video_id=document.video_id,
                    kind="transcript",
                    text=text,
                )
            )
    return fragments


def _lexical_token(value: str) -> str | None:
    token = value.strip().lower()
    if _CJK_TOKEN.fullmatch(token) or _ASCII_TOKEN.fullmatch(token):
        return token
    return None


def _segment(text: str) -> list[str]:
    return [
        token
        for value in _TOKENIZER.cut(text, cut_all=False, HMM=True)
        if (token := _lexical_token(value)) is not None
    ]


def _is_term(token: str) -> bool:
    if token in _STOPWORDS:
        return False
    if _CJK_TOKEN.fullmatch(token):
        return (
            2 <= len(token) <= 12
            and len(set(token)) > 1
            and not set(token) <= _FUNCTION_CHARS
        )
    return bool(_ASCII_TOKEN.fullmatch(token) and 2 <= len(token) <= 64)


def _phrase_text(tokens: Sequence[str]) -> str:
    if all(_CJK_TOKEN.fullmatch(token) for token in tokens):
        return "".join(tokens)
    return " ".join(tokens)


def _phrase_windows(tokens: Sequence[str]) -> list[tuple[str, int]]:
    windows: list[tuple[str, int]] = []
    upper = min(6, len(tokens))
    for size in range(2, upper + 1):
        for start in range(len(tokens) - size + 1):
            window = tokens[start : start + size]
            if sum(1 for token in window if _is_term(token)) < 2:
                continue
            phrase = _phrase_text(window)
            visible_length = len(phrase.replace(" ", ""))
            if not 4 <= visible_length <= 32 or len(set(phrase)) <= 2:
                continue
            windows.append((phrase, size))
    return windows


def _confidence(
    document_frequency: int,
    coverage_ratio: float,
) -> SignalConfidence:
    raw_score = min(document_frequency / 5, 1.0) * 0.45 + coverage_ratio * 0.55
    if document_frequency >= 3 and coverage_ratio >= 0.5:
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


def _phrase_id(phrase: str, video_ids: Sequence[str]) -> str:
    identity = "\n".join([phrase, *video_ids]).encode("utf-8")
    return f"phrase-{hashlib.sha256(identity).hexdigest()[:12]}"


def analyze_documents(
    documents: Sequence[TextDocument],
    *,
    term_limit: int | None = None,
    phrase_limit: int = DEFAULT_PHRASE_LIMIT,
    minimum_video_appearances: int = MINIMUM_VIDEO_APPEARANCES,
) -> TextAnalysisResult:
    """Analyze terms and phrases using video-level, source-grounded evidence."""

    if term_limit is not None and term_limit < 1:
        raise TextAnalysisError("term_limit must be at least 1 when provided")
    if phrase_limit < 1:
        raise TextAnalysisError("phrase_limit must be at least 1")
    if minimum_video_appearances < 2:
        raise TextAnalysisError(
            "minimum_video_appearances must be at least 2 for cross-video evidence"
        )
    corpus = _validated_documents(documents)
    fragments = _fragments(corpus)
    analyzed_video_ids = sorted({fragment.video_id for fragment in fragments})
    denominator = max(1, len(analyzed_video_ids))

    term_totals: Counter[str] = Counter()
    term_documents: dict[str, set[str]] = defaultdict(set)
    title_documents: dict[str, set[str]] = defaultdict(set)
    term_sources: dict[str, set[str]] = defaultdict(set)
    phrase_totals: Counter[str] = Counter()
    phrase_documents: dict[str, set[str]] = defaultdict(set)
    phrase_sources: dict[str, set[str]] = defaultdict(set)
    phrase_token_counts: dict[str, int] = {}

    for fragment in fragments:
        tokens = _segment(fragment.text)
        terms = [token for token in tokens if _is_term(token)]
        term_totals.update(terms)
        for term in set(terms):
            term_documents[term].add(fragment.video_id)
            term_sources[term].add(fragment.fragment_id)
            if fragment.kind == "title":
                title_documents[term].add(fragment.video_id)
        for phrase, token_count in _phrase_windows(tokens):
            phrase_totals[phrase] += 1
            phrase_documents[phrase].add(fragment.video_id)
            phrase_sources[phrase].add(fragment.fragment_id)
            phrase_token_counts[phrase] = token_count

    ranked_terms = sorted(
        term_totals,
        key=lambda term: (
            -len(term_documents[term]),
            -len(title_documents.get(term, set())),
            -term_totals[term],
            len(term),
            term,
        ),
    )
    if term_limit is not None:
        ranked_terms = ranked_terms[:term_limit]
    term_evidence = [
        TermEvidence(
            term=term,
            document_frequency=len(term_documents[term]),
            total_frequency=term_totals[term],
            title_document_frequency=len(title_documents.get(term, set())),
            coverage_ratio=round(len(term_documents[term]) / denominator, 4),
            representative_video_ids=sorted(term_documents[term]),
            source_fragment_ids=sorted(term_sources[term]),
        )
        for term in ranked_terms
    ]

    ranked_phrases = sorted(
        (
            phrase
            for phrase, video_ids in phrase_documents.items()
            if len(video_ids) >= minimum_video_appearances
        ),
        key=lambda phrase: (
            -len(phrase_documents[phrase]),
            -phrase_token_counts[phrase],
            -phrase_totals[phrase],
            phrase,
        ),
    )
    selected_phrases: list[str] = []
    for phrase in ranked_phrases:
        if any(
            phrase in selected
            and phrase_documents[phrase] == phrase_documents[selected]
            for selected in selected_phrases
        ):
            continue
        selected_phrases.append(phrase)
        if len(selected_phrases) >= phrase_limit:
            break
    phrase_evidence: list[PhraseEvidence] = []
    for phrase in selected_phrases:
        video_ids = sorted(phrase_documents[phrase])
        coverage_ratio = round(len(video_ids) / denominator, 4)
        phrase_evidence.append(
            PhraseEvidence(
                phrase_id=_phrase_id(phrase, video_ids),
                phrase=phrase,
                document_frequency=len(video_ids),
                total_frequency=phrase_totals[phrase],
                coverage_ratio=coverage_ratio,
                representative_video_ids=video_ids,
                source_fragment_ids=sorted(phrase_sources[phrase]),
                confidence=_confidence(len(video_ids), coverage_ratio),
            )
        )

    return {
        "schema_version": 1,
        "algorithm_version": TEXT_ANALYSIS_VERSION,
        "tokenizer_name": TOKENIZER_NAME,
        "tokenizer_version": TOKENIZER_VERSION,
        "tokenizer_mode": TOKENIZER_MODE,
        "stopword_version": STOPWORD_VERSION,
        "minimum_video_appearances": minimum_video_appearances,
        "document_count": len(analyzed_video_ids),
        "fragment_count": len(fragments),
        "terms": term_evidence,
        "repeated_phrases": phrase_evidence,
    }
