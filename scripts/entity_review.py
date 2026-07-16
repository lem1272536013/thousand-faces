#!/usr/bin/env python3
"""Versioned, source-traceable ASR entity detection and human review state."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, Mapping, Sequence


ENTITY_REVIEW_SCHEMA_VERSION = 1
ENTITY_REVIEW_ALGORITHM_VERSION = "1.1.0"
PROJECT_DICTIONARY_SCHEMA_VERSION = 1
ENTITY_DECISION_SCHEMA_VERSION = 1
PROJECT_DICTIONARY_RELATIVE_PATH = PurePosixPath("research/entity_dictionary.json")
ALLOWED_STATUSES = ("unresolved", "confirmed", "corrected", "ignored")
ALLOWED_IMPACTS = ("high", "medium", "low")
MAX_PROJECT_DICTIONARY_BYTES = 1024 * 1024
MAX_PROJECT_ENTITIES = 1000
MAX_ALIASES_PER_ENTITY = 50
MAX_DETECTED_ASCII_CANDIDATES = 60


class EntityReviewError(ValueError):
    """Raised when an entity dictionary or review contract is malformed."""


@dataclass(frozen=True)
class EntityDocument:
    """One platform video and its raw normalized ASR artifact identity."""

    video_id: str
    artifact_id: str
    title: str
    transcript: str


@dataclass(frozen=True)
class EntityDefinition:
    """One canonical entity plus explicit forms that may occur in ASR."""

    canonical_term: str
    aliases: tuple[str, ...]
    category: str
    impact: Literal["high", "medium", "low"]
    note: str
    registry_source: Literal["preset", "project", "detected"]


@dataclass(frozen=True)
class _Fragment:
    fragment_id: str
    video_id: str
    source_kind: Literal["title", "transcript"]
    artifact_path: str
    text: str


_ENTITY_SEPARATOR = re.compile(r"[\s._\-/\\·・]+")
_MATCH_SEPARATOR = r"[\s._\-/\\·・]*"
_ASCII_CANDIDATE = re.compile(r"[A-Za-z][A-Za-z0-9.+/-]{2,}")
_SENTENCE = re.compile(r"[^。！？!?；;\r\n]+(?:[。！？!?；;]+|$)")
_CATEGORY = re.compile(r"[a-z][a-z0-9_]{1,63}")
_IGNORED_ASCII = frozenset(
    {
        "and",
        "for",
        "from",
        "that",
        "the",
        "this",
        "with",
    }
)
_MARKDOWN_CONTROL_CHARACTERS = frozenset("\\|[]()`<>#:&!*_~{}")


def normalize_entity_key(value: str) -> str:
    """Normalize case, width, separators, and mixed-form spacing for identity."""

    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    return _ENTITY_SEPARATOR.sub("", normalized)


def project_dictionary_path(run_dir: Path) -> Path:
    """Return the fixed, run-confined project dictionary path."""

    return Path(run_dir).joinpath(*PROJECT_DICTIONARY_RELATIVE_PATH.parts)


def build_project_dictionary_template() -> dict[str, object]:
    """Create an intentionally empty, human-editable project extension."""

    return {
        "schema_version": PROJECT_DICTIONARY_SCHEMA_VERSION,
        "description": (
            "Project-level ASR entity aliases. Add brands, people, places, "
            "organizations, products, and professional terms without editing presets."
        ),
        "entity_contract": {
            "required_fields": [
                "canonical_term",
                "aliases",
                "category",
                "impact",
                "note",
            ],
            "allowed_impacts": list(ALLOWED_IMPACTS),
        },
        "entities": [],
    }


def _text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise EntityReviewError(f"{field} must be a string")
    cleaned = unicodedata.normalize("NFKC", value).strip()
    if not allow_empty and not cleaned:
        raise EntityReviewError(f"{field} must not be empty")
    if len(cleaned) > 256 or not cleaned.isprintable():
        raise EntityReviewError(f"{field} must be printable and at most 256 characters")
    return cleaned


def _project_path_label(path: Path) -> str:
    normalized = Path(path)
    if normalized.parent.name == "research":
        return f"research/{normalized.name}"
    return normalized.name


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_project_definitions(path: Path) -> tuple[list[EntityDefinition], dict[str, object]]:
    dictionary_path = Path(path)
    if not dictionary_path.is_file():
        return [], {
            "path": _project_path_label(dictionary_path),
            "sha256": "",
            "entity_count": 0,
            "status": "missing",
        }
    if dictionary_path.stat().st_size > MAX_PROJECT_DICTIONARY_BYTES:
        raise EntityReviewError(
            "project entity dictionary exceeds the 1 MiB safety limit"
        )
    try:
        payload = json.loads(dictionary_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EntityReviewError("project entity dictionary must be readable JSON") from error
    if not isinstance(payload, dict):
        raise EntityReviewError("project entity dictionary must be a JSON object")
    if payload.get("schema_version") != PROJECT_DICTIONARY_SCHEMA_VERSION:
        raise EntityReviewError(
            "project entity dictionary schema_version must be "
            f"{PROJECT_DICTIONARY_SCHEMA_VERSION}"
        )
    raw_entities = payload.get("entities")
    if not isinstance(raw_entities, list):
        raise EntityReviewError("project entity dictionary entities must be a list")
    if len(raw_entities) > MAX_PROJECT_ENTITIES:
        raise EntityReviewError(
            f"project entity dictionary cannot exceed {MAX_PROJECT_ENTITIES} entities"
        )
    definitions: list[EntityDefinition] = []
    for index, raw in enumerate(raw_entities):
        if not isinstance(raw, dict):
            raise EntityReviewError(f"project entity at index {index} must be an object")
        canonical = _text(raw.get("canonical_term"), f"entities[{index}].canonical_term")
        raw_aliases = raw.get("aliases")
        if not isinstance(raw_aliases, list):
            raise EntityReviewError(f"entities[{index}].aliases must be a list")
        if len(raw_aliases) > MAX_ALIASES_PER_ENTITY:
            raise EntityReviewError(
                f"entities[{index}].aliases cannot exceed {MAX_ALIASES_PER_ENTITY} items"
            )
        aliases = tuple(
            _text(alias, f"entities[{index}].aliases[{alias_index}]")
            for alias_index, alias in enumerate(raw_aliases)
        )
        category = _text(raw.get("category"), f"entities[{index}].category")
        if _CATEGORY.fullmatch(category) is None:
            raise EntityReviewError(
                f"entities[{index}].category must use lower_snake_case"
            )
        impact = _text(raw.get("impact"), f"entities[{index}].impact")
        if impact not in ALLOWED_IMPACTS:
            raise EntityReviewError(
                f"entities[{index}].impact must be one of {', '.join(ALLOWED_IMPACTS)}"
            )
        note = _text(
            raw.get("note", ""),
            f"entities[{index}].note",
            allow_empty=True,
        )
        definitions.append(
            EntityDefinition(
                canonical_term=canonical,
                aliases=aliases,
                category=category,
                impact=impact,  # type: ignore[arg-type]
                note=note,
                registry_source="project",
            )
        )
    return definitions, {
        "path": _project_path_label(dictionary_path),
        "sha256": _file_sha256(dictionary_path),
        "entity_count": len(definitions),
        "status": "loaded",
    }


def _effective_definitions(
    preset_entities: Sequence[str],
    project_dictionary_path: Path,
) -> tuple[list[EntityDefinition], dict[str, object]]:
    by_canonical: dict[str, EntityDefinition] = {}
    for index, raw_entity in enumerate(preset_entities):
        canonical = _text(raw_entity, f"preset_entities[{index}]")
        key = normalize_entity_key(canonical)
        if not key:
            raise EntityReviewError(f"preset entity {canonical!r} has no normalized identity")
        by_canonical[key] = EntityDefinition(
            canonical_term=canonical,
            aliases=(),
            category="preset_term",
            impact="high",
            note="Provided by the selected taxonomy preset.",
            registry_source="preset",
        )
    project_definitions, project_identity = _load_project_definitions(
        project_dictionary_path
    )
    for definition in project_definitions:
        key = normalize_entity_key(definition.canonical_term)
        if not key:
            raise EntityReviewError(
                f"project entity {definition.canonical_term!r} has no normalized identity"
            )
        previous = by_canonical.get(key)
        if previous is not None:
            aliases = tuple(
                dict.fromkeys(
                    [
                        *previous.aliases,
                        previous.canonical_term,
                        *definition.aliases,
                    ]
                )
            )
            definition = EntityDefinition(
                canonical_term=definition.canonical_term,
                aliases=aliases,
                category=definition.category,
                impact=definition.impact,
                note=definition.note,
                registry_source="project",
            )
        by_canonical[key] = definition

    alias_owner: dict[str, str] = {}
    for canonical_key, definition in by_canonical.items():
        for form in (definition.canonical_term, *definition.aliases):
            alias_key = normalize_entity_key(form)
            if not alias_key:
                raise EntityReviewError(
                    f"entity alias {form!r} has no normalized identity"
                )
            owner = alias_owner.get(alias_key)
            if owner is not None and owner != canonical_key:
                raise EntityReviewError(
                    f"entity alias collision for {form!r}: {owner!r} and {canonical_key!r}"
                )
            alias_owner[alias_key] = canonical_key

    definitions = sorted(
        by_canonical.values(),
        key=lambda item: (normalize_entity_key(item.canonical_term), item.canonical_term),
    )
    return definitions, {
        "preset_entity_count": len(tuple(preset_entities)),
        "project": project_identity,
        "effective_entity_count": len(definitions),
        "normalization": "NFKC+casefold+separator_compaction",
    }


def _validate_documents(documents: Sequence[EntityDocument]) -> list[EntityDocument]:
    validated: list[EntityDocument] = []
    seen_ids: set[str] = set()
    for index, document in enumerate(documents):
        if not isinstance(document, EntityDocument):
            raise EntityReviewError(
                f"entity document at index {index} must be an EntityDocument"
            )
        for field in ("video_id", "artifact_id"):
            value = getattr(document, field)
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
                or not value.isprintable()
                or any(marker in value for marker in ("#", "/", "\\"))
            ):
                raise EntityReviewError(
                    f"entity document {field} at index {index} is not a stable ID"
                )
        if document.video_id in seen_ids:
            raise EntityReviewError(
                f"duplicate entity document video_id {document.video_id!r}"
            )
        if not isinstance(document.title, str) or not isinstance(document.transcript, str):
            raise EntityReviewError(
                f"entity document {document.video_id!r} title and transcript must be strings"
            )
        seen_ids.add(document.video_id)
        validated.append(document)
    return sorted(validated, key=lambda item: item.video_id)


def _fragments(documents: Sequence[EntityDocument]) -> list[_Fragment]:
    fragments: list[_Fragment] = []
    for document in documents:
        title = re.sub(r"\s+", " ", document.title).strip()
        if title:
            fragments.append(
                _Fragment(
                    fragment_id=f"{document.video_id}#title",
                    video_id=document.video_id,
                    source_kind="title",
                    artifact_path="metadata/selected.compact.json",
                    text=title,
                )
            )
        transcript_index = 0
        for match in _SENTENCE.finditer(document.transcript):
            text = re.sub(r"\s+", " ", match.group(0).rstrip("。！？!?；;")).strip()
            if not text:
                continue
            transcript_index += 1
            fragments.append(
                _Fragment(
                    fragment_id=(
                        f"{document.video_id}#transcript:{transcript_index:04d}"
                    ),
                    video_id=document.video_id,
                    source_kind="transcript",
                    artifact_path=f"transcripts/{document.artifact_id}.txt",
                    text=text,
                )
            )
    return fragments


def _entity_pattern(form: str) -> re.Pattern[str]:
    compact = [
        character
        for character in unicodedata.normalize("NFKC", form)
        if _ENTITY_SEPARATOR.fullmatch(character) is None
    ]
    if not compact:
        raise EntityReviewError(f"entity form {form!r} has no matchable characters")
    expression = _MATCH_SEPARATOR.join(re.escape(character) for character in compact)
    if compact[0].isascii() and compact[0].isalnum():
        expression = rf"(?<![A-Za-z0-9]){expression}"
    if compact[-1].isascii() and compact[-1].isalnum():
        expression = rf"{expression}(?![A-Za-z0-9])"
    return re.compile(expression, re.IGNORECASE)


def _candidate_id(normalized_term: str) -> str:
    digest = hashlib.sha256(normalized_term.encode("utf-8")).hexdigest()[:12]
    return f"entity-{digest}"


def _entity_confidence(
    registry_source: object,
    document_frequency: int,
    occurrence_count: int,
) -> dict[str, object]:
    """Describe identification confidence without claiming the entity is factually correct."""

    if registry_source in {"preset", "project"}:
        return {
            "level": "high",
            "score": 0.95,
            "reason": "registered_dictionary_match",
        }
    if document_frequency >= 3:
        return {
            "level": "high",
            "score": 0.85,
            "reason": "detected_across_three_or_more_videos",
        }
    if document_frequency >= 2 or occurrence_count >= 3:
        return {
            "level": "medium",
            "score": 0.6,
            "reason": "detected_repeated_signal",
        }
    return {
        "level": "low",
        "score": 0.3,
        "reason": "detected_single_video_signal",
    }


def _source_references(
    fragment_matches: Mapping[str, list[str]],
    fragment_by_id: Mapping[str, _Fragment],
) -> list[dict[str, object]]:
    references: list[dict[str, object]] = []
    for fragment_id in sorted(fragment_matches):
        fragment = fragment_by_id[fragment_id]
        observations = fragment_matches[fragment_id]
        references.append(
            {
                "fragment_id": fragment.fragment_id,
                "video_id": fragment.video_id,
                "source_kind": fragment.source_kind,
                "artifact_path": fragment.artifact_path,
                "observed_forms": sorted(set(observations), key=lambda value: (value.casefold(), value)),
                "occurrence_count": len(observations),
            }
        )
    return references


def _candidate_payload(
    definition: EntityDefinition,
    fragment_matches: Mapping[str, list[str]],
    fragment_by_id: Mapping[str, _Fragment],
) -> dict[str, object]:
    references = _source_references(fragment_matches, fragment_by_id)
    video_ids = sorted({str(reference["video_id"]) for reference in references})
    observations = [
        observation
        for values in fragment_matches.values()
        for observation in values
    ]
    raw_asr = sorted(
        {
            str(reference["artifact_path"])
            for reference in references
            if reference["source_kind"] == "transcript"
        }
    )
    normalized = normalize_entity_key(definition.canonical_term)
    confidence = _entity_confidence(
        definition.registry_source,
        len(video_ids),
        len(observations),
    )
    return {
        "candidate_id": _candidate_id(normalized),
        "canonical_term": definition.canonical_term,
        "normalized_term": normalized,
        "aliases": list(definition.aliases),
        "category": definition.category,
        "impact": definition.impact,
        "registry_source": definition.registry_source,
        "dictionary_note": definition.note,
        "observed_forms": sorted(set(observations), key=lambda value: (value.casefold(), value)),
        "occurrence_count": len(observations),
        "document_frequency": len(video_ids),
        "representative_video_ids": video_ids,
        "confidence": confidence,
        "source_references": references,
        "raw_asr_references": raw_asr,
        "status": "unresolved",
        "treatment_note": "",
        "corrected_term": "",
        "final_references": [],
    }


def build_entity_review(
    documents: Sequence[EntityDocument],
    *,
    taxonomy: Mapping[str, str],
    preset_entities: Sequence[str],
    project_dictionary_path: Path,
) -> dict[str, object]:
    """Detect registered entities and bounded ASCII candidates with source evidence."""

    if not isinstance(taxonomy, Mapping) or not all(
        isinstance(taxonomy.get(field), str) and taxonomy.get(field)
        for field in ("preset", "version")
    ):
        raise EntityReviewError("taxonomy must contain non-empty preset and version strings")
    corpus = _validate_documents(documents)
    definitions, dictionary_identity = _effective_definitions(
        preset_entities,
        Path(project_dictionary_path),
    )
    fragments = _fragments(corpus)
    fragment_by_id = {fragment.fragment_id: fragment for fragment in fragments}
    registered_matches: dict[str, dict[str, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    registered_spans: dict[str, list[tuple[int, int]]] = defaultdict(list)

    for definition in definitions:
        canonical_key = normalize_entity_key(definition.canonical_term)
        patterns = {
            normalize_entity_key(form): _entity_pattern(form)
            for form in (definition.canonical_term, *definition.aliases)
        }
        for fragment in fragments:
            possible_matches = [
                match
                for pattern in patterns.values()
                for match in pattern.finditer(fragment.text)
            ]
            possible_matches.sort(
                key=lambda match: (match.start(), -(match.end() - match.start()))
            )
            spans: list[tuple[int, int]] = []
            for match in possible_matches:
                span = match.span()
                if any(span[0] < end and span[1] > start for start, end in spans):
                    continue
                spans.append(span)
                registered_matches[canonical_key][fragment.fragment_id].append(
                    match.group(0)
                )
                registered_spans[fragment.fragment_id].append(span)

    detected: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    detected_display: dict[str, Counter[str]] = defaultdict(Counter)
    for fragment in fragments:
        occupied = registered_spans.get(fragment.fragment_id, [])
        for match in _ASCII_CANDIDATE.finditer(fragment.text):
            if match.group(0).casefold() in _IGNORED_ASCII:
                continue
            if any(match.start() >= start and match.end() <= end for start, end in occupied):
                continue
            observed = match.group(0)
            key = normalize_entity_key(observed)
            if not key:
                continue
            detected[key][fragment.fragment_id].append(observed)
            detected_display[key][observed] += 1

    candidates: list[dict[str, object]] = []
    definitions_by_key = {
        normalize_entity_key(definition.canonical_term): definition
        for definition in definitions
    }
    for key, fragment_matches in registered_matches.items():
        candidates.append(
            _candidate_payload(
                definitions_by_key[key],
                fragment_matches,
                fragment_by_id,
            )
        )
    ranked_detected = sorted(
        detected,
        key=lambda key: (
            -len(
                {
                    fragment_by_id[fragment_id].video_id
                    for fragment_id in detected[key]
                }
            ),
            -sum(len(values) for values in detected[key].values()),
            key,
        ),
    )[:MAX_DETECTED_ASCII_CANDIDATES]
    for key in ranked_detected:
        fragment_matches = detected[key]
        display = sorted(
            detected_display[key],
            key=lambda value: (-detected_display[key][value], value.casefold(), value),
        )[0]
        video_ids = {
            fragment_by_id[fragment_id].video_id for fragment_id in fragment_matches
        }
        occurrence_count = sum(len(values) for values in fragment_matches.values())
        impact: Literal["medium", "low"] = (
            "medium" if len(video_ids) >= 2 or occurrence_count >= 3 else "low"
        )
        candidates.append(
            _candidate_payload(
                EntityDefinition(
                    canonical_term=display,
                    aliases=(),
                    category="unregistered_ascii",
                    impact=impact,
                    note="Automatically detected ASCII candidate; add it to the project dictionary if material.",
                    registry_source="detected",
                ),
                fragment_matches,
                fragment_by_id,
            )
        )

    impact_rank = {"high": 0, "medium": 1, "low": 2}
    def candidate_sort_key(candidate: Mapping[str, object]) -> tuple[int, int, str]:
        raw_frequency = candidate.get("document_frequency")
        frequency = raw_frequency if isinstance(raw_frequency, int) else 0
        return (
            impact_rank[str(candidate["impact"])],
            -frequency,
            str(candidate["normalized_term"]),
        )

    candidates.sort(key=candidate_sort_key)
    known_entities = {
        str(candidate["canonical_term"]): {
            "candidate_id": candidate["candidate_id"],
            "count": candidate["occurrence_count"],
            "video_ids": candidate["representative_video_ids"],
            "impact": candidate["impact"],
            "confidence": candidate["confidence"],
            "status": candidate["status"],
        }
        for candidate in candidates
        if candidate["registry_source"] != "detected"
    }
    additional = [
        {
            "candidate_id": candidate["candidate_id"],
            "term": candidate["canonical_term"],
            "count": candidate["occurrence_count"],
            "video_ids": candidate["representative_video_ids"],
            "impact": candidate["impact"],
            "confidence": candidate["confidence"],
            "status": candidate["status"],
        }
        for candidate in candidates
        if candidate["registry_source"] == "detected"
    ]
    return {
        "schema_version": ENTITY_REVIEW_SCHEMA_VERSION,
        "algorithm_version": ENTITY_REVIEW_ALGORITHM_VERSION,
        "taxonomy": dict(taxonomy),
        "dictionary": dictionary_identity,
        "normalization": {
            "unicode": "NFKC",
            "case": "casefold",
            "separators": "whitespace/dot/underscore/hyphen/slash/middle-dot",
            "aliases": "explicit preset or project dictionary forms",
        },
        "allowed_statuses": list(ALLOWED_STATUSES),
        "review_required": bool(candidates),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "known_entities": known_entities,
        "additional_ascii_candidates": additional,
        "status_counts": {
            "unresolved": len(candidates),
            "confirmed": 0,
            "corrected": 0,
            "ignored": 0,
        },
        "correction_policy": {
            "raw_asr_immutable": True,
            "decision_layer": "research/reviews/asr_entity_decisions.json",
            "corrected_requires_final_references": True,
        },
        "note": (
            "Review registered entities and material ASCII candidates. Corrections belong "
            "in the decision layer and final Skill references, never in raw ASR files."
        ),
    }


def _decision_template(candidate_id: str) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "status": "unresolved",
        "treatment_note": "",
        "corrected_term": "",
        "final_references": [],
        "reviewed_by": "",
        "reviewed_at": "",
    }


def build_entity_decision_ledger(
    report: Mapping[str, object],
    existing: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Create or synchronize a durable decision ledger while preserving human fields."""

    raw_candidates = report.get("candidates")
    if not isinstance(raw_candidates, list):
        raise EntityReviewError("entity report candidates must be a list")
    candidate_ids = [
        str(candidate.get("candidate_id"))
        for candidate in raw_candidates
        if isinstance(candidate, Mapping) and candidate.get("candidate_id")
    ]
    if len(candidate_ids) != len(raw_candidates) or len(candidate_ids) != len(set(candidate_ids)):
        raise EntityReviewError("entity report candidate IDs must be non-empty and unique")

    preserved: dict[str, dict[str, object]] = {}
    orphaned: list[dict[str, object]] = []
    if isinstance(existing, Mapping):
        old_orphans = existing.get("orphaned_decisions")
        if isinstance(old_orphans, list):
            orphaned.extend(item for item in old_orphans if isinstance(item, dict))
        old_decisions = existing.get("decisions")
        if isinstance(old_decisions, list):
            for item in old_decisions:
                if not isinstance(item, dict):
                    continue
                candidate_id = item.get("candidate_id")
                if candidate_id in candidate_ids and candidate_id not in preserved:
                    preserved[str(candidate_id)] = dict(item)
                else:
                    orphaned.append(
                        {**item, "orphan_reason": "candidate_removed_or_duplicate"}
                    )

    decisions: list[dict[str, object]] = []
    for candidate_id in candidate_ids:
        decision = _decision_template(candidate_id)
        decision.update(preserved.get(candidate_id, {}))
        decision["candidate_id"] = candidate_id
        decisions.append(decision)
    return {
        "schema_version": ENTITY_DECISION_SCHEMA_VERSION,
        "source": {
            "algorithm_version": report.get("algorithm_version"),
            "candidate_ids": candidate_ids,
        },
        "allowed_statuses": list(ALLOWED_STATUSES),
        "decision_contract": {
            "processed_required_fields": [
                "candidate_id",
                "status",
                "treatment_note",
                "reviewed_by",
                "reviewed_at",
            ],
            "corrected_required_fields": ["corrected_term", "final_references"],
            "final_reference_contract": ["path", "locator"],
            "raw_asr_immutable": True,
        },
        "decisions": decisions,
        "orphaned_decisions": orphaned,
    }


