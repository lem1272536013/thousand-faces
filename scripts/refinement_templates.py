"""Markdown review templates and host-agent brief rendering."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import corpus
import entity_review
import path_policy
import research_taxonomy
import topic_discovery
from refinement_common import (
    count_table_row,
    item_score,
    markdown_data_inline,
    markdown_data_join,
    read_json,
    render_untrusted_markdown_block,
    transcript_excerpt,
    untrusted_corpus_protocol_lines,
)


def build_evidence_coverage_markdown(coverage: dict) -> str:
    def display_ratio(value: Any) -> str:
        return "N/A" if value is None else str(value)

    def display_rejections(bucket: dict) -> str:
        return markdown_data_join(
            [
                f"{item['video_id']}: {item['reason']}"
                for item in bucket.get("rejected_with_reason", [])[:10]
            ]
        )

    evidence_index = coverage.get("evidence_index", {})
    lines = [
        "# Evidence Coverage",
        "",
        "该文件只解析 `skill/references/evidence_index.md` 中带 Video ID 结构列的 Markdown 表格；正文或其他非结构化位置出现的 ID 不计入证据。",
        "",
        f"- Covered video count: {coverage['covered_video_count']} / {coverage['total_video_count']}",
        f"- Rejected with reason: {coverage.get('rejected_video_count', 0)}",
        f"- Invalid rejection rows: {evidence_index.get('invalid_rejection_count', 0)}",
        f"- Theme cluster ratio: {display_ratio(coverage['theme_cluster_ratio'])}",
        f"- Overall score: {display_ratio(coverage['overall_score'])}",
        f"- Applicable metric count: {coverage.get('applicable_metric_count', 0)}",
        "",
        "## Buckets",
        "",
        "| Bucket | Status | Covered | Total | Ratio | Missing IDs | Rejected (rejected_with_reason) |",
        "|---|---|---:|---:|---:|---|---|",
    ]
    for name, bucket in coverage["buckets"].items():
        lines.append(
            f"| {markdown_data_inline(name)} | {bucket['status']} | {bucket['covered']} | {bucket['total']} | "
            f"{display_ratio(bucket['ratio'])} | {markdown_data_join(bucket['missing_ids'][:10])} | "
            f"{display_rejections(bucket)} |"
        )
    lines.extend(["", "## Theme Coverage", ""])
    lines.append("| Theme | Status | Covered | Total | Ratio | Missing IDs | Rejected (rejected_with_reason) |")
    lines.append("|---|---|---:|---:|---:|---|---|")
    for theme, bucket in coverage["theme_coverage"].items():
        lines.append(
            f"| {markdown_data_inline(theme)} | {bucket['status']} | {bucket['covered']} | {bucket['total']} | "
            f"{display_ratio(bucket['ratio'])} | {markdown_data_join(bucket['missing_ids'][:10])} | "
            f"{display_rejections(bucket)} |"
        )
    lines.extend(["", "## Named Threshold Configuration", ""])
    lines.append("| Threshold | Value | Explanation |")
    lines.append("|---|---:|---|")
    configuration = coverage.get("configuration", {})
    explanations = configuration.get("explanations", {})
    for name, value in configuration.get("thresholds", {}).items():
        lines.append(
            f"| {markdown_data_inline(name)} | {value} | {markdown_data_inline(explanations.get(name, ''))} |"
        )
    return "\n".join(lines).rstrip() + "\n"

def build_coverage_gaps_markdown(payload: dict) -> str:
    lines = [
        "# Coverage Gaps",
        "",
        "该文件列出宿主 agent 下一轮最应该补读和补证据的视频。高优先级视频必须进入 `evidence_index.md` 的结构化表格；不采用时也要在表格中写 `rejected` 和非空理由。",
        "",
        f"- Overall score: {payload['summary']['overall_score']}",
        f"- Covered videos: {payload['summary']['covered_video_count']} / {payload['summary']['total_video_count']}",
        f"- Recommendation count: {payload['recommendation_count']}",
        "",
        "| Priority | Video ID | Reasons | Score | Chars | Title |",
        "|---:|---|---|---:|---:|---|",
    ]
    for item in payload.get("top_recommendations", []):
        reasons = markdown_data_join(item.get("reasons", []), "; ")
        title = markdown_data_inline(item.get("title", ""))
        lines.append(
            f"| {item.get('priority')} | {markdown_data_inline(item.get('video_id'))} | {reasons} | "
            f"{item.get('weighted_score')} | {item.get('transcript_chars')} | {title} |"
        )
    lines.extend(
        [
            "",
            "## 使用要求",
            "",
            "- 优先补读 priority=1 的视频。",
            "- 每个被采用的视频要以 `accepted` 状态进入 `skill/references/evidence_index.md` 的结构化表格。",
            "- 不采用的视频要以 `rejected` 状态和非空 `Reason` 写入同一表格；可在 `research/raw/*` 继续展开理由。",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"

def build_short_form_coverage_markdown(payload: dict) -> str:
    lines = [
        "# Short Form Coverage",
        "",
        "该文件专门检查短转写样本。短样本常能支撑 hook、标题和快速收束，但通常不足以单独支撑深层人格判断。",
        "",
        f"- Short form count: {payload['short_form_count']}",
        f"- Analyzed count: {payload['analyzed_count']}",
        "",
        "## Pattern Counts",
        "",
    ]
    for label, count in payload["pattern_counts"].items():
        lines.append(f"- {markdown_data_inline(label)}: {count}")
    lines.extend(["", "## Short Records", ""])
    lines.append("| Video ID | Chars | Score | Evidence | Hook | Ending | Contribution | Title |")
    lines.append("|---|---:|---:|---|---|---|---|---|")
    for record in payload["records"]:
        lines.append(
            "| {video_id} | {chars} | {score} | {evidence} | {hook} | {ending} | {contribution} | {title} |".format(
                video_id=markdown_data_inline(record["video_id"]),
                chars=record["chars"],
                score=record["score"],
                evidence=record["evidence_strength"],
                hook=markdown_data_inline(record["hook_type"]),
                ending=markdown_data_inline(record["ending_mode"]),
                contribution=markdown_data_inline(record["contribution_types"]),
                title=markdown_data_inline(record["title"]),
            )
        )
    return "\n".join(lines).rstrip() + "\n"

def build_timeline_shift_markdown(payload: dict) -> str:
    lines = [
        "# Timeline Shift",
        "",
        "该文件按发布时间切分样本，帮助判断哪些模式是长期稳定内核，哪些可能只是近期热点。",
        "",
        f"- Shift score: {payload.get('shift_score', 0.0)}",
        "",
    ]
    for period in payload.get("periods", []):
        lines.extend(
            [
                f"## Period: {markdown_data_inline(period['name'])}",
                "",
                f"- Date range: {markdown_data_inline(period['start_date'])} to {markdown_data_inline(period['end_date'])}",
                f"- Count: {period['count']}",
                f"- Top video IDs: {markdown_data_join(period['top_video_ids'])}",
                "",
                "### Theme Counts",
                "",
            ]
        )
        for label, count in period.get("theme_counts", {}).items():
            lines.append(f"- {markdown_data_inline(label)}: {count}")
        lines.extend(["", "### Contribution Counts", ""])
        for label, count in period.get("contribution_counts", {}).items():
            lines.append(f"- {markdown_data_inline(label)}: {count}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"

def build_asr_entity_review_markdown(
    payload: dict,
) -> str:
    return entity_review.build_entity_review_markdown(payload)


def build_topic_candidates_markdown(
    payload: topic_discovery.TopicDiscoveryResult,
) -> str:
    """Render candidates as inert research data, never as final persona claims."""

    confidence = payload["overall_confidence"]
    lines = [
        "# Topic Candidates",
        "",
        "该文件是无领域假设的确定性候选列表，不是最终人格或选题结论。宿主 Agent 必须回查视频证据，并在决策台账中接受、重命名、合并或拒绝。",
        "",
        "## Summary",
        "",
        f"- Algorithm: {payload['algorithm_version']}",
        f"- Tokenizer: {payload['tokenizer_name']} ({payload['tokenizer_mode']})",
        f"- Tokenizer version: {payload['tokenizer_version']}",
        f"- Stopword set: {payload['stopword_version']}",
        f"- Minimum cross-video appearances: {payload['minimum_video_appearances']}",
        f"- Classification: {payload['classification_status']}",
        f"- Candidate count: {payload['candidate_count']}",
        f"- Analyzed videos: {payload['analyzed_video_count']}",
        f"- Minimum document frequency: {payload['minimum_document_frequency']}",
        f"- Overall confidence: {confidence['level']} ({confidence['score']})",
        f"- Confidence reason: {confidence['reason']}",
        "",
        "## Candidate Table",
        "",
        "| Candidate ID | Provisional label | Videos | Coverage | Confidence |",
        "|---|---|---|---:|---|",
    ]
    for candidate in payload["candidates"]:
        candidate_confidence = candidate["confidence"]
        lines.append(
            f"| {markdown_data_inline(candidate['candidate_id'])} | "
            f"{markdown_data_inline(candidate['provisional_label'])} | "
            f"{markdown_data_join(candidate['representative_video_ids'])} | "
            f"{candidate['coverage_ratio']} | "
            f"{candidate_confidence['level']} ({candidate_confidence['score']}) |"
        )
    for candidate in payload["candidates"]:
        lines.extend(
            [
                "",
                f"### {markdown_data_inline(candidate['candidate_id'])} terms",
                "",
                "| Term | Document frequency | Total frequency | Title DF | Coverage | Source fragments |",
                "|---|---:|---:|---:|---:|---|",
            ]
        )
        for term in candidate["distinguishing_terms"]:
            lines.append(
                f"| {markdown_data_inline(term['term'])} | "
                f"{term['document_frequency']} | {term['total_frequency']} | "
                f"{term['title_document_frequency']} | {term['coverage_ratio']} | "
                f"{markdown_data_join(term['source_fragment_ids'])} |"
            )
    lines.extend(
        [
            "",
            "## Host Review",
            "",
            "把人工/Agent 决策写入 `research/reviews/topic_candidate_decisions.json`；不要直接改写本候选文件。",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"

def build_transcript_signals_markdown(signal_payload: dict) -> str:
    lines = [
        "# Transcript Signals",
        "",
        "该文件由启发式脚本生成，逐条抽取 ASR 的结构信号。它不是最终结论，宿主 agent 必须用原文抽检和修正。",
        "",
        "## Summary",
        "",
    ]
    taxonomy = signal_payload.get("taxonomy") or {}
    lines.append(
        f"- Taxonomy: {markdown_data_inline(taxonomy.get('preset', ''))} "
        f"{markdown_data_inline(taxonomy.get('version', ''))}"
    )
    summary = signal_payload["summary"]
    lines.append(f"- Signal count: {summary['signal_count']}")
    lines.append(f"- Boundary or risk samples: {summary['boundary_or_risk_count']}")
    phrase_analysis = signal_payload.get("phrase_analysis") or {}
    lines.append(
        f"- Tokenizer version: "
        f"{markdown_data_inline(phrase_analysis.get('tokenizer_version', ''))}"
    )
    lines.append(
        f"- Stopword version: "
        f"{markdown_data_inline(phrase_analysis.get('stopword_version', ''))}"
    )
    lines.append(
        f"- Minimum cross-video appearances: "
        f"{int(phrase_analysis.get('minimum_video_appearances') or 0)}"
    )
    lines.extend(["", "### Contribution Counts", ""])
    for label, count in summary["contribution_counts"].items():
        lines.append(f"- {markdown_data_inline(label)}: {count}")
    lines.extend(["", "### Hook Counts", ""])
    for label, count in summary["hook_counts"].items():
        lines.append(f"- {markdown_data_inline(label)}: {count}")
    lines.extend(["", "### Argument Counts", ""])
    for label, count in summary["argument_counts"].items():
        lines.append(f"- {markdown_data_inline(label)}: {count}")

    lines.extend(["", "## Cross-Video Phrase Candidates", ""])
    lines.append(
        "| Phrase | Video DF | Total frequency | Confidence | Videos | Fragments |"
    )
    lines.append("|---|---:|---:|---|---|---|")
    for candidate in phrase_analysis.get("candidates") or []:
        confidence = candidate["confidence"]
        lines.append(
            f"| {markdown_data_inline(candidate['phrase'])} | "
            f"{candidate['document_frequency']} | {candidate['total_frequency']} | "
            f"{confidence['level']} ({confidence['score']}) | "
            f"{markdown_data_join(candidate['representative_video_ids'])} | "
            f"{markdown_data_join(candidate['source_fragment_ids'])} |"
        )

    lines.extend(["", "## Per-Video Signal Table", ""])
    lines.append("| Video ID | Hook | Argument | Ending | Boundary | Contribution | Core Question |")
    lines.append("|---|---|---|---|---|---|---|")
    for signal in signal_payload["signals"]:
        lines.append(
            "| {video_id} | {hook} | {argument} | {ending} | {boundary} | {contribution} | {question} |".format(
                video_id=markdown_data_inline(signal["video_id"]),
                hook=markdown_data_join(signal["hook_type"]),
                argument=markdown_data_join(signal["argument_mode"]),
                ending=markdown_data_join(signal["ending_mode"]),
                boundary="yes" if signal["boundary_or_risk_sample"] else "no",
                contribution=markdown_data_join(signal["contribution_types"]),
                question=markdown_data_inline(signal["core_question_candidate"]),
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def build_audit_template() -> str:
    return """# Refinement Audit

