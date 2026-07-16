"""Deterministic, per-video coverage reporting for creator pipeline runs."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from input_validation import validate_stage_threshold_config
import path_policy


STAGE_COVERAGE_SCHEMA_VERSION = 1
STAGES = ("selected", "downloaded", "audio", "transcribed")
MODES = {"online_media", "offline_transcripts"}


def _read_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _status_rows(path: Path, *keys: str) -> dict[str, dict[str, Any]]:
    payload = _read_object(path)
    rows = payload.get("results", [])
    indexed: dict[str, dict[str, Any]] = {}
    if not isinstance(rows, list):
        return indexed
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in keys:
            value = row.get(key)
            if not isinstance(value, str) or not value:
                continue
            identifier = Path(value).stem if key in {"audio", "transcript", "path"} else value
            indexed.setdefault(identifier, row)
    return indexed


def _state(status: str, reason: str, source: str) -> dict[str, Any]:
    return {
        "status": status,
        "covered": status == "covered",
        "reason": reason[:500],
        "source": source,
    }


def _row_reason(row: Mapping[str, Any], fallback: str) -> str:
    for key in ("error", "reason", "message"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:500]
    status = str(row.get("status") or "").strip()
    return f"{fallback}; recorded status={status or 'missing'}"


def _required_count(expected: int, min_count: int, min_ratio: float) -> int:
    if expected <= 0:
        return 0
    return min(expected, max(min_count, math.ceil(expected * min_ratio)))


def _add_issue(
    issues: list[dict[str, Any]],
    *,
    video_id: str | None,
    stage: str,
    status: str,
    code: str,
    reason: str,
) -> None:
    issues.append(
        {
            "video_id": video_id,
            "stage": stage,
            "status": status,
            "code": code,
            "reason": reason[:500],
        }
    )


def evaluate_stage_coverage(run_dir: Path) -> dict[str, Any]:
    """Return stage counts, thresholds, and traceable per-video outcomes."""

    input_payload = _read_object(run_dir / "input.json")
    configured_mode = str(input_payload.get("execution_mode") or "online_media")
    mode = configured_mode if configured_mode in MODES else "online_media"
    thresholds = validate_stage_threshold_config(_read_object(run_dir / "config.snapshot.json"))
    selected_payload = _read_object(run_dir / "metadata" / "selected.json")
    raw_items = selected_payload.get("items", [])
    items = [item for item in raw_items if isinstance(item, dict)] if isinstance(raw_items, list) else []
    try:
        declared_count = max(0, int(selected_payload.get("selected_count") or 0))
    except (TypeError, ValueError):
        declared_count = 0
    expected_count = max(declared_count, len(items))

    download_rows = _status_rows(
        run_dir / "logs" / "download_status.json",
        "artifact_id",
        "video_id",
        "platform_video_id",
    )
    audio_rows = _status_rows(run_dir / "logs" / "audio_status.json", "artifact_id", "video_id")
    asr_rows = _status_rows(
        run_dir / "logs" / "asr_status.json",
        "video_id",
        "artifact_id",
        "audio",
        "transcript",
    )
    video_files = {path.stem for path in path_policy.artifact_files(run_dir / "media" / "videos", ".mp4")}
    audio_files = set()
    audio_dir = run_dir / "media" / "audio"
    for candidate in sorted(audio_dir.iterdir() if audio_dir.exists() else []):
        if candidate.name.endswith(".manifest.json"):
            continue
        artifact_id = path_policy.validate_artifact_id(candidate.stem)
        contained = path_policy.resolve_within(audio_dir, candidate.name)
        if contained.is_file():
            audio_files.add(artifact_id)
    transcript_files = {
        path.stem
        for path in path_policy.artifact_files(run_dir / "transcripts", ".txt")
        if path.stat().st_size > 0
    }

    issues: list[dict[str, Any]] = []
    videos: list[dict[str, Any]] = []
    for index in range(expected_count):
        item = items[index] if index < len(items) else None
        raw_video_id = str((item or {}).get("platform_video_id") or "").strip()
        tracking_id = raw_video_id or f"missing-selected-item-{index + 1:03d}"
        video_id_error = ""
        try:
            artifact_id = path_policy.artifact_id_for_item(
                item or {},
                fallback=f"video-{index + 1}",
            )
        except path_policy.VideoIdError as error:
            artifact_id = f"invalid-video-{index + 1}"
            video_id_error = str(error)
        stages: dict[str, dict[str, Any]] = {}
        if item is None:
            selected_reason = "selected_count exceeds the number of selected item records"
            stages["selected"] = _state("failed", selected_reason, "metadata/selected.json")
            _add_issue(
                issues,
                video_id=tracking_id,
                stage="selected",
                status="failed",
                code="SELECTED_ITEM_MISSING",
                reason=selected_reason,
            )
        elif video_id_error:
            stages["selected"] = _state("failed", video_id_error, "metadata/selected.json")
            _add_issue(
                issues,
                video_id=tracking_id,
                stage="selected",
                status="failed",
                code="VIDEO_ID_INVALID",
                reason=video_id_error,
            )
        else:
            stages["selected"] = _state(
                "covered",
                "video is present in the selected metadata set",
                "metadata/selected.json",
            )

        if mode == "offline_transcripts":
            stages["downloaded"] = _state(
                "not_required",
                "download coverage is exempt for --transcripts-dir runs",
                "input.json",
            )
            stages["audio"] = _state(
                "not_required",
                "audio coverage is exempt for --transcripts-dir runs",
                "input.json",
            )
        else:
            download_row = download_rows.get(raw_video_id) or download_rows.get(artifact_id)
            download_status = str((download_row or {}).get("status") or "").lower()
            download_url = (item or {}).get("download_url")
            if not isinstance(download_url, str) or not download_url.strip():
                reason = "selected metadata is missing download_url"
                stages["downloaded"] = _state("failed", reason, "metadata/selected.json")
                _add_issue(
                    issues,
                    video_id=tracking_id,
                    stage="downloaded",
                    status="failed",
                    code="DOWNLOAD_URL_MISSING",
                    reason=reason,
                )
            elif download_status == "failed":
                reason = _row_reason(download_row or {}, "download failed")
                stages["downloaded"] = _state("failed", reason, "logs/download_status.json")
                _add_issue(
                    issues,
                    video_id=tracking_id,
                    stage="downloaded",
                    status="failed",
                    code="DOWNLOAD_FAILED",
                    reason=reason,
                )
            elif artifact_id in video_files:
                stages["downloaded"] = _state(
                    "covered",
                    "downloaded video artifact is present",
                    "media/videos",
                )
            else:
                reason = _row_reason(download_row or {}, "download did not produce a video artifact")
                code = "DOWNLOAD_SKIPPED" if download_status == "skipped" else "DOWNLOAD_FAILED"
                if not download_row:
                    code = "DOWNLOAD_NOT_RECORDED"
                elif download_status in {"downloaded", "succeeded", "completed"}:
                    code = "DOWNLOAD_ARTIFACT_MISSING"
                stages["downloaded"] = _state("failed", reason, "logs/download_status.json")
                _add_issue(
                    issues,
                    video_id=tracking_id,
                    stage="downloaded",
                    status="failed",
                    code=code,
                    reason=reason,
                )

            audio_row = audio_rows.get(raw_video_id) or audio_rows.get(artifact_id)
            audio_status = str((audio_row or {}).get("status") or "").lower()
            if audio_status == "failed":
                reason = _row_reason(audio_row or {}, "audio extraction failed")
                stages["audio"] = _state("failed", reason, "logs/audio_status.json")
                _add_issue(
                    issues,
                    video_id=tracking_id,
                    stage="audio",
                    status="failed",
                    code="AUDIO_FAILED",
                    reason=reason,
                )
            elif artifact_id in audio_files:
                stages["audio"] = _state(
                    "covered",
                    "audio artifact is present",
                    "media/audio",
                )
            elif stages["downloaded"]["status"] != "covered" and not audio_row:
                reason = "audio extraction was blocked because download coverage is missing"
                stages["audio"] = _state("blocked", reason, "stage dependency")
                _add_issue(
                    issues,
                    video_id=tracking_id,
                    stage="audio",
                    status="blocked",
                    code="AUDIO_BLOCKED",
                    reason=reason,
                )
            else:
                reason = _row_reason(audio_row or {}, "audio extraction did not produce an artifact")
                code = "AUDIO_SKIPPED" if audio_status == "skipped" else "AUDIO_FAILED"
                if not audio_row:
                    code = "AUDIO_NOT_PRODUCED"
                elif audio_status in {"extracted", "succeeded", "completed"}:
                    code = "AUDIO_ARTIFACT_MISSING"
                stages["audio"] = _state("failed", reason, "logs/audio_status.json")
                _add_issue(
                    issues,
                    video_id=tracking_id,
                    stage="audio",
                    status="failed",
                    code=code,
                    reason=reason,
                )

        asr_row = asr_rows.get(raw_video_id) or asr_rows.get(artifact_id)
        asr_status = str((asr_row or {}).get("status") or "").lower()
        if artifact_id in transcript_files:
            stages["transcribed"] = _state(
                "covered",
                "non-empty transcript artifact is present",
                "transcripts/*.txt",
            )
        elif asr_status == "skipped":
            reason = _row_reason(asr_row or {}, "ASR skipped this video without a transcript")
            stages["transcribed"] = _state("failed", reason, "logs/asr_status.json")
            _add_issue(
                issues,
                video_id=tracking_id,
                stage="transcribed",
                status="failed",
                code="ASR_SKIPPED",
                reason=reason,
            )
        elif asr_row and asr_status not in {"transcribed", "succeeded", "completed"}:
            reason = _row_reason(asr_row, "ASR failed without a transcript")
            stages["transcribed"] = _state("failed", reason, "logs/asr_status.json")
            _add_issue(
                issues,
                video_id=tracking_id,
                stage="transcribed",
                status="failed",
                code="ASR_FAILED",
                reason=reason,
            )
        elif mode == "online_media" and stages["audio"]["status"] != "covered":
            reason = "transcription was blocked because audio coverage is missing"
            stages["transcribed"] = _state("blocked", reason, "stage dependency")
            _add_issue(
                issues,
                video_id=tracking_id,
                stage="transcribed",
                status="blocked",
                code="TRANSCRIPTION_BLOCKED",
                reason=reason,
            )
        else:
            reason = "selected video has no non-empty transcript artifact"
            stages["transcribed"] = _state("failed", reason, "transcripts/*.txt")
            _add_issue(
                issues,
                video_id=tracking_id,
                stage="transcribed",
                status="failed",
                code="TRANSCRIPT_MISSING",
                reason=reason,
            )

        videos.append(
            {
                "selection_index": index + 1,
                "video_id": tracking_id,
                "artifact_id": artifact_id,
                "stages": stages,
            }
        )

    if expected_count == 0:
        _add_issue(
            issues,
            video_id=None,
            stage="selected",
            status="failed",
            code="NO_SELECTED_VIDEOS",
            reason="selected metadata contains no videos",
        )

    required_stages = (
        ("selected", "transcribed")
        if mode == "offline_transcripts"
        else STAGES
    )
    stage_reports: dict[str, dict[str, Any]] = {}
    for stage in STAGES:
        required = stage in required_stages
        count = sum(video["stages"][stage]["covered"] for video in videos)
        ratio = round(count / expected_count, 6) if expected_count else 0.0
        draft_required = _required_count(
            expected_count,
            int(thresholds["draft"]["min_count"]),
            float(thresholds["draft"]["min_ratio"]),
        ) if required else 0
        ready_required = _required_count(
            expected_count,
            int(thresholds["ready"]["min_count"]),
            float(thresholds["ready"]["min_ratio"]),
        ) if required else 0
        stage_reports[stage] = {
            "required": required,
            "count": count,
            "expected_count": expected_count,
            "ratio": ratio,
            "draft_required_count": draft_required,
            "ready_required_count": ready_required,
            "draft_passed": (not required) or (expected_count > 0 and count >= draft_required),
            "ready_passed": (not required) or (expected_count > 0 and count >= ready_required),
        }

    gates: dict[str, dict[str, Any]] = {}
    for level in ("draft", "ready"):
        failed_stages = [
            stage for stage in required_stages if not stage_reports[stage][f"{level}_passed"]
        ]
        gates[level] = {
            "passed": not failed_stages,
            "required_stages": list(required_stages),
            "failed_stages": failed_stages,
        }

    return {
        "schema_version": STAGE_COVERAGE_SCHEMA_VERSION,
        "mode": mode,
        "selected_count": expected_count,
        "thresholds": thresholds,
        "stages": stage_reports,
        "draft": gates["draft"],
        "ready": gates["ready"],
        "issues": issues,
        "videos": videos,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
