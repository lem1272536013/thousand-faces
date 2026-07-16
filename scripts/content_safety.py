#!/usr/bin/env python3
"""Deterministic copyright-overlap and encoding diagnostics without text leakage."""

from __future__ import annotations

import hashlib
import os
import re
import sys
import unicodedata
from collections.abc import Mapping, Set
from pathlib import Path
from typing import Any


CONTENT_SAFETY_SCHEMA_VERSION = 1
OVERLAP_NGRAM_CHARS = 48
MATCH_FINGERPRINT_CHARS = 128
FINAL_SKILL_TEXT_SUFFIXES = frozenset({".md", ".txt", ".json", ".yaml", ".yml"})
_TIMESTAMP_PATTERN = re.compile(
    r"""(?x)
    [\[(]?
    (?:(?:\d{1,3}:)?\d{1,2}:\d{2})
    (?:[.,]\d{1,3})?
    [\])]?
    """
)
_FENCE_OPEN_PATTERN = re.compile(
    r"^[ \t]{0,3}(?P<fence>`{3,}|~{3,})(?P<info>.*)$"
)
_FENCE_CLOSE_PATTERN = re.compile(
    r"^[ \t]{0,3}(?P<fence>`{3,}|~{3,})[ \t]*$"
)
_QUESTION_RUN_PATTERN = re.compile(r"[?？]+")

OVERLAP_THRESHOLDS: dict[str, dict[str, float | int]] = {
    "general": {
        "max_longest_overlap_chars": 239,
        "max_copied_ratio": 0.20,
        "min_ratio_matched_chars": 120,
    },
    "evidence_summary": {
        "max_longest_overlap_chars": 479,
        "max_copied_ratio": 0.55,
        "min_ratio_matched_chars": 240,
    },
}
EVIDENCE_SUMMARY_PATHS = {
    "skill/references/evidence_index.md",
    "skill/references/research_summary.md",
}


def normalize_for_overlap(text: str) -> str:
    """Remove layout, common timestamps, and punctuation from comparison text."""

    normalized = unicodedata.normalize("NFKC", _TIMESTAMP_PATTERN.sub("", text))
    return "".join(character.casefold() for character in normalized if character.isalnum())


class _SuffixAutomaton:
    """Recognize every exact substring of one normalized transcript in linear time."""

    def __init__(self, sequence: str) -> None:
        self.transitions: list[dict[str, int]] = [{}]
        self.links = [-1]
        self.lengths = [0]
        last = 0
        for character in sequence:
            last = self._extend(last, character)

    def _extend(self, last: int, character: str) -> int:
        current = len(self.transitions)
        self.transitions.append({})
        self.lengths.append(self.lengths[last] + 1)
        self.links.append(0)
        parent = last
        while parent >= 0 and character not in self.transitions[parent]:
            self.transitions[parent][character] = current
            parent = self.links[parent]
        if parent < 0:
            return current

        destination = self.transitions[parent][character]
        if self.lengths[parent] + 1 == self.lengths[destination]:
            self.links[current] = destination
            return current

        clone = len(self.transitions)
        self.transitions.append(dict(self.transitions[destination]))
        self.lengths.append(self.lengths[parent] + 1)
        self.links.append(self.links[destination])
        while (
            parent >= 0
            and self.transitions[parent].get(character) == destination
        ):
            self.transitions[parent][character] = clone
            parent = self.links[parent]
        self.links[destination] = clone
        self.links[current] = clone
        return current

    def matching_intervals(
        self,
        target: str,
        *,
        minimum: int,
    ) -> tuple[list[tuple[int, int]], int, int]:
        """Return merged target intervals and its real longest source substring."""

        state = 0
        matched_length = 0
        longest = 0
        longest_start = 0
        intervals: list[tuple[int, int]] = []
        interval_start = -1
        interval_end = -1
        for index, character in enumerate(target):
            while state and character not in self.transitions[state]:
                state = self.links[state]
                matched_length = min(matched_length, self.lengths[state])
            destination = self.transitions[state].get(character)
            if destination is None:
                state = 0
                matched_length = 0
            else:
                state = destination
                matched_length += 1

            if matched_length > longest:
                longest = matched_length
                longest_start = index - matched_length + 1
            if matched_length < minimum:
                continue

            start = index - matched_length + 1
            end = index + 1
            if interval_start < 0:
                interval_start, interval_end = start, end
            elif start <= interval_end:
                interval_end = end
            else:
                intervals.append((interval_start, interval_end))
                interval_start, interval_end = start, end

        if interval_start >= 0:
            intervals.append((interval_start, interval_end))
        return intervals, longest, longest_start