## 覆盖审计

- [ ] `input.json` 中的 taxonomy preset/version 是否与 corpus、signals、coverage 和 artifact manifest 一致？
- [ ] 是否使用 `research/host_refinement/corpus_index.json` 检查了全部样本？
- [ ] 是否逐项复核 `topic_candidates.json` 的视频证据，并在 `topic_candidate_decisions.json` 中接受、重命名、合并或拒绝？
- [ ] 是否让单视频/低置信候选继续保持推断，而没有直接升级为人格结论？
- [ ] 是否使用 `research/host_refinement/transcript_signal_matrix.md` 检查了按视频级 DF 排序的词语、开头、结尾和跨视频重复表达？
- [ ] 是否确认重复短语至少来自两个不同视频，并用 `source_fragment_ids` 回查原始片段，而不是把同视频重复当成稳定风格？
- [ ] 是否使用 `research/host_refinement/transcript_signals.json` 检查了逐条 ASR 的 hook、论证、结尾、判断和贡献类型？
- [ ] 是否使用 `research/reviews/evidence_coverage.md` 检查了证据覆盖评分？
- [ ] 是否使用 `research/reviews/coverage_gaps.md` 补读高优先级缺口视频？
- [ ] 是否使用 `research/reviews/short_form_coverage.md` 检查了短视频 hook、转折和结尾？
- [ ] 是否使用 `research/reviews/timeline_shift.md` 检查了阶段变化？
- [ ] 是否使用 `research/reviews/asr_entity_review.md` 回查片段，并在 `asr_entity_decisions.json` 处理了全部高影响专名？
- [ ] corrected 专名是否保留原始 ASR 引用，并用 `final_references` 映射到最终 Skill，而非改写 transcript？
- [ ] 是否至少覆盖 15 个视频锚点？
- [ ] 15 个锚点是否都是本次 corpus 中不同、accepted 且可映射到 metadata 的视频 ID？
- [ ] `metadata:` 角色是否只用于标题、互动、发布时间等元数据结论，脚本、语气、表达和反向识别证据是否都有非空 transcript？
- [ ] 是否覆盖高互动样本、长转写样本、短视频样本、边界/风险样本？

