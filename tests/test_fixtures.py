"""Contracts for the synthetic regression fixture matrix."""

from __future__ import annotations

import json
import os
import re
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest


PROVIDER_ENV_KEYS = {
    "ALI_ASR_API_KEY",
    "ALI_ASR_ENDPOINT",
    "ALI_OSS_ACCESS_KEY_ID",
    "ALI_OSS_ACCESS_KEY_SECRET",
    "DASHSCOPE_API_KEY",
    "DASHSCOPE_BASE_HTTP_API_URL",
    "TIKHUB_API_BASE",
    "TIKHUB_API_KEY",
}

REQUIRED_SCENARIOS = {
    "tikhub": {
        "single_page",
        "multi_page",
        "duplicate_videos",
        "field_variants",
        "empty_list",
        "anomalous_stats",
    },
    "asr": {
        "compatible_chat_completions",
        "audio_transcriptions",
        "dashscope_segments",
        "nested_duplicate_nodes",
        "legal_repeat",
        "start_zero",
        "out_of_order",
        "no_timestamp",
        "empty_text",
        "long_text",
    },
    "corpus": {"tech", "food", "legal", "parenting"},
    "security": {
        "malicious_urls",
        "path_traversal_ids",
        "prompt_injection",
        "forged_evidence_ids",
    },
    "run": {"legacy_v0"},
}

SECRET_PATTERNS = {
    "OpenAI-style key": re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    "private key": re.compile(r"BEGIN [A-Z ]*PRIVATE KEY"),
    "authorization bearer": re.compile(r"Bearer\s+[A-Za-z0-9._-]{16,}", re.IGNORECASE),
    "AWS access key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "signed URL": re.compile(r"(?:X-Amz-Signature|Signature|OSSAccessKeyId)=[^\s&]+", re.IGNORECASE),
}


class OfflineAccessError(AssertionError):
    """Raised when a fixture contract test attempts external access."""