def _empty_overlap_metrics() -> dict[str, Any]:
    return {
        "matched_chars": 0,
        "copied_ratio": 0.0,
        "longest_overlap_chars": 0,
        "match_fingerprint": "",
    }


def _finalize_overlap_metrics(
    sequence: str,
    coverage_delta: list[int],
    *,
    longest: int,
    longest_start: int,
) -> dict[str, Any]:
    if not sequence:
        return _empty_overlap_metrics()

    active = 0
    matched_chars = 0
    for delta in coverage_delta[:-1]:
        active += delta
        if active > 0:
            matched_chars += 1

    fingerprint = ""
    if longest:
        fingerprint_input = sequence[
            longest_start : longest_start + min(longest, MATCH_FINGERPRINT_CHARS)
        ]
        fingerprint = hashlib.sha256(fingerprint_input.encode("utf-8")).hexdigest()[:16]
    return {
        "matched_chars": matched_chars,
        "copied_ratio": round(matched_chars / len(sequence), 4),
        "longest_overlap_chars": longest,
        "match_fingerprint": fingerprint,
    }


def _overlap_file_result(
    path: str,
    sequence: str,
    metrics: Mapping[str, Any],
    *,
    category: str,
) -> dict[str, Any]:
    threshold = OVERLAP_THRESHOLDS[category]
    longest_failed = metrics["longest_overlap_chars"] > threshold[
        "max_longest_overlap_chars"
    ]
    ratio_failed = (
        metrics["matched_chars"] >= threshold["min_ratio_matched_chars"]
        and metrics["copied_ratio"] > threshold["max_copied_ratio"]
    )
    failed_reasons = []
    if longest_failed:
        failed_reasons.append("longest_overlap_exceeded")
    if ratio_failed:
        failed_reasons.append("copied_ratio_exceeded")
    return {
        "path": path,
        "category": category,
        "passed": not failed_reasons,
        "normalized_chars": len(sequence),
        **metrics,
        "failed_reasons": failed_reasons,
    }


def analyze_copyright_overlap(
    target_documents: Mapping[str, str],
    transcript_documents: Mapping[str, str],
    *,
    evidence_summary_paths: Set[str] | set[str] = frozenset(),
) -> dict[str, Any]:
    """Measure real contiguous source matches and union coverage without excerpts."""

    targets: dict[str, dict[str, Any]] = {}
    for path, text in sorted(target_documents.items()):
        sequence = normalize_for_overlap(text)
        targets[path] = {
            "sequence": sequence,
            "coverage_delta": [0] * (len(sequence) + 1),
            "longest": 0,
            "longest_start": 0,
        }

    transcript_corpus_available = False
    for text in transcript_documents.values():
        transcript_sequence = normalize_for_overlap(text)
        if not transcript_sequence:
            continue
        transcript_corpus_available = True
        if len(transcript_sequence) < OVERLAP_NGRAM_CHARS:
            continue
        automaton = _SuffixAutomaton(transcript_sequence)
        for state in targets.values():
            sequence = state["sequence"]
            intervals, longest, longest_start = automaton.matching_intervals(
                sequence,
                minimum=OVERLAP_NGRAM_CHARS,
            )
            coverage_delta = state["coverage_delta"]
            for start, end in intervals:
                coverage_delta[start] += 1
                coverage_delta[end] -= 1
            if longest > state["longest"]:
                state["longest"] = longest
                state["longest_start"] = longest_start

    files = []
    for path, state in targets.items():
        sequence = state["sequence"]
        metrics = _finalize_overlap_metrics(
            sequence,
            state["coverage_delta"],
            longest=state["longest"],
            longest_start=state["longest_start"],
        )
        files.append(
            _overlap_file_result(
                path,
                sequence,
                metrics,
                category=(
                    "evidence_summary" if path in evidence_summary_paths else "general"
                ),
            )
        )

    all_files_within_limits = bool(files) and all(file["passed"] for file in files)
    total_chars = sum(int(file["normalized_chars"]) for file in files)
    total_matched = sum(int(file["matched_chars"]) for file in files)
    return {
        "schema_version": CONTENT_SAFETY_SCHEMA_VERSION,
        "passed": transcript_corpus_available and all_files_within_limits,
        "checks": {
            "transcript_corpus_available": transcript_corpus_available,
            "target_documents_available": bool(files),
            "all_files_within_limits": all_files_within_limits,
        },
        "configuration": {
            "minimum_exact_match_chars": OVERLAP_NGRAM_CHARS,
            "ngram_chars": OVERLAP_NGRAM_CHARS,
            "longest_overlap_mode": "single_transcript_contiguous_substring",
        },
        "thresholds": {
            category: dict(values) for category, values in OVERLAP_THRESHOLDS.items()
        },
        "counts": {
            "target_files": len(files),
            "transcript_files": len(transcript_documents),
            "normalized_target_chars": total_chars,
            "matched_target_chars": total_matched,
        },
        "overall_copied_ratio": round(total_matched / total_chars, 4)
        if total_chars
        else 0.0,
        "longest_overlap_chars": max(
            (int(file["longest_overlap_chars"]) for file in files),
            default=0,
        ),
        "failed_files": [file["path"] for file in files if not file["passed"]],
        "files": files,
    }


