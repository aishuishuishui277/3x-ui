# 本次交付的验证边界

检查日期：2026-10-20；本地环境为 Windows。用户已明确允许 GitHub 阶段，维护分支已上传并设为默认分支，已触发真实 Actions。VPS 尚未连接或部署。

## 已完成

- 直接读取并下载公开上游 `v3.10.0`、`v3.10.2` 真实源码，以及用户已有 `no-sponsor-v3.10.0-fixed` 分支。
- 比较确认现有 Fork 仅修改赞助服务和原 release 工作流；确认前端构建必须先于 Go embed 编译。
- 通过 GitHub API 核查最新正式版 v3.10.2、发布时间和官方 AMD64 文件名及 `.sha256` 附件存在。
- 两版真实源码均成功应用严格指纹补丁；6 个指定文件和 13 种语言的赞助词条全部匹配，完整报告保存在 `evidence/` 中。
- 16 项维护单元/场景测试通过：真实 SQLite WAL 备份、包校验及篡改拒绝、路径穿越/链接/架构拒绝、未批准更新不触发停服、未知补丁/新入口拒绝、版本标签校验、保留核心/显式换核心、健康失败恢复、可捕获中断恢复、服务离线且当前 DB 损坏时的备份回滚，以及在停服前拒绝把共享系统目录作为安装目录。
- 场景测试实际读写临时面板文件、核心配置、SQLite 数据库及备份；systemd、HTTP、Linux 程序执行、root 所有权为替身。它证明恢复流程的文件和数据库行为，不证明线上服务兼容性。
- `actionlint 1.7.12` 对最终工作流的静态检查通过。检查工具来自其官方发行包并经 SHA256 对照。
- Bash 安装脚本语法检查、PowerShell 发布脚本语法解析、Python 编译检查通过。

## 已通过的 v3.10.2 远端 Actions 验收

- Go 1.27.2 + Node 26 的实际安装与依赖解析通过。
- 162 个前端测试文件、1,747 项 unit/components 测试全部通过，包括新增无广告渲染测试。
- `go test -timeout 15m ./...` 通过，日志列出 50 个通过测试的 Go 包，包括去赞助公共接口测试。
- Linux AMD64 静态链接、ELF 架构及 `3.10.2` 版本输出通过。
- 官方发布包 SHA256 校验及 Xray 26.10.10 版本检查通过。
- 临时数据库启动面板、登录 HTML、空赞助 API、Logo 404 全部通过。
- Artifacts 上传及草稿 Release 完整上传后公开发布通过。
- 已独立下载实际公开的 `v3.10.2-ns1` 包，用服务器脚本 `validate_package()` 验证通过。

Release：https://github.com/aishuishuishui277/3x-ui/releases/tag/v3.10.2-ns1

面板包 SHA256：`b0b0a205eab804aee0776e16abbc06c33cd890ca3d82b2b9a43621c3e3059e48`

上游源码提交 `608ef4e4010bf83e2e78328e08f77efc051ad4d7`，构建维护提交 `8cbf06671e0b24a7820b454a57265264642eb18e`。

以上构建验收已完成。真实 VPS/systemd、线上 SQLite 和客户端 Reality 验收仍未执行。

## 已通过的 v3.10.0 同版本构建验收

运行 https://github.com/aishuishuishui277/3x-ui/actions/runs/39363071547 同样全部成功：162 个前端文件、1,747 项前端测试、Go 全量测试、AMD64 静态编译、官方 Xray 26.10.10 校验、隔离面板启动与去赞助接口检查、Artifacts 上传和 Release 发布。

Release：https://github.com/aishuishuishui277/3x-ui/releases/tag/v3.10.0-ns1

面板包 SHA256：`744c1ef7d9d5b242f84e6773d1c2c021c30a3b57a163298d022f5585e8396971`

原版 3.10.0 用户可先选择此包进行同版本去广告；默认保留现有核心。两个版本的公开面板包、源码、manifest、补丁和测试报告均已独立下载并全部校验 SHA256；两包也均被服务器脚本校验器接受。线上 Reality 成功与否仍需部署后的实际客户端验收。

## 日常跳过重复构建已实测

运行 https://github.com/aishuishuishui277/3x-ui/actions/runs/39364229079 成功：当前维护提交 `73e9f98497d91ffcc95de2ce64a27d36b5aa9f27` 在 Linux 通过 16 项维护测试，检测到已发布的 `v3.10.2-ns1` 后跳过补丁、Go/Node 环境、编译、打包和发布，没有重写现有 Release。

默认分支已实际设为 `maintenance-no-sponsor`；每 6 小时 schedule 已放在该默认分支中。尚未等待到第一个自然定时时刻，已验证的是同一工作流的 push/手工触发路径；每 28 天 activity 提交也尚未自然触发。