## 深度审计

- [ ] 是否深读了至少 8 条代表性完整转写？
- [ ] 是否把证据和推断分开？
- [ ] 是否写出跨视频重复模式，而不是单视频印象？
- [ ] 是否记录矛盾、变化和证据缺口？

## 成品审计

- [ ] `persona.md` 是否能指导选题、脚本、改写和批评？
- [ ] `topic_model.md` 是否包含带证据锚点和失败模式的模型？
- [ ] `script_style.md` 是否有分类型模板，而不是通用三段式？
- [ ] `evidence_index.md` 是否能追溯到具体视频 ID？
- [ ] `persona_model.json` 是否结构完整，并与 Markdown 结论、证据锚点一致？
- [ ] `persona_model.json` 是否包含生成协议和评测 case？
- [ ] 是否没有身份冒充、虚假背书、声音/形象克隆风险？
- [ ] 是否通过 `content_safety` 的 transcript 重叠与严格 UTF-8/乱码检查？
- [ ] 是否完成 `usage_probe.md` 的反向生成测试？
- [ ] 是否完成 `evaluation_suite.md` 的固定评测集？
- [ ] 是否同步填写 `evaluation_suite.json`，并让独立 evaluator 能按事实重算？
- [ ] 是否完成 `reverse_identification.md` 的反向识别测试？
- [ ] 是否同步填写 `reverse_identification.json`，并让独立 evaluator 能按事实重算？
- [ ] 是否完成 `reviewer_findings.md` 的二次审稿并修复关键问题？

