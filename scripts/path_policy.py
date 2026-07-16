#!/usr/bin/env python3
"""Cross-platform video identity and filesystem containment policy."""

from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping, Sequence


VIDEO_ID_MAP_SCHEMA_VERSION = 1
MAX_PLATFORM_VIDEO_ID_LENGTH = 512
MAX_ARTIFACT_ID_LENGTH = 120
COLLISION_HASH_LENGTH = 10
_ARTIFACT_ID = re.compile(r"[a-z0-9](?:[a-z0-9_-]{0,119})\Z")
_WINDOWS_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


class VideoIdError(ValueError):
    """A platform or artifact identifier is unsafe or internally inconsistent."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.safe_message = message
        super().__init__(f"[{code}] {message}")


class PathContainmentError(ValueError):
    """A requested relative path would not remain below its declared root."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.safe_message = message
        super().__init__(f"[{code}] {message}")


def _raw_text(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise VideoIdError("VIDEO_ID_TYPE", "platform video ID must be a string or integer")
    text = str(value)
    if not text:
        raise VideoIdError("VIDEO_ID_EMPTY", "platform video ID must not be empty")
    if len(text) > MAX_PLATFORM_VIDEO_ID_LENGTH:
        raise VideoIdError("VIDEO_ID_TOO_LONG", "platform video ID exceeds the configured length limit")
    return text


def _windows_reserved(value: str) -> bool:
    stem = value.rstrip(". ").split(".", 1)[0].casefold()
    return stem in _WINDOWS_RESERVED


def validate_platform_video_id(value: object) -> str:
    """Return the original ID after cross-platform path/device validation."""

    raw = _raw_text(value)
    normalized = unicodedata.normalize("NFKC", raw)
    if raw != raw.strip() or normalized != normalized.strip():
        raise VideoIdError("VIDEO_ID_WHITESPACE", "platform video ID has leading or trailing whitespace")
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise VideoIdError("VIDEO_ID_CONTROL", "platform video ID contains a control character")
    if "/" in normalized or "\\" in normalized:
        raise VideoIdError("VIDEO_ID_SEPARATOR", "platform video ID contains a path separator")
    if ".." in normalized or normalized in {".", ".."}:
        raise VideoIdError("VIDEO_ID_TRAVERSAL", "platform video ID contains a traversal token")
    windows_path = PureWindowsPath(normalized)
    posix_path = PurePosixPath(normalized)
    if windows_path.drive or windows_path.root or posix_path.is_absolute() or ":" in normalized:
        raise VideoIdError("VIDEO_ID_ABSOLUTE", "platform video ID contains an absolute or device path")
    if normalized.endswith((".", " ")):
        raise VideoIdError("VIDEO_ID_TRAILING", "platform video ID has a trailing dot or space")
    if _windows_reserved(normalized):
        raise VideoIdError("VIDEO_ID_RESERVED", "platform video ID is a Windows reserved device name")
    return raw


def _digest(raw_id: str, length: int = COLLISION_HASH_LENGTH) -> str:
    return hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:length]


def _base_artifact_id(raw_id: str) -> str:
    normalized = unicodedata.normalize("NFKC", raw_id).casefold()
    base = re.sub(r"[^a-z0-9_-]+", "-", normalized)
    base = re.sub(r"-+", "-", base).strip("-_")
    if not base:
        return f"video--{_digest(raw_id)}"
    if _windows_reserved(base):
        base = f"video-{base}"
    return base[:MAX_ARTIFACT_ID_LENGTH].rstrip("-_")


def _collision_artifact_id(raw_id: str, base: str, length: int = COLLISION_HASH_LENGTH) -> str:
    suffix = f"--{_digest(raw_id, length)}"
    prefix = base[: MAX_ARTIFACT_ID_LENGTH - len(suffix)].rstrip("-_") or "video"
    return f"{prefix}{suffix}"