## 首次远端运行发现并修复的问题

首次运行 https://github.com/aishuishuishui277/3x-ui/actions/runs/39361969279 ：Linux 上 15 项维护测试、补丁指纹、Go/Node 环境和前端类型检查通过；1,747 项前端测试有 1 项失败，原因为赞助页面移除后留下 5 个未使用翻译词条。新增的无广告渲染测试通过。构建按设计停止，未发布 Release。

修复已清理全部 13 种语言中不再使用的页面词条，并为赞助翻译子树增加严格指纹。保留原测试；对 3.10.0 额外存在的赞助页面词条也作相同清理。修复提交 `8cbf06671e0b24a7820b454a57265264642eb18e`，重新运行 https://github.com/aishuishuishui277/3x-ui/actions/runs/39362569369 。

## 必须在获准部署后验证

- 用户 VPS 的实际 Debian/Python 版本、服务主进程、运行路径、sandbox 和 TLS 权限。
- 原始 SQLite 的完整性、实际 WAL 状态及备份。
- 更新后 Reality 私钥、UUID、端口、stream settings 等指纹保持，以及保留核心模式下 Xray 文件哈希保持。
- 手机或其他原客户端实际连接 Reality、访问目标网站、出口与订阅行为。

本包只移除 3x-ui 赞助展示，不解决前述 v0.9.1 客户端连接故障，也没有声称改善线路丢包或增加 Hy2 支持。

## Xray 自动维护扩展验收（2026-10-20）

用户现已确认：VPS 已部署无赞助面板 3.10.2、Xray 26.10.10，Reality 节点可正常连接。这是用户报告的线上实测结果；助手没有登录 VPS，也没有替换线上核心。

新增 `.github/workflows/xray.yml` 与原面板工作流共存，配置每 6 小时追踪官方核心；正式和预发布渠道分开，最低基线 26.10.10。官方最新正式 API 当前返回较旧的 26.3.27；用户当前核心与新候选 26.10.17 都是官方预发布版。没有把预发布版重新称为正式版，也不会自动降级现场核心。

完整发布运行：[39370348040](https://github.com/aishuishuishui277/3x-ui/actions/runs/39370348040)，维护提交 `790286e3d74d2fce97a34a6ba22cad705689cdf1`：

- Linux 维护测试通过；官方 ZIP 与 `.dgst` 两个 GitHub 资产 SHA256、ZIP 的官方 SHA2-256、二进制 ELF AMD64 和版本匹配均通过。
- 26.10.10 客户端 → 26.10.17 服务端、26.10.17 客户端 → 26.10.17 服务端，两组真实 VLESS + REALITY + Vision 传输均返回 HTTP 200，接收内容与随机测试标记完全一致。
- 发布为保留官方预发布标记的 [xray-v26.10.17-r1](https://github.com/aishuishuishui277/3x-ui/releases/tag/xray-v26.10.17-r1)，4 个资产均已公开。包 SHA256：`51d76443b7e94c8a5317fbfac19766530efdfb6699dc4dbe5e99cbd877924c02`。
- 下载公开包、manifest、验证报告和校验清单后，再次通过 `server/xray-maintain.py` 的真实包验证器。该步骤没有执行下载的 Linux 二进制，也未连接 VPS。
- 独立核心脚本共享原配置、锁和事务标记；故障与手工回滚只恢复核心文件，SQLite WAL 中更新后的流量值保持。维护测试另覆盖面板随包旧核心被拒绝降级现场新核心。

最初测试曾被两道实际问题拦下：核心默认私有目标拦截命中了 CI 本地 HTTP 目标，测试配置增加了仅该临时端口的 allow；单个 Actions 产物下载路径与多产物目录不同，发布脚本已兼容两者，并增加发布后的资产检查。没有改变 VPS 配置或跳过 REALITY 传输测试。

维护工具目前本地及 Linux 均有 28 项测试通过：[核心最终回归](https://github.com/aishuishuishui277/3x-ui/actions/runs/39370574886)、[原面板工作流回归](https://github.com/aishuishuishui277/3x-ui/actions/runs/39370574872)，代码提交 `fc21b13dd6437a10c267db4b3a4d8c0c032ad959`。详情见 `evidence/xray-acceptance.json`、`evidence/xray-local-tests.txt`、`evidence/ci-xray-26.10.17.txt`。两条工作流均识别现有已发布版本，跳过重复构建、传输测试和资产发布，没有改写现有公开 Release。

未验证范围：助手没有在用户 VPS 执行新核心脚本，尚未实测用户外网到 26.10.17 的连接；自然 schedule 与 VPS 可选检查 timer 尚未等到首次自然执行。现场部署后仍需用户用原 Reality 客户端验收。
