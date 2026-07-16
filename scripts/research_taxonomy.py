#!/usr/bin/env python3
"""Versioned, explicit taxonomy presets for creator research heuristics."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


DEFAULT_TAXONOMY_PRESET = "generic_zh_creator"
TAXONOMY_PRESET_VERSION = "1.0.0"


class TaxonomyPresetError(ValueError):
    """Raised when a requested taxonomy preset cannot be resolved exactly."""


def _immutable_keyword_map(
    groups: Mapping[str, tuple[str, ...]],
) -> Mapping[str, tuple[str, ...]]:
    """Copy keyword groups into a read-only mapping with immutable values."""

    return MappingProxyType(
        {label: tuple(keywords) for label, keywords in groups.items()}
    )


@dataclass(frozen=True)
class TaxonomyPreset:
    """Immutable-by-contract keyword groups consumed by research derivations."""

    name: str
    version: str
    theme_keywords: Mapping[str, tuple[str, ...]]
    hook_keywords: Mapping[str, tuple[str, ...]]
    argument_keywords: Mapping[str, tuple[str, ...]]
    ending_keywords: Mapping[str, tuple[str, ...]]
    judgment_keywords: tuple[str, ...]
    entity_patterns: tuple[str, ...]
    theme_contributions: Mapping[str, tuple[str, ...]]
    boundary_themes: tuple[str, ...]
    boundary_keywords: tuple[str, ...]

    def __post_init__(self) -> None:
        """Prevent callers from mutating shared registry data through a preset."""

        object.__setattr__(
            self,
            "theme_keywords",
            _immutable_keyword_map(self.theme_keywords),
        )
        object.__setattr__(
            self,
            "hook_keywords",
            _immutable_keyword_map(self.hook_keywords),
        )
        object.__setattr__(
            self,
            "argument_keywords",
            _immutable_keyword_map(self.argument_keywords),
        )
        object.__setattr__(
            self,
            "ending_keywords",
            _immutable_keyword_map(self.ending_keywords),
        )
        object.__setattr__(
            self,
            "theme_contributions",
            _immutable_keyword_map(self.theme_contributions),
        )

    def identity(self) -> dict[str, str]:
        """Return the stable public identity persisted in run artifacts."""

        return {"preset": self.name, "version": self.version}


TECH_CREATOR = TaxonomyPreset(
    name="tech_creator",
    version=TAXONOMY_PRESET_VERSION,
    theme_keywords={
        "AI / Agent / 模型": (
            "AI",
            "Agent",
            "智能体",
            "模型",
            "DeepSeek",
            "豆包",
            "Kimi",
            "Gemini",
            "Grok",
            "OpenAI",
            "Codex",
            "Claude",
        ),
        "工具教程 / 低门槛": (
            "教程",
            "免费",
            "上手",
            "工具",
            "PPT",
            "学习",
            "API",
            "中转站",
            "提示词",
            "vibecoding",
        ),
        "比赛 / 实验 / 模拟": (
            "比赛",
            "竞技",
            "大逃杀",
            "测评",
            "挑战",
            "预测",
            "外挂",
            "测试",
            "PK",
            "大战",
        ),
        "硬件 / 机器人 / 汽车": (
            "机器人",
            "手机",
            "汽车",
            "眼镜",
            "iPhone",
            "Siri",
            "华为",
            "宇树",
            "硬件",
        ),
        "现场 / 发布会 / 探访": (
            "现场",
            "发布会",
            "I/O",
            "迪士尼",
            "探访",
            "谷歌",
            "香港",
            "实验室",
        ),
        "教育 / 高考 / 学习": (
            "高考",
            "志愿",
            "作文",
            "数学",
            "学习",
            "学生",
            "论文",
            "毕业",
        ),
        "风险 / 灰区 / 安全": (
            "黑客",
            "注入",
            "安全",
            "举报",
            "灰色",
            "中转站",
            "攻击",
            "造假",
            "跑路",
        ),
    },
    hook_keywords={
        "反常识 / 离谱设定": (
            "你以为",
            "没想到",
            "离谱",
            "疯了",
            "炸了",
            "震惊",
            "竟然",
            "到底",
        ),
        "直接任务 / 教程入口": (
            "怎么",
            "如何",
            "教程",
            "上手",
            "一步",
            "免费",
            "工具",
            "普通人",
        ),
        "现场目击 / 发布会入口": (
            "现场",
            "发布会",
            "我在",
            "探访",
            "体验",
            "刚刚",
            "今天",
        ),
        "风险提示 / 灰区入口": (
            "风险",
            "黑客",
            "攻击",
            "注入",
            "安全",
            "举报",
            "灰色",
            "跑路",
        ),
    },
    argument_keywords={
        "实验演示": ("实验", "测试", "测评", "比赛", "PK", "挑战", "规则"),
        "步骤教程": ("第一步", "第二步", "接下来", "打开", "输入", "点击", "设置"),
        "机制拆解": ("原理", "机制", "为什么", "本质", "逻辑", "背后", "拆解"),
        "案例对照": ("比如", "案例", "相比", "对比", "以前", "现在", "国外", "国内"),
        "现场观察": ("现场", "看到", "体验", "发布会", "展台", "工作人员"),
    },
    ending_keywords={
        "能力边界判断": ("说明", "证明", "边界", "能力", "短板", "局限"),
        "行动建议": ("建议", "可以试试", "不要", "最好", "记住", "收藏"),
        "趋势判断": ("未来", "趋势", "接下来", "会变成", "意味着"),
        "风险收束": ("风险", "警惕", "安全", "别碰", "违规", "灰色"),
    },
    judgment_keywords=(
        "普通人",
        "门槛",
        "效率",
        "成本",
        "风险",
        "安全",
        "能力",
        "边界",
        "体验",
        "生态",
        "平台",
        "开源",
    ),
    entity_patterns=(
        "OpenAI",
        "Claude",
        "Gemini",
        "Kimi",
        "DeepSeek",
        "Codex",
        "Qoder",
        "TRAE",
        "Grok",
        "Google I/O",
        "Vision Pro",
        "Seedance",
        "GPT",
        "Agent",
        "API",
        "Steam",
        "eSIM",
    ),
    theme_contributions={
        "比赛 / 实验 / 模拟": ("script_template:experiment",),
        "工具教程 / 低门槛": ("topic_model:low_barrier_tutorial",),
        "教育 / 高考 / 学习": ("topic_model:low_barrier_tutorial",),
        "现场 / 发布会 / 探访": ("script_template:field_report",),
        "风险 / 灰区 / 安全": ("safety_boundary:risk_gray_area",),
    },
    boundary_themes=("风险 / 灰区 / 安全",),
    boundary_keywords=("黑客", "注入", "安全", "攻击", "灰色", "跑路", "举报", "违规"),
)


GENERIC_ZH_CREATOR = TaxonomyPreset(
    name=DEFAULT_TAXONOMY_PRESET,
    version=TAXONOMY_PRESET_VERSION,
    theme_keywords={
        "教程 / 方法": ("教程", "步骤", "方法", "如何", "怎么", "指南"),
        "案例 / 体验": ("案例", "体验", "实测", "现场", "故事", "经历"),
        "观点 / 解释": ("为什么", "原因", "机制", "观点", "分析", "解释"),
        "风险 / 边界": ("风险", "安全", "边界", "注意", "避免", "警惕"),
    },
    hook_keywords={
        "问题 / 悬念入口": ("为什么", "怎么", "如何", "到底", "是不是", "能不能"),
        "反差 / 转折入口": ("你以为", "没想到", "其实", "但是", "结果", "反而"),
        "直接任务 / 方法入口": ("怎么", "如何", "步骤", "方法", "教程", "先"),
        "现场 / 体验入口": ("现场", "我在", "体验", "刚刚", "今天", "亲自"),
    },
    argument_keywords={
        "步骤说明": ("第一步", "第二步", "接下来", "首先", "然后", "最后"),
        "机制解释": ("原理", "机制", "为什么", "本质", "逻辑", "背后", "原因"),
        "案例说明": ("比如", "例如", "案例", "经历", "故事"),
        "比较对照": ("相比", "对比", "以前", "现在", "一方面", "另一方面"),
        "现场观察": ("现场", "看到", "体验", "观察", "实测", "记录"),
    },
    ending_keywords={
        "边界判断": ("说明", "边界", "适用", "限制", "局限", "条件"),
        "行动建议": ("建议", "可以", "不要", "最好", "记住", "尝试"),
        "趋势判断": ("未来", "趋势", "接下来", "变化", "意味着"),
        "风险提醒": ("风险", "警惕", "安全", "避免", "注意", "违规"),
    },
    judgment_keywords=("门槛", "效率", "成本", "风险", "安全", "边界", "体验", "适用"),
    entity_patterns=(),
    theme_contributions={
        "教程 / 方法": ("topic_model:method_tutorial",),
        "案例 / 体验": ("script_template:case_or_experience",),
        "观点 / 解释": ("judgment_heuristic:explanation",),
        "风险 / 边界": ("safety_boundary:risk_and_limits",),
    },
    boundary_themes=("风险 / 边界",),
    boundary_keywords=("风险", "安全", "违规", "伤害", "欺骗", "隐私", "警惕", "避免"),
)


_PRESETS = {
    GENERIC_ZH_CREATOR.name: GENERIC_ZH_CREATOR,
    TECH_CREATOR.name: TECH_CREATOR,
}


def available_taxonomy_presets() -> tuple[str, ...]:
    return tuple(sorted(_PRESETS))


def get_taxonomy_preset(
    name: str | None = None,
    version: str | None = None,
) -> TaxonomyPreset:
    """Resolve one exact preset; never silently substitute an unknown request."""

    requested_name = DEFAULT_TAXONOMY_PRESET if name is None else name
    available = ", ".join(available_taxonomy_presets())
    if not isinstance(requested_name, str) or requested_name not in _PRESETS:
        raise TaxonomyPresetError(
            f"unknown taxonomy preset {requested_name!r}; available presets: {available}"
        )
    preset = _PRESETS[requested_name]
    if version is not None and version != preset.version:
        raise TaxonomyPresetError(
            f"taxonomy preset {requested_name!r} version mismatch: "
            f"requested {version!r}, available {preset.version!r}"
        )
    return preset


def resolve_run_taxonomy(run_dir: Path) -> TaxonomyPreset:
    """Resolve the version recorded by a run, defaulting legacy runs to generic."""

    input_path = Path(run_dir) / "input.json"
    if not input_path.is_file():
        return get_taxonomy_preset()
    try:
        payload = json.loads(input_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise TaxonomyPresetError("run input.json is not readable taxonomy metadata") from error
    if not isinstance(payload, dict):
        raise TaxonomyPresetError("run input.json must be an object containing taxonomy metadata")
    name = payload.get("taxonomy_preset")
    version = payload.get("taxonomy_version")
    if name is not None and not isinstance(name, str):
        raise TaxonomyPresetError("run taxonomy_preset must be a string")
    if version is not None and not isinstance(version, str):
        raise TaxonomyPresetError("run taxonomy_version must be a string")
    if (name is None) != (version is None):
        raise TaxonomyPresetError(
            "run taxonomy metadata is incomplete; both preset and version are required"
        )
    return get_taxonomy_preset(name, version)
