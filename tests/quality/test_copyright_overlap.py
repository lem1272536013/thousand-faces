"""Copyright overlap must be measured against current transcripts."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import content_safety
import creator_pipeline
import run_diagnostics


def source_transcript(segment_count: int = 80) -> str:
    return "".join(
        f"第{index:03d}段讨论独特实验现象与机制边界，并记录不同条件下的观察结果。"
        for index in range(segment_count)
    )


def split_every(text: str, width: int) -> str:
    return "\n".join(text[index : index + width] for index in range(0, len(text), width))


def analyze(
    target: str,
    transcript: str,
    *,
    target_path: str = "skill/references/persona.md",
    evidence_summary: bool = False,
) -> dict[str, Any]:
    return content_safety.analyze_copyright_overlap(
        {target_path: target},
        {"transcripts/video-001.txt": transcript},
        evidence_summary_paths={target_path} if evidence_summary else set(),
    )


def seed_quality_run(run_dir: Path, *, copied_text: str, transcript: str) -> None:
    refs = run_dir / "skill" / "references"
    metadata = run_dir / "metadata"
    merged = run_dir / "research" / "merged"
    transcripts = run_dir / "transcripts"
    for directory in (refs, metadata, merged, transcripts):
        directory.mkdir(parents=True, exist_ok=True)
    (run_dir / "input.json").write_text(
        json.dumps(
            {
                "run_format": run_diagnostics.RUN_FORMAT_NAME,
                "schema_version": run_diagnostics.RUN_FORMAT_SCHEMA_VERSION,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "config.snapshot.json").write_text(
        '{"settings_schema_version": 2}\n', encoding="utf-8"
    )
    (run_dir / "workflow.plan.json").write_text(
        '{"schema_version": 1}\n', encoding="utf-8"
    )
    (metadata / "provenance.json").write_text(
        '{"schema_version": 1}\n', encoding="utf-8"
    )

    (run_dir / "skill" / "SKILL.md").write_text(
        "# Skill\n\n免责声明：不代表创作者本人。安全边界：不得冒充或克隆。\n",
        encoding="utf-8",
    )
    documents = {
        "persona.md": "# Persona\n\n" + copied_text,
        "topic_model.md": "# Topic Model\n\n基于证据选择主题。\n",
        "script_style.md": "# Script Style\n\n先说明现象，再解释机制和边界。\n",
        "research_summary.md": "# Research Summary\n\n研究摘要使用改写结论。\n",
        "evidence_index.md": (
            "# Evidence\n\n| Video ID | Finding |\n|---|---|\n"
            "| 190000000000000501 | evidence |\n"
        ),
    }
    for name, text in documents.items():
        (refs / name).write_text(text, encoding="utf-8")
    (refs / "meta.json").write_text("{}\n", encoding="utf-8")
    for path in (
        metadata / "selected.json",
        metadata / "selected.compact.json",
        metadata / "creator_profile.json",
    ):
        path.write_text("{}\n", encoding="utf-8")
    (merged / "summary.md").write_text(
        "# Summary\n\nSynthetic research summary.\n",
        encoding="utf-8",
    )
    (transcripts / "video-001.txt").write_text(transcript, encoding="utf-8")


def force_non_text_gates_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        creator_pipeline.quality_engine,
        "evaluate_refinement_freshness",
        lambda *_args, **_kwargs: {
            "computed_from": {},
            "freshness": {
                "fresh": True,
                "stale_artifacts": [],
                "artifacts": {},
                "current": {},
                "repair_command": "",
            },
        },
    )
    monkeypatch.setattr(
        creator_pipeline,
        "creator_content_readiness",
        lambda *_args, **_kwargs: {
            "ready_for_use": True,
            "checks": {},
            "schema_validation": {
                name: {"valid": True, "errors": []}
                for name in (
                    "persona_model",
                    "evaluation_suite",
                    "reverse_identification",
                )
            },
            "evidence_integrity": {"valid": True, "checks": {}, "counts": {}},
            "evaluator_verdict": {"passed": True, "failed_blockers": []},
            "advisory_checks": {},
        },
    )
    monkeypatch.setattr(
        creator_pipeline,
        "evaluate_stage_coverage",
        lambda *_args, **_kwargs: {
            "draft": {"passed": True},
            "ready": {"passed": True, "failed_stages": []},
        },
    )
    monkeypatch.setattr(
        creator_pipeline.provenance,
        "evaluate_run_governance",
        lambda *_args, **_kwargs: {
            "ready_for_use": True,
            "commercial_delivery_ready": True,
            "checks": {},
        },
    )


def test_copy_split_into_100_character_lines_is_still_blocked() -> None:
    transcript = source_transcript()
    target = split_every(transcript, 100)

    report = analyze(target, transcript)
    result = report["files"][0]

    assert report["passed"] is False
    assert result["passed"] is False
    assert result["longest_overlap_chars"] >= 1000
    assert result["copied_ratio"] >= 0.95
    assert result["match_fingerprint"]


def test_short_quote_and_paraphrased_summary_are_allowed() -> None:
    transcript = source_transcript()
    short_quote = transcript[120:175]
    target = (
        "# 判断\n\n"
        f"短引用：{short_quote}\n\n"
        "改写摘要：样本反复先展示条件差异，再解释机制，并在证据不足时保留边界。"
    )

    report = analyze(target, transcript)

    assert report["passed"] is True
    assert report["files"][0]["longest_overlap_chars"] < 80


def test_short_transcript_is_available_but_cannot_form_a_long_copy() -> None:
    transcript = "短转写只包含一个可引用结论。"

    report = analyze("改写后的简短总结。", transcript)

    assert report["passed"] is True
    assert report["checks"]["transcript_corpus_available"] is True
    assert report["configuration"]["ngram_chars"] > len(
        content_safety.normalize_for_overlap(transcript)
    )


def test_evidence_summary_uses_a_more_permissive_overlap_threshold() -> None:
    transcript = source_transcript()
    copied = transcript[200:500]
    paraphrase = "研究者以重新组织的语言概括实验、限制和适用条件。" * 20
    target = copied + paraphrase

    general = analyze(target, transcript)
    evidence = analyze(
        target,
        transcript,
        target_path="skill/references/evidence_index.md",
        evidence_summary=True,
    )

    assert general["passed"] is False
    assert evidence["passed"] is True
    assert (
        evidence["thresholds"]["evidence_summary"]["max_longest_overlap_chars"]
        > evidence["thresholds"]["general"]["max_longest_overlap_chars"]
    )


def test_unrelated_long_markdown_code_block_is_not_a_copyright_failure() -> None:
    transcript = source_transcript()
    code = "result = pipeline.transform(record)  # deterministic operation\n" * 30
    target = f"# Implementation\n\n```python\n{code}```\n"

    report = analyze(target, transcript)

    assert report["passed"] is True
    assert report["files"][0]["longest_overlap_chars"] == 0


def test_overlap_report_contains_hashes_but_not_source_excerpts_or_absolute_paths(
    tmp_path: Path,
) -> None:
    transcript = source_transcript()
    secret_phrase = transcript[300:900]
    report = analyze(
        secret_phrase,
        transcript,
        target_path="skill/references/persona.md",
    )

    serialized = json.dumps(report, ensure_ascii=False)
    assert secret_phrase[:100] not in serialized
    assert transcript[:100] not in serialized
    assert str(tmp_path) not in serialized
    assert len(report["files"][0]["match_fingerprint"]) == 16


def test_overlap_analysis_is_deterministic_for_identical_inputs() -> None:
    transcript = source_transcript()
    target = split_every(transcript, 100)

    first = analyze(target, transcript)
    second = analyze(target, transcript)

    assert first == second


def test_common_timestamp_variants_cannot_break_a_long_copy_match() -> None:
    transcript = source_transcript()
    timestamped = ""
    stamps = ("00:01", "(00:02)", "00:00:03,120", "00:04 --> 00:05")
    for index in range(0, len(transcript), 20):
        stamp = stamps[(index // 20) % len(stamps)]
        timestamped += f"{stamp}{transcript[index:index + 20]}"

    report = analyze(transcript, timestamped)

    assert report["passed"] is False
    assert report["files"][0]["longest_overlap_chars"] >= 1000


def test_longest_overlap_does_not_stitch_unrelated_source_spans() -> None:
    first = source_transcript(20)
    second = "".join(
        f"样本{index:03d}说明另一组完全不同的装置参数和测量结论。"
        for index in range(20)
    )
    target = first[80:210] + second[100:230] + ("uniquefillerx" * 100)

    report = content_safety.analyze_copyright_overlap(
        {"skill/references/persona.md": target},
        {
            "transcripts/first.txt": first,
            "transcripts/second.txt": second,
        },
    )

    assert report["passed"] is True
    assert 120 <= report["longest_overlap_chars"] < 200
    assert report["overall_copied_ratio"] < 0.20


def test_creator_quality_check_blocks_current_transcript_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    transcript = source_transcript()
    seed_quality_run(run_dir, copied_text=split_every(transcript, 100), transcript=transcript)
    force_non_text_gates_ready(monkeypatch)

    report = creator_pipeline.creator_quality_check(run_dir)
    persisted = json.loads(
        (run_dir / "logs" / "creator_quality_report.json").read_text(
            encoding="utf-8"
        )
    )

    assert report["passed"] is False
    assert report["checks"]["no_transcript_dump"] is False
    assert report["content_safety"]["copyright_overlap"]["passed"] is False
    assert report["ready_for_use"] is False
    assert persisted["content_safety"] == report["content_safety"]
    assert report["computed_from"]["content_safety"] == report["content_safety"][
        "computed_from"
    ]
    assert transcript[:100] not in json.dumps(persisted, ensure_ascii=False)


def test_creator_quality_check_includes_structured_persona_model_in_final_skill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    transcript = source_transcript()
    seed_quality_run(
        run_dir,
        copied_text="这是独立编写的人格说明。" * 50,
        transcript=transcript,
    )
    (run_dir / "skill" / "references" / "persona_model.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "core_identity": split_every(transcript, 100),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    force_non_text_gates_ready(monkeypatch)

    report = creator_pipeline.creator_quality_check(run_dir)

    assert report["passed"] is False
    assert report["checks"]["no_transcript_dump"] is False
    assert (
        "skill/references/persona_model.json"
        in report["content_safety"]["copyright_overlap"]["failed_files"]
    )


def test_creator_quality_check_discovers_every_nested_skill_text_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    transcript = source_transcript()
    seed_quality_run(
        run_dir,
        copied_text="这是独立编写的人格说明。" * 50,
        transcript=transcript,
    )
    extra = run_dir / "skill" / "references" / "nested" / "extra.yaml"
    extra.parent.mkdir(parents=True)
    extra.write_text("copied: |\n  " + split_every(transcript, 100), encoding="utf-8")
    force_non_text_gates_ready(monkeypatch)

    report = creator_pipeline.creator_quality_check(run_dir)

    assert report["passed"] is False
    assert "skill/references/nested/extra.yaml" in report["content_safety"][
        "copyright_overlap"
    ]["failed_files"]


def test_computed_identity_hashes_the_exact_bytes_that_were_analyzed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    target = run_dir / "skill" / "SKILL.md"
    transcript = run_dir / "transcripts" / "video.txt"
    target.parent.mkdir(parents=True)
    transcript.parent.mkdir(parents=True)
    original = "独立撰写的安全说明。".encode()
    changed = source_transcript().encode()
    target.write_bytes(original)
    transcript.write_bytes(changed)
    original_read_bytes = Path.read_bytes
    raced = False

    def racing_read_bytes(path: Path) -> bytes:
        nonlocal raced
        raw = original_read_bytes(path)
        if path == target and not raced:
            raced = True
            path.write_bytes(changed)
        return raw

    monkeypatch.setattr(Path, "read_bytes", racing_read_bytes)

    report = content_safety.evaluate_run_content_safety(
        run_dir,
        target_paths=[target],
        transcript_paths=[transcript],
    )
    identity = next(
        item for item in report["computed_from"] if item["role"] == "final_skill_document"
    )

    assert identity["sha256"] == hashlib.sha256(original).hexdigest()
    assert identity["size_bytes"] == len(original)


def test_path_swap_to_outside_symlink_fails_safely_without_reading_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    target = run_dir / "skill" / "SKILL.md"
    transcript = run_dir / "transcripts" / "video.txt"
    outside = tmp_path / "outside-secret.txt"
    target.parent.mkdir(parents=True)
    transcript.parent.mkdir(parents=True)
    target.write_text("独立安全说明。", encoding="utf-8")
    transcript.write_text(source_transcript(), encoding="utf-8")
    outside.write_text("OUTSIDE_PRIVATE_MARKER", encoding="utf-8")
    original_resolve = Path.resolve
    swapped = False

    def racing_resolve(path: Path, *args: Any, **kwargs: Any) -> Path:
        nonlocal swapped
        resolved = original_resolve(path, *args, **kwargs)
        if path == target and not swapped:
            try:
                path.unlink()
                path.symlink_to(outside)
            except OSError:
                pytest.skip("This platform does not permit creating a test symlink")
            swapped = True
        return resolved

    monkeypatch.setattr(Path, "resolve", racing_resolve)

    report = content_safety.evaluate_run_content_safety(
        run_dir,
        target_paths=[target],
        transcript_paths=[transcript],
    )
    serialized = json.dumps(report, ensure_ascii=False)

    assert report["passed"] is False
    assert report["checks"]["inputs_contained"] is False
    assert "OUTSIDE_PRIVATE_MARKER" not in serialized
    assert str(outside) not in serialized


def test_parent_directory_swap_never_opens_outside_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    nested = run_dir / "skill" / "nested"
    saved = run_dir / "skill" / "nested-original"
    target = nested / "document.md"
    transcript = run_dir / "transcripts" / "video.txt"
    outside_dir = tmp_path / "outside"
    outside_target = outside_dir / "document.md"
    nested.mkdir(parents=True)
    transcript.parent.mkdir(parents=True)
    outside_dir.mkdir()
    target.write_text("独立安全说明。", encoding="utf-8")
    transcript.write_text(source_transcript(), encoding="utf-8")
    outside_target.write_text("OUTSIDE_PRIVATE_MARKER", encoding="utf-8")
    original_contains = content_safety._contains_symlink_component
    original_open = os.open
    swapped = False
    outside_read_attempted = False

    def racing_contains(root: Path, candidate: Path) -> bool:
        nonlocal swapped
        result = original_contains(root, candidate)
        if candidate == target and not swapped:
            nested.rename(saved)
            try:
                nested.symlink_to(outside_dir, target_is_directory=True)
            except OSError:
                saved.rename(nested)
                pytest.skip("This platform does not permit creating a directory symlink")
            swapped = True
        return result

    original_fdopen = os.fdopen

    def tracking_fdopen(*args: Any, **kwargs: Any) -> Any:
        nonlocal outside_read_attempted
        if os.name == "nt":
            opened_path = content_safety._windows_final_path(args[0])
        else:
            opened_path = os.readlink(f"/proc/self/fd/{args[0]}")
        if opened_path is not None and os.path.samefile(opened_path, outside_target):
            outside_read_attempted = True
        return original_fdopen(*args, **kwargs)

    monkeypatch.setattr(content_safety, "_contains_symlink_component", racing_contains)
    monkeypatch.setattr(content_safety.os, "open", original_open)
    monkeypatch.setattr(content_safety.os, "fdopen", tracking_fdopen)
    try:
        report = content_safety.evaluate_run_content_safety(
            run_dir,
            target_paths=[target],
            transcript_paths=[transcript],
        )
    finally:
        if nested.is_symlink():
            nested.unlink()
        if saved.exists():
            saved.rename(nested)

    assert report["passed"] is False
    assert outside_read_attempted is False


def test_missing_explicit_input_returns_a_safe_failure(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    transcript = run_dir / "transcripts" / "video.txt"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(source_transcript(), encoding="utf-8")

    report = content_safety.evaluate_run_content_safety(
        run_dir,
        target_paths=[run_dir / "skill" / "missing.md"],
        transcript_paths=[transcript],
    )

    assert report["passed"] is False
    assert report["checks"]["inputs_available"] is False
    assert report["computed_from"][0] == {
        "role": "final_skill_document",
        "path": "skill/missing.md",
        "status": "missing",
    }


def test_creator_quality_check_blocks_any_content_safety_input_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    transcript = source_transcript()
    seed_quality_run(
        run_dir,
        copied_text="这是独立编写的人格说明。" * 50,
        transcript=transcript,
    )
    force_non_text_gates_ready(monkeypatch)
    original = content_safety.evaluate_run_content_safety

    def unsafe_report(*args: Any, **kwargs: Any) -> dict[str, Any]:
        report = original(*args, **kwargs)
        report["passed"] = False
        report["checks"]["inputs_contained"] = False
        return report

    monkeypatch.setattr(content_safety, "evaluate_run_content_safety", unsafe_report)

    report = creator_pipeline.creator_quality_check(run_dir)

    assert report["passed"] is False
    assert report["checks"]["content_safety_passed"] is False
    assert report["ready_for_use"] is False


def test_creator_quality_check_blocks_replacement_character_in_final_skill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    transcript = source_transcript()
    seed_quality_run(
        run_dir,
        copied_text="这是独立说明，但包含损坏字符�需要修复。",
        transcript=transcript,
    )
    force_non_text_gates_ready(monkeypatch)

    report = creator_pipeline.creator_quality_check(run_dir)

    assert report["passed"] is False
    assert report["checks"]["no_mojibake"] is False
    assert report["content_safety"]["encoding"]["failed_files"] == [
        "skill/references/persona.md"
    ]


def test_text_quality_report_exposes_overlap_and_encoding_metrics(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = {
        "passed": False,
        "ready_for_use": False,
        "commercial_delivery_ready": False,
        "checks": {"no_transcript_dump": False, "no_mojibake": True},
        "content_readiness": {"checks": {}},
        "governance": {"checks": {}},
        "evidence_integrity": {"valid": True, "counts": {}},
        "evaluator_verdict": {"passed": True},
        "blocking_checks": {},
        "advisory_checks": {},
        "freshness": {"fresh": True},
        "content_safety": {
            "copyright_overlap": {
                "passed": False,
                "longest_overlap_chars": 812,
                "overall_copied_ratio": 0.64,
                "failed_files": ["skill/references/persona.md"],
            },
            "encoding": {"passed": True, "failed_files": []},
        },
    }
    monkeypatch.setattr(creator_pipeline, "creator_quality_check", lambda _run: report)

    exit_code = creator_pipeline.command_quality_check(
        SimpleNamespace(run_dir="run", json=False, report_only=False)
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "COPYRIGHT_OVERLAP FAIL longest=812 ratio=0.64" in output
    assert "COPYRIGHT_FAILED_FILES skill/references/persona.md" in output
    assert "ENCODING PASS" in output
