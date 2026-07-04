#!/usr/bin/env python3
"""Deterministic pipeline utilities for Thousand Faces Style Skill."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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
TEXT_KEYS = ("text", "transcript", "sentence", "content")
SEGMENT_KEYS = ("sentences", "segments", "transcripts", "paragraphs", "words")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def update_workflow_state(run_dir: Path, step_id: str, status: str, note: str = "") -> None:
    """Update workflow.plan.json with best-effort runtime status."""
    workflow_path = run_dir / "workflow.plan.json"
    if not workflow_path.exists():
        return

    try:
        workflow = read_json(workflow_path)
    except (OSError, json.JSONDecodeError):
        return

    now = datetime.now(timezone.utc).isoformat()
    workflow["status"] = "failed" if status == "failed" else "running"
    workflow["updated_at"] = now

    found = False
    for step in workflow.get("steps", []):
        if step.get("step_id") != step_id:
            continue
        found = True
        step["status"] = status
        step["updated_at"] = now
        if status == "running":
            step.setdefault("started_at", now)
        if status in {"completed", "skipped", "failed"}:
            step["completed_at"] = now
        if note:
            step["note"] = note
        break

    if not found:
        workflow.setdefault("steps", []).append(
            {
                "step_id": step_id,
                "status": status,
                "updated_at": now,
                "note": note,
            }
        )

    steps = workflow.get("steps", [])
    if steps and all(step.get("status") in {"completed", "skipped"} for step in steps):
        workflow["status"] = "completed"

    write_json(workflow_path, workflow)


def load_env_file(path: Path | None) -> None:
    if not path:
        return
    if not path.exists():
        raise SystemExit(f"env file not found: {path}")
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


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
    normalized = []
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

    write_json(output_path, {"count": len(normalized), "items": normalized})
    return output_path


def compact_metadata_item(item: dict) -> dict:
    return {
        "platform": item.get("platform", "douyin"),
        "platform_video_id": item.get("platform_video_id", ""),
        "title": item.get("title", ""),
        "published_at": item.get("published_at", ""),
        "duration": item.get("duration"),
        "stats": item.get("stats", {}),
        "download_url": item.get("download_url", ""),
        "source_url": item.get("source_url", ""),
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
    payload = read_json(metadata_path)
    items = payload.get("items", payload if isinstance(payload, list) else [])
    sorted_items = sorted(
        items,
        key=lambda item: item.get("published_at") or "",
        reverse=True,
    )
    selected = sorted_items[:sample_count]
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
    return output_path


def download_one(item: dict, output_dir: Path, timeout: int, retries: int) -> dict:
    video_id = safe_filename(str(item.get("platform_video_id") or "video"), "video")
    url = item.get("download_url")
    final_path = output_dir / f"{video_id}.mp4"
    part_path = output_dir / f"{video_id}.mp4.part"
    if final_path.exists() and final_path.stat().st_size > 0:
        return {"video_id": video_id, "status": "skipped", "path": str(final_path)}
    if not url:
        return {"video_id": video_id, "status": "failed", "error": "missing download_url"}

    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=timeout) as response, open(part_path, "wb") as handle:
                shutil.copyfileobj(response, handle)
            if part_path.stat().st_size <= 0:
                raise RuntimeError("downloaded file is empty")
            part_path.replace(final_path)
            return {"video_id": video_id, "status": "downloaded", "path": str(final_path)}
        except Exception as exc:  # noqa: BLE001 - record provider/network failure
            if attempt == retries:
                return {"video_id": video_id, "status": "failed", "error": str(exc)}
            time.sleep(min(attempt * 2, 10))
    return {"video_id": video_id, "status": "failed", "error": "unknown download error"}


def download_videos(selected_path: Path, output_dir: Path, logs_dir: Path) -> Path:
    payload = read_json(selected_path)
    items = payload.get("items", [])
    output_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    concurrency = int(os.environ.get("DOWNLOAD_CONCURRENCY", "6"))
    retries = int(os.environ.get("DOWNLOAD_RETRY", "3"))
    timeout = int(os.environ.get("HTTP_TIMEOUT_SECONDS", "60"))

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, concurrency)) as executor:
        futures = [executor.submit(download_one, item, output_dir, timeout, retries) for item in items]
        results = [future.result() for future in concurrent.futures.as_completed(futures)]

    output_path = logs_dir / "download_status.json"
    write_json(output_path, {"count": len(results), "results": sorted(results, key=lambda row: row["video_id"])})
    return output_path


def extract_audio(video_dir: Path, audio_dir: Path) -> Path:
    audio_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg = os.environ.get("FFMPEG_BIN", "ffmpeg")
    audio_format = os.environ.get("ALI_ASR_AUDIO_FORMAT", "wav").lstrip(".")
    results = []
    for video_path in sorted(video_dir.glob("*.mp4")):
        output_path = audio_dir / f"{video_path.stem}.{audio_format}"
        if output_path.exists() and output_path.stat().st_size > 0:
            results.append({"video_id": video_path.stem, "status": "skipped", "path": str(output_path)})
            continue
        cmd = [
            ffmpeg,
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            os.environ.get("ASR_SAMPLE_RATE", "16000"),
        ]
        if audio_format in {"mp3", "mpeg"}:
            cmd.extend(["-codec:a", "libmp3lame", "-b:a", os.environ.get("ASR_MP3_BITRATE", "64k")])
        cmd.append(str(output_path))
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
            results.append({"video_id": video_path.stem, "status": "extracted", "path": str(output_path)})
        else:
            results.append({"video_id": video_path.stem, "status": "failed", "error": proc.stderr[-2000:]})
    output_status = audio_dir.parent.parent / "logs" / "audio_status.json"
    write_json(output_status, {"count": len(results), "results": results})
    return output_status


def collect_text_segments(obj: Any) -> list[dict]:
    segments: list[dict] = []
    if isinstance(obj, dict):
        if any(key in obj for key in TEXT_KEYS):
            text = next((str(obj[key]).strip() for key in TEXT_KEYS if obj.get(key)), "")
            if text:
                begin = obj.get("begin_time") or obj.get("start_time") or obj.get("start") or obj.get("begin")
                segments.append({"start": begin, "text": text})
        for key in SEGMENT_KEYS:
            value = obj.get(key)
            if isinstance(value, list):
                for item in value:
                    segments.extend(collect_text_segments(item))
        for value in obj.values():
            if isinstance(value, (dict, list)):
                segments.extend(collect_text_segments(value))
    elif isinstance(obj, list):
        for item in obj:
            segments.extend(collect_text_segments(item))
    return segments


def format_start(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        number = float(value)
        if number >= 1000:
            number = number / 1000
        minutes, seconds = divmod(int(number), 60)
        hours, minutes = divmod(minutes, 60)
        return f"[{hours:02d}:{minutes:02d}:{seconds:02d}] "
    except (TypeError, ValueError):
        return ""


def asr_json_to_transcript(input_path: Path, output_path: Path) -> Path:
    data = read_json(input_path)
    segments = collect_text_segments(data)
    seen = set()
    lines = []
    for segment in segments:
        text = re.sub(r"\s+", " ", segment["text"]).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        lines.append(f"{format_start(segment.get('start'))}{text}".strip())
    if not lines:
        fallback = find_first_key(data, TEXT_KEYS)
        if fallback:
            lines.append(str(fallback).strip())
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return output_path


def summarize_transcripts(transcripts_dir: Path, output_dir: Path, overwrite: bool = True) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "summary.md"
    if output_path.exists() and output_path.stat().st_size > 20 and not overwrite:
        return output_path

    rows = []
    all_text = []
    for path in sorted(transcripts_dir.glob("*.txt")):
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            continue
        rows.append(f"| {path.stem} | {len(text)} | {len(re.findall(r'[。！？!?]', text))} |")
        all_text.append((path.stem, text))

    top_terms = extract_terms("\n".join(text for _, text in all_text))
    summary = [
        "# Creator Transcript Research Summary",
        "",
        "## Coverage",
        "",
        "| Video | Chars | Sentence-like breaks |",
        "|---|---:|---:|",
        *(rows or ["| none | 0 | 0 |"]),
        "",
        "## Repeated Terms",
        "",
        *(f"- {term}" for term in top_terms[:30]),
        "",
        "## Preliminary Findings",
        "",
        "- This draft is generated from transcripts and should be refined with LLM-assisted style analysis.",
        "- Treat repeated terms, opening patterns, and sentence rhythm as research cues, not final conclusions.",
        "- Keep full transcripts outside the generated skill; only concise evidence notes should be promoted.",
        "- ASR may misrecognize proper nouns, names, brands, and English model names; verify key terms against metadata or source material before finalizing the skill.",
        "",
    ]
    output_path.write_text("\n".join(summary), encoding="utf-8")
    return output_path


def collect_transcript_corpus(transcripts_dir: Path, max_chars: int) -> str:
    chunks = []
    remaining = max_chars
    for path in sorted(transcripts_dir.glob("*.txt")):
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            continue
        block = f"\n\n## Video: {path.stem}\n\n{text}"
        if len(block) > remaining:
            block = block[:remaining]
        chunks.append(block)
        remaining -= len(block)
        if remaining <= 0:
            break
    return "".join(chunks).strip()


def extract_terms(text: str) -> list[str]:
    tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z][a-zA-Z0-9_-]{2,}", text.lower())
    stop = {"这个", "一个", "我们", "你们", "他们", "就是", "然后", "因为", "所以", "但是", "the", "and", "for"}
    counts: dict[str, int] = {}
    for token in tokens:
        if token in stop:
            continue
        counts[token] = counts.get(token, 0) + 1
    return [f"{term}: {count}" for term, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)]


def build_creator_skill(run_dir: Path, project_name: str, overwrite: bool = True) -> Path:
    skill_dir = run_dir / "skill"
    if (skill_dir / "SKILL.md").exists() and (skill_dir / "SKILL.md").stat().st_size > 20 and not overwrite:
        return skill_dir

    refs = skill_dir / "references"
    refs.mkdir(parents=True, exist_ok=True)
    research_summary = run_dir / "research" / "merged" / "summary.md"
    style_json = run_dir / "research" / "merged" / "style_research.json"
    creator_profile_path = run_dir / "metadata" / "creator_profile.json"
    summary_text = research_summary.read_text(encoding="utf-8") if research_summary.exists() else ""
    style = read_json(style_json) if style_json.exists() else {}
    creator_profile = read_json(creator_profile_path) if creator_profile_path.exists() else {}
    display_name = creator_profile.get("nickname") or project_name
    created_at = datetime.now(timezone.utc).isoformat()

    disclaimer = (
        "这是一个基于公开或授权材料生成的 AI 创作者风格辅助 Skill。"
        "它不代表创作者本人，也不得用于身份冒充、虚假背书或误导性代言。"
    )
    files = {
        refs / "research_summary.md": summary_text or "# 研究摘要\n\n尚未生成转写摘要。\n",
        refs / "persona.md": "# 人设与边界\n\n" + disclaimer + "\n\n## 结构化模型优先级\n\n生成、改写、批评和拒绝请求前，先读取 `persona_model.json`，按其中的 `generation_protocol` 选择 topic model、script template、judgment heuristic、expression DNA、anti-pattern 和 safety boundary。\n\n" + str(style.get("safety_boundary", "")),
        refs / "topic_model.md": "# 选题模型\n\n优先使用 `persona_model.json` 的 `topic_models` 和 `generation_protocol.task_routing` 判断选题；本文件用于展开解释和证据补充。\n\n" + str(style.get("topic_system", "根据转写研究笔记提出选题，并明确标注证据强弱。")) + "\n\n## 选题判断模型\n\n" + str(style.get("topic_selection_model", "")),
        refs / "script_style.md": "# 脚本风格\n\n优先使用 `persona_model.json` 的 `script_templates`、`expression_dna` 和 `anti_patterns` 生成或批评脚本；本文件用于展开结构、节奏和语感。\n\n" + str(style.get("script_structure_model", "优先参考证据索引中观察到的开头、节奏和结构模式。")) + "\n\n## Hook 模式\n\n" + str(style.get("hook_patterns", "")) + "\n\n## 表达 DNA\n\n" + str(style.get("expression_dna", "")),
        refs / "evidence_index.md": "# 证据索引\n\n" + str(style.get("evidence_index", "完整转写稿保存在 skill 外部。这里仅添加简短、改写后的证据笔记。")),
    }
    for path, text in files.items():
        path.write_text(text, encoding="utf-8")
    write_json(
        refs / "meta.json",
        {
            "name": display_name,
            "project_name": project_name,
            "creator_profile": creator_profile,
            "created_at": created_at,
            "source": "thousand-faces-style-skill",
            "safety_boundary": True,
        },
    )

    skill_md = f"""---
