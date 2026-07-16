"""Host-refinement corpus loading is single-pass and bounded."""

from __future__ import annotations

import sys
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import IO, Any

import pytest

import corpus
import prepare_host_refinement
import quality_engine
import research_taxonomy
import run_diagnostics
import text_analysis
from entity_review import build_project_dictionary_template, project_dictionary_path
from io_utils import atomic_write_json


MEDIUM_TRANSCRIPT_COUNT = 50


def seed_medium_corpus(run_dir: Path, *, count: int = MEDIUM_TRANSCRIPT_COUNT) -> list[str]:
    metadata = run_dir / "metadata"
    transcripts = run_dir / "transcripts"
    metadata.mkdir(parents=True)
    transcripts.mkdir()
    atomic_write_json(
        run_dir / "input.json",
        {
            "run_format": run_diagnostics.RUN_FORMAT_NAME,
            "schema_version": run_diagnostics.RUN_FORMAT_SCHEMA_VERSION,
        },
    )
    atomic_write_json(run_dir / "config.snapshot.json", {"settings_schema_version": 2})
    atomic_write_json(run_dir / "workflow.plan.json", {"schema_version": 1})
    atomic_write_json(metadata / "provenance.json", {"schema_version": 1})
    items: list[dict[str, object]] = []
    names: list[str] = []
    repeated_body = "控制火候保持口感，然后解释原因并给出边界。" * 120
    for index in range(1, count + 1):
        artifact_id = f"medium-{index:03d}"
        names.append(f"{artifact_id}.txt")
        items.append(
            {
                "platform_video_id": artifact_id,
                "artifact_id": artifact_id,
                "title": f"第 {index:03d} 条中等长度人工语料",
                "published_at": f"2026-01-{((index - 1) % 28) + 1:02d}T00:00:00+00:00",
                "duration": 60,
                "stats": {
                    "like": index,
                    "favorite": index % 7,
                    "share": index % 5,
                    "comment": index % 3,
                },
            }
        )
        (transcripts / names[-1]).write_text(
            f"这是第 {index:03d} 条转写。{repeated_body}\n",
            encoding="utf-8",
        )
    atomic_write_json(
        metadata / "selected.compact.json",
        {
            "requested_count": count,
            "selected_count": count,
            "selection_strategy": "published_at_desc",
            "creator_profile": {"nickname": "性能基准创作者"},
            "items": items,
        },
    )
    atomic_write_json(
        project_dictionary_path(run_dir),
        build_project_dictionary_template(),
    )
    return names


def build_all_transcript_consumers(
    run_dir: Path,
    *,
    snapshot: corpus.CorpusSnapshot | None,
) -> dict[str, object]:
    taxonomy = research_taxonomy.resolve_run_taxonomy(run_dir)
    corpus_index = prepare_host_refinement.build_corpus_index(
        run_dir,
        preset=taxonomy,
        corpus_snapshot=snapshot,
    )
    topic_candidates = prepare_host_refinement.build_topic_candidates(
        run_dir,
        corpus_index,
        corpus_snapshot=snapshot,
    )
    signals = prepare_host_refinement.build_transcript_signals(
        run_dir,
        corpus_index,
        preset=taxonomy,
        corpus_snapshot=snapshot,
    )
    entity_report = prepare_host_refinement.build_asr_entity_review(
        run_dir,
        corpus_index,
        preset=taxonomy,
        corpus_snapshot=snapshot,
    )
    matrix = prepare_host_refinement.build_signal_matrix(
        run_dir,
        corpus_index,
        corpus_snapshot=snapshot,
    )
    brief = prepare_host_refinement.build_brief(
        run_dir,
        25,
        10,
        900,
        preset=taxonomy,
        corpus_snapshot=snapshot,
    )
    specs = quality_engine.refinement_artifact_specs(
        run_dir,
        corpus_snapshot=snapshot,
    )
    return {
        "corpus_index": corpus_index,
        "topic_candidates": topic_candidates,
        "signals": signals,
        "entity_report": entity_report,
        "matrix": matrix,
        "brief": brief,
        "specs": {name: spec.contract() for name, spec in specs.items()},
    }


