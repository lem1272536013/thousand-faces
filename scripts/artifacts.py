#!/usr/bin/env python3
"""Content-addressed artifact manifests for safe pipeline cache reuse."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

from io_utils import atomic_write_json


ARTIFACT_SCHEMA_VERSION = 1
_SENSITIVE_KEY = re.compile(
    r"(?:^|_)(?:api_?key|access_?key|authorization|cookie|credential|password|secret|session|signature|signed_?url|token)(?:$|_)",
    re.IGNORECASE,
)
_SENSITIVE_VALUE = re.compile(r"(?:authorization\s*:|bearer\s+[a-z0-9._~+/=-]+)", re.IGNORECASE)


class ArtifactManifestError(ValueError):
    """Raised when a manifest contract could disclose secrets or is malformed."""


def _validate_safe_json(value: Any, path: str) -> None:
    if value is None or isinstance(value, (bool, int, float)):
        return
    if isinstance(value, str):
        if _SENSITIVE_VALUE.search(value):
            raise ArtifactManifestError(f"sensitive value is not allowed at {path}")
        parsed = urlsplit(value)
        if parsed.scheme.lower() in {"http", "https"} and parsed.query:
            raise ArtifactManifestError(f"sensitive URL query is not allowed at {path}")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ArtifactManifestError(f"manifest key must be a string at {path}")
            normalized_key = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
            if _SENSITIVE_KEY.search(normalized_key):
                raise ArtifactManifestError(f"sensitive key is not allowed at {path}.{key}")
            _validate_safe_json(child, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _validate_safe_json(child, f"{path}[{index}]")
        return
    raise ArtifactManifestError(f"unsupported manifest value at {path}: {type(value).__name__}")


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    """Return the SHA-256 digest of a file without loading it all into memory."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_input(path: Path, *, role: str) -> dict[str, Any]:
    """Build a non-secret input identity from a local file's content."""

    source = Path(path)
    if not source.is_file():
        raise ArtifactManifestError(f"artifact input is not a file: {source}")
    return {
        "role": role,
        "name": source.name,
        "sha256": file_sha256(source),
        "size_bytes": source.stat().st_size,
    }