@pytest.fixture(autouse=True)
def offline_without_provider_config(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Prove fixture validation needs neither provider settings nor network access."""

    for key in PROVIDER_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    def deny_network(*_args: object, **_kwargs: object) -> None:
        raise OfflineAccessError("fixture tests must not access the network")

    original_path_open = Path.open

    def deny_dotenv(path: Path, *args: Any, **kwargs: Any) -> Any:
        if path.name == ".env" or path.name.startswith(".env."):
            raise OfflineAccessError("fixture tests must not read .env files")
        return original_path_open(path, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", deny_network)
    monkeypatch.setattr(socket.socket, "connect", deny_network)
    monkeypatch.setattr(Path, "open", deny_dotenv)
    yield


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def fixture_manifest(
    fixture_root: Path,
    offline_without_provider_config: None,
) -> dict[str, Any]:
    payload = read_json(fixture_root / "manifest.json")
    assert isinstance(payload, dict)
    return payload


def entry_by_id(fixture_manifest: dict[str, Any], fixture_id: str) -> dict[str, Any]:
    return next(entry for entry in fixture_manifest["fixtures"] if entry["id"] == fixture_id)


def test_manifest_declares_complete_synthetic_matrix(fixture_manifest: dict[str, Any]) -> None:
    assert fixture_manifest["schema_version"] == 1
    assert fixture_manifest["policy"] == {
        "synthetic_only": True,
        "credentials_allowed": False,
        "external_network_allowed": False,
        "signed_urls_allowed": False,
    }

    fixtures = fixture_manifest["fixtures"]
    assert fixtures
    assert len({entry["id"] for entry in fixtures}) == len(fixtures)
    assert all(entry.get("description") and entry.get("synthetic") is True for entry in fixtures)

    declared_by_category: dict[str, set[str]] = {}
    for entry in fixtures:
        declared_by_category.setdefault(entry["category"], set()).update(entry["scenarios"])
    assert declared_by_category.keys() == REQUIRED_SCENARIOS.keys()
    for category, required in REQUIRED_SCENARIOS.items():
        assert required <= declared_by_category[category]


def test_manifest_paths_are_confined_small_and_parseable(
    fixture_root: Path,
    fixture_manifest: dict[str, Any],
) -> None:
    root = fixture_root.resolve()
    allowed_suffixes = {".json", ".md", ".txt"}
    declared_paths: set[str] = set()

    for entry in fixture_manifest["fixtures"]:
        for relative_text in entry["paths"]:
            relative = Path(relative_text)
            assert not relative.is_absolute()
            assert ".." not in relative.parts
            assert relative_text not in declared_paths
            declared_paths.add(relative_text)

            path = (fixture_root / relative).resolve()
            assert path.is_relative_to(root)
            assert path.is_file()
            assert path.suffix.lower() in allowed_suffixes
            assert 0 < path.stat().st_size <= 32_768
            if path.suffix.lower() == ".json":
                read_json(path)

    actual_paths = {
        path.relative_to(fixture_root).as_posix()
        for path in fixture_root.rglob("*")
        if path.is_file()
    }
    assert actual_paths == declared_paths | {"README.md", "manifest.json"}


def test_tikhub_fixtures_encode_provider_variants(
    fixture_root: Path,
    fixture_manifest: dict[str, Any],
) -> None:
    single = read_json(fixture_root / entry_by_id(fixture_manifest, "tikhub-single-page")["paths"][0])
    multi = read_json(fixture_root / entry_by_id(fixture_manifest, "tikhub-multi-page")["paths"][0])
    duplicates = read_json(fixture_root / entry_by_id(fixture_manifest, "tikhub-duplicates")["paths"][0])
    variants = read_json(fixture_root / entry_by_id(fixture_manifest, "tikhub-field-variants")["paths"][0])
    empty = read_json(fixture_root / entry_by_id(fixture_manifest, "tikhub-empty-list")["paths"][0])
    anomalous = read_json(fixture_root / entry_by_id(fixture_manifest, "tikhub-anomalous-stats")["paths"][0])

    assert len(single["data"]["aweme_list"]) == 2
    assert len(multi["pages"]) == 2
    assert multi["pages"][0]["data"]["has_more"] is True
    duplicate_ids = [item["aweme_id"] for item in duplicates["data"]["aweme_list"]]
    assert len(duplicate_ids) > len(set(duplicate_ids))
    assert {"videos", "items", "list"} <= set(variants)
    assert empty["data"]["aweme_list"] == []
    stats = anomalous["data"]["aweme_list"][0]["statistics"]
    assert any(value is None or not isinstance(value, int) or value < 0 for value in stats.values())


def test_asr_fixtures_encode_provider_and_transcript_edges(
    fixture_root: Path,
    fixture_manifest: dict[str, Any],
) -> None:
    compatible = read_json(fixture_root / entry_by_id(fixture_manifest, "asr-compatible-chat")["paths"][0])
    transcriptions = read_json(
        fixture_root / entry_by_id(fixture_manifest, "asr-audio-transcriptions")["paths"][0]
    )
    dashscope = read_json(fixture_root / entry_by_id(fixture_manifest, "asr-dashscope")["paths"][0])
    nested = read_json(fixture_root / entry_by_id(fixture_manifest, "asr-nested-duplicates")["paths"][0])
    edges = read_json(fixture_root / entry_by_id(fixture_manifest, "asr-transcript-edges")["paths"][0])

    assert compatible["choices"][0]["message"]["content"]
    assert len(transcriptions["segments"]) == 2
    assert len(dashscope["transcripts"][0]["sentences"]) == 2
    assert nested["payload"]["segments"] == nested["payload"]["result"]["segments"]

    cases = {case["case_id"]: case for case in edges["cases"]}
    assert cases.keys() == {"legal_repeat", "start_zero", "out_of_order", "no_timestamp", "empty_text", "long_text"}
    repeated = cases["legal_repeat"]["segments"]
    assert repeated[0]["text"] == repeated[1]["text"] and repeated[0]["start"] != repeated[1]["start"]
    assert cases["start_zero"]["segments"][0]["start"] == 0
    starts = [segment["start"] for segment in cases["out_of_order"]["segments"]]
    assert starts != sorted(starts)
    assert "start" not in cases["no_timestamp"]["segments"][0]
    assert cases["empty_text"]["segments"][0]["text"] == ""
    assert len(cases["long_text"]["segments"][0]["text"]) >= 5_000


@pytest.mark.parametrize("domain", ["tech", "food", "legal", "parenting"])
def test_cross_domain_corpus_has_metadata_and_matching_transcript(
    fixture_root: Path,
    fixture_manifest: dict[str, Any],
    domain: str,
) -> None:
    entry = entry_by_id(fixture_manifest, f"corpus-{domain}")
    metadata_path = fixture_root / next(path for path in entry["paths"] if path.endswith("metadata.json"))
    transcript_paths = [
        fixture_root / path for path in entry["paths"] if path.endswith(".txt")
    ]
    metadata = read_json(metadata_path)
    items = metadata["data"]["aweme_list"]

    assert {item["aweme_id"] for item in items} == {
        transcript_path.stem for transcript_path in transcript_paths
    }
    assert all(len(item["desc"]) >= 8 for item in items)
    assert all(
        len(transcript_path.read_text(encoding="utf-8")) >= 80
        for transcript_path in transcript_paths
    )
    assert all(domain in item["fixture_domain"] for item in items)


def test_security_fixtures_are_adversarial_but_inert(
    fixture_root: Path,
    fixture_manifest: dict[str, Any],
) -> None:
    urls = read_json(fixture_root / entry_by_id(fixture_manifest, "security-malicious-urls")["paths"][0])
    ids = read_json(fixture_root / entry_by_id(fixture_manifest, "security-path-ids")["paths"][0])
    injection_path = fixture_root / entry_by_id(fixture_manifest, "security-prompt-injection")["paths"][0]
    forged = read_json(fixture_root / entry_by_id(fixture_manifest, "security-forged-evidence")["paths"][0])

    assert {case["reason"] for case in urls["cases"]} >= {"loopback", "private_ip", "cloud_metadata", "non_http"}
    assert any(".." in value or "/" in value or "\\" in value for value in ids["ids"])
    injection = injection_path.read_text(encoding="utf-8")
    assert "UNTRUSTED SYNTHETIC TRANSCRIPT" in injection
    assert "忽略之前" in injection and ".env" in injection
    assert not set(forged["claimed_evidence_ids"]) <= set(forged["corpus_video_ids"])


def test_fixture_tree_contains_no_secret_or_signed_url(fixture_root: Path) -> None:
    for path in fixture_root.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for label, pattern in SECRET_PATTERNS.items():
            assert not pattern.search(text), f"{label} found in {path.relative_to(fixture_root)}"


def test_offline_guard_removed_provider_environment() -> None:
    assert PROVIDER_ENV_KEYS.isdisjoint(os.environ)
    with pytest.raises(OfflineAccessError, match="must not access the network"):
        socket.create_connection(("example.invalid", 443))