def test_one_prepare_reads_each_transcript_exactly_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    expected_names = seed_medium_corpus(run_dir)
    transcript_dir = (run_dir / "transcripts").resolve()
    read_opens: Counter[str] = Counter()
    original_open = Path.open

    def tracked_open(
        path: Path,
        mode: str = "r",
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> IO[Any]:
        if (
            path.parent.resolve() == transcript_dir
            and "r" in mode
            and "+" not in mode
        ):
            read_opens[path.name] += 1
        return original_open(path, mode, buffering, encoding, errors, newline)

    monkeypatch.setattr(Path, "open", tracked_open)
    monkeypatch.setattr(
        sys,
        "argv",
        ["prepare_host_refinement.py", "--run-dir", str(run_dir)],
    )

    prepare_host_refinement.main()

    assert sorted(read_opens) == expected_names
    assert set(read_opens.values()) == {1}


def test_shared_snapshot_preserves_legacy_consumer_outputs(tmp_path: Path) -> None:
    legacy_run = tmp_path / "legacy"
    cached_run = tmp_path / "cached"
    seed_medium_corpus(legacy_run, count=3)
    seed_medium_corpus(cached_run, count=3)

    legacy = build_all_transcript_consumers(legacy_run, snapshot=None)
    snapshot = corpus.load_corpus(cached_run)
    cached = build_all_transcript_consumers(cached_run, snapshot=snapshot)

    assert cached == legacy


@pytest.mark.parametrize(
    ("texts", "max_file_chars", "max_total_chars", "expected_code"),
    [
        (["单文件超限" * 20], 16, 10_000, "CORPUS_FILE_CHAR_LIMIT"),
        (["第一条" * 10, "第二条" * 10], 100, 50, "CORPUS_TOTAL_CHAR_LIMIT"),
    ],
)
def test_corpus_limits_fail_closed_with_hierarchical_index_strategy(
    tmp_path: Path,
    texts: list[str],
    max_file_chars: int,
    max_total_chars: int,
    expected_code: str,
) -> None:
    run_dir = tmp_path / "limited"
    names = seed_medium_corpus(run_dir, count=len(texts))
    for name, text in zip(names, texts, strict=True):
        (run_dir / "transcripts" / name).write_text(text, encoding="utf-8")

    with pytest.raises(corpus.CorpusLimitError) as raised:
        corpus.load_corpus(
            run_dir,
            max_file_chars=max_file_chars,
            max_total_chars=max_total_chars,
        )

    error = raised.value
    assert error.code == expected_code
    assert error.strategy["name"] == "hierarchical_batch_index"
    assert error.strategy["truncate_transcripts"] is False
    assert error.strategy["strata"] == [
        "top_interaction",
        "top_transcript_length",
        "short_transcripts",
        "boundary_or_risk",
        "remaining",
    ]
    assert str(run_dir.resolve()) not in str(error)
    assert "balanced batches" in str(error)
    assert "top_interaction" in str(error)
    assert error.strategy["batch_max_chars"] == max_total_chars
    if expected_code == "CORPUS_FILE_CHAR_LIMIT":
        assert error.strategy["max_transcript_chars"] == max_file_chars
        assert error.strategy["recommended_minimum_segments"] >= 2


def test_corpus_read_error_is_actionable_and_does_not_leak_absolute_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "unreadable"
    names = seed_medium_corpus(run_dir, count=1)
    transcript = (run_dir / "transcripts" / names[0]).resolve()
    original_open = Path.open

    def failing_open(path: Path, *args: Any, **kwargs: Any) -> IO[Any]:
        if path.resolve() == transcript:
            raise PermissionError("simulated access failure")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", failing_open)

    with pytest.raises(corpus.CorpusLoadError) as raised:
        corpus.load_corpus(run_dir)

    assert raised.value.code == "CORPUS_READ_ERROR"
    assert names[0] in str(raised.value)
    assert str(run_dir.resolve()) not in str(raised.value)


def test_snapshot_rejects_cross_run_reuse_and_changed_inputs(tmp_path: Path) -> None:
    first_run = tmp_path / "first"
    second_run = tmp_path / "second"
    first_names = seed_medium_corpus(first_run, count=1)
    seed_medium_corpus(second_run, count=1)
    snapshot = corpus.load_corpus(first_run)

    with pytest.raises(corpus.CorpusLoadError, match="CORPUS_RUN_MISMATCH"):
        prepare_host_refinement.build_corpus_index(
            second_run,
            corpus_snapshot=snapshot,
        )

    changed_path = first_run / "transcripts" / first_names[0]
    changed_path.write_text(
        changed_path.read_text(encoding="utf-8") + "修改后的输入",
        encoding="utf-8",
    )
    with pytest.raises(corpus.CorpusLoadError, match="CORPUS_INPUT_CHANGED"):
        quality_engine.refinement_artifact_specs(
            first_run,
            corpus_snapshot=snapshot,
        )


def test_snapshot_rejects_document_provenance_outside_run(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    seed_medium_corpus(run_dir, count=1)
    snapshot = corpus.load_corpus(run_dir)
    outside_path = tmp_path / snapshot.documents[0].path.name
    outside_path.write_text(snapshot.documents[0].source_text, encoding="utf-8")
    forged_document = replace(snapshot.documents[0], path=outside_path.resolve())

    with pytest.raises(corpus.CorpusLoadError, match="CORPUS_DOCUMENT_OUTSIDE_RUN"):
        replace(snapshot, documents=(forged_document,))


def test_prepare_reports_input_change_without_partial_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_dir = tmp_path / "changing"
    names = seed_medium_corpus(run_dir, count=1)
    original_builder = prepare_host_refinement.build_asr_entity_review

    def build_then_change(*args: Any, **kwargs: Any) -> dict[str, object]:
        payload = original_builder(*args, **kwargs)
        transcript = run_dir / "transcripts" / names[0]
        transcript.write_text(
            transcript.read_text(encoding="utf-8") + "并发修改",
            encoding="utf-8",
        )
        return payload

    monkeypatch.setattr(
        prepare_host_refinement,
        "build_asr_entity_review",
        build_then_change,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["prepare_host_refinement.py", "--run-dir", str(run_dir)],
    )

    with pytest.raises(SystemExit) as raised:
        prepare_host_refinement.main()

    captured = capsys.readouterr()
    assert raised.value.code == 2
    assert "CORPUS_INPUT_CHANGED" in captured.err
    assert "Traceback" not in captured.err
    assert not (run_dir / "research" / "host_refinement" / "corpus_index.json").exists()


def test_50_medium_transcripts_are_not_slower_with_shared_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy_run = tmp_path / "legacy-performance"
    cached_run = tmp_path / "cached-performance"
    seed_medium_corpus(legacy_run)
    seed_medium_corpus(cached_run)
    transcript_roots = {
        (legacy_run / "transcripts").resolve(),
        (cached_run / "transcripts").resolve(),
    }
    original_open = Path.open

    def slow_transcript_open(
        path: Path,
        mode: str = "r",
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> IO[Any]:
        if path.parent.resolve() in transcript_roots and "r" in mode and "+" not in mode:
            time.sleep(0.004)
        return original_open(path, mode, buffering, encoding, errors, newline)

    text_analysis.analyze_documents(
        [text_analysis.TextDocument("warmup", "", "预热中文分词。")]
    )
    monkeypatch.setattr(Path, "open", slow_transcript_open)

    legacy_started = time.perf_counter()
    legacy = build_all_transcript_consumers(legacy_run, snapshot=None)
    legacy_seconds = time.perf_counter() - legacy_started

    cached_started = time.perf_counter()
    snapshot = corpus.load_corpus(cached_run)
    cached = build_all_transcript_consumers(cached_run, snapshot=snapshot)
    cached_seconds = time.perf_counter() - cached_started

    print(
        "TF031 benchmark: "
        f"legacy_seconds={legacy_seconds:.4f} "
        f"cached_seconds={cached_seconds:.4f} "
        f"ratio={cached_seconds / legacy_seconds:.4f}"
    )
    assert cached == legacy
    assert cached_seconds <= legacy_seconds