def safe_url_input(raw_url: str, *, role: str) -> dict[str, Any]:
    """Hash a URL while retaining only its non-query origin for diagnostics."""

    parsed = urlsplit(raw_url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ArtifactManifestError(f"{role} must be an absolute HTTP(S) URL")
    try:
        port = parsed.port
    except ValueError as error:
        raise ArtifactManifestError(f"{role} contains an invalid port") from error
    host = parsed.hostname.lower()
    origin = f"{parsed.scheme.lower()}://{host}"
    if port is not None:
        origin = f"{origin}:{port}"
    return {"role": role, "sha256": _sha256_text(raw_url), "origin": origin}


@dataclass(frozen=True)
class ArtifactSpec:
    """Expected provenance for one artifact, excluding the artifact's own digest."""

    artifact_type: str
    inputs: Sequence[Mapping[str, Any]]
    config: Mapping[str, Any]
    producer: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.artifact_type or not re.fullmatch(r"[a-z][a-z0-9_]*", self.artifact_type):
            raise ArtifactManifestError("artifact_type must use lowercase snake_case")
        _validate_safe_json(self.inputs, "inputs")
        _validate_safe_json(self.config, "config")
        _validate_safe_json(self.producer, "producer")

    def contract(self) -> dict[str, Any]:
        """Return the canonical, secret-free fields covered by the fingerprint."""

        return {
            "artifact_type": self.artifact_type,
            "inputs": [dict(item) for item in self.inputs],
            "config": dict(self.config),
            "producer": dict(self.producer),
        }

    @property
    def fingerprint(self) -> str:
        return _sha256_text(_canonical_json(self.contract()))


@dataclass(frozen=True)
class ArtifactDecision:
    """Machine-readable explanation of whether a cache entry is reusable."""

    reusable: bool
    reason: str
    manifest_path: Path


def artifact_manifest_path(artifact_path: Path) -> Path:
    artifact = Path(artifact_path)
    return artifact.with_name(f"{artifact.name}.manifest.json")


def write_artifact_manifest(
    artifact_path: Path,
    spec: ArtifactSpec,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> Path:
    """Atomically write a complete sidecar for a non-empty artifact."""

    artifact = Path(artifact_path)
    if not artifact.is_file() or artifact.stat().st_size <= 0:
        raise ArtifactManifestError(f"cannot certify missing or empty artifact: {artifact}")
    safe_metadata = dict(metadata or {})
    _validate_safe_json(safe_metadata, "metadata")
    manifest_path = artifact_manifest_path(artifact)
    atomic_write_json(
        manifest_path,
        {
            "schema_version": ARTIFACT_SCHEMA_VERSION,
            "status": "complete",
            **spec.contract(),
            "fingerprint": spec.fingerprint,
            "artifact": {
                "name": artifact.name,
                "sha256": file_sha256(artifact),
                "size_bytes": artifact.stat().st_size,
            },
            "metadata": safe_metadata,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return manifest_path


def _inspect_recorded_artifact(artifact_path: Path) -> tuple[ArtifactDecision, dict[str, Any] | None]:
    artifact = Path(artifact_path)
    manifest_path = artifact_manifest_path(artifact)
    if not artifact.is_file():
        return ArtifactDecision(False, "artifact_missing", manifest_path), None
    if artifact.stat().st_size <= 0:
        return ArtifactDecision(False, "artifact_empty", manifest_path), None
    if not manifest_path.is_file():
        return ArtifactDecision(False, "legacy_unverified", manifest_path), None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return ArtifactDecision(False, "manifest_invalid", manifest_path), None
    if not isinstance(manifest, dict):
        return ArtifactDecision(False, "manifest_invalid", manifest_path), None
    try:
        _validate_safe_json(manifest, "manifest")
    except ArtifactManifestError:
        return ArtifactDecision(False, "manifest_unsafe", manifest_path), None
    if manifest.get("schema_version") != ARTIFACT_SCHEMA_VERSION or manifest.get("status") != "complete":
        return ArtifactDecision(False, "manifest_invalid", manifest_path), None
    try:
        recorded_spec = ArtifactSpec(
            artifact_type=manifest["artifact_type"],
            inputs=manifest["inputs"],
            config=manifest["config"],
            producer=manifest["producer"],
        )
    except (ArtifactManifestError, KeyError, TypeError):
        return ArtifactDecision(False, "manifest_invalid", manifest_path), None
    if manifest.get("fingerprint") != recorded_spec.fingerprint:
        return ArtifactDecision(False, "manifest_contract_mismatch", manifest_path), None
    recorded_artifact = manifest.get("artifact")
    if not isinstance(recorded_artifact, dict):
        return ArtifactDecision(False, "manifest_invalid", manifest_path), None
    if recorded_artifact.get("name") != artifact.name:
        return ArtifactDecision(False, "manifest_artifact_mismatch", manifest_path), None
    if recorded_artifact.get("sha256") != file_sha256(artifact):
        return ArtifactDecision(False, "artifact_hash_mismatch", manifest_path), None
    if recorded_artifact.get("size_bytes") != artifact.stat().st_size:
        return ArtifactDecision(False, "artifact_size_mismatch", manifest_path), None
    return ArtifactDecision(True, "verified", manifest_path), manifest


def inspect_artifact(artifact_path: Path) -> ArtifactDecision:
    """Validate a recorded manifest and artifact without reconstructing its expected inputs."""

    decision, _ = _inspect_recorded_artifact(artifact_path)
    return decision


def assess_artifact(artifact_path: Path, spec: ArtifactSpec) -> ArtifactDecision:
    """Validate the sidecar, expected provenance, and current artifact contents."""

    decision, manifest = _inspect_recorded_artifact(artifact_path)
    if not decision.reusable or manifest is None:
        return decision
    if manifest.get("artifact_type") != spec.artifact_type or manifest.get("fingerprint") != spec.fingerprint:
        return ArtifactDecision(False, "fingerprint_mismatch", decision.manifest_path)
    contract = spec.contract()
    if any(manifest.get(key) != value for key, value in contract.items()):
        return ArtifactDecision(False, "manifest_contract_mismatch", decision.manifest_path)
    return decision
