# 安全策略

本项目处理外部 URL、媒体文件、转写文本、供应商凭证和可能含个人信息的创作者语料。请把疑似 SSRF、路径穿越、任意文件读写、凭证泄露、越权、供应链污染、提示注入越界或安全门禁绕过按安全问题处理。

## 支持范围

| 版本或分支 | 安全修复状态 |
|---|---|
| `main` 当前代码 | 接受报告并尽力修复 |
| Git tag / GitHub Release | 尚未发布，不作支持承诺 |
| 无格式清单的历史 run | 仅支持只读诊断，不在原目录修复或迁移 |

`pyproject.toml` 中的 `0.1.0` 是首个候选发布的开发基线，不代表已经存在可下载或受长期支持的发布。首次正式发布后，维护者必须在本表中列出仍接收安全修复的版本范围。

## 报告流程

<!-- security-reporting: public-contact-with-private-handoff -->

当前仓库尚未启用 GitHub Private Vulnerability Reporting，因此采用“公开联络、私密交接”的明确流程：

1. 打开一个[仅用于请求私密联络的 issue](https://github.com/lem1272536013/thousand-faces/issues/new?title=%5BSECURITY%5D%20Private%20contact%20request)。标题可保持预填内容，正文只写受影响的组件名称和“需要私密交接”；不要在公开 issue 中提交漏洞细节、复现步骤、日志、样本、密钥或利用代码。
2. 维护者确认后创建 GitHub draft security advisory，并将报告者加入该私密协作区。报告者只在安全公告中提交完整材料；公开 issue 随后关闭并引用非敏感状态说明。
3. 如果维护者以后启用 Private Vulnerability Reporting，应把本节改为仓库的私密报告入口，并同步更新 `security-reporting` 标记和发布元数据测试。

此流程没有承诺响应 SLA。在收到维护者的私密交接确认前，请不要把公开 issue 视为漏洞已被安全接收；也不要为了催促而公开技术细节。

私密报告建议包含：

- 受影响的 commit、候选发布版本，以及相关 run/schema/preset 版本；
- 影响、前置条件、攻击边界和最小可复现步骤；
- 使用合成数据得到的预期结果与实际结果；
- 已知缓解方式、修复建议和是否疑似已被利用；
- 希望在公告中使用的署名，或明确要求匿名。

## 敏感日志与样本

提交前只保留证明问题所需的最小片段，并逐项脱敏：

- 删除或替换 API key、token、Cookie、Authorization header、OSS 凭证和其他 secret；若真实 secret 曾出现在任何报告、日志或提交中，先在对应供应商处撤销或轮换，不要等待代码修复。
- 删除签名 URL 的 query、临时下载地址、真实 bucket/key、内部 endpoint、用户名目录和本机绝对路径。
- 不提交完整 transcript、原始媒体、完整供应商响应或创作者私有语料；使用短小的合成重现，并把域名固定为 `example.invalid`。
- 删除姓名、电话、邮箱、账号 ID、精确位置等个人信息；必须保留的数据应使用稳定的合成标识符。
- 不把 `.env`、run 目录、`logs/`、`reports/`、缓存或包含真实数据的压缩包作为附件上传。

即使私密安全公告限制了可见范围，也仍要遵守最小披露原则。哈希、错误码、字段名和经过裁剪的堆栈通常足以定位问题；如果必须提供更大样本，应先与维护者约定传输和删除方式。

## 协调修复与公开披露

维护者会先确认影响范围，再在私密分支或最小补丁中修复并补充回归测试。公开安全公告前应尽可能准备可用修复版本、受影响版本范围、迁移或缓解步骤，并避免在修复可用前泄露可直接利用的细节。

一般功能 bug、质量规则建议、文档问题以及不跨越权限或信任边界的模型输出偏差，请使用普通 issue；不要把安全通道作为优先级升级渠道。

流程依据：GitHub 官方文档说明，未启用私密漏洞报告的仓库应遵循安全策略，或创建不含漏洞信息的 issue 询问首选安全联系方式；仓库安全公告可用于私密讨论和修复。

- [GitHub：Privately reporting a security vulnerability](https://docs.github.com/code-security/security-advisories/guidance-on-reporting-and-writing/privately-reporting-a-security-vulnerability)
- [GitHub：Creating a repository security advisory](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/fix-reported-vulnerabilities/create-repository-advisory)
