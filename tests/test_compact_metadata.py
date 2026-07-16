"""Host-facing compact metadata must not contain media credentials."""

from __future__ import annotations

import json
from pathlib import Path

import creator_pipeline


SIGNED_URL = (
    "https://cdn.example.invalid/video.mp4"
    "?X-Amz-Signature=download-signature&OSSAccessKeyId=download-access-key"
)


def metadata_item(*, download_url: str = SIGNED_URL) -> dict[str, object]:
    return {
        "platform": "douyin",
        "platform_video_id": "platform-video-1",
        "title": "Safe research title",
        "published_at": "2026-07-15T00:00:00Z",
        "duration": 30,
        "stats": {"like": 12, "comment": 3},
        "download_url": download_url,
        "source_url": (
            "https://viewer:source-password@www.douyin.com/video/platform-video-1"
            "?share_token=source-secret&from=profile"
        ),
        "raw": {"provider_noise": True},
    }


def assert_no_download_credentials(value: object) -> None:
    rendered = json.dumps(value, ensure_ascii=False)
    for forbidden in (
        "download_url",
        "download-signature",
        "download-access-key",
        "source-password",
        "source-secret",
        "X-Amz-Signature",
        "OSSAccessKeyId",
    ):
        assert forbidden not in rendered


def test_compact_metadata_item_uses_boolean_instead_of_download_url() -> None:
    compact = creator_pipeline.compact_metadata_item(metadata_item())

    assert compact["download_available"] is True
    assert compact["source_url"] == (
        "https://www.douyin.com/video/platform-video-1?from=profile"
    )
    assert_no_download_credentials(compact)


def test_compact_metadata_marks_missing_download_without_adding_url() -> None:
    compact = creator_pipeline.compact_metadata_item(metadata_item(download_url=""))

    assert compact["download_available"] is False
    assert_no_download_credentials(compact)


def test_select_samples_keeps_download_url_only_in_internal_metadata(tmp_path: Path) -> None:
    normalized_path = tmp_path / "normalized.json"
    selected_path = tmp_path / "selected.json"
    creator_pipeline.write_json(normalized_path, {"count": 1, "items": [metadata_item()]})

    creator_pipeline.select_samples(normalized_path, selected_path, 1)

    internal = json.loads(selected_path.read_text(encoding="utf-8"))
    compact_path = selected_path.with_name("selected.compact.json")
    compact_text = compact_path.read_text(encoding="utf-8")
    compact = json.loads(compact_text)

    assert internal["items"][0]["download_url"] == SIGNED_URL
    assert compact["items"][0]["download_available"] is True
    assert compact["items"][0]["source_url"].endswith("?from=profile")
    assert_no_download_credentials(compact_text)
