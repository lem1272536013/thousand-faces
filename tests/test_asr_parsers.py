"""Provider-specific ASR parsing must preserve transcript semantics."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import creator_pipeline
from asr_parsers import (
    ASRParseError,
    TranscriptSegment,
    parse_asr_response,
    parse_audio_transcriptions,
    parse_compatible_chat,
    parse_dashscope,
    render_transcript,
)


def load_fixture(fixture_root: Path, name: str) -> object:
    return json.loads((fixture_root / "asr" / name).read_text(encoding="utf-8"))


def load_edge_case(fixture_root: Path, case_id: str) -> list[dict[str, object]]:
    payload = load_fixture(fixture_root, "transcript_edge_cases.json")
    assert isinstance(payload, dict)
    cases = payload["cases"]
    assert isinstance(cases, list)
    case = next(item for item in cases if isinstance(item, dict) and item.get("case_id") == case_id)
    segments = case["segments"]
    assert isinstance(segments, list)
    return segments


def as_dashscope_response(rows: list[dict[str, object]]) -> dict[str, object]:
    sentences = []
    for index, row in enumerate(rows):
        sentence = {
            "sentence_id": index,
            "text": row.get("text"),
        }
        if "start" in row:
            sentence["begin_time"] = row["start"]
        if "end" in row:
            sentence["end_time"] = row["end"]
        sentences.append(sentence)
    return {"transcripts": [{"channel_id": 0, "sentences": sentences}]}


def test_transcript_segment_exposes_canonical_provenance_fields() -> None:
    segment = TranscriptSegment(
        text="人工片段",
        start_ms=0,
        end_ms=900,
        source_index=3,
        provider="dashscope",
    )

    assert segment.text == "人工片段"
    assert segment.start_ms == 0
    assert segment.end_ms == 900
    assert segment.source_index == 3
    assert segment.provider == "dashscope"


def test_compatible_chat_adapter_reads_only_message_content(fixture_root: Path) -> None:
    payload = load_fixture(fixture_root, "compatible_chat_completions.json")

    segments = parse_compatible_chat(payload)

    assert segments == [
        TranscriptSegment(
            text="这是完全人工构造的兼容接口转写文本。",
            start_ms=None,
            end_ms=None,
            source_index=0,
            provider="compatible_chat",
        )
    ]


def test_audio_transcriptions_adapter_converts_seconds_to_milliseconds(fixture_root: Path) -> None:
    payload = load_fixture(fixture_root, "audio_transcriptions.json")

    segments = parse_audio_transcriptions(payload)

    assert [segment.text for segment in segments] == ["第一句人工文本。", "第二句人工文本。"]
    assert [(segment.start_ms, segment.end_ms) for segment in segments] == [(0, 1200), (1200, 2800)]
    assert [segment.source_index for segment in segments] == [0, 1]
    assert {segment.provider for segment in segments} == {"audio_transcriptions"}


def test_dashscope_adapter_preserves_millisecond_zero_timestamp(fixture_root: Path) -> None:
    payload = load_fixture(fixture_root, "dashscope_segments.json")

    segments = parse_dashscope(payload)

    assert [(segment.start_ms, segment.end_ms) for segment in segments] == [(0, 1250), (1250, 2600)]
    assert render_transcript(segments).splitlines()[0] == "[00:00:00] 零毫秒开始的人工句子。"


def test_three_input_segments_are_not_recursively_doubled() -> None:
    payload = {
        "task": "synthetic",
        "segments": [
            {"start": 0.0, "end": 0.8, "text": "第一段。"},
            {"start": 0.8, "end": 1.6, "text": "第二段。"},
            {"start": 1.6, "end": 2.4, "text": "第三段。"},
        ],
    }

    segments = parse_asr_response(payload)

    assert len(segments) == 3
    assert [segment.text for segment in segments] == ["第一段。", "第二段。", "第三段。"]


def test_mirrored_parent_and_result_segments_are_mapped_once(fixture_root: Path) -> None:
    payload = load_fixture(fixture_root, "nested_duplicate_nodes.json")

    segments = parse_asr_response(payload)

    assert len(segments) == 1
    assert segments[0].text == "父子节点重复出现的人工句子。"


def test_mirrored_paths_only_remove_exact_matches_and_keep_distinct_times() -> None:
    payload = {
        "payload": {
            "segments": [{"start": 1.0, "end": 1.8, "text": "镜像中的相同话术。"}],
            "result": {
                "segments": [
                    {"start": 1.0, "end": 1.8, "text": "镜像中的相同话术。"},
                    {"start": 9.0, "end": 9.8, "text": "镜像中的相同话术。"},
                ]
            },
        }
    }

    segments = parse_asr_response(payload)

    assert len(segments) == 2
    assert [segment.start_ms for segment in segments] == [1000, 9000]


def test_same_text_at_different_times_is_preserved(fixture_root: Path) -> None:
    payload = as_dashscope_response(load_edge_case(fixture_root, "legal_repeat"))

    segments = parse_asr_response(payload)

    assert len(segments) == 2
    assert [segment.start_ms for segment in segments] == [1000, 9000]
    assert segments[0].text == segments[1].text


def test_out_of_order_segments_are_stably_sorted_by_valid_time(fixture_root: Path) -> None:
    timed_rows = load_edge_case(fixture_root, "out_of_order")
    no_time_rows = load_edge_case(fixture_root, "no_timestamp")
    payload = as_dashscope_response([*timed_rows, *no_time_rows])

    segments = parse_asr_response(payload)

    assert [segment.text for segment in segments] == [
        "输入中的较早时刻。",
        "输入中的后一时刻。",
        "该人工句子没有时间字段。",
    ]
    assert [segment.source_index for segment in segments] == [1, 0, 2]


def test_unknown_response_fails_without_creating_transcript_and_preserves_raw_json(tmp_path: Path) -> None:
    input_path = tmp_path / "unknown.result.json"
    output_path = tmp_path / "unknown.txt"
    raw_document = '{\n  "status": "ok",\n  "metadata": {"text": "不能递归猜测这里是转写"}\n}\n'
    input_path.write_text(raw_document, encoding="utf-8")

    with pytest.raises(ASRParseError, match="unrecognized ASR response structure.*raw response preserved"):
        creator_pipeline.asr_json_to_transcript(input_path, output_path)

    assert input_path.read_text(encoding="utf-8") == raw_document
    assert not output_path.exists()