def validate_artifact_id(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise VideoIdError("ARTIFACT_ID_INVALID", "artifact ID must be a non-empty normalized string")
    if len(value) > MAX_ARTIFACT_ID_LENGTH or not _ARTIFACT_ID.fullmatch(value):
        raise VideoIdError(
            "ARTIFACT_ID_INVALID",
            "artifact ID must contain only lowercase ASCII letters, digits, underscore, and hyphen",
        )
    if _windows_reserved(value):
        raise VideoIdError("ARTIFACT_ID_RESERVED", "artifact ID is a Windows reserved device name")
    return value


def _artifact_id_matches_raw(raw_id: str, artifact_id: str) -> bool:
    base = _base_artifact_id(raw_id)
    if artifact_id == base:
        return True
    for length in range(COLLISION_HASH_LENGTH, 65, 2):
        if artifact_id == _collision_artifact_id(raw_id, base, length):
            return True
    return False


class ArtifactIdRegistry:
    """Assign stable local IDs while preserving repeated raw-ID identity."""

    def __init__(self) -> None:
        self._by_raw: dict[str, str] = {}
        self._by_artifact: dict[str, str] = {}

    def assign(self, value: object, *, preferred: object | None = None) -> str:
        raw_id = validate_platform_video_id(value)
        existing = self._by_raw.get(raw_id)
        if existing is not None:
            if preferred is not None and validate_artifact_id(preferred) != existing:
                raise VideoIdError(
                    "ARTIFACT_ID_MAPPING_CONFLICT",
                    "one platform video ID maps to multiple artifact IDs",
                )
            return existing

        if preferred is not None:
            candidate = validate_artifact_id(preferred)
            if not _artifact_id_matches_raw(raw_id, candidate):
                raise VideoIdError(
                    "ARTIFACT_ID_MAPPING_INVALID",
                    "preassigned artifact ID does not match its platform video ID",
                )
            owner = self._by_artifact.get(candidate)
            if owner is not None and owner != raw_id:
                raise VideoIdError(
                    "ARTIFACT_ID_COLLISION",
                    "multiple platform video IDs claim the same artifact ID",
                )
        else:
            base = _base_artifact_id(raw_id)
            candidate = base
            owner = self._by_artifact.get(candidate)
            if owner is not None and owner != raw_id:
                for length in range(COLLISION_HASH_LENGTH, 65, 2):
                    candidate = _collision_artifact_id(raw_id, base, length)
                    owner = self._by_artifact.get(candidate)
                    if owner is None or owner == raw_id:
                        break
                else:  # pragma: no cover - a SHA-256 prefix collision across every length is infeasible
                    raise VideoIdError("ARTIFACT_ID_COLLISION", "artifact ID collision could not be resolved")

        self._by_raw[raw_id] = candidate
        self._by_artifact[candidate] = raw_id
        return candidate


def assign_artifact_ids(
    items: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Copy items, preserve raw IDs, and assign one traceable artifact ID per record."""

    registry = ArtifactIdRegistry()
    normalized_items: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        copied = dict(item)
        raw_value = copied.get("platform_video_id")
        generated = raw_value in (None, "")
        if generated:
            raw_value = f"video-{index}"
        raw_id = validate_platform_video_id(raw_value)
        preferred = copied.get("artifact_id")
        artifact_id = registry.assign(raw_id, preferred=preferred if preferred not in (None, "") else None)
        copied["platform_video_id"] = raw_id
        copied["artifact_id"] = artifact_id
        if generated:
            copied["platform_video_id_generated"] = True
        normalized_items.append(copied)
        records.append(
            {
                "source_index": index,
                "platform_video_id": raw_id,
                "artifact_id": artifact_id,
                "platform_video_id_generated": generated,
            }
        )
    return normalized_items, records


def video_id_map_payload(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": VIDEO_ID_MAP_SCHEMA_VERSION,
        "records": [dict(record) for record in records],
    }


def artifact_id_for_item(item: Mapping[str, Any], *, fallback: str = "video") -> str:
    raw_value = item.get("platform_video_id")
    if raw_value in (None, ""):
        raw_value = fallback
    registry = ArtifactIdRegistry()
    preferred = item.get("artifact_id")
    return registry.assign(raw_value, preferred=preferred if preferred not in (None, "") else None)


def resolve_within(root: Path, relative: os.PathLike[str] | str) -> Path:
    """Resolve an untrusted relative path and prove it remains below root."""

    root_path = Path(root).resolve(strict=False)
    raw_relative = os.fspath(relative)
    if not raw_relative or "\x00" in raw_relative:
        raise PathContainmentError("PATH_RELATIVE_INVALID", "relative path is empty or contains NUL")
    windows_path = PureWindowsPath(raw_relative)
    posix_path = PurePosixPath(raw_relative)
    if windows_path.drive or windows_path.root or windows_path.is_absolute() or posix_path.is_absolute():
        raise PathContainmentError("PATH_ABSOLUTE", "absolute, drive-relative, and UNC paths are forbidden")
    if ".." in windows_path.parts or ".." in posix_path.parts:
        raise PathContainmentError("PATH_TRAVERSAL", "parent traversal is forbidden")
    candidate = (root_path / Path(raw_relative)).resolve(strict=False)
    if candidate == root_path or not candidate.is_relative_to(root_path):
        raise PathContainmentError("PATH_ESCAPE", "resolved path is outside its declared root")
    return candidate


def validate_artifact_suffix(suffix: object) -> str:
    if not isinstance(suffix, str) or not re.fullmatch(r"\.[a-zA-Z0-9._-]+", suffix) or ".." in suffix:
        raise PathContainmentError("PATH_SUFFIX_INVALID", "artifact suffix is invalid")
    return suffix


def artifact_path(root: Path, artifact_id: object, suffix: str) -> Path:
    safe_id = validate_artifact_id(artifact_id)
    safe_suffix = validate_artifact_suffix(suffix)
    return resolve_within(root, f"{safe_id}{safe_suffix}")


def artifact_files(root: Path, suffix: str) -> list[Path]:
    """List only normalized, contained, non-symlink-escaping artifact files."""

    safe_suffix = validate_artifact_suffix(suffix)
    if not root.exists():
        return []
    paths: list[Path] = []
    for candidate in sorted(root.glob(f"*{safe_suffix}")):
        artifact_name = candidate.name.removesuffix(safe_suffix)
        validate_artifact_id(artifact_name)
        contained = resolve_within(root, candidate.name)
        if contained.is_file():
            paths.append(contained)
    return paths