def _without_fenced_code(text: str) -> str:
    output: list[str] = []
    pending: list[str] = []
    opening_fence = ""
    for line in text.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        if not opening_fence:
            opening = _FENCE_OPEN_PATTERN.fullmatch(content)
            if opening is None:
                output.append(line)
                continue
            candidate = opening.group("fence")
            if candidate.startswith("`") and "`" in opening.group("info"):
                output.append(line)
                continue
            opening_fence = candidate
            pending = [line]
            continue

        pending.append(line)
        closing = _FENCE_CLOSE_PATTERN.fullmatch(content)
        if closing is None:
            continue
        candidate = closing.group("fence")
        if candidate[0] != opening_fence[0] or len(candidate) < len(opening_fence):
            continue
        opening_fence = ""
        pending = []

    if pending:
        output.extend(pending)
    return "".join(output)


def analyze_text_encoding(text: str) -> dict[str, Any]:
    """Assess replacement markers and suspicious question density in decoded text."""

    replacement_count = text.count("\ufffd")
    prose = _without_fenced_code(text)
    question_count = prose.count("?") + prose.count("？")
    visible_char_count = sum(1 for character in prose if not character.isspace())
    density = question_count / visible_char_count if visible_char_count else 0.0
    maximum_run = max(
        (len(match.group(0)) for match in _QUESTION_RUN_PATTERN.finditer(prose)),
        default=0,
    )
    density_acceptable = not (
        (question_count >= 4 and maximum_run >= 4)
        or (question_count >= 12 and density >= 0.15)
    )
    checks = {
        "utf8_decodable": True,
        "no_replacement_characters": replacement_count == 0,
        "question_mark_density_acceptable": density_acceptable,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "replacement_character_count": replacement_count,
        "question_mark_count": question_count,
        "question_mark_density": round(density, 4),
        "maximum_question_mark_run": maximum_run,
    }


def analyze_encoding_documents(documents: Mapping[str, bytes]) -> dict[str, Any]:
    """Strictly decode documents and return diagnostics that never echo their content."""

    files: list[dict[str, Any]] = []
    for path, raw in sorted(documents.items()):
        try:
            text = raw.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError:
            files.append(
                {
                    "path": path,
                    "passed": False,
                    "checks": {
                        "utf8_decodable": False,
                        "no_replacement_characters": False,
                        "question_mark_density_acceptable": False,
                    },
                    "error": "invalid_utf8",
                }
            )
            continue
        files.append({"path": path, **analyze_text_encoding(text)})

    failed_files = [file["path"] for file in files if not file["passed"]]
    return {
        "schema_version": CONTENT_SAFETY_SCHEMA_VERSION,
        "passed": bool(files) and not failed_files,
        "checks": {
            "documents_available": bool(files),
            "all_documents_valid": bool(files) and not failed_files,
        },
        "counts": {
            "files": len(files),
            "failed_files": len(failed_files),
        },
        "failed_files": failed_files,
        "files": files,
    }


