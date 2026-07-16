"""Creator skill draft construction from deterministic run artifacts."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import provenance
from creator_metadata import read_json, safe_filename
from io_utils import atomic_write_json as write_json
from pipeline_models import StepResult


def build_creator_skill(run_dir: Path, project_name: str, overwrite: bool = True) -> Path:
    skill_dir = run_dir / "skill"
    if (skill_dir / "SKILL.md").exists() and (skill_dir / "SKILL.md").stat().st_size > 20 and not overwrite:
        return skill_dir

    refs = skill_dir / "references"
    refs.mkdir(parents=True, exist_ok=True)
    research_summary = run_dir / "research" / "merged" / "summary.md"
    creator_profile_path = run_dir / "metadata" / "creator_profile.json"
    summary_text = research_summary.read_text(encoding="utf-8") if research_summary.exists() else ""
    creator_profile = read_json(creator_profile_path) if creator_profile_path.exists() else {}
    display_name = creator_profile.get("nickname") or project_name
    created_at = datetime.now(timezone.utc).isoformat()
    governance = provenance.record_for_skill(run_dir, fallback_time=created_at)

    disclaimer = (
        "这是一个基于公开或授权材料生成的 AI 创作者风格辅助 Skill。"
        "它不代表创作者本人，也不得用于身份冒充、虚假背书或误导性代言。"
    )
    evidence_draft = "完整转写稿保存在 skill 外部。这里仅添加简短、改写后的证据笔记。"
    evidence_text = """# 证据索引

## 结构化记录格式

覆盖率只解析下列表格格式；正文、列表和其他文件中偶然出现的视频 ID 不算证据。
`Status` 使用 `accepted` 或 `rejected`。`rejected` 必须填写 `Reason`，它不会增加证据分数，但会关闭对应缺口。
每个 `Video ID` 必须属于本次 corpus，且只能有一条不冲突的决策记录。重复、伪造或同时 accepted/rejected 的 ID 都会阻断引用完整性。

| Video ID | Status | Reason | Finding |
|---|---|---|---|

## 初稿证据笔记

""" + evidence_draft
    files = {
        refs / "research_summary.md": summary_text or "# 研究摘要\n\n尚未生成转写摘要。\n",
        refs / "persona.md": "# 人设与边界\n\n" + disclaimer + "\n\n## 结构化模型优先级\n\n生成、改写、批评和拒绝请求前，先读取 `persona_model.json`，按其中的 `generation_protocol` 选择 topic model、script template、judgment heuristic、expression DNA、anti-pattern 和 safety boundary。\n\n",
        refs / "topic_model.md": "# 选题模型\n\n优先使用 `persona_model.json` 的 `topic_models` 和 `generation_protocol.task_routing` 判断选题；本文件用于展开解释和证据补充。\n\n根据转写研究笔记提出选题，并明确标注证据强弱。\n\n## 选题判断模型\n\n",
        refs / "script_style.md": "# 脚本风格\n\n优先使用 `persona_model.json` 的 `script_templates`、`expression_dna` 和 `anti_patterns` 生成或批评脚本；本文件用于展开结构、节奏和语感。\n\n优先参考证据索引中观察到的开头、节奏和结构模式。\n\n## Hook 模式\n\n\n\n## 表达 DNA\n\n",
        refs / "evidence_index.md": evidence_text,
    }
    for path, text in files.items():
        path.write_text(text, encoding="utf-8")
    write_json(
        refs / "meta.json",
        {
            "name": display_name,
            "project_name": project_name,
            "creator_profile": creator_profile,
            "created_at": created_at,
            "source": "thousand-faces-style-skill",
            "safety_boundary": True,
            **provenance.skill_meta_fields(governance),
        },
    )

    governance_lines = "\n".join(
        (
            f"- 来源平台：{provenance.markdown_inline(governance['source_platform'])}",
            f"- 采集时间：{provenance.markdown_inline(governance['source_collected_at'])}",
            f"- 权利依据：`{governance['rights_basis']}`",
            f"- 本地保留策略：`{governance['retention_policy']}`",
            f"- 退出/下架联系：{provenance.markdown_inline(governance['takedown_contact'])}",
            f"- 使用边界：{provenance.markdown_inline(governance['usage_boundary'])}",
        )
    )

    skill_md = f"""---
name: creator-{safe_filename(project_name, "creator")}
description: "基于公开或授权内容转写研究生成的创作者风格辅助 Skill。适用于中文场景下的选题、提纲、脚本、改写和风格批评任务，必须遵守免责声明与安全边界。"
---

# {display_name} 创作者 Skill

## 免责声明

{disclaimer}

## 来源与使用边界

{governance_lines}

## 工作模式

- 选题：输出包含角度、冲突、演示方式和匹配度的选题卡。
- 提纲：生成短视频结构，包括开头、主体、转折和结尾。
- 脚本：起草脚本，但不得声称这些话由创作者本人说过。
- 改写：把用户提供的材料改写得更接近研究到的表达方式，但不得冒充本人。
- 批评：根据研究笔记评分，并说明哪里匹配、哪里不匹配。

## 使用参考

- 先读 `references/persona_model.json`。按 `generation_protocol.field_order` 选择结构化字段，并记录使用了哪些 topic model、script template、judgment heuristic、expression DNA、anti-pattern 和 safety boundary。
- 再读 `references/research_summary.md`。
- 用 `references/topic_model.md` 判断选题。
- 用 `references/script_style.md` 判断结构、节奏和表达。
- 用 `references/evidence_index.md` 做证据锚定。
- 遵守 `references/persona.md` 中的安全边界。

## 生成协议

1. 识别任务类型：选题、提纲、脚本、改写、批评或越界请求。
2. 从 `persona_model.json` 选择对应字段，不要只凭泛泛风格描述生成。
3. 每个高置信判断至少绑定证据 ID；证据不足时降级为推断。
4. 输出前检查 `anti_patterns` 和 `safety_boundaries`，删除通用 AI 腔和身份越界表述。
5. 对风格批评类任务，指出 creator-specific markers、generic AI markers 和对应证据。

## 安全规则

- 不要声称自己是该创作者。
- 不要声称创作者认可、批准或说过生成内容。
- 不要克隆声音、脸、私人身份或私密信息。
- 证据以改写和摘要为主，只有确有必要时才使用很短的原文片段。
"""
    (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")
    return skill_dir


def build_creator_skill_step(run_dir: Path, project_name: str, *, overwrite: bool = True) -> StepResult:
    started = time.monotonic()
    skill_dir = build_creator_skill(run_dir, project_name, overwrite=overwrite)
    return StepResult.succeeded(
        "build_creator_skill",
        duration_ms=round((time.monotonic() - started) * 1000),
        output_paths=(str(skill_dir / "SKILL.md"),),
    )
