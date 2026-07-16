# 贡献指南

感谢参与 Thousand Faces。这个项目把外部媒体、转写语料和宿主精修产物串成可恢复流水线，因此贡献的首要要求是：行为可证明、产物可追溯、测试不接触真实凭证或网络。

安全漏洞不要提交普通修复 issue；请先按 [SECURITY.md](SECURITY.md) 完成无细节的私密交接。

## 开发环境

项目支持 Python 3.11。请在独立虚拟环境内安装开发依赖，不以全局 Python 环境的结果判断项目健康。

```powershell
python -m venv .venv
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pip check
```

Linux/macOS 可把解释器路径换成 `./.venv/bin/python`；本文命令统一写成 `python`，CI 会在 Windows 和 Linux 上执行同一门禁。

## 行为修改与测试

新增或改变行为必须先有失败测试。bug 修复应先提交能稳定复现根因的测试，再做最小实现；不能只断言“命令运行过”，而要断言产物、状态、退出码或拒绝原因。

- 单元测试覆盖纯解析、状态转换、边界值和错误码。
- 集成测试覆盖 run 创建、恢复、质量门禁和产物之间的不变量。
- 安全测试覆盖不可信 URL、路径、媒体、transcript 和凭证边界。
- 性能测试使用确定性合成 corpus，不把墙钟偶发波动当作唯一断言。
- 修改公共产物格式时，必须同时增加旧格式测试、明确迁移策略，并更新版本常量和 changelog。

定向测试先运行受影响文件；提交前执行完整门禁：

```powershell
python -m pytest tests/test_release_metadata.py -q
python -m ruff check .
python -m mypy scripts
python scripts/generate_config_docs.py --check
python scripts/verify_release_metadata.py
python scripts/verify_docs_commands.py
python -m pytest -q
python scripts/self_test.py
python -m pip check
```

pytest 临时目录应位于系统临时目录；不要把测试产物写入仓库的 `runs/`、`logs/` 或根目录。Windows 上若需要显式指定，可使用 `--basetemp` 指向新建的系统临时子目录。

## Fixture 与脱敏

fixture 只能使用短小、可审查、可再分发的合成数据：

- 不得使用真实凭证、`.env` 内容、Cookie、Authorization header、签名 URL 或真实供应商 token。
- 域名使用 `example.invalid`；账号、视频和人物使用稳定的合成 ID，不使用真实创作者私有内容。
- transcript 只保留证明行为所需的短句，不复制长篇受版权保护文本，不放置个人信息。
- 外部服务响应使用脱敏录制 fixture 或本地 mock；默认测试不得访问真实 TikHub、ASR、OSS、LLM 或任意公网地址。
- 新增 fixture 时更新 `tests/fixtures/manifest.json`，说明来源是 synthetic/redacted、用途和对应测试。
- 恶意输入必须明显标为不可信数据，不能在测试收集、日志格式化或文档构建时被执行。

## 任务与 PR 粒度

一个 PR 只处理一个 TF 或一个可独立回滚的逻辑问题。不要把无关格式化、依赖升级、架构重构和功能变更混在一起；发现必须扩大范围时，先更新 `plan/PLAN.md` 的依赖、边界和验收标准。

提交前先查看 `git status --short`，区分自己的改动、用户已有改动和生成文件。不要使用 `git add .`；只暂存本任务文件。除非维护者明确要求，不提交 `.env`、运行产物、报告、覆盖率文件、日志或缓存。

## schema/preset 与发布元数据

版本轴和兼容规则见 [references/versioning.md](references/versioning.md)。修改任一持久化 schema/preset 版本时必须在同一个 PR 中完成：

1. 更新唯一源常量及其读写方，不能只改生成 JSON 中的数字。
2. 说明兼容方向、旧 reader/new reader 行为和 legacy run 处理方式。
3. 增加当前格式、旧格式、未来未知版本的测试；不支持迁移时要快速失败并给出重建步骤。
4. 在 `CHANGELOG.md` 的 `[Unreleased]` 中写清人类可读变更，并同步机器校验的当前版本清单。
5. 若影响 CLI 或对外产物，按 `0.x`/稳定期策略提升项目版本；各版本轴不能为了“看起来一致”而强行改成相同数字。
6. 运行 `python scripts/verify_release_metadata.py`，证明源码、版本策略和 changelog 无漂移。

生成的配置模板、配置表和 `references/settings.schema.json` 必须通过 `python scripts/generate_config_docs.py --check`；不要手工维护生成区块。

## PR 自检清单

- [ ] 变更范围与一个 TF/逻辑问题一致，未混入无关文件。
- [ ] 行为变更已有先红后绿的测试，错误路径和退出码有断言。
- [ ] fixture 为 synthetic/redacted，未读取真实 `.env`，未发起真实网络请求。
- [ ] schema/preset、CLI 或配置变更已更新兼容说明和 `CHANGELOG.md`。
- [ ] Ruff、Mypy、生成物 drift、发布元数据、文档命令、全量 pytest、self-test 和 pip check 通过。
- [ ] `git diff --check` 无新增空白错误，`git status --short` 中没有意外产物或 secret。