def _lexical_candidate(root: Path, path: Path) -> tuple[Path, str] | None:
    candidate = path if path.is_absolute() else root / path
    candidate = candidate.absolute()
    try:
        relative_path = candidate.relative_to(root)
    except ValueError:
        return None
    if ".." in relative_path.parts:
        return None
    return candidate, relative_path.as_posix()


def _contains_symlink_component(root: Path, candidate: Path) -> bool:
    try:
        relative_parts = candidate.relative_to(root).parts
    except ValueError:
        return True
    current = root
    for part in relative_parts:
        current /= part
        if current.is_symlink():
            return True
    return False


def _normalized_windows_path(path: str | Path) -> str:
    value = str(path)
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return os.path.normcase(os.path.abspath(value))


if sys.platform == "win32":

    def _windows_final_path(descriptor: int) -> str | None:
        import ctypes
        import msvcrt
        from ctypes import wintypes

        get_final_path = ctypes.windll.kernel32.GetFinalPathNameByHandleW
        get_final_path.argtypes = [
            wintypes.HANDLE,
            wintypes.LPWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        get_final_path.restype = wintypes.DWORD
        buffer = ctypes.create_unicode_buffer(32768)
        length = get_final_path(
            wintypes.HANDLE(msvcrt.get_osfhandle(descriptor)),
            buffer,
            len(buffer),
            0,
        )
        if length == 0 or length >= len(buffer):
            return None
        return buffer.value

else:

    def _windows_final_path(descriptor: int) -> str | None:
        del descriptor
        return None


def _path_is_within(root: Path, candidate: str | Path) -> bool:
    if os.name == "nt":
        root_value = _normalized_windows_path(root)
        candidate_value = _normalized_windows_path(candidate)
    else:
        root_value = os.path.normcase(os.path.abspath(root))
        candidate_value = os.path.normcase(os.path.abspath(candidate))
    try:
        return os.path.commonpath([root_value, candidate_value]) == root_value
    except ValueError:
        return False


def _read_windows_handle(
    root: Path,
    candidate: Path,
    expected: Path,
) -> tuple[bytes | None, str]:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(candidate, flags)
    except OSError:
        return None, "unreadable"
    try:
        final_path = _windows_final_path(descriptor)
        if final_path is None:
            return None, "unreadable"
        if not _path_is_within(root, final_path):
            return None, "outside_run_dir"
        if _normalized_windows_path(final_path) != _normalized_windows_path(expected):
            return None, "changed_during_read"
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            return handle.read(), "read"
    except OSError:
        return None, "unreadable"
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _read_posix_openat(
    root: Path,
    candidate: Path,
) -> tuple[bytes | None, str]:
    relative_parts = candidate.relative_to(root).parts
    if not relative_parts:
        return None, "unreadable"
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    directory_descriptor = -1
    try:
        directory_descriptor = os.open(root, directory_flags)
        for part in relative_parts[:-1]:
            next_descriptor = os.open(
                part,
                directory_flags,
                dir_fd=directory_descriptor,
            )
            os.close(directory_descriptor)
            directory_descriptor = next_descriptor
        file_descriptor = os.open(
            relative_parts[-1],
            file_flags,
            dir_fd=directory_descriptor,
        )
        with os.fdopen(file_descriptor, "rb") as handle:
            return handle.read(), "read"
    except OSError:
        return None, "unreadable"
    finally:
        if directory_descriptor >= 0:
            os.close(directory_descriptor)


def _secure_read_bytes(
    root: Path,
    candidate: Path,
    expected: Path,
) -> tuple[bytes | None, str]:
    if os.name == "nt":
        return _read_windows_handle(root, candidate, expected)
    return _read_posix_openat(root, candidate)


def _read_contained_input(
    root: Path,
    path: Path,
    *,
    role: str,
) -> tuple[str | None, bytes | None, dict[str, Any]]:
    lexical = _lexical_candidate(root, path)
    if lexical is None:
        return None, None, {
            "role": role,
            "path": "<outside_run_dir>",
            "status": "outside_run_dir",
        }
    candidate, relative = lexical
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError:
        return relative, None, {"role": role, "path": relative, "status": "missing"}
    except OSError:
        return relative, None, {"role": role, "path": relative, "status": "unreadable"}

    try:
        resolved.relative_to(root)
    except ValueError:
        return relative, None, {
            "role": role,
            "path": relative,
            "status": "outside_run_dir",
        }
    if _contains_symlink_component(root, candidate):
        return relative, None, {
            "role": role,
            "path": relative,
            "status": "outside_run_dir",
        }

    raw, read_status = _secure_read_bytes(root, candidate, resolved)
    if raw is None:
        return relative, None, {
            "role": role,
            "path": relative,
            "status": read_status,
        }
    return relative, raw, {
        "role": role,
        "path": relative,
        "status": "read",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }


def _discover_skill_text_paths(root: Path) -> tuple[list[Path], list[dict[str, Any]]]:
    skill_root = root / "skill"
    if not skill_root.exists():
        return [], []
    if skill_root.is_symlink():
        return [], [
            {
                "role": "final_skill_document",
                "path": "skill",
                "status": "outside_run_dir",
            }
        ]
    try:
        paths = [
            path
            for path in skill_root.rglob("*")
            if path.suffix.casefold() in FINAL_SKILL_TEXT_SUFFIXES
            and (path.is_file() or path.is_symlink())
        ]
    except OSError:
        return [], [
            {
                "role": "final_skill_document",
                "path": "skill",
                "status": "unreadable",
            }
        ]
    return sorted(paths), []


def _collect_inputs(
    root: Path,
    paths: list[Path],
    *,
    role: str,
) -> tuple[dict[str, bytes], list[dict[str, Any]]]:
    documents: dict[str, bytes] = {}
    identities: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        relative, raw, identity = _read_contained_input(root, path, role=role)
        identity_key = f"{identity['path']}:{identity['status']}"
        if identity_key in seen:
            continue
        seen.add(identity_key)
        identities.append(identity)
        if relative is not None and raw is not None:
            documents[relative] = raw
    return documents, identities


def evaluate_run_content_safety(
    run_dir: Path,
    *,
    target_paths: list[Path] | None = None,
    transcript_paths: list[Path],
) -> dict[str, Any]:
    """Read contained files once; hash and analyze the exact same immutable bytes."""

    root = Path(run_dir).resolve(strict=False)
    discovery_issues: list[dict[str, Any]] = []
    if target_paths is None:
        target_paths, discovery_issues = _discover_skill_text_paths(root)

    target_bytes, target_identities = _collect_inputs(
        root,
        target_paths,
        role="final_skill_document",
    )
    transcript_bytes, transcript_identities = _collect_inputs(
        root,
        transcript_paths,
        role="transcript",
    )
    identities = [*discovery_issues, *target_identities, *transcript_identities]

    all_bytes = {**target_bytes, **transcript_bytes}
    encoding = analyze_encoding_documents(all_bytes)
    target_documents: dict[str, str] = {}
    transcript_documents: dict[str, str] = {}
    for relative_path, raw in target_bytes.items():
        try:
            target_documents[relative_path] = raw.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError:
            continue
    for relative_path, raw in transcript_bytes.items():
        try:
            transcript_documents[relative_path] = raw.decode(
                "utf-8-sig", errors="strict"
            )
        except UnicodeDecodeError:
            continue

    copyright_overlap = analyze_copyright_overlap(
        target_documents,
        transcript_documents,
        evidence_summary_paths=EVIDENCE_SUMMARY_PATHS,
    )
    statuses = {str(identity["status"]) for identity in identities}
    inputs_contained = not statuses.intersection(
        {"outside_run_dir", "changed_during_read"}
    )
    inputs_available = (
        bool(target_bytes)
        and bool(transcript_bytes)
        and bool(identities)
        and statuses == {"read"}
    )
    checks = {
        "inputs_contained": inputs_contained,
        "inputs_available": inputs_available,
        "encoding_valid": encoding["passed"] is True,
        "copyright_overlap_valid": copyright_overlap["passed"] is True,
    }
    return {
        "schema_version": CONTENT_SAFETY_SCHEMA_VERSION,
        "passed": all(checks.values()),
        "checks": checks,
        "encoding": encoding,
        "copyright_overlap": copyright_overlap,
        "computed_from": identities,
    }
