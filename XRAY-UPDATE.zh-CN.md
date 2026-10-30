# Xray 独立候选维护（2026-10-30 修复）

本次只在本地修复分支验证，没有推送、合并、发布或连接任何 VPS。旧版结果存于 VERIFICATION.md，不能把历史 26.10.10 基线用于当前构建。

## 三种版本角色

| 角色 | 来源 | 当前值 |
|---|---|---|
| 独立候选最低允许版本 | maintenance/xray-policy.json 的 minimum_candidate_version | v26.10.21 |
| REALITY 客户端回归基线 | 同文件 reality_baseline 与 baseline_assets | v26.10.21，两个官方资产 SHA256 已审核并固定 |
| 面板随包核心 | maintenance/profiles.json 对应版本的 bundle | v3.10.2 → 26.10.10；v3.11.0 → 26.10.21 |

三个角色分别读取和校验，不能因为独立候选变成 26.10.29，就把面板官方安装包的核心替换成它。旧面板的 26.10.10 按该面板官方归档摘要与已审查二进制摘要校验，不再访问已经 404 的 Xray v26.10.10 Release API。

官方 API 核验：[26.10.21](https://github.com/XTLS/Xray-core/releases/tag/v26.10.21) 和 [26.10.29](https://github.com/XTLS/Xray-core/releases/tag/v26.10.29) 当前均为正式版。需要预发布版时才选择 preview，保留官方标记。

## 自动化与真实测试

两条工作流改为每日两次检查：面板北京时间 10:23、22:23，核心 10:47、22:47。GitHub schedule 可能延迟。手动 workflow_dispatch 随时可用，不必为低频正式发布每六小时重复下载或报错。

只使用官方未修改的 Linux AMD64 核心，严格校验 GitHub 资产摘要、官方 .dgst SHA2-256、ELF 和实际版本。基线资产还必须匹配审核时固定的摘要，删除、替换或校验失败均阻止发布。

真实流量测试分别使用 26.10.21 基线客户端和候选客户端连接候选服务端，实际传输 REALITY + Vision 数据并比较随机正文。临时 TLS、HTTP 目标、UUID 和密钥都仅在本机/CI 临时目录中创建，不读取或修改 VPS 的 Reality 配置。

完整 Release 已发布时返回 NO_UPDATE，不下载候选或基线。preview 不重复构建 stable 已覆盖的正式版。手动标签由匹配的渠道执行；validate_existing 可重新验证，仍不能覆盖已有公开 Release。

首次真实失败仍让 workflow 失败，分别记录 BUILD_FAILED / TEST_FAILED。之后相同输入、资产和维护代码的定时检查记录原阻塞状态，跳过重试，不会将原失败改成通过。workflow_dispatch、代码/策略或官方资产变化会重新尝试。Actions cache 被清理时可能重新发现一次失败；缓存不能授权发布或代替校验。

## 发布与审批边界

修复分支 push 只能验证并提供 Artifact。发布只允许稳定维护分支 schedule 或 publish=true 的手动操作，手动默认不发布。上传前校验全部文件清单、SHA256、manifest 和真实测试报告，草稿资产再与 GitHub API 摘要逐项比较，全部符合才公开。

服务端安装、审批和回滚代码本次保持原样。面板更新默认保留现场核心，--with-bundled-xray 不允许随包旧核心降级现场新核心。核心单独批准 SHA256 后才能替换，回滚只恢复核心，不恢复旧数据库、SQLite WAL 或地理数据。

未来经批准合并后的正式渠道检查仍为：

~~~bash
sudo xray-maintain check
~~~

官方预发布渠道才使用：

~~~bash
sudo xray-maintain check --channel preview
~~~

检查输出具体批准命令；仅用户执行该命令才会停止服务更新。回滚仍为 xray-maintain rollback 备份ID --approve-rollback，中断恢复仍为 xray-maintain recover --approve-rollback。

本次不执行这些服务器命令，不修改 VPS timer、systemd、证书、数据库或节点。旧有 VPS 可选检查 timer 的频率未改动。

## 本地复现核心验证（隔离 Linux x86_64）

需要 Python 3.11+、openssl、curl 和联网访问官方 GitHub。在本仓库独立工作副本执行，以下没有发布动作：

~~~bash
export GITHUB_REPOSITORY=aishuishuishui277/3x-ui
export GITHUB_SHA=local-validation-unpublished
export GITHUB_RUN_ID=local
export GITHUB_OUTPUT="$PWD/local-core-output.txt"
export CHANNEL=stable XRAY_TAG=v26.10.29 FORCE_VALIDATE=true
python3 maintenance/xray_release.py
python3 maintenance/xray_smoke.py
python3 maintenance/verify_release.py core xray-dist
~~~

生成目录为本地验证结果，不能据此声称已经发布或验证用户外部网络。测试基线消失时应复核更新策略，不能跳过旧客户端流量测试。
