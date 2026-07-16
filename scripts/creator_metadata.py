"""Creator metadata discovery, normalization, and sampling."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import path_policy
import redaction
from input_validation import SAMPLE_COUNT_RANGE, validate_bounded_int
from io_utils import atomic_write_json as write_json


COMMON_VIDEO_KEYS = ("aweme_list", "videos", "items", "list", "data")
ID_KEYS = ("platform_video_id", "aweme_id", "video_id", "item_id", "id")
TITLE_KEYS = ("title", "desc", "description", "caption")
PUBLISHED_KEYS = ("published_at", "create_time", "createTime", "publish_time", "timestamp")
AUTHOR_NAME_KEYS = ("nickname", "owner_nickname", "author_name", "display_name", "name")
AUTHOR_HANDLE_KEYS = ("unique_id", "owner_handle", "short_id", "handle")
AUTHOR_ID_KEYS = ("uid", "user_id", "author_id", "owner_id")
AUTHOR_SEC_UID_KEYS = ("sec_uid", "sec_user_id")
DOWNLOAD_KEYS = (
    "download_url",
    "play_url",
    "play_addr",
    "download_addr",
    "play_addr_h264",
    "play_addr_265",
    "video_url",
    "url_list",
    "url",
    "src",
)
SOURCE_URL_KEYS = ("share_url", "source_url", "detail_url", "url")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))

def get_path(obj: Any, path: str | None) -> Any:
    if not path:
        return None
    current = obj
    for part in path.split("."):
        if current is None:
            return None
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def first_value(obj: Any, paths: list[str], keys: tuple[str, ...]) -> Any:
    for path in paths:
        value = get_path(obj, path)
        if value not in (None, ""):
            return value
    return find_first_key(obj, keys)


def find_first_key(obj: Any, keys: tuple[str, ...]) -> Any:
    if isinstance(obj, dict):
        for key in keys:
            if key in obj and obj[key] not in (None, ""):
                value = obj[key]
                if isinstance(value, dict):
                    url = extract_url(value)
                    return url or value
                if isinstance(value, list):
                    url = extract_url(value)
                    return url or value
                return value
        for value in obj.values():
            found = find_first_key(value, keys)
            if found not in (None, ""):
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = find_first_key(item, keys)
            if found not in (None, ""):
                return found
    return None


def extract_url(value: Any) -> str | None:
    if isinstance(value, str):
        return value if value.startswith(("http://", "https://")) else None
    if isinstance(value, list):
        for item in value:
            url = extract_url(item)
            if url:
                return url
    if isinstance(value, dict):
        for key in ("url", "download_url", "play_url", "play_addr", "url_list", "uri", "src"):
            if key in value:
                url = extract_url(value[key])
                if url:
                    return url
        for nested in value.values():
            url = extract_url(nested)
            if url:
                return url
    return None


def collect_candidate_lists(obj: Any) -> list[list[Any]]:
    candidates: list[list[Any]] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in COMMON_VIDEO_KEYS and isinstance(value, list):
                candidates.append(value)
            candidates.extend(collect_candidate_lists(value))
    elif isinstance(obj, list):
        if obj and all(isinstance(item, dict) for item in obj):
            candidates.append(obj)
        for item in obj:
            candidates.extend(collect_candidate_lists(item))
    return candidates


def infer_video_items(raw: Any, configured_path: str | None = None) -> list[dict]:
    configured = get_path(raw, configured_path) if configured_path else None
    if isinstance(configured, list):
        return [item for item in configured if isinstance(item, dict)]

    candidates = collect_candidate_lists(raw)
    if not candidates:
        return []

    def score(items: list[Any]) -> int:
        total = 0
        for item in items[:10]:
            if not isinstance(item, dict):
                continue
            if find_first_key(item, ID_KEYS):
                total += 2
            if find_first_key(item, TITLE_KEYS):
                total += 1
            if find_first_key(item, DOWNLOAD_KEYS):
                total += 2
        return total

    best = max(candidates, key=score)
    return [item for item in best if isinstance(item, dict)]


def normalize_timestamp(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)):
        seconds = float(value)
        if seconds > 10_000_000_000:
            seconds = seconds / 1000
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return str(value)
    return str(value)


def safe_filename(value: str, fallback: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff._-]+", "-", value).strip("-_.")
    return text[:120] or fallback


def normalize_metadata(raw_path: Path, output_path: Path) -> Path:
    raw = read_json(raw_path)
    item_path = os.environ.get("TIKHUB_ITEMS_PATH", "")
    items = infer_video_items(raw, item_path)

    paths = {
        "id": [os.environ.get("TIKHUB_VIDEO_ID_PATH", "")],
        "title": [os.environ.get("TIKHUB_VIDEO_TITLE_PATH", "")],
        "published": [os.environ.get("TIKHUB_VIDEO_PUBLISHED_AT_PATH", "")],
        "download": [
            os.environ.get("TIKHUB_VIDEO_DOWNLOAD_URL_PATH", ""),
            "video.play_addr_h264",
            "video.play_addr",
            "video.play_addr_265",
            "video.download_addr",
        ],
        "source": [os.environ.get("TIKHUB_VIDEO_SOURCE_URL_PATH", "")],
    }
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        video_id = str(first_value(item, paths["id"], ID_KEYS) or f"video-{index}")
        title = str(first_value(item, paths["title"], TITLE_KEYS) or video_id)
        published = normalize_timestamp(first_value(item, paths["published"], PUBLISHED_KEYS))
        download_url = extract_url(first_value(item, paths["download"], DOWNLOAD_KEYS))
        source_url = extract_url(first_value(item, paths["source"], SOURCE_URL_KEYS))
        normalized.append(
            {
                "platform": "douyin",
                "platform_video_id": video_id,
                "title": title,
                "published_at": published,
                "duration": find_first_key(item, ("duration", "duration_ms")),
                "stats": {
                    "like": find_first_key(item, ("digg_count", "like", "like_count")),
                    "favorite": find_first_key(item, ("collect_count", "favorite", "favorite_count")),
                    "share": find_first_key(item, ("share_count", "share")),
                    "comment": find_first_key(item, ("comment_count", "comment")),
                },
                "download_url": download_url or "",
                "source_url": source_url or "",
                "raw": item,
            }
        )

    normalized, id_records = path_policy.assign_artifact_ids(normalized)
    write_json(output_path, {"count": len(normalized), "items": normalized})
    id_map_path = path_policy.resolve_within(output_path.parent, "video_id_map.json")
    write_json(id_map_path, path_policy.video_id_map_payload(id_records))
    return output_path


def compact_metadata_item(item: dict) -> dict:
    download_url = item.get("download_url")
    source_url = str(item.get("source_url") or "").strip()
    return {
        "platform": item.get("platform", "douyin"),
        "platform_video_id": item.get("platform_video_id", ""),
        "artifact_id": item.get("artifact_id", ""),
        "title": item.get("title", ""),
        "published_at": item.get("published_at", ""),
        "duration": item.get("duration"),
        "stats": item.get("stats", {}),
        "download_available": isinstance(download_url, str) and bool(download_url.strip()),
        "source_url": redaction.redact_url(source_url) if source_url else "",
    }


def candidate_author_dicts(obj: Any) -> list[dict]:
    candidates: list[dict] = []
    if isinstance(obj, dict):
        if any(key in obj for key in AUTHOR_NAME_KEYS + AUTHOR_HANDLE_KEYS + AUTHOR_ID_KEYS + AUTHOR_SEC_UID_KEYS):
            candidates.append(obj)
        for key in ("author", "user", "music", "account", "creator"):
            value = obj.get(key)
            if isinstance(value, dict):
                candidates.extend(candidate_author_dicts(value))
        for value in obj.values():
            if isinstance(value, (dict, list)):
                candidates.extend(candidate_author_dicts(value))
    elif isinstance(obj, list):
        for item in obj:
            candidates.extend(candidate_author_dicts(item))
    return candidates


def extract_creator_profile(items: list[dict]) -> dict:
    scored: list[tuple[int, dict]] = []
    for item in items:
        raw = item.get("raw", item)
        for candidate in candidate_author_dicts(raw):
            nickname = str(find_first_key(candidate, AUTHOR_NAME_KEYS) or "").strip()
            handle = str(find_first_key(candidate, AUTHOR_HANDLE_KEYS) or "").strip()
            author_id = str(find_first_key(candidate, AUTHOR_ID_KEYS) or "").strip()
            sec_uid = str(find_first_key(candidate, AUTHOR_SEC_UID_KEYS) or "").strip()
            if is_bad_profile_value(nickname):
                nickname = ""
            if is_bad_profile_value(handle):
                handle = ""
            if is_bad_profile_value(author_id):
                author_id = ""
            if is_bad_profile_value(sec_uid):
                sec_uid = ""
            if not any((nickname, handle, author_id, sec_uid)):
                continue
            score = 0
            score += 4 if nickname else 0
            score += 3 if handle else 0
            score += 2 if author_id else 0
            score += 2 if sec_uid else 0
            scored.append(
                (
                    score,
                    {
                        "platform": "douyin",
                        "nickname": nickname,
                        "handle": handle,
                        "author_id": author_id,
                        "sec_uid": sec_uid,
                    },
                )
            )
    if not scored:
        return {"platform": "douyin", "nickname": "", "handle": "", "author_id": "", "sec_uid": ""}
    scored.sort(key=lambda row: row[0], reverse=True)
    return scored[0][1]


def is_bad_profile_value(value: str) -> bool:
    if not value:
        return True
    lower = value.lower()
    if lower in {"0", "false", "true", "none", "null"}:
        return True
    if value.startswith(("http://", "https://")):
        return True
    return False


def select_samples(metadata_path: Path, output_path: Path, sample_count: int) -> Path:
    sample_count = validate_bounded_int("--sample-count", sample_count, SAMPLE_COUNT_RANGE)
    payload = read_json(metadata_path)
    items = payload.get("items", payload if isinstance(payload, list) else [])
    sorted_items = sorted(
        items,
        key=lambda item: item.get("published_at") or "",
        reverse=True,
    )
    selected, id_records = path_policy.assign_artifact_ids(sorted_items[:sample_count])
    compact_items = [compact_metadata_item(item) for item in selected]
    creator_profile = extract_creator_profile(selected)
    write_json(
        output_path,
        {
            "requested_count": sample_count,
            "selected_count": len(selected),
            "selection_strategy": "published_at_desc",
            "items": selected,
        },
    )
    write_json(
        output_path.with_name("selected.compact.json"),
        {
            "requested_count": sample_count,
            "selected_count": len(selected),
            "selection_strategy": "published_at_desc",
            "creator_profile": creator_profile,
            "items": compact_items,
        },
    )
    write_json(output_path.with_name("creator_profile.json"), creator_profile)
    id_map_path = path_policy.resolve_within(output_path.parent, "selected.video_id_map.json")
    write_json(id_map_path, path_policy.video_id_map_payload(id_records))
    return output_path
