"""Artifact manifests must prove provenance without persisting secrets."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import artifacts


def make_spec(source: Path, *, model: str = "asr-model-a") -> artifacts.ArtifactSpec:
    return artifacts.ArtifactSpec(
        artifact_type="asr_raw_response",
        inputs=(
            artifacts.file_input(source, role="source_audio"),
            artifacts.safe_url_input(
                "https://asr.example.invalid/v1?Signature=private-signature&token=private-token",
                role="endpoint",
            ),
        ),
        config={
            "provider": "openai-compatible",
            "model": model,
            "language": "zh-CN",
            "segment_seconds": 120,
            "parser_version": "1",
        },
        producer={"name": "run_creator_skill_build", "version": "1"},
    )


def test_manifest_round_trip_is_verified_and_does_not_persist_signed_url(tmp_path: Path) -> None:
    source = tmp_path / "source.mp3"
    source.write_bytes(b"source audio")
    artifact = tmp_path / "source.result.json"
    artifact.write_text('{"text":"ok"}', encoding="utf-8")
    spec = make_spec(source)

    manifest_path = artifacts.write_artifact_manifest(artifact, spec, metadata={"http_status": 200})

    decision = artifacts.assess_artifact(artifact, spec)
    recorded_decision = artifacts.inspect_artifact(artifact)
    manifest_text = manifest_path.read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    assert decision.reusable is True
    assert decision.reason == "verified"
    assert recorded_decision.reusable is True
    assert manifest["fingerprint"] == spec.fingerprint
    assert manifest["artifact"]["sha256"] == artifacts.file_sha256(artifact)
    assert manifest["inputs"][1]["origin"] == "https://asr.example.invalid"
    assert "private-signature" not in manifest_text
    assert "private-token" not in manifest_text
    assert "Signature=" not in manifest_text


def test_config_or_artifact_content_change_invalidates_verified_cache(tmp_path: Path) -> None:
    source = tmp_path / "source.mp3"
    source.write_bytes(b"source audio")
    artifact = tmp_path / "source.result.json"
    artifact.write_text('{"text":"ok"}', encoding="utf-8")
    original = make_spec(source)
    artifacts.write_artifact_manifest(artifact, original)

    assert artifacts.assess_artifact(artifact, make_spec(source, model="asr-model-b")).reason == "fingerprint_mismatch"

    artifact.write_text('{"text":"tampered"}', encoding="utf-8")
    decision = artifacts.assess_artifact(artifact, original)
    assert decision.reusable is False
    assert decision.reason == "artifact_hash_mismatch"


@pytest.mark.parametrize(
    ("content", "expected_reason"),
    [
        (b"", "artifact_empty"),
        (b"legacy cache", "legacy_unverified"),
    ],
)
def test_empty_and_manifestless_legacy_artifacts_are_not_reused(
    tmp_path: Path,
    content: bytes,
    expected_reason: str,
) -> None:
    source = tmp_path / "source.mp3"
    source.write_bytes(b"source audio")
    artifact = tmp_path / "source.result.json"
    artifact.write_bytes(content)

    decision = artifacts.assess_artifact(artifact, make_spec(source))

    assert decision.reusable is False
    assert decision.reason == expected_reason
    assert artifacts.inspect_artifact(artifact).reason == expected_reason


def test_truncated_manifest_is_not_reused(tmp_path: Path) -> None:
    source = tmp_path / "source.mp3"
    source.write_bytes(b"source audio")
    artifact = tmp_path / "source.result.json"
    artifact.write_text('{"text":"ok"}', encoding="utf-8")
    artifacts.artifact_manifest_path(artifact).write_text('{"schema_version":', encoding="utf-8")

    decision = artifacts.assess_artifact(artifact, make_spec(source))

    assert decision.reusable is False
    assert decision.reason == "manifest_invalid"


@pytest.mark.parametrize(
    "unsafe_config",
    [
        {"api_key": "secret-value"},
        {"headers": {"Authorization": "Bearer secret-value"}},
        {"metadata": {"X-Amz-Signature": "secret-value"}},
        {"endpoint": "https://example.invalid/path?X-Amz-Signature=secret-value"},
    ],
)
def test_manifest_contract_rejects_secret_bearing_fields(unsafe_config: dict[str, object]) -> None:
    with pytest.raises(artifacts.ArtifactManifestError, match="sensitive"):
        artifacts.ArtifactSpec(
            artifact_type="unsafe",
            inputs=(),
            config=unsafe_config,
            producer={"name": "test", "version": "1"},
        )