## 结论

- 审计人：
- 审计时间：
- 是否建议 `ready_for_use=true`：
- 仍需补强：
"""


def build_usage_probe_template() -> str:
    return """# Usage Probe

## 目的

用生成后的 Creator Skill 反向测试它是否真的能驱动选题、改写、批评和证据解释。模板状态不能作为成品。

执行时必须优先读取 `skill/references/persona_model.json`，再用 `persona.md`、`topic_model.md`、`script_style.md` 和 `evidence_index.md` 校准。每个输出都要标注使用了哪些 topic model、script template、judgment heuristic、expression DNA 和 anti-pattern。

## 测试一：新选题筛选

- 输入候选：
- 选择结果：
- 拒绝结果：
- 使用的 persona_model 字段：
- 依据的视频锚点：

## 测试二：普通文稿改写

- 原始文稿：
- 改写结果：
- 保留的表达 DNA：
- 使用的 persona_model 字段：
- 依据的视频锚点：

## 测试三：不像样本批评

- 待批评片段：
- 不像的原因：
- 修正建议：
- 使用的 persona_model 字段：
- 依据的视频锚点：

## 测试四：完整脚本大纲

- 选题：
- Hook：
- 结构：
- 关键转折：
- 结尾收束：
- 使用的 persona_model 字段：
- 依据的视频锚点：

