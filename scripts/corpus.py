#!/usr/bin/env python3
"""Bounded, immutable transcript snapshots for one analysis execution."""

from __future__ import annotations

import codecs
import hashlib
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

import path_policy


DEFAULT_MAX_TRANSCRIPT_CHARS = 500_000
DEFAULT_MAX_CORPUS_CHARS = 5_000_000
READ_CHUNK_BYTES = 1024 * 1024
HIERARCHICAL_STRATA = (
    "top_interaction",
    "top_transcript_length",
    "short_transcripts",
    "boundary_or_risk",
    "remaining",
)


class CorpusLoadError(ValueError):
    """Raised when one immutable corpus snapshot cannot be built safely."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"[{code}] {message}")


class CorpusLimitError(CorpusLoadError):
    """Raised instead of silently truncating an oversized transcript corpus."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        observed_chars: int,
        limit_chars: int,
        max_total_chars: int,
    ) -> None:
        file_limit_exceeded = code == "CORPUS_FILE_CHAR_LIMIT"
        recommended_batches = max(2, math.ceil(observed_chars / max_total_chars))
        recommended_segments = (
            max(2, math.ceil(observed_chars / limit_chars))
            if file_limit_exceeded
            else 1
        )
        self.observed_chars = observed_chars
        self.limit_chars = limit_chars
        self.strategy: Mapping[str, Any] = MappingProxyType(
            {
                "name": "hierarchical_batch_index",
                "truncate_transcripts": False,
                "strata": list(HIERARCHICAL_STRATA),
                "recommended_minimum_batches": recommended_batches,
                "recommended_minimum_segments": recommended_segments,
                "batch_max_chars": max_total_chars,
                "max_transcript_chars": limit_chars if file_limit_exceeded else None,
                "oversized_document_policy": "segment_then_summarize",
                "instructions": (
                    "Build a metadata-first index, distribute every stratum across "
                    "balanced batches below the applicable limit, assign each "
                    "within-limit transcript to exactly one batch, index oversized "
                    "transcripts as bounded contiguous segments without truncation, "
                    "then synthesize document and batch summaries."
                ),
            }
        )
        super().__init__(
            code,
            f"{message}; use hierarchical_batch_index across strata "
            f"{', '.join(HIERARCHICAL_STRATA)} with balanced batches instead of "
            "truncating transcript evidence",
        )


