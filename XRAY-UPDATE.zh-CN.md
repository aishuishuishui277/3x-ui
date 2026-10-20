# Xray 核心自动维护（与面板方案共存）

用户于 2026-10-20 确认：VPS 已更新到无赞助面板 3.10.2，Xray 26.10.10 正常运行，Reality 节点可连接。这是用户实测基线；本工具没有登录或修改 VPS。

## 自动化做什么

- 面板：原 `no-sponsor.yml` 每 6 小时追踪 3x-ui 正式版，严格补丁、编译、测试、发布照常执行。`xui-maintain update` 默认保留现有核心。
- 核心：新增 `xray.yml` 每 6 小时分别检查 XTLS 官方正式版和预发布版，最低基线 26.10.10。使用官方 Linux AMD64 二进制，核对 GitHub 资产 SHA256 和官方 `.dgst` 的 SHA2-256，不修改核心、不在 VPS 编译。
- 发布前核对 ELF 架构及二进制版本，并用 **26.10.10 客户端、新版客户端分别连接新版服务端**，实际传输 VLESS + REALITY + Vision HTTP 数据。TLS 目标与 HTTP 目标均为 CI 本地临时服务，不依赖公共伪装站。
- 测试通过才发布独立 `xray-v版本-r1` Release，保留官方的预发布标记。正式版和预发布版均只生成候选包；不持有 SSH 凭据，不自动替换线上核心。
- 现有每 28 天的仓库活动记录由面板工作流继续维护。GitHub schedule 可能延迟；失败查看 Actions，并可手动 Run workflow 重试。建议在 GitHub 仓库 Watch → Custom 中订阅 Releases；这一步由账号本人设置。

## 当前官方渠道差异

2026-10-20 读取 XTLS 官方 Release API：`26.10.10` 与 `26.10.17` 的 `prerelease=true`，最新正式版 API 返回 `26.3.27`。因此默认正式渠道目前不会提供高于你的基线的更新，也绝不把 26.3.27 装回去。

需要与现有核心同类的官方预发布版本时，检查命令明确选择 `--channel preview`；实际安装再显式加 `--allow-prerelease`。预发布包不是经本项目重新认定的正式版。