name: creator-{safe_filename(project_name, "creator")}
description: "基于公开或授权内容转写研究生成的创作者风格辅助 Skill。适用于中文场景下的选题、提纲、脚本、改写和风格批评任务，必须遵守免责声明与安全边界。"
---

# {display_name} 创作者 Skill

## 免责声明

{disclaimer}

## 工作模式

- 选题：输出包含角度、冲突、演示方式和匹配度的选题卡。
- 提纲：生成短视频结构，包括开头、主体、转折和结尾。
- 脚本：起草脚本，但不得声称这些话由创作者本人说过。
- 改写：把用户提供的材料改写得更接近研究到的表达方式，但不得冒充本人。
- 批评：根据研究笔记评分，并说明哪里匹配、哪里不匹配。

## 使用参考

- 先读 `references/persona_model.json`。按 `generation_protocol.field_order` 选择结构化字段，并记录使用了哪些 topic model、script template、judgment heuristic、expression DNA、anti-pattern 和 safety boundary。
- 再读 `references/research_summary.md`。
- 用 `references/topic_model.md` 判断选题。
- 用 `references/script_style.md` 判断结构、节奏和表达。
- 用 `references/evidence_index.md` 做证据锚定。
- 遵守 `references/persona.md` 中的安全边界。

## 生成协议

