#!/usr/bin/env python3
"""Auditable rights, source, and retention governance for each pipeline run."""

from __future__ import annotations

import re
import json
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping

import redaction
from io_utils import atomic_write_json


PROVENANCE_SCHEMA_VERSION = 1
RIGHTS_BASES = (
    "unspecified",
    "public_research",
    "creator_authorized",
    "team_owned",
)
DECLARED_RIGHTS_BASES = frozenset(RIGHTS_BASES) - {"unspecified"}
RETENTION_POLICIES = (
    "retain_media",
    "transcripts_only",
    "final_skill_only",
)
TAKEDOWN_CONTACT_NOT_PROVIDED = "not_provided"
_REFERENCE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

USAGE_BOUNDARIES = {
    "unspecified": (
        "Draft research only. Rights are not declared; do not publish, commercially deliver, "
        "or imply creator approval."
    ),
    "public_research": (
        "Public-expression research and style assistance only; no identity impersonation, "
        "endorsement claim, or commercial delivery."
    ),
    "creator_authorized": (
        "Use only within the separately recorded creator authorization scope; authorization "
        "does not permit identity impersonation or fabricated endorsement."
    ),
    "team_owned": (
        "Use only under the owning team's policy and takedown process; do not fabricate a "
        "person's identity, approval, or private views."
    ),
}


class ProvenanceError(ValueError):
    """A governance field is unsafe, unsupported, or internally inconsistent."""


def _optional_text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _choice(name: str, value: object, allowed: tuple[str, ...], default: str) -> str:
    text = _optional_text(value) or default
    if text not in allowed:
        raise ProvenanceError(f"{name} must be one of: {', '.join(allowed)}")
    return text


def _authorization_reference_id(value: object) -> str:
    text = _optional_text(value)
    if text and not _REFERENCE_ID.fullmatch(text):
        raise ProvenanceError(
            "authorization_reference_id must be 1-128 safe ASCII identifier characters"
        )
    return text


def _authorization_note_path(value: object, *, require_exists: bool = True) -> str:
    text = _optional_text(value).replace("\\", "/")
    if not text:
        return ""
    windows = PureWindowsPath(text)
    posix = PurePosixPath(text)
    if (
        len(text) > 240
        or _CONTROL.search(text)
        or windows.drive
        or windows.root
        or posix.is_absolute()
        or any(part in {"", ".", ".."} for part in posix.parts)
    ):
        raise ProvenanceError(
            "authorization_note_path must be a safe relative local file path"
        )
    if require_exists and not Path(text).is_file():
        raise ProvenanceError("authorization_note_path must reference an existing local file")
    return posix.as_posix()


def _takedown_contact(value: object) -> str:
    text = _optional_text(value) or TAKEDOWN_CONTACT_NOT_PROVIDED
    if len(text) > 200 or _CONTROL.search(text):
        raise ProvenanceError(
            "takedown_contact must be a single-line value of at most 200 characters"
        )
    return text


def build_run_record(
    args: object,
    *,
    source_platform: str,
    source_collected_at: str,
) -> dict[str, Any]:
    """Validate CLI governance input and return the canonical secret-free record."""
    rights_basis = _choice(
        "rights_basis",
        getattr(args, "rights_basis", None),
        RIGHTS_BASES,
        "unspecified",
    )
    retention_policy = _choice(
        "retention_policy",
        getattr(args, "retention_policy", None),
        RETENTION_POLICIES,
        "retain_media",
    )
    authorization = {
        "reference_id": _authorization_reference_id(
            getattr(args, "authorization_reference_id", None)
        ),
        "note_path": _authorization_note_path(
            getattr(args, "authorization_note_path", None)
        ),
    }
    takedown_contact = _takedown_contact(getattr(args, "takedown_contact", None))
    rights_declared = rights_basis in DECLARED_RIGHTS_BASES
    authorization_referenced = bool(
        authorization["reference_id"] or authorization["note_path"]
    )
    contact_provided = takedown_contact != TAKEDOWN_CONTACT_NOT_PROVIDED
    commercial_eligible = contact_provided and (
        rights_basis == "team_owned"
        or (rights_basis == "creator_authorized" and authorization_referenced)
    )
    return {
        "schema_version": PROVENANCE_SCHEMA_VERSION,
        "source_platform": source_platform,
        "source_url": redaction.redact_url(getattr(args, "source_url", "")),
        "source_collected_at": source_collected_at,
        "rights_basis": rights_basis,
        "rights_declared": rights_declared,
        "authorization": authorization,
        "retention_policy": retention_policy,
        "takedown_contact": takedown_contact,
        "usage_boundary": USAGE_BOUNDARIES[rights_basis],
        "commercial_delivery_eligible": commercial_eligible,
    }


