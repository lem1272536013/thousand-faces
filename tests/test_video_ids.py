"""Platform IDs and local artifact IDs have one stable, traceable contract."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import creator_pipeline
import path_policy
import prepare_host_refinement
import run_creator_skill_build as runner
import stage_coverage


@pytest.mark.parametrize(
    ("raw_id", "artifact_id"),
    [
        ("190000000000000001", "190000000000000001"),
        ("food-synthetic-001", "food-synthetic-001"),
        ("Legacy_ID-01", "legacy_id-01"),
        ("legacy id 01", "legacy-id-01"),
    ],
)
def test_douyin_short_and_legacy_ids_have_explicit_artifact_ids(raw_id: str, artifact_id: str) -> None:
    assert path_policy.ArtifactIdRegistry().assign(raw_id) == artifact_id


def test_unicode_only_id_gets_stable_ascii_hash_identity() -> None:
    first = path_policy.ArtifactIdRegistry().assign("测试视频")
    second = path_policy.ArtifactIdRegistry().assign("测试视频")

    assert first == second
    assert re.fullmatch(r"video--[0-9a-f]{10}", first)
    assert path_policy.validate_artifact_id(first) == first


def test_normalization_collisions_get_stable_non_overwriting_suffixes() -> None:
    raw_ids = ["A B", "A+B", "A B"]

    first_items, first_records = path_policy.assign_artifact_ids(
        [{"platform_video_id": raw_id} for raw_id in raw_ids]
    )
    second_items, second_records = path_policy.assign_artifact_ids(
        [{"platform_video_id": raw_id} for raw_id in raw_ids]
    )

    first_ids = [item["artifact_id"] for item in first_items]
    assert first_ids == [item["artifact_id"] for item in second_items]
    assert first_records == second_records
    assert first_ids[0] == "a-b"
    assert re.fullmatch(r"a-b--[0-9a-f]{10}", first_ids[1])
    assert first_ids[2] == first_ids[0]
    assert len(set(first_ids[:2])) == 2


def test_preassigned_collision_id_survives_selection_subset() -> None:
    normalized, _records = path_policy.assign_artifact_ids(
        [
            {"platform_video_id": "A B"},
            {"platform_video_id": "A+B"},
        ]
    )

    selected, selected_records = path_policy.assign_artifact_ids([normalized[1]])

    assert selected[0]["artifact_id"] == normalized[1]["artifact_id"]
    assert selected_records[0]["platform_video_id"] == "A+B"


def test_long_collision_ids_stay_bounded_and_unique() -> None:
    prefix = "a" * 200
    items, _records = path_policy.assign_artifact_ids(
        [
            {"platform_video_id": prefix + " x"},
            {"platform_video_id": prefix + "+x"},
        ]
    )

    artifact_ids = [item["artifact_id"] for item in items]
    assert len(set(artifact_ids)) == 2
    assert all(len(artifact_id) <= path_policy.MAX_ARTIFACT_ID_LENGTH for artifact_id in artifact_ids)


def test_normalize_and_select_write_structured_id_maps(tmp_path: Path) -> None:
    raw_path = tmp_path / "raw.json"
    normalized_path = tmp_path / "metadata" / "normalized.json"
    selected_path = normalized_path.with_name("selected.json")
    raw_path.write_text(
        json.dumps(
            {
                "items": [
                    {"aweme_id": "A B", "desc": "first", "play_url": "https://media.example/1.mp4"},
                    {"aweme_id": "A+B", "desc": "second", "play_url": "https://media.example/2.mp4"},
                ]
            }
        ),
        encoding="utf-8",
    )

    creator_pipeline.normalize_metadata(raw_path, normalized_path)
    creator_pipeline.select_samples(normalized_path, selected_path, 2)

    normalized = creator_pipeline.read_json(normalized_path)
    selected = creator_pipeline.read_json(selected_path)
    full_map = creator_pipeline.read_json(normalized_path.parent / "video_id_map.json")
    selected_map = creator_pipeline.read_json(normalized_path.parent / "selected.video_id_map.json")
    assert [item["platform_video_id"] for item in normalized["items"]] == ["A B", "A+B"]
    assert [item["artifact_id"] for item in normalized["items"]] == ["a-b", selected["items"][1]["artifact_id"]]
    assert selected["items"][0]["artifact_id"] == "a-b"
    assert selected["items"][0]["raw"]["aweme_id"] == "A B"
    assert selected["items"][0]["artifact_id"] != selected["items"][1]["artifact_id"]
    assert full_map["schema_version"] == path_policy.VIDEO_ID_MAP_SCHEMA_VERSION
    assert full_map["records"] == selected_map["records"]


def test_existing_transcripts_are_mapped_from_platform_to_artifact_id(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    (source / "A B.txt").write_text("mapped transcript", encoding="utf-8")
    selected_path = tmp_path / "selected.json"
    creator_pipeline.write_json(
        selected_path,
        {"items": [{"platform_video_id": "A B", "artifact_id": "a-b"}]},
    )

    runner.copy_existing_transcripts(source, target, selected_path=selected_path)

    assert (target / "a-b.txt").read_text(encoding="utf-8") == "mapped transcript"
    assert not (target / "A B.txt").exists()


def test_host_corpus_reads_artifact_file_but_keeps_platform_evidence_id(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    metadata = run_dir / "metadata"
    transcripts = run_dir / "transcripts"
    metadata.mkdir(parents=True)
    transcripts.mkdir()
    creator_pipeline.write_json(
        metadata / "selected.compact.json",
        {
            "requested_count": 1,
            "selected_count": 1,
            "selection_strategy": "published_at_desc",
            "creator_profile": {},
            "items": [
                {
                    "platform_video_id": "A B",
                    "artifact_id": "a-b",
                    "title": "mapped evidence",
                    "published_at": "2026-01-01T00:00:00+00:00",
                    "stats": {},
                }
            ],
        },
    )
    (transcripts / "a-b.txt").write_text("这是通过本地 artifact ID 读取的转写内容。", encoding="utf-8")

    corpus = prepare_host_refinement.build_corpus_index(run_dir)
    record = corpus["records"][0]

    assert record["video_id"] == "A B"
    assert record["platform_video_id"] == "A B"
    assert record["artifact_id"] == "a-b"
    assert record["transcript_chars"] > 0
    assert corpus["video_id_map"] == [{"platform_video_id": "A B", "artifact_id": "a-b"}]


def test_stage_coverage_uses_artifact_files_and_reports_platform_id(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    for relative in ("metadata", "media/videos", "media/audio", "transcripts", "logs"):
        (run_dir / relative).mkdir(parents=True, exist_ok=True)
    creator_pipeline.write_json(run_dir / "input.json", {"execution_mode": "online_media"})
    creator_pipeline.write_json(
        run_dir / "config.snapshot.json",
        {
            "DRAFT_MIN_STAGE_COUNT": "1",
            "DRAFT_MIN_STAGE_RATIO": "1",
            "READY_MIN_STAGE_COUNT": "1",
            "READY_MIN_STAGE_RATIO": "1",
        },
    )
    creator_pipeline.write_json(
        run_dir / "metadata" / "selected.json",
        {
            "selected_count": 1,
            "items": [
                {
                    "platform_video_id": "A B",
                    "artifact_id": "a-b",
                    "download_url": "https://media.example.invalid/a.mp4",
                }
            ],
        },
    )
    (run_dir / "media" / "videos" / "a-b.mp4").write_bytes(b"video")
    (run_dir / "media" / "audio" / "a-b.mp3").write_bytes(b"audio")
    (run_dir / "transcripts" / "a-b.txt").write_text("transcript", encoding="utf-8")
    creator_pipeline.write_json(
        run_dir / "logs" / "download_status.json",
        {"results": [{"platform_video_id": "A B", "artifact_id": "a-b", "video_id": "a-b", "status": "downloaded"}]},
    )
    creator_pipeline.write_json(
        run_dir / "logs" / "audio_status.json",
        {"results": [{"video_id": "a-b", "status": "extracted"}]},
    )
    creator_pipeline.write_json(
        run_dir / "logs" / "asr_status.json",
        {"results": [{"video_id": "a-b", "status": "transcribed", "transcript": str(run_dir / "transcripts" / "a-b.txt")}]},
    )

    report = stage_coverage.evaluate_stage_coverage(run_dir)

    assert report["draft"]["passed"] is True
    assert report["videos"][0]["video_id"] == "A B"
    assert report["videos"][0]["artifact_id"] == "a-b"
    assert all(stage["covered"] for stage in report["videos"][0]["stages"].values())


def test_stage_coverage_marks_tampered_selected_id_invalid(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "metadata").mkdir(parents=True)
    creator_pipeline.write_json(run_dir / "input.json", {"execution_mode": "offline_transcripts"})
    creator_pipeline.write_json(run_dir / "config.snapshot.json", {})
    creator_pipeline.write_json(
        run_dir / "metadata" / "selected.json",
        {
            "selected_count": 1,
            "items": [{"platform_video_id": "../tampered", "artifact_id": "tampered"}],
        },
    )

    report = stage_coverage.evaluate_stage_coverage(run_dir)

    assert report["videos"][0]["stages"]["selected"]["status"] == "failed"
    assert any(issue["code"] == "VIDEO_ID_INVALID" for issue in report["issues"])
