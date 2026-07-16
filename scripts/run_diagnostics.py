#!/usr/bin/env python3
"""Read-only, bounded diagnosis for versioned creator pipeline runs."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


RUN_FORMAT_NAME = "thousand-faces.creator-run"
RUN_FORMAT_SCHEMA_VERSION = 1
RUN_INSPECTION_SCHEMA_VERSION = 1
SUPPORTED_FORMAT_VERSIONS = (RUN_FORMAT_SCHEMA_VERSION,)
MAX_MANIFEST_BYTES = 1_048_576
QUALITY_REPORT = "logs/creator_quality_report.json"

_MANIFEST_SCHEMAS = {
    "config.snapshot.json": "settings_schema_version",
    "workflow.plan.json": "schema_version",
    "metadata/provenance.json": "schema_version",
}


class RunFormatError(ValueError):
    """Raised when a write-capable operation targets an unverified run."""


def _issue(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}


def _read_object(root: Path, relative: str) -> tuple[str, Mapping[str, Any] | None]:
    """Read one known manifest without following it outside the run boundary."""

    path = root.joinpath(*relative.split("/"))
    if path.is_symlink():
        return "invalid", None
    if not path.exists():
        return "missing", None
    try:
        resolved_root = root.resolve(strict=True)
        resolved_path = path.resolve(strict=True)
        resolved_path.relative_to(resolved_root)
        if not path.is_file():
            return "invalid", None
        if path.stat().st_size > MAX_MANIFEST_BYTES:
            return "invalid", None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return "invalid", None
    if not isinstance(payload, Mapping):
        return "invalid", None
    return "loaded", payload


def _base_report() -> dict[str, Any]:
    return {
        "schema_version": RUN_INSPECTION_SCHEMA_VERSION,
        "format_name": None,
        "format_version": None,
        "supported_format_versions": list(SUPPORTED_FORMAT_VERSIONS),
        "format_status": "not_found",
        "format_verified": False,
        "missing_manifests": [],
        "invalid_manifests": [],
        "issues": [],
        "recommended_action": {
            "code": "CHECK_RUN_DIR",
            "command": (
                "python scripts/creator_pipeline.py inspect-run "
                "--run-dir <run-dir> --json"
            ),
            "message": "Check that the run directory exists, then inspect it again.",
        },
    }


def _action_for(status: str) -> dict[str, str]:
    inspect_command = (
        "python scripts/creator_pipeline.py inspect-run --run-dir <run-dir> --json"
    )
    if status == "legacy_unverified":
        return {
            "code": "CREATE_NEW_RUN",
            "command": (
                "python scripts/build_creator_skill.py --source-url <source-url> "
                "--project-name <project-name>"
            ),
            "message": (
                "Create a new versioned run from the original source. "
                "Do not copy or promote legacy readiness claims."
            ),
        }
    if status == "current_verified":
        return {
            "code": "RUN_QUALITY_CHECK",
            "command": (
                "python scripts/creator_pipeline.py quality-check "
                "--run-dir <run-dir> --json --report-only"
            ),
            "message": "Run the quality gate before claiming the run is ready for use.",
        }
    if status == "not_found":
        return {
            "code": "CHECK_RUN_DIR",
            "command": inspect_command,
            "message": "Check that the run directory exists, then inspect it again.",
        }
    return {
        "code": "RECREATE_OR_REPAIR_RUN",
        "command": inspect_command,
        "message": (
            "Do not use this run until its version and required manifests are supported "
            "and valid. Prefer creating a new run from the original source."
        ),
    }


def _inspect_required_manifests(root: Path, report: dict[str, Any]) -> None:
    for relative, version_key in _MANIFEST_SCHEMAS.items():
        state, payload = _read_object(root, relative)
        if state == "missing":
            report["missing_manifests"].append(relative)
            report["issues"].append(
                _issue("REQUIRED_MANIFEST_MISSING", relative, "Required manifest is missing.")
            )
            continue
        version = payload.get(version_key) if payload is not None else None
        if (
            state != "loaded"
            or not isinstance(version, int)
            or isinstance(version, bool)
            or version < 1
        ):
            report["invalid_manifests"].append(relative)
            report["issues"].append(
                _issue("REQUIRED_MANIFEST_INVALID", relative, "Required manifest is invalid.")
            )


def inspect_run_structure(run_dir: Path) -> dict[str, Any]:
    """Diagnose the run descriptor and required manifests without writing anything."""

    root = Path(run_dir)
    report = _base_report()
    if not root.is_dir():
        return report

    input_state, descriptor = _read_object(root, "input.json")
    if input_state == "missing":
        report["format_status"] = "legacy_unverified"
        report["missing_manifests"].append("input.json")
        report["issues"].append(
            _issue("RUN_DESCRIPTOR_MISSING", "input.json", "Run descriptor is missing.")
        )
        _inspect_required_manifests(root, report)
        report["missing_manifests"].sort()
        report["invalid_manifests"].sort()
        report["recommended_action"] = _action_for("legacy_unverified")
        return report
    if input_state == "invalid" or descriptor is None:
        report["format_status"] = "invalid"
        report["invalid_manifests"].append("input.json")
        report["issues"].append(
            _issue("RUN_DESCRIPTOR_INVALID", "input.json", "Run descriptor is invalid.")
        )
        _inspect_required_manifests(root, report)
        report["missing_manifests"].sort()
        report["invalid_manifests"].sort()
        report["recommended_action"] = _action_for("invalid")
        return report

    format_name = descriptor.get("run_format")
    format_version = descriptor.get("schema_version")
    report["format_name"] = format_name if isinstance(format_name, str) else None
    if isinstance(format_version, int) and not isinstance(format_version, bool):
        report["format_version"] = format_version

    if format_name is None and format_version is None:
        report["format_status"] = "legacy_unverified"
        report["issues"].append(
            _issue(
                "RUN_FORMAT_LEGACY",
                "input.json",
                "Run descriptor has no explicit format name or version.",
            )
        )
    elif format_name != RUN_FORMAT_NAME or format_version not in SUPPORTED_FORMAT_VERSIONS:
        report["format_status"] = "unsupported"
        report["issues"].append(
            _issue(
                "RUN_FORMAT_UNSUPPORTED",
                "input.json",
                "Run format name or version is unsupported.",
            )
        )
        report["recommended_action"] = _action_for("unsupported")
        return report
    else:
        report["format_status"] = "current_verified"

    _inspect_required_manifests(root, report)

    report["missing_manifests"].sort()
    report["invalid_manifests"].sort()
    if report["format_status"] == "current_verified":
        if report["invalid_manifests"]:
            report["format_status"] = "invalid"
        elif report["missing_manifests"]:
            report["format_status"] = "current_incomplete"
    report["format_verified"] = report["format_status"] == "current_verified"
    report["recommended_action"] = _action_for(report["format_status"])
    return report


def inspect_run(run_dir: Path) -> dict[str, Any]:
    """Add persisted quality status without trusting legacy or stale readiness claims."""

    root = Path(run_dir)
    report = inspect_run_structure(root)
    quality: dict[str, Any] = {
        "status": (
            "ignored_unverified"
            if not report["format_verified"] and (root / QUALITY_REPORT).exists()
            else "missing"
        ),
        "declared_ready_for_use": False,
        "format_verified": False,
    }
    ready_for_use = False
    if report["format_verified"]:
        state, quality_payload = _read_object(root, QUALITY_REPORT)
        quality["status"] = state
        if state == "loaded" and quality_payload is not None:
            quality["declared_ready_for_use"] = (
                quality_payload.get("ready_for_use") is True
            )
            quality_format = quality_payload.get("run_format")
            quality["format_verified"] = bool(
                isinstance(quality_format, Mapping)
                and quality_format.get("format_verified") is True
                and quality_format.get("format_name") == RUN_FORMAT_NAME
                and quality_format.get("format_version") == RUN_FORMAT_SCHEMA_VERSION
            )
            ready_for_use = bool(
                quality["declared_ready_for_use"] and quality["format_verified"]
            )
        elif state == "invalid":
            report["issues"].append(
                _issue(
                    "QUALITY_REPORT_INVALID",
                    QUALITY_REPORT,
                    "Persisted quality report is invalid.",
                )
            )
    report["quality"] = quality
    report["ready_for_use"] = ready_for_use
    if ready_for_use:
        report["recommended_action"] = {
            "code": "NONE",
            "command": "",
            "message": "The current format and persisted quality report are verified.",
        }
    return report


def require_current_run(run_dir: Path) -> dict[str, Any]:
    """Return structural evidence or reject before a caller can mutate the run."""

    report = inspect_run_structure(run_dir)
    if report["format_verified"]:
        return report
    raise RunFormatError(
        "RUN_FORMAT_UNVERIFIED: run format is "
        f"{report['format_status']}; inspect with: "
        "python scripts/creator_pipeline.py inspect-run --run-dir <run-dir> --json"
    )