def _valid_final_reference(
    value: object,
    *,
    run_dir: Path | None,
) -> bool:
    if not isinstance(value, Mapping):
        return False
    raw_path = value.get("path")
    locator = value.get("locator")
    if not isinstance(raw_path, str) or not raw_path.strip() or "\\" in raw_path:
        return False
    if not isinstance(locator, str) or not locator.strip():
        return False
    pure = PurePosixPath(raw_path)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts or pure.parts[0] != "skill":
        return False
    if run_dir is None:
        return True
    root = Path(run_dir).resolve()
    target = root.joinpath(*pure.parts).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return False
    return target.is_file()


def _empty_assessment(reason: str) -> dict[str, object]:
    return {
        "valid": False,
        "complete": False,
        "review_required": False,
        "candidate_count": 0,
        "processed_count": 0,
        "status_counts": {status: 0 for status in ALLOWED_STATUSES},
        "blocker_count": 1,
        "warning_count": 0,
        "blocking_reasons": [reason],
        "warnings": [],
        "decision_errors": [],
        "unresolved_high_impact_candidate_ids": [],
        "unresolved_warning_candidate_ids": [],
        "correction_mappings": [],
    }


def _valid_report_candidate(candidate: Mapping[str, object]) -> bool:
    canonical = candidate.get("canonical_term")
    normalized = candidate.get("normalized_term")
    candidate_id = candidate.get("candidate_id")
    references = candidate.get("source_references")
    video_ids = candidate.get("representative_video_ids")
    raw_asr = candidate.get("raw_asr_references")
    document_frequency = candidate.get("document_frequency")
    occurrence_count = candidate.get("occurrence_count")
    expected_confidence = (
        _entity_confidence(
            candidate.get("registry_source"),
            document_frequency,
            occurrence_count,
        )
        if isinstance(document_frequency, int)
        and not isinstance(document_frequency, bool)
        and isinstance(occurrence_count, int)
        and not isinstance(occurrence_count, bool)
        else None
    )
    return bool(
        isinstance(canonical, str)
        and canonical.strip()
        and isinstance(normalized, str)
        and normalized == normalize_entity_key(canonical)
        and candidate_id == _candidate_id(normalized)
        and candidate.get("impact") in ALLOWED_IMPACTS
        and candidate.get("status") == "unresolved"
        and candidate.get("treatment_note") == ""
        and candidate.get("registry_source") in {"preset", "project", "detected"}
        and isinstance(video_ids, list)
        and video_ids
        and all(isinstance(video_id, str) and video_id for video_id in video_ids)
        and isinstance(document_frequency, int)
        and not isinstance(document_frequency, bool)
        and document_frequency == len(video_ids)
        and isinstance(occurrence_count, int)
        and not isinstance(occurrence_count, bool)
        and occurrence_count >= document_frequency
        and candidate.get("confidence") == expected_confidence
        and isinstance(references, list)
        and references
        and all(isinstance(reference, Mapping) for reference in references)
        and isinstance(raw_asr, list)
    )


