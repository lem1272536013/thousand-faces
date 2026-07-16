# 版本与兼容策略

本项目同时发布代码、命令行行为和多种持久化产物。它们是不同契约轴：版本号不要求相同，也不能因为项目版本变化就机械提升全部 schema；反过来，任何持久化 schema/preset 变化都必须进入项目 changelog 和一个新的项目发布。

项目版本遵循 [Semantic Versioning 2.0.0](https://semver.org/)。changelog 采用 [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/) 的 `[Unreleased]` 和变更类型结构。

## 当前对外版本基线

<!-- versioning-metadata:current:start -->
| 版本源 | 当前值 | 对外含义 |
|---|---|---|
| `package_cli` | `0.1.0` | 项目代码和 CLI 行为的候选发布版本 |
| `scripts/run_diagnostics.py::RUN_FORMAT_SCHEMA_VERSION` | `1` | run 根格式及其可写入兼容边界 |
| `scripts/settings.py::SETTINGS_SCHEMA_VERSION` | `2` | `config.snapshot.json` 的设置快照格式 |
| `scripts/schema_validation.py::SCHEMA_VERSION` | `1.1.0` | persona、evaluation suite、reverse identification 严格 JSON Schema 族 |
| `scripts/research_taxonomy.py::TAXONOMY_PRESET_VERSION` | `1.0.0` | 持久化 taxonomy preset 的精确语义版本 |
<!-- versioning-metadata:current:end -->

`scripts/verify_release_metadata.py` 会从源码 AST 读取这些值，并扫描所有模块级 `*_SCHEMA_VERSION` / `*_PRESET_VERSION` 字面量。它不导入运行模块、不读取 `.env`、不访问 Git 或网络。

## 各版本轴的职责

| 轴 | 唯一版本源 | 何时提升 | 旧数据原则 |
|---|---|---|---|
| 项目 / CLI | `pyproject.toml` 的 `project.version` | 对外命令、退出码、默认行为或发布内容变化 | CLI 兼容性由 release notes 说明，不另造一个相同数字的 CLI schema |
| run format | `RUN_FORMAT_SCHEMA_VERSION` | 根清单、必需 artifact、跨文件语义或可恢复性边界变化 | `SUPPORTED_FORMAT_VERSIONS` 显式列出可写版本；未知未来版本拒绝，缺少清单的目录标为 `legacy_unverified` |
| settings snapshot | `SETTINGS_SCHEMA_VERSION` | 非敏感配置快照的字段、类型或解释变化 | 旧快照不能阻断只读诊断；需要继续写入时必须有显式支持或重建 run |
| persona schema 族 | `schema_validation.SCHEMA_VERSION` | persona/evaluation/reverse JSON 的有效实例集合或消费者契约变化 | 运行时按 `$id` 和 `x-schema-version` 严格验证；不匹配不能伪装为通过 |
| taxonomy preset | `TAXONOMY_PRESET_VERSION` | 分类标签、关键词、贡献映射或边界语义变化 | run 持久化 preset 名称和精确版本；解析器不能静默替换成“最新”版本 |
| 内部持久化 schema | 各 owner 模块的 `*_SCHEMA_VERSION` | 对应 JSON/manifest 的结构或解释变化 | 由 run format 包含；若变化破坏 run 兼容性，还必须提升 run format |
| producer/algorithm | owner 的 producer/config/freshness 版本 | 计算逻辑或缓存新鲜度变化 | 主要用于重算和审计，不自动等同于 schema 或项目版本 |

persona 模型实例中的 `"version": "1.0"` 是模型内容模板版本，不是 JSON Schema 版本。两者不得互相替代。

## 项目 SemVer 规则

当前处于 `0.x` 初始开发期。SemVer 允许该阶段快速变化，但本项目采用更严格的发布约束：

- `PATCH`：只用于向后兼容的 bug、安全或文档修复，且不改变公开 CLI、有效产物集合、taxonomy 语义或迁移要求。
- `MINOR`：新增对外能力、标记弃用，或引入任何不兼容 CLI/产物变化。`0.x` 阶段的不兼容变化不能只升 patch。
- `1.0.0` 之后：向后兼容功能升 MINOR，向后兼容修复升 PATCH，任何公开契约不兼容变化升 MAJOR。

发布过的版本内容不可被原地替换；修复必须形成新版本。Git tag、`pyproject.toml`、发布标题和 changelog 标题必须一致。

## run 与嵌套 schema

run format 是跨文件兼容总开关。以下任一变化通常需要提升 `RUN_FORMAT_SCHEMA_VERSION`：

- 增删继续写入所必需的根清单或 artifact；
- 改变 workflow 状态、证据归属、路径身份或 readiness 的持久化语义；
- 旧 reader 无法安全忽略的新字段，或旧数据无法满足的新必需字段；
- 嵌套 schema 变化导致旧 run 不能继续诊断、恢复或质量检查。

同版本内只允许真正双向安全的兼容扩展。reader 必须显式拒绝未知未来版本；不得把 `legacy_unverified` 自动升级成当前格式，也不得在缺少来源证据时补造根清单。当前没有原地 migrator，处理旧 run 的方式是只读诊断后从原始授权来源新建 run。

## persona schema 兼容性

persona/evaluation/reverse schema 使用 SemVer，但兼容性按“旧 reader 能否验证并正确解释新实例”判断。当前 schema 使用 `additionalProperties: false`；新增一个看似可选的属性也可能被旧 validator 拒绝，因此不能默认视为 MINOR。

- 有效实例集合、必需字段、字段类型、枚举或语义发生变化时，按不兼容变更处理并提升 MAJOR。
- MINOR 只用于不改变既有实例有效性和旧消费者解释的新增能力；无法证明时按 MAJOR。
- PATCH 只用于不改变验证集合的说明、标题或注解修正。

schema 提升必须同时增加旧版本拒绝/迁移测试、更新 `$id` 和 `x-schema-version`，并说明已有精修产物如何处理。

## taxonomy preset 兼容性

taxonomy 决定主题、开头、论证、结尾、判断词和安全边界的派生结果。标签重命名、含义变化或映射重构升 MAJOR；保持原标签语义的新增分类能力或行为关键词变化至少升 MINOR；不改变分类行为的拼写/文档修复才可升 PATCH。

运行时按名称和精确版本解析。任何版本提升都必须保留旧 preset 实现，或明确将旧 run 限制为只读并提供重建步骤；不能静默替换旧 run 的 taxonomy 后重算质量结论。

## 变更与发布清单

修改任一 schema/preset 时，同一 PR 必须完成：

1. 更新 owner 常量、reader/writer、生成物和测试。
2. 说明向前/向后兼容性；补当前、旧版和未知未来版本测试。
3. 在 `CHANGELOG.md` 的 `[Unreleased]` 中写出影响、breaking change 和 legacy 处理。
4. 同步 changelog 的完整当前版本表；若属于上面的对外轴，还要同步本文基线表。
5. 判断是否同时提升 run format 与项目版本，运行发布元数据、生成物和全量测试门禁。

首个候选发布版本是 `0.1.0`。发布前必须把 `[Unreleased]` 的 breaking changes 和 legacy run 策略审完；真正创建 tag/release 时再写发布日期，本开发任务不预造发布记录。