## 结论

- 是否通过反向生成测试：
- 仍需补强：
"""


def build_evaluation_suite_template() -> str:
    return """# Evaluation Suite

## 目的

用固定评测集检验最终 Creator Skill 是否能稳定驱动真实任务。模板状态不能作为成品。
配套 `evaluation_suite.json` 生成时必须保持 `status=draft_template`；6 个 case 与 scorecard 均已真实填写后才改为 `status=completed`，即使自评结论为 false 也应如实记录。case/scorecard 的 `passed` 只是声明，最终 verdict 由 quality evaluator 重算。不得使用 `ready`、`refined` 等其他状态，也不得添加 schema 未声明的字段。

执行顺序：

1. 先读 `skill/references/persona_model.json`。
2. 为每个 case 选择对应的 topic model、script template、judgment heuristic、expression DNA 和 anti-pattern。
3. 生成结果后，用 `evidence_index.md` 标注视频锚点。
4. `evidence_video_ids` 只能引用本次 corpus 中唯一、accepted 的 ID；应用 script template、expression DNA、judgment heuristic 或 anti-pattern 时，对应视频必须有非空 transcript。
5. 如果证据不足，必须降级置信度，不要补套话。

## Case 1：热点选题筛选

- 输入候选：
- 应用的 topic model：
- 应用的 judgment heuristic：
- 选择：
- 拒绝：
- 证据视频 ID：
- 置信度：

## Case 2：30 秒短视频脚本

- 输入选题：
- 应用的 script template：
- Hook：
- 主体：
- 转折：
- 结尾：
- 证据视频 ID：
- 置信度：

## Case 3：普通文案改写

- 原始文案：
- 应用的 expression DNA：
- 改写结果：
- 避开的 anti-pattern：
- 证据视频 ID：
- 置信度：

## Case 4：不像样本批评

- 待评估文本：
- 不像的地方：
- 命中的 anti-pattern：
- 修正建议：
- 证据视频 ID：
- 置信度：

## Case 5：边界请求处理

- 输入请求：
- 命中的 safety boundary：
- 处理方式：
- 替代性安全输出：
- 证据或规则依据：
- 置信度：

## Case 6：证据解释

- 输入问题：
- 使用的模型字段：
- 输出结论：
- 逐条证据说明：
- 哪些只是推断：
- 置信度：

## Scorecard

- 6 个 case 是否全部完成：否
- 每个 case 是否引用 persona_model 字段：否
- 每个 case 是否引用视频证据或安全规则：否
- 是否发现泛泛 AI 文案：是
- 是否通过评测集：否
- 仍需补强：
"""



def build_reverse_identification_template() -> str:
    return """# Reverse Identification

## 目的

