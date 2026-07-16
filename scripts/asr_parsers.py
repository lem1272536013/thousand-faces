#!/usr/bin/env python3
"""Explicit adapters for supported ASR response structures."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Literal


TimeUnit = Literal["milliseconds", "seconds"]
ASR_PARSER_VERSION = "1"


class ASRParseError(ValueError):
    """Raised when an ASR response is unknown or contains no usable transcript."""


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    """Provider-neutral transcript segment with stable source provenance."""

    text: str
    start_ms: int | None
    end_ms: int | None
    source_index: int
    provider: str


class TranscriptMergeError(ValueError):
    """Raised when chunk transcripts cannot form a trustworthy timeline."""


@dataclass(frozen=True, slots=True)
class ChunkTranscript:
    """Parsed segments and actual boundaries for one source audio chunk."""

    chunk_index: int
    chunk_path: str
    start_ms: int
    end_ms: int
    segments: tuple[TranscriptSegment, ...]


@dataclass(frozen=True, slots=True)
class SegmentSource:
    """Separate provenance mapping for one rendered global segment."""

    segment_index: int
    chunk_index: int
    chunk_path: str
    chunk_start_ms: int
    local_source_index: int
    provider: str
    global_start_ms: int | None
    global_end_ms: int | None


@dataclass(frozen=True, slots=True)
class TranscriptMergeResult:
    """Validated global transcript plus its out-of-band provenance."""

    segments: tuple[TranscriptSegment, ...]
    sources: tuple[SegmentSource, ...]
    input_segment_count: int
    dropped_overlap_count: int
    nonempty_ratio: float


@dataclass(frozen=True, slots=True)
class _MergeCandidate:
    sort_key: tuple[int, bool, int, int]
    chunk: ChunkTranscript
    local_segment: TranscriptSegment
    text: str
    global_start_ms: int | None
    global_end_ms: int | None


def _clean_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _to_milliseconds(value: object, unit: TimeUnit) -> int | None:
    if value is None or value == "" or isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    if unit == "seconds":
        number *= 1000
    return round(number)


def _sort_segments(segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
    return sorted(
        segments,
        key=lambda segment: (
            segment.start_ms is None,
            segment.start_ms if segment.start_ms is not None else 0,
            segment.source_index,
        ),
    )


def _chat_content(value: object) -> str:
    if isinstance(value, str):
        return _clean_text(value)
    if not isinstance(value, list):
        return ""
    parts = []
    for item in value:
        if not isinstance(item, dict):
            continue
        text = _clean_text(item.get("text"))
        if text:
            parts.append(text)
    return " ".join(parts)


def parse_compatible_chat(payload: object) -> list[TranscriptSegment]:
    """Parse an OpenAI-compatible chat-completions ASR response."""

    if not isinstance(payload, dict) or not isinstance(payload.get("choices"), list):
        raise ASRParseError("not a compatible chat-completions response")
    for source_index, choice in enumerate(payload["choices"]):
        if not isinstance(choice, dict):
            continue
        message = choice.get("message")
        if not isinstance(message, dict):
            continue
        text = _chat_content(message.get("content"))
        if text:
            return [
                TranscriptSegment(
                    text=text,
                    start_ms=None,
                    end_ms=None,
                    source_index=source_index,
                    provider="compatible_chat",
                )
            ]
    raise ASRParseError("compatible chat response contains no non-empty message content")


AUDIO_SEGMENT_PATHS = (
    ("segments",),
    ("result", "segments"),
    ("payload", "segments"),
    ("payload", "result", "segments"),
)


def _path_value(payload: dict[str, Any], path: tuple[str, ...]) -> object:
    current: object = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _audio_segment_lists(payload: dict[str, Any]) -> list[list[object]]:
    segment_lists = []
    for path in AUDIO_SEGMENT_PATHS:
        value = _path_value(payload, path)
        if isinstance(value, list):
            segment_lists.append(value)
    return segment_lists


def parse_audio_transcriptions(payload: object) -> list[TranscriptSegment]:
    """Parse a compatible ``/audio/transcriptions`` JSON response."""

    if not isinstance(payload, dict):
        raise ASRParseError("not an audio-transcriptions response")
    segment_lists = _audio_segment_lists(payload)
    segments = []
    source_index = 0
    seen_from_prior_paths: set[tuple[str, int | None, int | None]] = set()
    for rows in segment_lists:
        current_path_keys: set[tuple[str, int | None, int | None]] = set()
        for row in rows:
            current_index = source_index
            source_index += 1
            if not isinstance(row, dict):
                continue
            text = _clean_text(row.get("text"))
            if not text:
                continue
            start_ms = _to_milliseconds(row.get("start"), "seconds")
            end_ms = _to_milliseconds(row.get("end"), "seconds")
            identity = (text, start_ms, end_ms)
            if identity in seen_from_prior_paths:
                continue
            current_path_keys.add(identity)
            segments.append(
                TranscriptSegment(
                    text=text,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    source_index=current_index,
                    provider="audio_transcriptions",
                )
            )
        seen_from_prior_paths.update(current_path_keys)
    if segments:
        return _sort_segments(segments)

    text = _clean_text(payload.get("text"))
    if text:
        return [
            TranscriptSegment(
                text=text,
                start_ms=None,
                end_ms=None,
                source_index=0,
                provider="audio_transcriptions",
            )
        ]
    raise ASRParseError("audio-transcriptions response contains no non-empty transcript")


def parse_dashscope(payload: object) -> list[TranscriptSegment]:
    """Parse a DashScope transcription result containing transcripts/sentences."""

    if not isinstance(payload, dict) or not isinstance(payload.get("transcripts"), list):
        raise ASRParseError("not a DashScope transcripts response")

    segments = []
    source_index = 0
    for transcript in payload["transcripts"]:
        if not isinstance(transcript, dict):
            continue
        sentences = transcript.get("sentences")
        if isinstance(sentences, list):
            for sentence in sentences:
                current_index = source_index
                source_index += 1
                if not isinstance(sentence, dict):
                    continue
                text = _clean_text(sentence.get("text"))
                if not text:
                    continue
                segments.append(
                    TranscriptSegment(
                        text=text,
                        start_ms=_to_milliseconds(sentence.get("begin_time"), "milliseconds"),
                        end_ms=_to_milliseconds(sentence.get("end_time"), "milliseconds"),
                        source_index=current_index,
                        provider="dashscope",
                    )
                )
            continue

        text = _clean_text(transcript.get("text"))
        if text:
            segments.append(
                TranscriptSegment(
                    text=text,
                    start_ms=None,
                    end_ms=None,
                    source_index=source_index,
                    provider="dashscope",
                )
            )
            source_index += 1

    if not segments:
        raise ASRParseError("DashScope response contains no non-empty transcript sentences")
    return _sort_segments(segments)


def parse_asr_response(payload: object) -> list[TranscriptSegment]:
    """Dispatch a response only when it matches one supported provider structure."""

    if isinstance(payload, dict) and isinstance(payload.get("choices"), list):
        return parse_compatible_chat(payload)
    if isinstance(payload, dict) and isinstance(payload.get("transcripts"), list):
        return parse_dashscope(payload)
    if isinstance(payload, dict) and (_audio_segment_lists(payload) or isinstance(payload.get("text"), str)):
        return parse_audio_transcriptions(payload)

    keys = ", ".join(sorted(str(key) for key in payload)) if isinstance(payload, dict) else type(payload).__name__
    raise ASRParseError(f"unrecognized ASR response structure (top-level keys/type: {keys or 'empty'})")


def render_transcript(segments: list[TranscriptSegment]) -> str:
    """Render canonical segments as a timestamped UTF-8 text transcript."""

    lines = []
    for segment in segments:
        prefix = ""
        if segment.start_ms is not None:
            total_seconds = segment.start_ms // 1000
            minutes, seconds = divmod(total_seconds, 60)
            hours, minutes = divmod(minutes, 60)
            prefix = f"[{hours:02d}:{minutes:02d}:{seconds:02d}] "
        lines.append(f"{prefix}{segment.text}")
    return "\n".join(lines) + ("\n" if lines else "")


def merge_chunk_transcripts(
    chunks: list[ChunkTranscript],
    *,
    min_nonempty_ratio: float = 0.9,
    boundary_window_ms: int = 2000,
    text_similarity_threshold: float = 0.92,
) -> TranscriptMergeResult:
    """Offset local segments, sort them globally, and validate merge quality."""

    if not chunks:
        raise TranscriptMergeError("chunk transcript list is empty")
    ordered_chunks = sorted(chunks, key=lambda chunk: (chunk.start_ms, chunk.chunk_index))
    if len({chunk.chunk_index for chunk in ordered_chunks}) != len(ordered_chunks):
        raise TranscriptMergeError("chunk indexes must be unique")
    if any(chunk.start_ms < 0 or chunk.end_ms <= chunk.start_ms for chunk in ordered_chunks):
        raise TranscriptMergeError("chunk boundaries must have positive, ordered durations")

    input_count = sum(len(chunk.segments) for chunk in ordered_chunks)
    if input_count == 0:
        raise TranscriptMergeError("chunk transcripts contain no segments")
    nonempty_count = sum(1 for chunk in ordered_chunks for item in chunk.segments if _clean_text(item.text))
    nonempty_ratio = nonempty_count / input_count
    if nonempty_ratio < min_nonempty_ratio:
        raise TranscriptMergeError(
            f"non-empty transcript ratio {nonempty_ratio:.3f} is below required {min_nonempty_ratio:.3f}"
        )

    candidates: list[_MergeCandidate] = []
    for chunk in ordered_chunks:
        for local_order, item in enumerate(chunk.segments):
            text = _clean_text(item.text)
            if not text:
                continue
            global_start_ms = chunk.start_ms + item.start_ms if item.start_ms is not None else None
            global_end_ms = chunk.start_ms + item.end_ms if item.end_ms is not None else None
            effective_start = global_start_ms if global_start_ms is not None else chunk.start_ms
            candidates.append(
                _MergeCandidate(
                    sort_key=(effective_start, global_start_ms is None, chunk.chunk_index, local_order),
                    chunk=chunk,
                    local_segment=item,
                    text=text,
                    global_start_ms=global_start_ms,
                    global_end_ms=global_end_ms,
                )
            )

    candidates.sort(key=lambda candidate: candidate.sort_key)
    chunk_positions = {chunk.chunk_index: position for position, chunk in enumerate(ordered_chunks)}
    kept_candidates: list[_MergeCandidate] = []
    kept_by_chunk: dict[int, list[_MergeCandidate]] = {}
    dropped_overlap_count = 0
    for candidate in candidates:
        current_position = chunk_positions[candidate.chunk.chunk_index]
        previous_candidates = (
            kept_by_chunk.get(ordered_chunks[current_position - 1].chunk_index, []) if current_position > 0 else []
        )
        overlaps_previous_chunk = any(
            previous.global_end_ms is not None
            and candidate.global_start_ms is not None
            and abs(previous.chunk.end_ms - previous.global_end_ms) <= boundary_window_ms
            and abs(candidate.global_start_ms - candidate.chunk.start_ms) <= boundary_window_ms
            and abs(candidate.global_start_ms - previous.global_end_ms) <= boundary_window_ms
            and min(len(previous.text), len(candidate.text)) >= 4
            and SequenceMatcher(None, previous.text.casefold(), candidate.text.casefold()).ratio()
            >= text_similarity_threshold
            for previous in reversed(previous_candidates)
        )
        if overlaps_previous_chunk:
            dropped_overlap_count += 1
            continue
        kept_candidates.append(candidate)
        kept_by_chunk.setdefault(candidate.chunk.chunk_index, []).append(candidate)

    merged_segments = []
    sources = []
    for segment_index, candidate in enumerate(kept_candidates):
        merged_segments.append(
            TranscriptSegment(
                text=candidate.text,
                start_ms=candidate.global_start_ms,
                end_ms=candidate.global_end_ms,
                source_index=segment_index,
                provider=candidate.local_segment.provider,
            )
        )
        sources.append(
            SegmentSource(
                segment_index=segment_index,
                chunk_index=candidate.chunk.chunk_index,
                chunk_path=candidate.chunk.chunk_path,
                chunk_start_ms=candidate.chunk.start_ms,
                local_source_index=candidate.local_segment.source_index,
                provider=candidate.local_segment.provider,
                global_start_ms=candidate.global_start_ms,
                global_end_ms=candidate.global_end_ms,
            )
        )

    timestamped_starts = [item.start_ms for item in merged_segments if item.start_ms is not None]
    if timestamped_starts != sorted(timestamped_starts):
        raise TranscriptMergeError("merged transcript timestamps are not monotonic")
    return TranscriptMergeResult(
        segments=tuple(merged_segments),
        sources=tuple(sources),
        input_segment_count=input_count,
        dropped_overlap_count=dropped_overlap_count,
        nonempty_ratio=nonempty_ratio,
    )
