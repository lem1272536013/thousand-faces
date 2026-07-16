"""Chunk transcripts must merge into one monotonic, traceable global timeline."""

from __future__ import annotations

import pytest

from asr_parsers import (
    ChunkTranscript,
    TranscriptMergeError,
    TranscriptSegment,
    merge_chunk_transcripts,
    render_transcript,
)


def segment(text: str, start_ms: int | None, end_ms: int | None, source_index: int = 0) -> TranscriptSegment:
    return TranscriptSegment(
        text=text,
        start_ms=start_ms,
        end_ms=end_ms,
        source_index=source_index,
        provider="audio_transcriptions",
    )


def chunk(
    chunk_index: int,
    start_ms: int,
    duration_ms: int,
    segments: list[TranscriptSegment],
) -> ChunkTranscript:
    return ChunkTranscript(
        chunk_index=chunk_index,
        chunk_path=f"chunk-{chunk_index:03d}.mp3",
        start_ms=start_ms,
        end_ms=start_ms + duration_ms,
        segments=tuple(segments),
    )


def test_second_chunk_local_five_seconds_becomes_global_125_seconds() -> None:
    result = merge_chunk_transcripts(
        [
            chunk(0, 0, 120000, [segment("第一片尾部。", 119000, 120000)]),
            chunk(1, 120000, 120000, [segment("第二片五秒处。", 5000, 6000)]),
        ]
    )

    assert [item.start_ms for item in result.segments] == [119000, 125000]
    assert "[00:02:05] 第二片五秒处。" in render_transcript(list(result.segments))
    assert result.sources[1].chunk_index == 1
    assert result.sources[1].local_source_index == 0


def test_exact_boundary_overlap_in_adjacent_chunks_is_removed_once() -> None:
    result = merge_chunk_transcripts(
        [
            chunk(0, 0, 120000, [segment("跨片边界重复句子。", 119000, 120000)]),
            chunk(1, 120000, 120000, [segment("跨片边界重复句子。", 0, 1000)]),
        ]
    )

    assert [item.text for item in result.segments] == ["跨片边界重复句子。"]
    assert result.dropped_overlap_count == 1


def test_legal_repeat_outside_boundary_time_window_is_preserved() -> None:
    result = merge_chunk_transcripts(
        [
            chunk(0, 0, 120000, [segment("这句话可以合法重复。", 100000, 101000)]),
            chunk(1, 120000, 120000, [segment("这句话可以合法重复。", 10000, 11000)]),
        ]
    )

    assert len(result.segments) == 2
    assert [item.start_ms for item in result.segments] == [100000, 130000]
    assert result.dropped_overlap_count == 0


def test_different_text_inside_boundary_window_is_preserved() -> None:
    result = merge_chunk_transcripts(
        [
            chunk(0, 0, 120000, [segment("上一片结尾。", 119000, 120000)]),
            chunk(1, 120000, 120000, [segment("下一片开头。", 0, 1000)]),
        ]
    )

    assert [item.text for item in result.segments] == ["上一片结尾。", "下一片开头。"]
    assert result.dropped_overlap_count == 0


def test_merged_timestamps_are_monotonic_even_when_local_input_is_out_of_order() -> None:
    result = merge_chunk_transcripts(
        [
            chunk(
                0,
                0,
                120000,
                [
                    segment("五秒。", 5000, 6000, source_index=0),
                    segment("一秒。", 1000, 2000, source_index=1),
                ],
            ),
            chunk(1, 120000, 5000, [segment("下一片。", 0, 1000)]),
        ]
    )

    starts = [item.start_ms for item in result.segments if item.start_ms is not None]
    assert starts == [1000, 5000, 120000]
    assert starts == sorted(starts)
    assert [source.local_source_index for source in result.sources] == [1, 0, 0]


def test_low_nonempty_ratio_fails_merge_validation() -> None:
    with pytest.raises(TranscriptMergeError, match="non-empty transcript ratio"):
        merge_chunk_transcripts(
            [
                chunk(
                    0,
                    0,
                    120000,
                    [segment("", 0, 1000), segment("有效文本。", 1000, 2000)],
                )
            ]
        )