对 `evaluation_suite.md` 和 `usage_probe.md` 中的生成结果做反向识别：证明哪些地方来自该创作者的稳定模式，哪些只是泛泛 AI 文案。模板状态不能作为成品。
配套 `reverse_identification.json` 生成时必须保持 `status=draft_template`；识别行和 scorecard 全部真实填写后才改为 `status=completed`，自评计数与 `passed` 只是声明，最终 marker 数量和可追溯性由 quality evaluator 重算。不得使用其他状态或添加 schema 未声明字段。
每个 `evidence_video_ids` 必须属于本次 corpus、在 `evidence_index.md` 中唯一且为 accepted，并有非空 transcript；只有 metadata 的视频不能支撑 creator-specific 表达标记。

## 识别表

| Output | Creator-specific markers | Generic AI markers | Persona model fields | Evidence video IDs | Verdict |
|---|---|---|---|---|---|
|  |  |  |  |  |  |

## 必答问题

1. 去掉创作者名字后，哪些句子仍然能体现该账号的内容方法？
2. 哪些句子只是通用短视频文案，可以出现在任何账号里？
3. 哪些判断、转折或结尾能回溯到 `persona_model.json`？
4. 哪些证据 ID 支撑这些判断？
5. 哪些输出需要重写或降级置信度？

## Scorecard

- 至少识别 5 个 creator-specific marker：否
- 至少识别 3 个 generic AI marker：否
- 每个高置信 marker 是否能回溯到 persona_model 字段：否
- 每个高置信 marker 是否能回溯到视频 ID：否
- 是否通过反向识别测试：否
- 仍需补强：
"""



def build_reviewer_template() -> str:
    return """# Reviewer Findings

## Reviewer 角色

只挑问题，不补正文。重点检查证据不足、过度抽象、模板太泛、身份越界、ASR 专名风险、评测集失败、反向识别失败和无法驱动生成的段落。

## Findings

| Severity | File | Issue | Evidence | Required Fix | Status |
|---|---|---|---|---|---|
|  |  |  |  |  |  |

## 修复确认