1. 识别任务类型：选题、提纲、脚本、改写、批评或越界请求。
2. 从 `persona_model.json` 选择对应字段，不要只凭泛泛风格描述生成。
3. 每个高置信判断至少绑定证据 ID；证据不足时降级为推断。
4. 输出前检查 `anti_patterns` 和 `safety_boundaries`，删除通用 AI 腔和身份越界表述。
5. 对风格批评类任务，指出 creator-specific markers、generic AI markers 和对应证据。

## 安全规则

- 不要声称自己是该创作者。
- 不要声称创作者认可、批准或说过生成内容。
- 不要克隆声音、脸、私人身份或私密信息。
- 证据以改写和摘要为主，只有确有必要时才使用很短的原文片段。
"""
    (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")
    return skill_dir


def has_long_transcript_dump(text: str) -> bool:
    timestamp_lines = len(re.findall(r"(?m)^\s*\[\d{2}:\d{2}:\d{2}\]", text))
    if timestamp_lines >= 5:
        return True
    long_quote_lines = len([line for line in text.splitlines() if len(line) > 500])
    return long_quote_lines > 0


def markdown_nonempty_bullets(text: str) -> int:
    return len(re.findall(r"(?m)^\s*[-*]\s+\S", text))


def markdown_heading_count(text: str) -> int:
    return len(re.findall(r"(?m)^#{2,4}\s+\S", text))


def markdown_table_rows(text: str) -> int:
    return len(re.findall(r"(?m)^\|[^|\n]+\|", text))


def has_mojibake(text: str) -> bool:
    if "�" in text or "????" in text:
        return True
    question_runs = re.findall(r"\?{3,}", text)
    return len(question_runs) >= 3


GENERIC_AI_PHRASES = [
    "引发共鸣",
    "层层递进",
    "通俗易懂",
    "深入浅出",
    "既专业又亲切",
    "用通俗语言解释复杂问题",
    "生动形象",
    "干货满满",
    "娓娓道来",
    "逻辑清晰",
    "观点鲜明",
    "贴近生活",
    "真实自然",
    "情绪价值",
    "爆款",
]


def generic_template_stats(text: str) -> dict:
    hits = []
    for phrase in GENERIC_AI_PHRASES:
        count = text.count(phrase)
        if count:
            hits.append({"phrase": phrase, "count": count})
    total_hits = sum(item["count"] for item in hits)
    return {
        "hit_count": total_hits,
        "unique_hit_count": len(hits),
        "hits": hits,
        "passed": total_hits <= 6 and len(hits) <= 4,
    }


def raw_research_note_stats(run_dir: Path) -> dict:
    raw_dir = run_dir / "research" / "raw"
    notes = sorted(raw_dir.glob("*.md")) if raw_dir.exists() else []
    substantial = [path for path in notes if path.stat().st_size >= 1200]
    return {
        "count": len(notes),
        "substantial_count": len(substantial),
        "files": [str(path.relative_to(run_dir)) for path in notes],
    }


def host_refinement_stats(run_dir: Path) -> dict:
    refinement_dir = run_dir / "research" / "host_refinement"
    reviews_dir = run_dir / "research" / "reviews"
    brief = refinement_dir / "brief.md"
    corpus_index = refinement_dir / "corpus_index.json"
    signal_matrix = refinement_dir / "transcript_signal_matrix.md"
    transcript_signals = refinement_dir / "transcript_signals.json"
    coverage_report = reviews_dir / "evidence_coverage.json"
    coverage_gaps_report = reviews_dir / "coverage_gaps.json"
    short_form_report = reviews_dir / "short_form_coverage.json"
    timeline_report = reviews_dir / "timeline_shift.json"
    entity_report = reviews_dir / "asr_entity_review.json"
    audit = reviews_dir / "refinement_audit.md"
    usage_probe = reviews_dir / "usage_probe.md"
    evaluation_suite = reviews_dir / "evaluation_suite.md"
    evaluation_suite_json = reviews_dir / "evaluation_suite.json"
    evaluation_suite_schema = reviews_dir / "evaluation_suite.schema.json"
    reverse_identification = reviews_dir / "reverse_identification.md"
    reverse_identification_json = reviews_dir / "reverse_identification.json"
    reverse_identification_schema = reviews_dir / "reverse_identification.schema.json"
    reviewer_findings = reviews_dir / "reviewer_findings.md"

    corpus_record_count = 0
    corpus_transcript_count = 0
    if corpus_index.exists():
        try:
            corpus = read_json(corpus_index)
            corpus_record_count = len(corpus.get("records") or [])
            corpus_transcript_count = int((corpus.get("coverage") or {}).get("transcript_count") or 0)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            corpus_record_count = 0
            corpus_transcript_count = 0

    transcript_signal_count = 0
    if transcript_signals.exists():
        try:
            signal_payload = read_json(transcript_signals)
            transcript_signal_count = int((signal_payload.get("summary") or {}).get("signal_count") or 0)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            transcript_signal_count = 0

    coverage_score = 0.0
    covered_video_count = 0
    coverage_gap_count = 0
    if coverage_report.exists():
        try:
            coverage_payload = read_json(coverage_report)
            coverage_score = float(coverage_payload.get("overall_score") or 0.0)
            covered_video_count = int(coverage_payload.get("covered_video_count") or 0)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            coverage_score = 0.0
            covered_video_count = 0
    if coverage_gaps_report.exists():
        try:
            coverage_gaps_payload = read_json(coverage_gaps_report)
            coverage_gap_count = int(coverage_gaps_payload.get("recommendation_count") or 0)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            coverage_gap_count = 0

    short_form_count = 0
    if short_form_report.exists():
        try:
            short_form_payload = read_json(short_form_report)
            short_form_count = int(short_form_payload.get("short_form_count") or 0)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            short_form_count = 0

    timeline_period_count = 0
    if timeline_report.exists():
        try:
            timeline_payload = read_json(timeline_report)
            timeline_period_count = len(timeline_payload.get("periods") or [])
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            timeline_period_count = 0

    entity_candidate_count = 0
    entity_review_required = False
    entity_report_valid = False
    if entity_report.exists():
        try:
            entity_payload = read_json(entity_report)
            entity_report_valid = True
            entity_review_required = bool(entity_payload.get("review_required"))
            entity_candidate_count = len(entity_payload.get("known_entities") or {}) + len(
                entity_payload.get("additional_ascii_candidates") or []
            )
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            entity_candidate_count = 0
            entity_review_required = False
            entity_report_valid = False

    signal_text = signal_matrix.read_text(encoding="utf-8", errors="replace") if signal_matrix.exists() else ""
    audit_text = audit.read_text(encoding="utf-8", errors="replace") if audit.exists() else ""
    usage_text = usage_probe.read_text(encoding="utf-8", errors="replace") if usage_probe.exists() else ""
    evaluation_text = evaluation_suite.read_text(encoding="utf-8", errors="replace") if evaluation_suite.exists() else ""
    reverse_text = (
        reverse_identification.read_text(encoding="utf-8", errors="replace")
        if reverse_identification.exists()
        else ""
    )
    reviewer_text = reviewer_findings.read_text(encoding="utf-8", errors="replace") if reviewer_findings.exists() else ""
    audit_recommends_ready = bool(
        re.search(r"是否建议\s*`?ready_for_use=true`?\s*[：:]\s*(是|yes|true)", audit_text, re.IGNORECASE)
    )
    audit_template_unfilled = "- [ ]" in audit_text or bool(
        re.search(r"审计人\s*[：:]\s*$|审计时间\s*[：:]\s*$|仍需补强\s*[：:]\s*$", audit_text, re.MULTILINE)
    )
    usage_probe_passed = bool(re.search(r"是否通过反向生成测试\s*[：:]\s*(是|yes|true)", usage_text, re.IGNORECASE))
    usage_probe_template_unfilled = bool(
        re.search(
            r"输入候选\s*[：:]\s*$|改写结果\s*[：:]\s*$|待批评片段\s*[：:]\s*$|选题\s*[：:]\s*$|使用的 persona_model 字段\s*[：:]\s*$",
            usage_text,
            re.MULTILINE,
        )
    )
    evaluation_suite_passed = bool(re.search(r"是否通过评测集\s*[：:]\s*(是|yes|true)", evaluation_text, re.IGNORECASE))
    evaluation_suite_template_unfilled = bool(
        re.search(r"输入候选\s*[：:]\s*$|输入选题\s*[：:]\s*$|原始文案\s*[：:]\s*$|待评估文本\s*[：:]\s*$", evaluation_text, re.MULTILINE)
    ) or bool(re.search(r"6 个 case 是否全部完成\s*[：:]\s*(否|no|false)", evaluation_text, re.IGNORECASE))
    reverse_identification_passed = bool(
        re.search(r"是否通过反向识别测试\s*[：:]\s*(是|yes|true)", reverse_text, re.IGNORECASE)
    )
    reverse_identification_template_unfilled = "|  |  |  |  |  |  |" in reverse_text or bool(
        re.search(r"至少识别 5 个 creator-specific marker\s*[：:]\s*(否|no|false)", reverse_text, re.IGNORECASE)
    )
    evaluation_suite_json_ready = False
    if evaluation_suite_json.exists():
        try:
            evaluation_payload = read_json(evaluation_suite_json)
            evaluation_cases = evaluation_payload.get("cases") or []
            evaluation_scorecard = evaluation_payload.get("scorecard") or {}
            evaluation_suite_json_ready = (
                evaluation_payload.get("status") != "draft_template"
                and len(evaluation_cases) >= 6
                and bool(evaluation_scorecard.get("passed"))
                and bool(evaluation_scorecard.get("all_cases_completed"))
                and bool(evaluation_scorecard.get("persona_model_fields_cited"))
                and bool(evaluation_scorecard.get("evidence_or_rule_cited"))
                and all(
                    isinstance(case, dict)
                    and case.get("passed") is True
                    and len(case.get("applied_persona_model_fields") or []) >= 2
                    and (case.get("evidence_video_ids") or case.get("safety_rule_ids"))
                    for case in evaluation_cases
                )
            )
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            evaluation_suite_json_ready = False
    reverse_identification_json_ready = False
    if reverse_identification_json.exists():
        try:
            reverse_payload = read_json(reverse_identification_json)
            reverse_rows = reverse_payload.get("rows") or []
            reverse_scorecard = reverse_payload.get("scorecard") or {}
            reverse_identification_json_ready = (
                reverse_payload.get("status") != "draft_template"
                and len(reverse_rows) >= 5
                and bool(reverse_scorecard.get("passed"))
                and int(reverse_scorecard.get("creator_specific_marker_count") or 0) >= 5
                and int(reverse_scorecard.get("generic_ai_marker_count") or 0) >= 3
                and bool(reverse_scorecard.get("fields_traceable"))
                and bool(reverse_scorecard.get("evidence_traceable"))
                and all(
                    isinstance(row, dict)
                    and row.get("creator_specific_markers")
                    and row.get("persona_model_fields")
                    and row.get("evidence_video_ids")
                    and row.get("verdict")
                    for row in reverse_rows
                )
            )
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            reverse_identification_json_ready = False
    reviewer_recommends_ready = bool(
        re.search(r"是否建议进入\s*`?ready_for_use=true`?\s*[：:]\s*(是|yes|true)", reviewer_text, re.IGNORECASE)
    )
    reviewer_template_unfilled = "|  |  |  |  |  |  |" in reviewer_text or bool(
        re.search(r"是否处理全部 high / medium 问题\s*[：:]\s*$", reviewer_text, re.MULTILINE)
    )

    checks = {
        "brief_present": brief.exists() and brief.stat().st_size >= 1000,
        "corpus_index_present": corpus_record_count > 0 and corpus_transcript_count > 0,
        "signal_matrix_present": signal_matrix.exists()
        and signal_matrix.stat().st_size >= 1000
        and "Per-Video Signals" in signal_text,
        "transcript_signals_present": transcript_signal_count > 0,
        "evidence_coverage_present": coverage_report.exists()
        and covered_video_count >= min(15, max(1, corpus_record_count))
        and coverage_score >= 0.45,
        "coverage_gaps_present": coverage_gaps_report.exists()
        and coverage_gaps_report.stat().st_size > 100
        and coverage_gap_count >= 0,
        "short_form_coverage_present": short_form_report.exists() and short_form_report.stat().st_size > 100,
        "timeline_shift_present": timeline_report.exists()
        and timeline_report.stat().st_size > 100
        and timeline_period_count >= min(2, max(1, corpus_record_count)),
        "asr_entity_review_present": entity_report.exists()
        and entity_report.stat().st_size > 100
        and entity_report_valid,
        "usage_probe_filled": usage_probe.exists()
        and usage_probe.stat().st_size >= 700
        and usage_probe_passed
        and not usage_probe_template_unfilled,
        "evaluation_suite_filled": evaluation_suite.exists()
        and evaluation_suite.stat().st_size >= 900
        and evaluation_suite_schema.exists()
        and evaluation_suite_json.exists()
        and evaluation_suite_passed
        and not evaluation_suite_template_unfilled,
        "evaluation_suite_json_filled": evaluation_suite_json_ready,
        "reverse_identification_filled": reverse_identification.exists()
        and reverse_identification.stat().st_size >= 700
        and reverse_identification_schema.exists()
        and reverse_identification_json.exists()
        and reverse_identification_passed
        and not reverse_identification_template_unfilled,
        "reverse_identification_json_filled": reverse_identification_json_ready,
        "reviewer_findings_filled": reviewer_findings.exists()
        and reviewer_findings.stat().st_size >= 500
        and reviewer_recommends_ready
        and not reviewer_template_unfilled,
        "refinement_audit_filled": audit.exists()
        and audit.stat().st_size >= 500
        and audit_recommends_ready
        and not audit_template_unfilled,
    }
    return {
        "checks": checks,
        "ready": all(checks.values()),
        "files": {
            "brief": str(brief.relative_to(run_dir)) if brief.exists() else "",
            "corpus_index": str(corpus_index.relative_to(run_dir)) if corpus_index.exists() else "",
            "signal_matrix": str(signal_matrix.relative_to(run_dir)) if signal_matrix.exists() else "",
            "transcript_signals": str(transcript_signals.relative_to(run_dir)) if transcript_signals.exists() else "",
            "evidence_coverage": str(coverage_report.relative_to(run_dir)) if coverage_report.exists() else "",
            "coverage_gaps": str(coverage_gaps_report.relative_to(run_dir)) if coverage_gaps_report.exists() else "",
            "short_form_coverage": str(short_form_report.relative_to(run_dir)) if short_form_report.exists() else "",
            "timeline_shift": str(timeline_report.relative_to(run_dir)) if timeline_report.exists() else "",
            "asr_entity_review": str(entity_report.relative_to(run_dir)) if entity_report.exists() else "",
            "audit": str(audit.relative_to(run_dir)) if audit.exists() else "",
            "usage_probe": str(usage_probe.relative_to(run_dir)) if usage_probe.exists() else "",
            "evaluation_suite": str(evaluation_suite.relative_to(run_dir)) if evaluation_suite.exists() else "",
            "evaluation_suite_json": str(evaluation_suite_json.relative_to(run_dir)) if evaluation_suite_json.exists() else "",
            "reverse_identification": str(reverse_identification.relative_to(run_dir)) if reverse_identification.exists() else "",
            "reverse_identification_json": str(reverse_identification_json.relative_to(run_dir)) if reverse_identification_json.exists() else "",
            "reviewer_findings": str(reviewer_findings.relative_to(run_dir)) if reviewer_findings.exists() else "",
        },
        "corpus_record_count": corpus_record_count,
        "corpus_transcript_count": corpus_transcript_count,
        "transcript_signal_count": transcript_signal_count,
        "covered_video_count": covered_video_count,
        "coverage_score": coverage_score,
        "coverage_gap_count": coverage_gap_count,
        "short_form_count": short_form_count,
        "timeline_period_count": timeline_period_count,
        "entity_candidate_count": entity_candidate_count,
        "entity_review_required": entity_review_required,
    }


def extract_video_ids_from_value(value: Any) -> set[str]:
    if isinstance(value, str):
        return set(re.findall(r"\b\d{16,20}\b", value))
    if isinstance(value, dict):
        ids: set[str] = set()
        for nested in value.values():
            ids.update(extract_video_ids_from_value(nested))
        return ids
    if isinstance(value, list):
        ids: set[str] = set()
        for nested in value:
            ids.update(extract_video_ids_from_value(nested))
        return ids
    return set()


def nonempty_items(value: Any) -> list[Any]:
    if not isinstance(value, list):
        return []
    return [item for item in value if item not in (None, "", [], {})]


def persona_model_stats(run_dir: Path, skill_dir: Path, markdown_texts: dict[str, str]) -> dict:
    refs = skill_dir / "references"
    schema_path = refs / "persona_model.schema.json"
    model_path = refs / "persona_model.json"
    diagnostics_path = run_dir / "research" / "reviews" / "persona_model_diagnostics.json"
    evidence_text = markdown_texts.get("evidence", "")
    topic_text = markdown_texts.get("topic", "")
    script_text = markdown_texts.get("script", "")
    persona_text = markdown_texts.get("persona", "")
    combined_md = "\n\n".join([persona_text, topic_text, script_text, evidence_text])

    model: dict[str, Any] = {}
    issues: list[dict[str, str]] = []
    if model_path.exists():
        try:
            loaded = read_json(model_path)
            if isinstance(loaded, dict):
                model = loaded
            else:
                issues.append({"severity": "high", "issue": "persona_model.json is not a JSON object"})
        except (OSError, json.JSONDecodeError) as exc:
            issues.append({"severity": "high", "issue": f"persona_model.json cannot be parsed: {exc}"})
    else:
        issues.append({"severity": "high", "issue": "persona_model.json missing"})

    required_fields = [
        "version",
        "core_identity",
        "topic_models",
        "script_templates",
        "judgment_heuristics",
        "expression_dna",
        "anti_patterns",
        "safety_boundaries",
        "evidence_anchors",
        "generation_protocol",
        "evaluation_cases",
    ]
    missing_fields = [field for field in required_fields if field not in model]
    if missing_fields:
        issues.append({"severity": "high", "issue": "missing required fields: " + ", ".join(missing_fields)})

    topic_models = nonempty_items(model.get("topic_models"))
    script_templates = nonempty_items(model.get("script_templates"))
    judgment_heuristics = nonempty_items(model.get("judgment_heuristics"))
    expression_dna = nonempty_items(model.get("expression_dna"))
    anti_patterns = nonempty_items(model.get("anti_patterns"))
    safety_boundaries = nonempty_items(model.get("safety_boundaries"))
    evidence_anchors = nonempty_items(model.get("evidence_anchors"))
    generation_protocol = model.get("generation_protocol") if isinstance(model.get("generation_protocol"), dict) else {}
    evaluation_cases = nonempty_items(model.get("evaluation_cases"))

    topic_model_ids = [extract_video_ids_from_value(item.get("evidence_ids", [])) for item in topic_models if isinstance(item, dict)]
    topic_models_complete = len(topic_models) >= 5 and all(
        isinstance(item, dict)
        and item.get("name")
        and item.get("definition")
        and len(nonempty_items(item.get("use_cases"))) >= 1
        and len(extract_video_ids_from_value(item.get("evidence_ids", []))) >= 2
        and len(nonempty_items(item.get("failure_modes"))) >= 1
        for item in topic_models
    )
    script_templates_complete = len(script_templates) >= 4 and all(
        isinstance(item, dict)
        and item.get("name")
        and len(nonempty_items(item.get("use_cases"))) >= 1
        and item.get("hook")
        and item.get("body")
        and item.get("ending")
        and len(nonempty_items(item.get("failure_modes"))) >= 1
        and len(extract_video_ids_from_value(item.get("evidence_ids", []))) >= 1
        for item in script_templates
    )
    model_ids = extract_video_ids_from_value(model)
    evidence_ids = extract_video_ids_from_value(evidence_text)
    missing_from_evidence_index = sorted(video_id for video_id in model_ids if video_id not in evidence_ids)
    topic_names = [str(item.get("name", "")) for item in topic_models if isinstance(item, dict)]
    topic_name_hits = sum(1 for name in topic_names if name and name in topic_text)
    script_names = [str(item.get("name", "")) for item in script_templates if isinstance(item, dict)]
    script_name_hits = sum(1 for name in script_names if name and name in script_text)
    safety_text = "\n".join(str(item) for item in safety_boundaries)
    safety_complete = all(term in safety_text for term in ["冒充", "本人"]) and bool(re.search(r"声音|形象|克隆", safety_text))
    generation_protocol_complete = (
        len(nonempty_items(generation_protocol.get("field_order"))) >= 5
        and len(nonempty_items(generation_protocol.get("task_routing"))) >= 4
        and bool(generation_protocol.get("evidence_policy"))
        and bool(generation_protocol.get("confidence_policy"))
    )
    evaluation_cases_complete = len(evaluation_cases) >= 6 and all(
        isinstance(item, dict)
        and item.get("name")
        and item.get("task")
        and len(nonempty_items(item.get("expected_fields"))) >= 2
        and len(nonempty_items(item.get("pass_criteria"))) >= 2
        for item in evaluation_cases
    )

    checks = {
        "schema_file_present": schema_path.exists() and schema_path.stat().st_size > 100,
        "model_file_present": model_path.exists() and model_path.stat().st_size > 100,
        "not_template": model.get("status") != "draft_template",
        "required_top_fields": not missing_fields,
        "core_identity_present": isinstance(model.get("core_identity"), str) and len(model.get("core_identity", "")) >= 40,
        "topic_models_complete": topic_models_complete,
        "script_templates_complete": script_templates_complete,
        "judgment_heuristics_min": len(judgment_heuristics) >= 6,
        "expression_dna_min": len(expression_dna) >= 6,
        "anti_patterns_min": len(anti_patterns) >= 5,
        "safety_boundaries_complete": safety_complete,
        "evidence_anchors_min": len(evidence_anchors) >= 15 and len(model_ids) >= 15,
        "generation_protocol_complete": generation_protocol_complete,
        "evaluation_cases_complete": evaluation_cases_complete,
        "evidence_ids_in_evidence_index": not missing_from_evidence_index,
        "markdown_alignment": topic_name_hits >= min(5, len(topic_names)) and script_name_hits >= min(3, len(script_names)),
        "no_mojibake": not has_mojibake(json.dumps(model, ensure_ascii=False)) and not has_mojibake(combined_md),
    }
    if not checks["not_template"]:
        issues.append({"severity": "high", "issue": "persona_model.json is still the draft template"})
    if missing_from_evidence_index:
        issues.append(
            {
                "severity": "high",
                "issue": "persona_model evidence IDs missing from evidence_index.md: "
                + ", ".join(missing_from_evidence_index[:20]),
            }
        )
    if not checks["markdown_alignment"]:
        issues.append({"severity": "medium", "issue": "persona_model names do not align with Markdown topic/script files"})

    diagnostics = {
        "ready": all(checks.values()),
        "checks": checks,
        "counts": {
            "topic_models": len(topic_models),
            "script_templates": len(script_templates),
            "judgment_heuristics": len(judgment_heuristics),
            "expression_dna": len(expression_dna),
            "anti_patterns": len(anti_patterns),
            "safety_boundaries": len(safety_boundaries),
            "evidence_anchors": len(evidence_anchors),
            "task_routing": len(nonempty_items(generation_protocol.get("task_routing"))),
            "evaluation_cases": len(evaluation_cases),
            "referenced_video_ids": len(model_ids),
            "topic_name_hits": topic_name_hits,
            "script_name_hits": script_name_hits,
        },
        "issues": issues,
        "files": {
            "schema": str(schema_path.relative_to(run_dir)) if schema_path.exists() else "",
            "model": str(model_path.relative_to(run_dir)) if model_path.exists() else "",
            "diagnostics": str(diagnostics_path.relative_to(run_dir)),
        },
    }
    diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(diagnostics_path, diagnostics)
    return diagnostics


def creator_content_readiness(skill_dir: Path, run_dir: Path | None = None) -> dict:
    persona = skill_dir / "references" / "persona.md"
    topic = skill_dir / "references" / "topic_model.md"
    script = skill_dir / "references" / "script_style.md"
    evidence = skill_dir / "references" / "evidence_index.md"

    persona_text = persona.read_text(encoding="utf-8", errors="replace") if persona.exists() else ""
    topic_text = topic.read_text(encoding="utf-8", errors="replace") if topic.exists() else ""
    script_text = script.read_text(encoding="utf-8", errors="replace") if script.exists() else ""
    evidence_text = evidence.read_text(encoding="utf-8", errors="replace") if evidence.exists() else ""
    combined = "\n\n".join([persona_text, topic_text, script_text, evidence_text])
    generic_stats = generic_template_stats(combined)
    raw_stats = raw_research_note_stats(run_dir) if run_dir else {"count": 0, "substantial_count": 0, "files": []}
    refinement_stats = host_refinement_stats(run_dir) if run_dir else {"checks": {}, "ready": False}
    persona_stats = (
        persona_model_stats(
            run_dir,
            skill_dir,
            {"persona": persona_text, "topic": topic_text, "script": script_text, "evidence": evidence_text},
        )
        if run_dir
        else {"ready": False, "checks": {}}
    )

    checks = {
        "host_refinement_package_ready": refinement_stats["ready"],
        "persona_model_ready": persona_stats["ready"],
        "raw_research_notes_present": raw_stats["substantial_count"] >= 5,
        "persona_min_density": len(persona_text) >= 3500
        and markdown_heading_count(persona_text) >= 8
        and bool(re.search(r"表达\s*DNA|Agent\s*使用协议|反模式|安全边界", persona_text, re.IGNORECASE)),
        "topic_models_present": len(re.findall(r"(?m)^#{2,4}\s*.*模型|模型[一二三四五六七八九十\d]", topic_text)) >= 5
        and bool(re.search(r"证据|锚点", topic_text))
        and bool(re.search(r"失败模式|不适合|低匹配", topic_text)),
        "script_templates_present": (
            len(re.findall(r"(?m)^#{2,4}\s+", script_text)) >= 8
            or len(re.findall(r"(?m)^#{2,4}\s*.*(?:模板|Hook)|模板[:：]", script_text)) >= 4
        )
        and len(set(re.findall(r"实验|教程|现场|产业|灰区|风险|工具|产品", script_text))) >= 4,
        "evidence_entries_present": markdown_table_rows(evidence_text) >= 15
        or markdown_nonempty_bullets(evidence_text) >= 15,
        "anti_template_pass": generic_stats["passed"],
        "no_mojibake": not has_mojibake(combined),
    }
    return {
        "ready_for_use": all(checks.values()),
        "checks": checks,
        "raw_research_notes": raw_stats,
        "host_refinement": refinement_stats,
        "persona_model": persona_stats,
        "generic_template_phrases": generic_stats,
        "note": (
            "ready_for_use=false means the deterministic pipeline produced a recoverable draft "
            "or the host-agent refinement is still too thin. Generate research/host_refinement/brief.md, "
            "corpus_index.json, transcript_signal_matrix.md, and transcript_signals.json; write at least five "
            "substantial research/raw notes; fill persona_model.json, evidence_coverage, usage_probe, "
            "evaluation_suite.md/json, reverse_identification.md/json, reviewer_findings, and refinement_audit; then rewrite the Creator Skill."
        ),
    }


def creator_quality_check(run_dir: Path) -> dict:
    skill_dir = run_dir / "skill"
    required_files = [
        skill_dir / "SKILL.md",
        skill_dir / "references" / "persona.md",
        skill_dir / "references" / "topic_model.md",
        skill_dir / "references" / "script_style.md",
        skill_dir / "references" / "research_summary.md",
        skill_dir / "references" / "evidence_index.md",
        skill_dir / "references" / "meta.json",
    ]
    missing_files = [str(path.relative_to(run_dir)) for path in required_files if not path.exists()]
    text_blobs = []
    for path in required_files:
        if path.exists() and path.suffix.lower() in {".md", ".txt"}:
            text_blobs.append(path.read_text(encoding="utf-8", errors="replace"))
    combined = "\n\n".join(text_blobs)
    transcript_files = list((run_dir / "transcripts").glob("*.txt"))
    config_snapshot = run_dir / "config.snapshot.json"
    selected_metadata = run_dir / "metadata" / "selected.json"
    selected_compact = run_dir / "metadata" / "selected.compact.json"
    creator_profile = run_dir / "metadata" / "creator_profile.json"
    research_summary = run_dir / "research" / "merged" / "summary.md"
    readiness = creator_content_readiness(skill_dir, run_dir)

    checks = {
        "required_files": not missing_files,
        "has_disclaimer": bool(re.search(r"disclaimer|does not represent|不代表|免责声明", combined, re.IGNORECASE)),
        "has_safety_boundary": bool(re.search(r"safety|identity deception|冒充|clone|克隆|边界", combined, re.IGNORECASE)),
        "has_evidence_index": (skill_dir / "references" / "evidence_index.md").exists()
        and (skill_dir / "references" / "evidence_index.md").stat().st_size > 20,
        "no_transcript_dump": not has_long_transcript_dump(combined),
        "has_transcripts": bool(transcript_files),
        "has_config_snapshot": config_snapshot.exists(),
        "has_selected_metadata": selected_metadata.exists(),
        "has_selected_compact_metadata": selected_compact.exists(),
        "has_creator_profile": creator_profile.exists(),
        "has_research_summary": research_summary.exists() and research_summary.stat().st_size > 20,
        "no_mojibake": not has_mojibake(combined),
    }
    report = {
        "passed": all(checks.values()),
        "checks": checks,
        "content_readiness": readiness,
        "ready_for_use": readiness["ready_for_use"],
        "missing_files": missing_files,
        "transcript_count": len(transcript_files),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json(run_dir / "logs" / "creator_quality_report.json", report)
    return report


def write_run_summary(run_dir: Path, quality_report: dict | None = None) -> Path:
    def count_glob(relative: str, pattern: str) -> int:
        root = run_dir / relative
        return len(list(root.glob(pattern))) if root.exists() else 0

    summary = {
        "run_dir": str(run_dir),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "artifacts": {
            "raw_metadata": (run_dir / "metadata" / "raw.json").exists(),
            "selected_metadata": (run_dir / "metadata" / "selected.json").exists(),
            "selected_compact_metadata": (run_dir / "metadata" / "selected.compact.json").exists(),
            "creator_profile": (run_dir / "metadata" / "creator_profile.json").exists(),
            "videos": count_glob("media/videos", "*.mp4"),
            "audio": count_glob("media/audio", "*.*"),
            "transcripts": count_glob("transcripts", "*.txt"),
            "asr_raw_json": count_glob("transcripts/raw_json", "*.json"),
            "research_summary": (run_dir / "research" / "merged" / "summary.md").exists(),
            "style_research_json": (run_dir / "research" / "merged" / "style_research.json").exists(),
            "skill": (run_dir / "skill" / "SKILL.md").exists(),
        },
        "quality": quality_report or {},
    }
    output_path = run_dir / "run_summary.json"
    write_json(output_path, summary)
    return output_path


def command_normalize_metadata(args: argparse.Namespace) -> None:
    print(normalize_metadata(Path(args.input), Path(args.output)))


def command_select_samples(args: argparse.Namespace) -> None:
    print(select_samples(Path(args.input), Path(args.output), args.sample_count))


def command_download_videos(args: argparse.Namespace) -> None:
    print(download_videos(Path(args.input), Path(args.output_dir), Path(args.logs_dir)))


def command_extract_audio(args: argparse.Namespace) -> None:
    print(extract_audio(Path(args.video_dir), Path(args.audio_dir)))


def command_asr_json_to_transcript(args: argparse.Namespace) -> None:
    print(asr_json_to_transcript(Path(args.input), Path(args.output)))


def command_summarize_transcripts(args: argparse.Namespace) -> None:
    print(summarize_transcripts(Path(args.transcripts_dir), Path(args.output_dir)))


def command_build_skill(args: argparse.Namespace) -> None:
    print(build_creator_skill(Path(args.run_dir), args.project_name))


def command_quality_check(args: argparse.Namespace) -> None:
    report = creator_quality_check(Path(args.run_dir))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    for name, passed in report["checks"].items():
        print(f"{'PASS' if passed else 'FAIL'}  {name}")
    for name, passed in report.get("content_readiness", {}).get("checks", {}).items():
        print(f"{'PASS' if passed else 'WARN'}  readiness.{name}")
    print(f"READY_FOR_USE {'YES' if report.get('ready_for_use') else 'NO'}")
    print(f"OVERALL {'PASS' if report['passed'] else 'FAIL'}")


def command_run_summary(args: argparse.Namespace) -> None:
    report_path = Path(args.run_dir) / "logs" / "creator_quality_report.json"
    report = read_json(report_path) if report_path.exists() else None
    print(write_run_summary(Path(args.run_dir), report))


def main() -> None:
    parser = argparse.ArgumentParser(description="Creator Skill deterministic pipeline utilities")
    parser.add_argument("--env", help="Path to .env file")
    subparsers = parser.add_subparsers(dest="command", required=True)

    normalize = subparsers.add_parser("normalize-metadata")
    normalize.add_argument("--input", required=True)
    normalize.add_argument("--output", required=True)
    normalize.set_defaults(func=command_normalize_metadata)

    select = subparsers.add_parser("select-samples")
    select.add_argument("--input", required=True)
    select.add_argument("--output", required=True)
    select.add_argument("--sample-count", type=int, required=True)
    select.set_defaults(func=command_select_samples)

    download = subparsers.add_parser("download-videos")
    download.add_argument("--input", required=True)
    download.add_argument("--output-dir", required=True)
    download.add_argument("--logs-dir", required=True)
    download.set_defaults(func=command_download_videos)

    audio = subparsers.add_parser("extract-audio")
    audio.add_argument("--video-dir", required=True)
    audio.add_argument("--audio-dir", required=True)
    audio.set_defaults(func=command_extract_audio)

    transcript = subparsers.add_parser("asr-json-to-transcript")
    transcript.add_argument("--input", required=True)
    transcript.add_argument("--output", required=True)
    transcript.set_defaults(func=command_asr_json_to_transcript)

    summary = subparsers.add_parser("summarize-transcripts")
    summary.add_argument("--transcripts-dir", required=True)
    summary.add_argument("--output-dir", required=True)
    summary.set_defaults(func=command_summarize_transcripts)

    skill = subparsers.add_parser("build-skill")
    skill.add_argument("--run-dir", required=True)
    skill.add_argument("--project-name", required=True)
    skill.set_defaults(func=command_build_skill)

    quality = subparsers.add_parser("quality-check")
    quality.add_argument("--run-dir", required=True)
    quality.add_argument("--json", action="store_true")
    quality.set_defaults(func=command_quality_check)

    run_summary = subparsers.add_parser("run-summary")
    run_summary.add_argument("--run-dir", required=True)
    run_summary.set_defaults(func=command_run_summary)

    args = parser.parse_args()
    load_env_file(Path(args.env).expanduser() if args.env else None)
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(1)