来源：[官方发布列表](https://github.com/XTLS/Xray-core/releases)、[26.10.17](https://github.com/XTLS/Xray-core/releases/tag/v26.10.17)、[26.10.10](https://github.com/XTLS/Xray-core/releases/tag/v26.10.10)。3x-ui 源码依据：v3.10.2 的 `internal/web/service/server.go`（下载 `.dgst` 和 `UpdateXray`）、`internal/xray/process.go`（从数据库生成配置并启动核心）。

## 已安装原方案的 VPS：只需升级维护工具一次

如果你沿用原方案的 `/opt/3x-ui-maintenance` 克隆目录，直接执行：

```bash
sudo git -C /opt/3x-ui-maintenance pull --ff-only
sudo bash /opt/3x-ui-maintenance/server/install.sh
sudo xui-maintain inspect
sudo xray-maintain check --channel preview
```

如果 pull 报错或目录不存在，停止这条路径，改用下面的完整源码包安装方法，不执行来源不明的已有文件。完整源码包可从本说明所在 GitHub 分支页面的 Code → Download ZIP 下载；也可在 VPS 使用 git clone（目录需尚不存在）：

```bash
sudo git clone --depth 1 --branch maintenance-no-sponsor \
  https://github.com/aishuishuishui277/3x-ui.git /opt/3x-ui-maintenance
```

下载本仓库 **maintenance-no-sponsor 分支的完整源码包**，解压后进入目录执行：

```bash
sudo bash server/install.sh
sudo xui-maintain inspect
```

这会安装/更新 `/usr/local/sbin/xui-maintain` 和 `/usr/local/sbin/xray-maintain`。沿用 `/etc/x-ui-maintainer.json`，无需重新 init；不重启面板、不改 systemd sandbox、不更新核心。如果此前只部署了面板、尚未初始化维护工具，请先按 `INSTALL-NOW.md` 初始化健康检查地址。

更新工具时下载完整目录，不能只下载新核心脚本：核心脚本需要同目录的 `xui-maintain`。下载源码包失败时停止，不执行不完整的脚本。

## 日常检查与批准

```bash
# 检查并下载已经通过 GitHub 测试的正式渠道候选；不重启服务
sudo xray-maintain check

# 检查官方预发布渠道；与你当前 26.10.10 的官方渠道一致
sudo xray-maintain check --channel preview

# 或明确检查某个候选
sudo xray-maintain check xray-v26.10.17-r1 --channel preview
```

检查会显示准确版本、官方预发布标记、包 SHA256 和完整的批准命令。复制该次输出的命令才执行安装。每个新包都需批准自己的 SHA256，不能用旧哈希或 `latest` 批准未来未知版本。若核心已相同或更新，停止并保留当前核心。

首个候选包 `26.10.17-r1` 已公开发布，并下载后再次通过服务器包验证器。它的准确 SHA256 如下；先运行上面的 check 核对一致，只有决定升级时才执行：

```bash
sudo xray-maintain update xray-v26.10.17-r1 \
  --approve 51d76443b7e94c8a5317fbfac19766530efdfb6699dc4dbe5e99cbd877924c02 \
  --allow-prerelease
```

下一版不能沿用这一哈希，使用下一次 check 输出的命令。发布包和验证报告见 [xray-v26.10.17-r1](https://github.com/aishuishuishui277/3x-ui/releases/tag/xray-v26.10.17-r1)。

执行时再次核对完整包/报告、现场生成配置和当前地理数据；配置不兼容时在停服务前拒绝。通过后短暂停止整个 x-ui 服务，备份旧核心，原子替换，启动原服务，并检查面板健康、Xray 子进程、SQLite 完整性及 Reality 节点配置指纹。默认等待 15 秒后再检健康。此操作会短暂中断连接。

核心更新仅替换 `xray-linux-amd64`。面板、SQLite/WAL、UUID、Reality 私钥、端口和 geoip/geosite 文件不由该工具覆盖。面板启动时仍会按原机制从数据库生成 `config.json`。核心更新与面板更新共享锁和未完成事务记录，不能并发更新。

**更新成功后用你实际的 Reality 客户端连接验证。** CI 本地传输和服务器配置/健康检查不能证明你家网络到 VPS 的外部连接正常，也不能覆盖所有自定义协议或路由。

## 一键回滚核心

```bash
sudo xray-maintain backups
sudo xray-maintain rollback 上面列出的备份ID --approve-rollback
```

恢复旧核心前校验备份和现场配置；恢复后用原 systemd 服务启动。故障核心另存救援副本。**不恢复旧数据库，不回退已累计流量，不改地理数据。** 备份位于 `/var/lib/x-ui-maintainer/core-backups/`，配置诊断副本含节点密钥，应仅 root 访问。

更新中断后若提示未完成核心事务：

```bash
sudo xray-maintain recover --approve-rollback
```

面板事务仍用 `xui-maintain recover --approve-rollback`。两个工具会检查事务类型并指向正确命令。不要手工删除 pending.json 绕过恢复。

## 可选：VPS 定时下载检查，仍不自动部署

```bash
sudo bash server/install-xray-watch.sh preview
# 只接受正式渠道则把 preview 改成 stable
systemctl list-timers xray-maintain-check.timer
journalctl -u xray-maintain-check.service -n 50 --no-pager
```

该可选脚本只创建专用检查服务/定时器；每 6 小时检查一次，成功下载后在日志中打印批准命令。不改 x-ui.service 或其 sandbox，也不包含自动 update 命令。不要同时使用面板的自动核心更新任务，以免出现另一条不经过批准的替换路径。

停用：`sudo systemctl disable --now xray-maintain-check.timer`。候选包检查占用存储，已有同一标签会重新校验/暂存；脚本不会自动清理用于恢复的备份。

## 保留原方案的边界

面板更新默认保留你安装的新核心。`--with-bundled-xray` 是原有显式可选项，仅在你确实需要面板随包核心时使用；如果随包核心比现场核心旧，脚本在停服前拒绝。正常回退核心使用 `xray-maintain rollback`。

未来面板上游改动赞助入口或随包核心版本时，原严格校验仍可能停止面板构建，需要一次源码复核；独立核心工作流可继续检查。自动化不通过放宽补丁指纹、跳过测试或隐藏失败来保证每版必定发布。

SHA256 在 GitHub HTTPS 信任边界内校验完整性，不能等同于独立发布者签名。包内包含官方 MIT LICENSE，并链接官方对应版本源码。