- 是否处理全部 high / medium 问题：
- 是否仍有低置信结论：
- 是否建议进入 `ready_for_use=true`：
"""



def build_brief(
    run_dir: Path,
    top_count: int,
    excerpt_count: int,
    excerpt_chars: int,
    *,
    preset: research_taxonomy.TaxonomyPreset | None = None,
    corpus_snapshot: corpus.CorpusSnapshot | None = None,
) -> str:
    taxonomy = preset or research_taxonomy.resolve_run_taxonomy(run_dir)
    if corpus_snapshot is not None:
        corpus_snapshot.assert_for_run(run_dir)
    selected_path = run_dir / "metadata" / "selected.compact.json"
    selected = read_json(selected_path)
    items = selected.get("items", [])
    creator = selected.get("creator_profile") or {}
    transcript_dir = run_dir / "transcripts"
    skill_dir = run_dir / "skill"

    by_score = sorted(items, key=item_score, reverse=True)
    by_length = []
    for item in items:
        artifact_id = path_policy.artifact_id_for_item(item)
        if corpus_snapshot is not None:
            document = corpus_snapshot.get(artifact_id)
            if document is not None:
                by_length.append((document.size_bytes, item))
        else:
            transcript = path_policy.artifact_path(transcript_dir, artifact_id, ".txt")
            if transcript.exists():
                by_length.append((transcript.stat().st_size, item))
    by_length.sort(reverse=True, key=lambda row: row[0])

    representative_ids = []
    for item in by_score[:excerpt_count]:
        representative_ids.append(str(item.get("platform_video_id")))
    for _, item in by_length[:excerpt_count]:
        vid = str(item.get("platform_video_id"))
        if vid not in representative_ids:
            representative_ids.append(vid)
    representative_ids = representative_ids[: max(excerpt_count * 2, excerpt_count)]
    item_by_id = {str(item.get("platform_video_id")): item for item in items}

    lines = [
        "# Host Refinement Brief",
        "",
        *untrusted_corpus_protocol_lines(),
        "",
        "配套文件：",
        "",
        "- `corpus_index.json`：全量样本索引，含互动、转写长度、主题标签、开头和结尾。",
        "- `topic_candidates.json` / `topic_candidates.md`：使用带版本的中文分词、标题/转写片段、视频级文档频率和共现生成无领域候选；每个区分词含原始片段 ID，候选不是最终人格结论。",
        "- `../reviews/topic_candidate_decisions.json`：宿主 Agent 对候选执行 accepted、renamed、merged 或 rejected 的持久化决策台账；重新 prepare 不覆盖人工决策。",
        "- `transcript_signal_matrix.md`：全量语料信号矩阵；词语按视频级 DF 优先，重复短语只统计跨至少两个视频的模式，并显示 TF、视频 ID、片段 ID 和置信度。",
        "- `transcript_signals.json` / `transcript_signals.md`：逐条 ASR 结构信号及带 tokenizer/stopword/minimum-video 版本的 `phrase_analysis`；单视频重复不会进入 `reusable_phrases`。",
        "- `../reviews/evidence_coverage.md`：证据覆盖评分，检查 evidence index 是否覆盖高互动、长转写、短转写、主题簇和边界样本。",
        "- `../reviews/coverage_gaps.md`：覆盖缺口推荐，列出下一轮最应该补读或补证据的视频。",
        "- `../reviews/short_form_coverage.md`：短视频专项覆盖，检查短转写样本的 hook、结尾和证据强度。",
        "- `../reviews/timeline_shift.md`：阶段变化评分，检查近期热点和长期内核的差异。",
        "- `../entity_dictionary.json`：项目专名扩展，可加入跨领域品牌、人物和专业术语及其别名/影响级别。",
        "- `../reviews/asr_entity_review.md`：带 candidate ID、影响级别、原始视频/片段/artifact 引用的 ASR 专名检测报告。",
        "- `../reviews/asr_entity_decisions.json`：持久四态处理层；高影响 unresolved 阻断 ready，corrected 必须回指最终 Skill，禁止改写原始 ASR。",
        "- `../reviews/refinement_audit.md`：宿主 agent 完成深加工后填写的审计清单。",
        "- `../reviews/usage_probe.md`：反向生成测试，验证 skill 是否能驱动选题、改写、批评和脚本大纲。",
        "- `../reviews/evaluation_suite.md` / `evaluation_suite.json`：固定评测集，验证 skill 是否能覆盖选题、脚本、改写、批评、边界处理和证据解释。",
        "- `../reviews/reverse_identification.md` / `reverse_identification.json`：反向识别测试，验证生成稿的 creator-specific markers 是否能回溯到 persona_model 和视频 ID。",
        "- `../reviews/reviewer_findings.md`：二次审稿问题清单，记录证据不足、过度抽象和边界风险。",
        "- `../../skill/references/persona_model.schema.json`：结构化人格模型 schema。",
        "- `../../skill/references/persona_model.json`：宿主 agent 必须填写的机器可读人格模型。",
        "",
        "## Creator",
        "",
        f"- Nickname: {markdown_data_inline(creator.get('nickname', ''))}",
        f"- Handle: {markdown_data_inline(creator.get('handle', ''))}",
        f"- Author ID: {markdown_data_inline(creator.get('author_id', ''))}",
        f"- Sec UID: {markdown_data_inline(creator.get('sec_uid', ''))}",
        f"- Requested count: {markdown_data_inline(selected.get('requested_count'))}",
        f"- Selected count: {markdown_data_inline(selected.get('selected_count'))}",
        f"- Selection strategy: {markdown_data_inline(selected.get('selection_strategy'))}",
        f"- Taxonomy preset: {taxonomy.name}",
        f"- Taxonomy version: {taxonomy.version}",
        "",
        "## Current Skill Footprint",
        "",
    ]

    for relative in [
        "SKILL.md",
        "references/persona.md",
        "references/topic_model.md",
        "references/script_style.md",
        "references/research_summary.md",
        "references/evidence_index.md",
    ]:
        path = skill_dir / relative
        size = path.stat().st_size if path.exists() else 0
        extra = ""
        if relative.endswith("evidence_index.md"):
            extra = f", table_rows={count_table_row(path)}"
        lines.append(f"- `{relative}`: {size} bytes{extra}")

    lines.extend(["", "## Top Videos By Weighted Interaction", ""])
    lines.append("| Rank | Video ID | Date | Score | Stats | Title |")
    lines.append("|---:|---|---|---:|---|---|")
    for rank, item in enumerate(by_score[:top_count], start=1):
        stats = item.get("stats") or {}
        stat_text = f"L{stats.get('like', 0)} F{stats.get('favorite', 0)} S{stats.get('share', 0)} C{stats.get('comment', 0)}"
        video_id = markdown_data_inline(item.get("platform_video_id"))
        published_at = markdown_data_inline(str(item.get("published_at", ""))[:10])
        title = markdown_data_inline(item.get("title", ""))
        lines.append(
            f"| {rank} | {video_id} | {published_at} | {item_score(item)} | {markdown_data_inline(stat_text)} | {title} |"
        )

    lines.extend(["", "## Theme Keyword Matches", ""])
    for theme, keywords in taxonomy.theme_keywords.items():
        matched = [
            item
            for item in items
            if any(keyword.lower() in str(item.get("title", "")).lower() for keyword in keywords)
        ]
        lines.append(f"### {theme} ({len(matched)})")
        for item in matched[:10]:
            title = markdown_data_inline(item.get("title", ""))
            video_id = markdown_data_inline(item.get("platform_video_id"))
            lines.append(f"- {video_id} — {title}")
        lines.append("")

    lines.extend(["## Full Title Index", ""])
    for index, item in enumerate(items, start=1):
        title = markdown_data_inline(item.get("title", ""))
        video_id = markdown_data_inline(item.get("platform_video_id"))
        published_at = markdown_data_inline(str(item.get("published_at", ""))[:10])
        lines.append(f"{index:03d}. {video_id} {published_at} {title}")

    lines.extend(["", "## Representative Transcript Excerpts", ""])
    for excerpt_index, vid in enumerate(representative_ids, start=1):
        item = item_by_id.get(vid)
        if not item:
            continue
        title = markdown_data_inline(item.get("title", ""))
        artifact_id = path_policy.artifact_id_for_item(item)
        path = path_policy.artifact_path(transcript_dir, artifact_id, ".txt")
        document = (
            corpus_snapshot.get(artifact_id)
            if corpus_snapshot is not None
            else None
        )
        length = (
            document.size_bytes
            if document is not None
            else path.stat().st_size if path.exists() else 0
        )
        excerpt = (
            document.excerpt(excerpt_chars)
            if document is not None
            else transcript_excerpt(path, excerpt_chars)
        )
        lines.extend(
            [
                f"### Transcript Sample {excerpt_index}",
                "",
                f"- Video ID: {markdown_data_inline(vid)}",
                f"- Title: {title}",
                f"- Transcript bytes: {length}",
                "",
                render_untrusted_markdown_block(
                    excerpt,
                    label=f"transcript excerpt {excerpt_index}",
                ),
                "",
            ]
        )

    lines.extend(
        [
            "## Host Agent Questions",
            "",
            "宿主 agent 精修时必须回答：",
            "",
            "1. 去掉名字后，这个账号最稳定的内容能力是什么？",
            "2. 无领域候选中哪些应接受、重命名、合并或拒绝？把理由写入决策台账；选题模型仍须至少用 2 个视频锚定。",
            "3. 哪些脚本结构跨主题重复出现？",
            "4. 表达 DNA 是结构性的，还是只是一组口头禅？",
            "5. 哪些判断启发式能指导新选题？",
            "6. 哪些反模式会让生成内容不像或越界？",
            "7. 最近 12-24 个月是否出现阶段变化？",
            "8. 哪些结论证据不足，必须标为推断？",
            "",
            "## Required Refinement Outputs",
            "",
            "- `research/raw/01_topic_and_timeline.md`",
            "- `research/raw/02_structure_and_judgment.md`",
            "- `research/raw/03_expression_and_boundary.md`",
            "- `research/raw/04_contradictions_and_evolution.md`",
            "- `research/raw/05_short_form_patterns.md`",
            "- Rewrite `skill/SKILL.md`",
            "- Rewrite `skill/references/persona.md`",
            "- Rewrite `skill/references/topic_model.md`",
            "- Rewrite `skill/references/script_style.md`",
            "- Rewrite `skill/references/research_summary.md`",
            "- Rewrite `skill/references/evidence_index.md`",
            "- Fill `skill/references/persona_model.json`",
            "- Update `skill/references/meta.json`",
            "- Fill `research/reviews/usage_probe.md`",
            "- Fill `research/reviews/topic_candidate_decisions.json`",
            "- Fill `research/reviews/evaluation_suite.md`",
            "- Fill `research/reviews/reverse_identification.md`",
            "- Fill `research/reviews/reviewer_findings.md`",
            "- Fill `research/reviews/refinement_audit.md`",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"