def evaluate_entity_review(
    report: object,
    ledger: object,
    *,
    run_dir: Path | None = None,
) -> dict[str, object]:
    """Validate decisions and compute blockers/warnings without trusting declarations."""

    if not isinstance(report, Mapping) or not isinstance(ledger, Mapping):
        return _empty_assessment("review_contract_invalid")
    raw_candidates = report.get("candidates")
    raw_decisions = ledger.get("decisions")
    if not isinstance(raw_candidates, list) or not isinstance(raw_decisions, list):
        return _empty_assessment("review_contract_invalid")
    candidates: list[Mapping[str, object]] = [
        item for item in raw_candidates if isinstance(item, Mapping)
    ]
    if len(candidates) != len(raw_candidates):
        return _empty_assessment("review_contract_invalid")
    candidate_ids = [str(candidate.get("candidate_id") or "") for candidate in candidates]
    source = ledger.get("source")
    computed_review_required = bool(candidates)
    contract_valid = bool(
        report.get("schema_version") == ENTITY_REVIEW_SCHEMA_VERSION
        and report.get("algorithm_version") == ENTITY_REVIEW_ALGORITHM_VERSION
        and report.get("candidate_count") == len(candidates)
        and report.get("review_required") is computed_review_required
        and len(candidate_ids) == len(set(candidate_ids))
        and all(candidate_ids)
        and all(_valid_report_candidate(candidate) for candidate in candidates)
        and ledger.get("schema_version") == ENTITY_DECISION_SCHEMA_VERSION
        and isinstance(source, Mapping)
        and source.get("algorithm_version") == report.get("algorithm_version")
        and source.get("candidate_ids") == candidate_ids
        and ledger.get("allowed_statuses") == list(ALLOWED_STATUSES)
    )
    by_id = {str(candidate["candidate_id"]): candidate for candidate in candidates}
    decision_by_id: dict[str, Mapping[str, object]] = {}
    decision_errors: list[str] = []
    for index, decision in enumerate(raw_decisions):
        if not isinstance(decision, Mapping):
            decision_errors.append(f"/decisions/{index}")
            continue
        candidate_id = str(decision.get("candidate_id") or "")
        if candidate_id not in by_id or candidate_id in decision_by_id:
            decision_errors.append(f"/decisions/{index}/candidate_id")
            continue
        decision_by_id[candidate_id] = decision
    if set(decision_by_id) != set(candidate_ids):
        decision_errors.append("/decisions")

    status_counts = {status: 0 for status in ALLOWED_STATUSES}
    high_unresolved: list[str] = []
    warning_unresolved: list[str] = []
    correction_mappings: list[dict[str, object]] = []
    processed_count = 0
    for candidate_id in candidate_ids:
        candidate = by_id[candidate_id]
        decision = decision_by_id.get(candidate_id)
        if decision is None:
            continue
        status = decision.get("status")
        if status not in ALLOWED_STATUSES:
            decision_errors.append(f"/decisions/{candidate_id}/status")
            continue
        status_counts[str(status)] += 1
        if status == "unresolved":
            if any(
                decision.get(field) not in (None, "", [])
                for field in (
                    "treatment_note",
                    "corrected_term",
                    "final_references",
                    "reviewed_by",
                    "reviewed_at",
                )
            ):
                decision_errors.append(f"/decisions/{candidate_id}/unresolved_fields")
            if candidate.get("impact") == "high":
                high_unresolved.append(candidate_id)
            else:
                warning_unresolved.append(candidate_id)
            continue
        processed_count += 1
        for field in ("treatment_note", "reviewed_by", "reviewed_at"):
            value = decision.get(field)
            if not isinstance(value, str) or not value.strip():
                decision_errors.append(f"/decisions/{candidate_id}/{field}")
        if status in {"confirmed", "ignored"} and (
            decision.get("corrected_term") not in (None, "")
            or decision.get("final_references") not in (None, [])
        ):
            decision_errors.append(
                f"/decisions/{candidate_id}/non_correction_fields"
            )
        if status == "corrected":
            corrected = decision.get("corrected_term")
            final_references = decision.get("final_references")
            if not isinstance(corrected, str) or not corrected.strip():
                decision_errors.append(f"/decisions/{candidate_id}/corrected_term")
            if not isinstance(final_references, list) or not final_references:
                decision_errors.append(f"/decisions/{candidate_id}/final_references")
                final_references = []
            elif not all(
                _valid_final_reference(reference, run_dir=run_dir)
                for reference in final_references
            ):
                decision_errors.append(f"/decisions/{candidate_id}/final_references")
            correction_mappings.append(
                {
                    "candidate_id": candidate_id,
                    "original_term": candidate.get("canonical_term"),
                    "corrected_term": corrected,
                    "source_references": candidate.get("source_references"),
                    "final_references": final_references,
                    "treatment_note": decision.get("treatment_note"),
                }
            )

    blocking_reasons: list[str] = []
    if not contract_valid:
        blocking_reasons.append("review_contract_invalid")
    if decision_errors:
        blocking_reasons.append("invalid_or_incomplete_decisions")
    if high_unresolved:
        blocking_reasons.append("unresolved_high_impact_entities")
    review_required = computed_review_required
    if review_required and processed_count == 0 and not high_unresolved:
        blocking_reasons.append("review_not_started")
    warnings = (
        ["unresolved_medium_or_low_impact_entities"] if warning_unresolved else []
    )
    blocker_count = (
        len(high_unresolved)
        + int(not contract_valid)
        + int(bool(decision_errors))
        + int(review_required and processed_count == 0 and not high_unresolved)
    )
    return {
        "valid": contract_valid and not decision_errors,
        "complete": not blocking_reasons,
        "review_required": review_required,
        "candidate_count": len(candidates),
        "processed_count": processed_count,
        "status_counts": status_counts,
        "blocker_count": blocker_count,
        "warning_count": len(warning_unresolved),
        "blocking_reasons": blocking_reasons,
        "warnings": warnings,
        "decision_errors": sorted(set(decision_errors)),
        "unresolved_high_impact_candidate_ids": high_unresolved,
        "unresolved_warning_candidate_ids": warning_unresolved,
        "correction_mappings": correction_mappings,
    }