@dataclass(frozen=True, slots=True)
class CorpusDocument:
    """One transcript decoded, normalized, and fingerprinted by a single read."""

    artifact_id: str
    path: Path
    source_text: str
    normalized_text: str
    decoded_chars: int
    size_bytes: int
    sha256: str
    modified_ns: int

    def excerpt(self, chars: int) -> str:
        if chars < 1:
            raise ValueError("excerpt chars must be positive")
        text = (
            self.source_text.replace("\r\n", "\n")
            .replace("\r", "\n")
            .replace("\x00", "�")
            .strip()
        )
        if len(text) <= chars:
            return text
        third = chars // 3
        head = text[:third]
        mid_start = max(0, len(text) // 2 - chars // 6)
        mid = text[mid_start : mid_start + third]
        tail = text[-third:]
        return "\n\n".join((f"开头：{head}", f"中段：{mid}", f"结尾：{tail}"))

    def input_identity(self, *, role: str) -> dict[str, object]:
        return {
            "role": role,
            "name": self.path.name,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True, slots=True)
class CorpusSnapshot:
    """Read-only transcript data shared by every consumer in one execution."""

    run_dir: Path
    documents: tuple[CorpusDocument, ...]
    total_decoded_chars: int
    max_file_chars: int
    max_total_chars: int
    _by_artifact_id: Mapping[str, CorpusDocument] = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        root = Path(self.run_dir).resolve(strict=False)
        transcript_root = (root / "transcripts").resolve(strict=False)
        object.__setattr__(self, "run_dir", root)
        _positive_limit(self.max_file_chars, "max_file_chars")
        _positive_limit(self.max_total_chars, "max_total_chars")
        by_id = {document.artifact_id: document for document in self.documents}
        if len(by_id) != len(self.documents):
            raise CorpusLoadError(
                "CORPUS_DUPLICATE_ARTIFACT",
                "transcript artifact IDs must be unique",
            )
        for document in self.documents:
            try:
                expected_path = path_policy.artifact_path(
                    transcript_root,
                    document.artifact_id,
                    ".txt",
                ).resolve(strict=False)
            except (path_policy.VideoIdError, path_policy.PathContainmentError) as error:
                raise CorpusLoadError(
                    "CORPUS_DOCUMENT_OUTSIDE_RUN",
                    "corpus snapshot contains an invalid transcript artifact",
                ) from error
            if document.path.resolve(strict=False) != expected_path:
                raise CorpusLoadError(
                    "CORPUS_DOCUMENT_OUTSIDE_RUN",
                    f"transcript {document.path.name!r} is outside this run",
                )
        if self.total_decoded_chars != sum(
            document.decoded_chars for document in self.documents
        ):
            raise CorpusLoadError(
                "CORPUS_TOTAL_MISMATCH",
                "corpus snapshot total does not match its documents",
            )
        object.__setattr__(self, "_by_artifact_id", MappingProxyType(by_id))

    def get(self, artifact_id: object) -> CorpusDocument | None:
        return self._by_artifact_id.get(str(artifact_id))

    def text_for(self, artifact_id: object) -> str:
        document = self.get(artifact_id)
        return document.normalized_text if document is not None else ""

    def transcript_inputs(self) -> tuple[dict[str, object], ...]:
        return tuple(
            document.input_identity(role=f"transcript:{document.path.name}")
            for document in self.documents
        )

    def assert_for_run(self, run_dir: Path) -> None:
        if Path(run_dir).resolve(strict=False) != self.run_dir:
            raise CorpusLoadError(
                "CORPUS_RUN_MISMATCH",
                "corpus snapshot belongs to a different run",
            )

    def assert_unchanged(self) -> None:
        """Fail if a cached input changed before its derived artifacts are certified."""

        for document in self.documents:
            try:
                state = document.path.stat()
            except OSError as error:
                raise CorpusLoadError(
                    "CORPUS_INPUT_CHANGED",
                    f"transcript {document.path.name!r} disappeared after loading",
                ) from error
            if (
                state.st_size != document.size_bytes
                or state.st_mtime_ns != document.modified_ns
            ):
                raise CorpusLoadError(
                    "CORPUS_INPUT_CHANGED",
                    f"transcript {document.path.name!r} changed after loading; rerun prepare",
                )


def normalize_analysis_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _positive_limit(value: int, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _read_document(
    path: Path,
    *,
    total_before: int,
    max_file_chars: int,
    max_total_chars: int,
) -> CorpusDocument:
    before = path.stat()
    digest = hashlib.sha256()
    decoder = codecs.getincrementaldecoder("utf-8-sig")(errors="replace")
    parts: list[str] = []
    decoded_chars = 0
    size_bytes = 0
    with path.open("rb") as stream:
        while True:
            block = stream.read(READ_CHUNK_BYTES)
            if not block:
                break
            size_bytes += len(block)
            digest.update(block)
            decoded = decoder.decode(block)
            parts.append(decoded)
            decoded_chars += len(decoded)
            if decoded_chars > max_file_chars:
                raise CorpusLimitError(
                    "CORPUS_FILE_CHAR_LIMIT",
                    f"transcript {path.name!r} exceeds {max_file_chars} decoded characters",
                    observed_chars=decoded_chars,
                    limit_chars=max_file_chars,
                    max_total_chars=max_total_chars,
                )
            if total_before + decoded_chars > max_total_chars:
                raise CorpusLimitError(
                    "CORPUS_TOTAL_CHAR_LIMIT",
                    f"corpus exceeds {max_total_chars} decoded characters at {path.name!r}",
                    observed_chars=total_before + decoded_chars,
                    limit_chars=max_total_chars,
                    max_total_chars=max_total_chars,
                )
        tail = decoder.decode(b"", final=True)
        parts.append(tail)
        decoded_chars += len(tail)
    if decoded_chars > max_file_chars or total_before + decoded_chars > max_total_chars:
        code = (
            "CORPUS_FILE_CHAR_LIMIT"
            if decoded_chars > max_file_chars
            else "CORPUS_TOTAL_CHAR_LIMIT"
        )
        limit = max_file_chars if code == "CORPUS_FILE_CHAR_LIMIT" else max_total_chars
        raise CorpusLimitError(
            code,
            f"transcript corpus exceeds the {limit} character limit at {path.name!r}",
            observed_chars=(
                decoded_chars
                if code == "CORPUS_FILE_CHAR_LIMIT"
                else total_before + decoded_chars
            ),
            limit_chars=limit,
            max_total_chars=max_total_chars,
        )
    after = path.stat()
    if (
        before.st_size != size_bytes
        or after.st_size != size_bytes
        or before.st_mtime_ns != after.st_mtime_ns
    ):
        raise CorpusLoadError(
            "CORPUS_INPUT_CHANGED",
            f"transcript {path.name!r} changed while it was being loaded",
        )
    source_text = "".join(parts)
    return CorpusDocument(
        artifact_id=path.stem,
        path=path,
        source_text=source_text,
        normalized_text=normalize_analysis_text(source_text),
        decoded_chars=decoded_chars,
        size_bytes=size_bytes,
        sha256=digest.hexdigest(),
        modified_ns=after.st_mtime_ns,
    )


def load_corpus(
    run_dir: Path,
    *,
    max_file_chars: int = DEFAULT_MAX_TRANSCRIPT_CHARS,
    max_total_chars: int = DEFAULT_MAX_CORPUS_CHARS,
) -> CorpusSnapshot:
    """Read each contained transcript once and return one bounded immutable snapshot."""

    file_limit = _positive_limit(max_file_chars, "max_file_chars")
    total_limit = _positive_limit(max_total_chars, "max_total_chars")
    root = Path(run_dir).resolve(strict=False)
    documents: list[CorpusDocument] = []
    total_chars = 0
    for path in path_policy.artifact_files(root / "transcripts", ".txt"):
        try:
            document = _read_document(
                path,
                total_before=total_chars,
                max_file_chars=file_limit,
                max_total_chars=total_limit,
            )
        except OSError as error:
            raise CorpusLoadError(
                "CORPUS_READ_ERROR",
                f"could not read transcript {path.name!r}; check access and retry",
            ) from error
        documents.append(document)
        total_chars += document.decoded_chars
    return CorpusSnapshot(
        run_dir=root,
        documents=tuple(documents),
        total_decoded_chars=total_chars,
        max_file_chars=file_limit,
        max_total_chars=total_limit,
    )
