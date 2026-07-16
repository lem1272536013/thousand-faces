#!/usr/bin/env python3
"""CLI orchestration and compatibility facade for host refinement preparation."""

from __future__ import annotations

import argparse
from pathlib import Path

import artifacts as artifacts
import corpus as corpus
import entity_review as entity_review
import quality_engine as quality_engine
import research_taxonomy as research_taxonomy
import run_diagnostics
import topic_discovery as topic_discovery
from io_utils import atomic_write_json
from refinement_common import (
    _MARKDOWN_CONTROL_CHARACTERS as _MARKDOWN_CONTROL_CHARACTERS,
    clean_text as clean_text,
    count_table_row as count_table_row,
    item_score as item_score,
    markdown_data_inline as markdown_data_inline,
    markdown_data_join as markdown_data_join,
    read_json as read_json,
    render_untrusted_markdown_block as render_untrusted_markdown_block,
    transcript_excerpt as transcript_excerpt,
    untrusted_corpus_protocol_lines as untrusted_corpus_protocol_lines,
)
from refinement_coverage import (
    _ACCEPTED_EVIDENCE_STATUSES as _ACCEPTED_EVIDENCE_STATUSES,
    _REASON_HEADERS as _REASON_HEADERS,
    _REJECTED_EVIDENCE_STATUSES as _REJECTED_EVIDENCE_STATUSES,
    _STATUS_HEADERS as _STATUS_HEADERS,
    _VIDEO_ID_HEADERS as _VIDEO_ID_HEADERS,
    _markdown_table_cells as _markdown_table_cells,
    _markdown_table_separator as _markdown_table_separator,
    _normalized_evidence_header as _normalized_evidence_header,
    _normalized_evidence_status as _normalized_evidence_status,
    COVERAGE_THRESHOLDS as COVERAGE_THRESHOLDS,
    COVERAGE_THRESHOLD_EXPLANATIONS as COVERAGE_THRESHOLD_EXPLANATIONS,
    _taxonomy_from_corpus as _taxonomy_from_corpus,
    build_coverage_gaps as build_coverage_gaps,
    build_evidence_coverage as build_evidence_coverage,
    build_short_form_coverage as build_short_form_coverage,
    build_timeline_shift as build_timeline_shift,
    coverage_bucket as coverage_bucket,
    covered_video_ids as covered_video_ids,
    parse_evidence_index as parse_evidence_index,
    ratio as ratio,
)
from refinement_signals import (
    _phrase_analysis_payload as _phrase_analysis_payload,
    _text_analysis_documents as _text_analysis_documents,
    build_asr_entity_review as build_asr_entity_review,
    build_corpus_index as build_corpus_index,
    build_signal_matrix as build_signal_matrix,
    build_topic_candidates as build_topic_candidates,
    build_transcript_signals as build_transcript_signals,
    common_phrase_candidates as common_phrase_candidates,
    contribution_types as contribution_types,
    first_matching_sentence as first_matching_sentence,
    keyword_labels as keyword_labels,
    reusable_phrase_candidates as reusable_phrase_candidates,
    sentence_like_count as sentence_like_count,
    split_sentences as split_sentences,
    top_terms_for_text as top_terms_for_text,
    transcript_record as transcript_record,
    transcript_signal as transcript_signal,
    transcript_text as transcript_text,
)
from refinement_schemas import (
    _relax_template_constraints as _relax_template_constraints,
    _status_document_schema as _status_document_schema,
    _strict_schema_objects as _strict_schema_objects,
    build_evaluation_suite_json_template as build_evaluation_suite_json_template,
    build_evaluation_suite_schema as build_evaluation_suite_schema,
    build_persona_model_schema as build_persona_model_schema,
    build_persona_model_template as build_persona_model_template,
    build_reverse_identification_json_template as build_reverse_identification_json_template,
    build_reverse_identification_schema as build_reverse_identification_schema,
)
from refinement_templates import (
    build_asr_entity_review_markdown as build_asr_entity_review_markdown,
    build_audit_template as build_audit_template,
    build_brief as build_brief,
    build_coverage_gaps_markdown as build_coverage_gaps_markdown,
    build_evaluation_suite_template as build_evaluation_suite_template,
    build_evidence_coverage_markdown as build_evidence_coverage_markdown,
    build_reverse_identification_template as build_reverse_identification_template,
    build_reviewer_template as build_reviewer_template,
    build_short_form_coverage_markdown as build_short_form_coverage_markdown,
    build_timeline_shift_markdown as build_timeline_shift_markdown,
    build_topic_candidates_markdown as build_topic_candidates_markdown,
    build_transcript_signals_markdown as build_transcript_signals_markdown,
    build_usage_probe_template as build_usage_probe_template,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare a compact host-agent refinement brief")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--top-count", type=int, default=25)
    parser.add_argument("--excerpt-count", type=int, default=10)
    parser.add_argument("--excerpt-chars", type=int, default=900)
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser()
    try:
        run_diagnostics.require_current_run(run_dir)
    except run_diagnostics.RunFormatError as error:
        parser.error(str(error))
    try:
        taxonomy = research_taxonomy.resolve_run_taxonomy(run_dir)
    except research_taxonomy.TaxonomyPresetError as error:
        parser.error(str(error))
    try:
        corpus_snapshot = corpus.load_corpus(run_dir)
    except corpus.CorpusLoadError as error:
        parser.error(str(error))
    output_dir = run_dir / "research" / "host_refinement"
    output_dir.mkdir(parents=True, exist_ok=True)
    reviews_dir = run_dir / "research" / "reviews"
    reviews_dir.mkdir(parents=True, exist_ok=True)
    skill_refs_dir = run_dir / "skill" / "references"
    skill_refs_dir.mkdir(parents=True, exist_ok=True)
    entity_dictionary_path = entity_review.project_dictionary_path(run_dir)
    if not entity_dictionary_path.exists():
        atomic_write_json(
            entity_dictionary_path,
            entity_review.build_project_dictionary_template(),
        )

    corpus_index = build_corpus_index(
        run_dir,
        preset=taxonomy,
        corpus_snapshot=corpus_snapshot,
    )
    topic_candidates = build_topic_candidates(
        run_dir,
        corpus_index,
        corpus_snapshot=corpus_snapshot,
    )
    signal_payload = build_transcript_signals(
        run_dir,
        corpus_index,
        preset=taxonomy,
        corpus_snapshot=corpus_snapshot,
    )
    evidence_coverage = build_evidence_coverage(
        run_dir,
        corpus_index,
        signal_payload,
        preset=taxonomy,
    )
    coverage_gaps = build_coverage_gaps(corpus_index, signal_payload, evidence_coverage)
    short_form_coverage = build_short_form_coverage(corpus_index, signal_payload)
    timeline_shift = build_timeline_shift(corpus_index, signal_payload)
    asr_entity_review = build_asr_entity_review(
        run_dir,
        corpus_index,
        preset=taxonomy,
        corpus_snapshot=corpus_snapshot,
    )
    corpus_path = output_dir / "corpus_index.json"
    topic_candidates_path = output_dir / "topic_candidates.json"
    topic_candidates_markdown_path = output_dir / "topic_candidates.md"
    matrix_path = output_dir / "transcript_signal_matrix.md"
    signals_json_path = output_dir / "transcript_signals.json"
    signals_md_path = output_dir / "transcript_signals.md"
    brief_path = output_dir / "brief.md"
    coverage_json_path = reviews_dir / "evidence_coverage.json"
    coverage_md_path = reviews_dir / "evidence_coverage.md"
    coverage_gaps_json_path = reviews_dir / "coverage_gaps.json"
    coverage_gaps_md_path = reviews_dir / "coverage_gaps.md"
    short_form_json_path = reviews_dir / "short_form_coverage.json"
    short_form_md_path = reviews_dir / "short_form_coverage.md"
    timeline_json_path = reviews_dir / "timeline_shift.json"
    timeline_md_path = reviews_dir / "timeline_shift.md"
    entity_json_path = reviews_dir / "asr_entity_review.json"
    entity_md_path = reviews_dir / "asr_entity_review.md"
    entity_decisions_path = reviews_dir / "asr_entity_decisions.json"
    topic_decisions_path = reviews_dir / "topic_candidate_decisions.json"
    audit_path = reviews_dir / "refinement_audit.md"
    usage_probe_path = reviews_dir / "usage_probe.md"
    evaluation_suite_path = reviews_dir / "evaluation_suite.md"
    evaluation_suite_json_path = reviews_dir / "evaluation_suite.json"
    evaluation_suite_schema_path = reviews_dir / "evaluation_suite.schema.json"
    reverse_identification_path = reviews_dir / "reverse_identification.md"
    reverse_identification_json_path = reviews_dir / "reverse_identification.json"
    reverse_identification_schema_path = reviews_dir / "reverse_identification.schema.json"
    reviewer_path = reviews_dir / "reviewer_findings.md"
    persona_schema_path = skill_refs_dir / "persona_model.schema.json"
    persona_model_path = skill_refs_dir / "persona_model.json"

    existing_entity_decisions: dict[str, object] | None = None
    if entity_decisions_path.exists():
        loaded_entity_decisions = read_json(entity_decisions_path)
        if not isinstance(loaded_entity_decisions, dict):
            raise entity_review.EntityReviewError(
                "asr_entity_decisions.json must contain a JSON object"
            )
        existing_entity_decisions = loaded_entity_decisions
    asr_entity_decisions = entity_review.build_entity_decision_ledger(
        asr_entity_review,
        existing_entity_decisions,
    )

    try:
        refinement_specs = quality_engine.refinement_artifact_specs(
            run_dir,
            corpus_snapshot=corpus_snapshot,
        )
    except corpus.CorpusLoadError as error:
        parser.error(str(error))

    atomic_write_json(corpus_path, corpus_index)
    atomic_write_json(topic_candidates_path, topic_candidates)
    topic_candidates_markdown_path.write_text(
        build_topic_candidates_markdown(topic_candidates),
        encoding="utf-8",
    )
    matrix_path.write_text(
        build_signal_matrix(
            run_dir,
            corpus_index,
            corpus_snapshot=corpus_snapshot,
        ),
        encoding="utf-8",
    )
    atomic_write_json(signals_json_path, signal_payload)
    signals_md_path.write_text(build_transcript_signals_markdown(signal_payload), encoding="utf-8")
    artifacts.write_artifact_manifest(
        corpus_path,
        refinement_specs["corpus_index"],
    )
    artifacts.write_artifact_manifest(
        topic_candidates_path,
        refinement_specs["topic_candidates"],
    )
    artifacts.write_artifact_manifest(
        topic_candidates_markdown_path,
        refinement_specs["topic_candidates_markdown"],
    )
    artifacts.write_artifact_manifest(
        matrix_path,
        refinement_specs["transcript_signal_matrix"],
    )
    artifacts.write_artifact_manifest(
        signals_json_path,
        refinement_specs["transcript_signals"],
    )
    artifacts.write_artifact_manifest(
        signals_md_path,
        refinement_specs["transcript_signals_markdown"],
    )

    coverage_specs = quality_engine.coverage_artifact_specs(run_dir)
    atomic_write_json(coverage_json_path, evidence_coverage)
    coverage_md_path.write_text(build_evidence_coverage_markdown(evidence_coverage), encoding="utf-8")
    artifacts.write_artifact_manifest(
        coverage_json_path,
        coverage_specs["evidence_coverage"],
    )
    artifacts.write_artifact_manifest(
        coverage_md_path,
        coverage_specs["evidence_coverage_markdown"],
    )
    atomic_write_json(coverage_gaps_json_path, coverage_gaps)
    coverage_gaps_md_path.write_text(build_coverage_gaps_markdown(coverage_gaps), encoding="utf-8")
    atomic_write_json(short_form_json_path, short_form_coverage)
    short_form_md_path.write_text(build_short_form_coverage_markdown(short_form_coverage), encoding="utf-8")
    atomic_write_json(timeline_json_path, timeline_shift)
    timeline_md_path.write_text(build_timeline_shift_markdown(timeline_shift), encoding="utf-8")
    atomic_write_json(entity_json_path, asr_entity_review)
    entity_md_path.write_text(
        build_asr_entity_review_markdown(
            asr_entity_review,
        ),
        encoding="utf-8",
    )
    atomic_write_json(entity_decisions_path, asr_entity_decisions)
    artifacts.write_artifact_manifest(
        entity_json_path,
        refinement_specs["asr_entity_review"],
    )
    artifacts.write_artifact_manifest(
        entity_md_path,
        refinement_specs["asr_entity_review_markdown"],
    )
    atomic_write_json(persona_schema_path, build_persona_model_schema())
    if not persona_model_path.exists() or persona_model_path.stat().st_size < 20:
        atomic_write_json(persona_model_path, build_persona_model_template(corpus_index))
    brief_path.write_text(
        build_brief(
            run_dir,
            args.top_count,
            args.excerpt_count,
            args.excerpt_chars,
            preset=taxonomy,
            corpus_snapshot=corpus_snapshot,
        ),
        encoding="utf-8",
    )
    if not audit_path.exists() or audit_path.stat().st_size < 20:
        audit_path.write_text(build_audit_template(), encoding="utf-8")
    if not topic_decisions_path.exists():
        atomic_write_json(
            topic_decisions_path,
            topic_discovery.build_topic_review_template(topic_candidates),
        )
    if not usage_probe_path.exists() or usage_probe_path.stat().st_size < 20:
        usage_probe_path.write_text(build_usage_probe_template(), encoding="utf-8")
    if not evaluation_suite_path.exists() or evaluation_suite_path.stat().st_size < 20:
        evaluation_suite_path.write_text(build_evaluation_suite_template(), encoding="utf-8")
    atomic_write_json(evaluation_suite_schema_path, build_evaluation_suite_schema())
    if not evaluation_suite_json_path.exists() or evaluation_suite_json_path.stat().st_size < 20:
        atomic_write_json(evaluation_suite_json_path, build_evaluation_suite_json_template())
    if not reverse_identification_path.exists() or reverse_identification_path.stat().st_size < 20:
        reverse_identification_path.write_text(build_reverse_identification_template(), encoding="utf-8")
    atomic_write_json(reverse_identification_schema_path, build_reverse_identification_schema())
    if not reverse_identification_json_path.exists() or reverse_identification_json_path.stat().st_size < 20:
        atomic_write_json(reverse_identification_json_path, build_reverse_identification_json_template())
    if not reviewer_path.exists() or reviewer_path.stat().st_size < 20:
        reviewer_path.write_text(build_reviewer_template(), encoding="utf-8")

    print(brief_path)
    print(corpus_path)
    print(topic_candidates_path)
    print(topic_candidates_markdown_path)
    print(matrix_path)
    print(signals_json_path)
    print(signals_md_path)
    print(coverage_json_path)
    print(coverage_md_path)
    print(coverage_gaps_json_path)
    print(coverage_gaps_md_path)
    print(short_form_json_path)
    print(short_form_md_path)
    print(timeline_json_path)
    print(timeline_md_path)
    print(entity_json_path)
    print(entity_md_path)
    print(topic_decisions_path)
    print(persona_schema_path)
    print(persona_model_path)
    print(audit_path)
    print(usage_probe_path)
    print(evaluation_suite_path)
    print(evaluation_suite_schema_path)
    print(evaluation_suite_json_path)
    print(reverse_identification_path)
    print(reverse_identification_schema_path)
    print(reverse_identification_json_path)
    print(reviewer_path)


if __name__ == "__main__":
    main()