def input_fields(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return canonical governance fields intended for top-level input.json."""
    return {
        key: record[key]
        for key in (
            "source_platform",
            "source_url",
            "source_collected_at",
            "rights_basis",
            "authorization",
            "retention_policy",
            "takedown_contact",
            "usage_boundary",
        )
    }


def write_run_manifest(run_dir: Path, record: Mapping[str, Any]) -> Path:
    path = Path(run_dir) / "metadata" / "provenance.json"
    atomic_write_json(path, dict(record))
    return path


def _record_from_values(
    *,
    source_platform: object,
    source_url: object,
    source_collected_at: object,
    rights_basis: object,
    authorization: object,
    retention_policy: object,
    takedown_contact: object,
) -> dict[str, Any]:
    platform = _optional_text(source_platform)
    if not re.fullmatch(r"[a-z][a-z0-9_-]{1,31}", platform):
        raise ProvenanceError("source_platform must be a safe lowercase platform identifier")
    collected_at = _optional_text(source_collected_at)
    try:
        parsed_time = datetime.fromisoformat(collected_at)
    except ValueError as error:
        raise ProvenanceError("source_collected_at must be an ISO-8601 timestamp") from error
    if parsed_time.tzinfo is None:
        raise ProvenanceError("source_collected_at must include a timezone")
    basis = _choice("rights_basis", rights_basis, RIGHTS_BASES, "unspecified")
    policy = _choice(
        "retention_policy",
        retention_policy,
        RETENTION_POLICIES,
        "retain_media",
    )
    authorization_data = authorization if isinstance(authorization, Mapping) else {}
    normalized_authorization = {
        "reference_id": _authorization_reference_id(
            authorization_data.get("reference_id")
        ),
        "note_path": _authorization_note_path(
            authorization_data.get("note_path"),
            require_exists=False,
        ),
    }
    contact = _takedown_contact(takedown_contact)
    rights_declared = basis in DECLARED_RIGHTS_BASES
    authorization_referenced = bool(
        normalized_authorization["reference_id"]
        or normalized_authorization["note_path"]
    )
    contact_provided = contact != TAKEDOWN_CONTACT_NOT_PROVIDED
    return {
        "schema_version": PROVENANCE_SCHEMA_VERSION,
        "source_platform": platform,
        "source_url": redaction.redact_url(source_url) if source_url else "",
        "source_collected_at": parsed_time.isoformat(),
        "rights_basis": basis,
        "rights_declared": rights_declared,
        "authorization": normalized_authorization,
        "retention_policy": policy,
        "takedown_contact": contact,
        "usage_boundary": USAGE_BOUNDARIES[basis],
        "commercial_delivery_eligible": contact_provided
        and (
            basis == "team_owned"
            or (basis == "creator_authorized" and authorization_referenced)
        ),
    }


def record_from_input(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Revalidate a persisted input record before copying it into a product."""
    return _record_from_values(
        source_platform=payload.get("source_platform") or payload.get("platform"),
        source_url=payload.get("source_url"),
        source_collected_at=payload.get("source_collected_at") or payload.get("created_at"),
        rights_basis=payload.get("rights_basis"),
        authorization=payload.get("authorization"),
        retention_policy=payload.get("retention_policy"),
        takedown_contact=payload.get("takedown_contact"),
    )


def record_for_skill(run_dir: Path, *, fallback_time: str | None = None) -> dict[str, Any]:
    """Load canonical governance, falling back to a non-ready legacy boundary."""
    input_path = Path(run_dir) / "input.json"
    if input_path.is_file():
        try:
            payload = json.loads(input_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ProvenanceError("input.json is unreadable for provenance") from error
        if not isinstance(payload, Mapping):
            raise ProvenanceError("input.json must contain an object")
        return record_from_input(payload)
    return _record_from_values(
        source_platform="unknown",
        source_url="",
        source_collected_at=fallback_time or datetime.now(timezone.utc).isoformat(),
        rights_basis="unspecified",
        authorization={},
        retention_policy="retain_media",
        takedown_contact=TAKEDOWN_CONTACT_NOT_PROVIDED,
    )


def skill_meta_fields(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: record[key]
        for key in (
            "source_platform",
            "source_url",
            "source_collected_at",
            "rights_basis",
            "authorization",
            "retention_policy",
            "takedown_contact",
            "usage_boundary",
        )
    }


_MARKDOWN_CONTROL = frozenset("\\|[]()`<>#:&!*_~{}")


def markdown_inline(value: object) -> str:
    """Render a governance scalar without active Markdown or HTML syntax."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return "".join(
        f"&#{ord(character)};" if character in _MARKDOWN_CONTROL else character
        for character in text
    )


def _read_object(path: Path) -> Mapping[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, Mapping) else None


def _matching_fields(
    expected: Mapping[str, Any] | None,
    actual: Mapping[str, Any] | None,
    fields: tuple[str, ...],
) -> bool:
    return expected is not None and actual is not None and all(
        actual.get(field) == expected.get(field) for field in fields
    )


def evaluate_run_governance(run_dir: Path) -> dict[str, Any]:
    """Cross-check run input, provenance manifest, and shipped skill metadata."""
    root = Path(run_dir)
    input_payload = _read_object(root / "input.json")
    manifest = _read_object(root / "metadata" / "provenance.json")
    meta = _read_object(root / "skill" / "references" / "meta.json")
    record: dict[str, Any] | None = None
    if input_payload is not None:
        try:
            record = record_from_input(input_payload)
        except ProvenanceError:
            record = None

    manifest_fields = (
        "schema_version",
        "source_platform",
        "source_url",
        "source_collected_at",
        "rights_basis",
        "rights_declared",
        "authorization",
        "retention_policy",
        "takedown_contact",
        "usage_boundary",
        "commercial_delivery_eligible",
    )
    meta_fields = (
        "source_platform",
        "source_url",
        "source_collected_at",
        "rights_basis",
        "authorization",
        "retention_policy",
        "takedown_contact",
        "usage_boundary",
    )
    basis = str(record.get("rights_basis")) if record else "unspecified"
    authorization = record.get("authorization") if record else {}
    authorization_referenced = isinstance(authorization, Mapping) and bool(
        authorization.get("reference_id") or authorization.get("note_path")
    )
    authorization_sufficient = basis != "creator_authorized" or authorization_referenced
    skill_path = root / "skill" / "SKILL.md"
    skill_text = (
        skill_path.read_text(encoding="utf-8", errors="replace")
        if skill_path.is_file()
        else ""
    )
    skill_boundary_present = bool(
        record
        and "## 来源与使用边界" in skill_text
        and f"`{basis}`" in skill_text
        and markdown_inline(record.get("takedown_contact")) in skill_text
    )
    checks = {
        "input_present_and_valid": record is not None,
        "provenance_manifest_present": manifest is not None,
        "skill_meta_present": meta is not None,
        "rights_basis_declared": bool(record and record.get("rights_declared")),
        "takedown_contact_provided": bool(
            record
            and record.get("takedown_contact") != TAKEDOWN_CONTACT_NOT_PROVIDED
        ),
        "authorization_reference_if_required": authorization_sufficient,
        "source_boundary_present": bool(
            record
            and record.get("source_platform")
            and record.get("source_collected_at")
            and record.get("usage_boundary")
        ),
        "input_manifest_consistent": _matching_fields(
            record,
            manifest,
            manifest_fields,
        ),
        "input_meta_consistent": _matching_fields(record, meta, meta_fields),
        "skill_usage_boundary_present": skill_boundary_present,
    }
    ready_for_use = all(checks.values())
    commercial_delivery_ready = bool(
        ready_for_use and record and record.get("commercial_delivery_eligible")
    )
    return {
        "rights_basis": basis,
        "retention_policy": (
            str(record.get("retention_policy")) if record else "retain_media"
        ),
        "usage_boundary": str(record.get("usage_boundary")) if record else "",
        "checks": checks,
        "ready_for_use": ready_for_use,
        "commercial_delivery_ready": commercial_delivery_ready,
        "note": (
            "unspecified rights or missing governance references may be used only for draft "
            "research; ready and commercial delivery require consistent provenance, a "
            "takedown contact, and the applicable authorization reference."
        ),
    }