def _markdown_data_inline(value: object) -> str:
    text = re.sub(r"\s+", " ", "" if value is None else str(value)).strip()
    return "".join(
        f"&#{ord(character)};"
        if character in _MARKDOWN_CONTROL_CHARACTERS
        else character
        for character in text
    )


def build_entity_review_markdown(report: Mapping[str, object]) -> str:
    """Render the immutable detection layer; live states remain in the decision JSON."""

    lines = [
        "# ASR Entity Review",
        "",
        "原始 ASR 只读。请在 `asr_entity_decisions.json` 记录处理状态；`corrected` 还必须回指最终 Skill。",
        "",
        "| Candidate ID | Canonical | Category | Impact | Confidence | Initial status | Videos | Source fragments |",
        "|---|---|---|---|---|---|---:|---:|",
    ]
    raw_candidates = report.get("candidates")
    candidates = raw_candidates if isinstance(raw_candidates, list) else []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        candidate_id = str(candidate.get("candidate_id") or "")
        references = candidate.get("source_references")
        video_ids = candidate.get("representative_video_ids")
        lines.append(
            "| "
            + " | ".join(
                [
                    candidate_id,
                    _markdown_data_inline(candidate.get("canonical_term")),
                    str(candidate.get("category") or ""),
                    str(candidate.get("impact") or ""),
                    str((candidate.get("confidence") or {}).get("level") or "")
                    if isinstance(candidate.get("confidence"), Mapping)
                    else "",
                    str(candidate.get("status") or "unresolved"),
                    str(len(video_ids) if isinstance(video_ids, list) else 0),
                    str(len(references) if isinstance(references, list) else 0),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Decision contract",
            "",
            "- `unresolved`：尚未处理；高影响项阻塞 ready，中低影响项保留 warning。",
            "- `confirmed`：确认原写法，填写处理说明、审查者和时间。",
            "- `corrected`：填写正确写法，并用 `final_references` 映射到最终 Skill 文件和定位符。",
            "- `ignored`：确认不影响最终内容，并说明忽略理由。",
            "- 不得直接改写 `transcripts/*.txt` 来隐藏 ASR 错误。",
            "",
        ]
    )
    return "\n".join(lines)
