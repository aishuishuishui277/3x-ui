# 3x-ui 自动去赞助维护包

适用对象：`aishuishuishui277/3x-ui`，美国 Debian x86_64、现有原版 3x-ui 3.10.0、Xray 26.10.10、SQLite、systemd 安装。核查日期：2026-10-20。

**以后由 GitHub 自动跟踪正式版、检查补丁、编译和发布；VPS 下载并校验构建包，由你批准具体包后更新。无需再次 Fork、手工改源代码、手机编译或 Termux SCP。**

GitHub 阶段已获授权并落地：`maintenance-no-sponsor` 分支已上传且设为默认分支，`v3.10.0-ns1` 和 `v3.10.2-ns1` 均已通过真实 Linux 构建、全部测试和隔离启动检查，并公开发布。VPS 尚未连接或修改。详细记录见 `VERIFICATION.md`。首次服务器更新和真实 Reality 客户端验收仍需单独批准；原版 3.10.0 用户可先使用 3.10.0-ns1 做同版本去广告，具体命令见 `INSTALL-NOW.md`。

## 已从真实源码确认的内容

| 项目 | 本次核对结果 |
|---|---|
| 现有分支 | `no-sponsor-v3.10.0-fixed`，HEAD `c69f1d5e58bfc2ce71870d3395617330c176e611` |
| 该分支的实际改动 | 相对 v3.10.0，仅修改后端 `GetSponsors()` 和 `.github/workflows/release.yml` |
| v3.10.0 | 提交 `74c3cc38821cabd66ad316ea562851422d0b0063` |
| 最新正式版 | v3.10.2，2026-10-14 发布，提交 `608ef4e4010bf83e2e78328e08f77efc051ad4d7` |
| 上游构建要求 | Go 1.27.2、Node 26；先构建 React 前端，再把 dist 嵌入 Go；SQLite 需要 CGO |
| 原版打包 | Linux AMD64 静态程序；官方发布包中包含 Xray 26.10.10 |
| 原版默认目录 | `/usr/local/x-ui/x-ui`、`/usr/local/x-ui/bin`、`/etc/x-ui/x-ui.db`；允许环境变量改变目录 |
| sandbox | 原版 service 自带限制和路径白名单；本工具保留 service、drop-in 和环境文件 |

来源：[上游 v3.10.0 工作流](https://github.com/MHSanaei/3x-ui/blob/v3.10.0/.github/workflows/release.yml)、[v3.10.2 Release](https://github.com/MHSanaei/3x-ui/releases/tag/v3.10.2)、[现有 Fork](https://github.com/aishuishuishui277/3x-ui/tree/no-sponsor-v3.10.0-fixed)、[后端赞助代码](https://github.com/MHSanaei/3x-ui/blob/v3.10.2/internal/web/service/panel/sponsor.go)、[service](https://github.com/MHSanaei/3x-ui/blob/v3.10.0/x-ui.service.debian)、[配置目录](https://github.com/MHSanaei/3x-ui/blob/v3.10.0/internal/config/config.go)。

## 自动维护如何工作

1. Actions 每 6 小时查询上游正式 Release，跳过 draft、prerelease 和 `dev-latest`；也可手工指定稳定标签。
2. 单独下载该标签源码，记录真实提交。已核查过的标签若移动到其他提交，直接停止。
3. 对 6 个关键源文件校验完整内容指纹、13 种语言的赞助词条校验内容指纹，同时检查含 sponsor 的源码文件清单。只有与已审查的 3.10.0 或 3.10.2 结构匹配才应用补丁，拒绝模糊匹配。
4. 后端赞助列表固定为空，Logo 请求固定拒绝；前端不请求赞助数据，广告位、赞助菜单、赞助招募页均不展示，并清理页面移除后不再使用的翻译词条。
5. 保留上游原赞助实现为私有方法，原有相关测试转向这些私有方法；另加测试验证公共接口不发网络请求、无广告渲染。没有通过删除测试来掩盖行为变化。
6. 执行维护工具测试、前端类型检查、前端 unit/components 测试、前端构建、Go 全量测试，再构建静态 Linux AMD64。
7. 下载同一正式版的官方 AMD64 包并核对官方 SHA256，从中提取 Xray；当前仅接受已审查的 26.10.10。此提取不会把原版面板放入自定义包。
8. 使用临时数据库和端口启动新面板，测试登录 HTML、空赞助 API、Logo 404。测试不接触线上数据库。
9. 全部通过后上传 Actions Artifact；先创建草稿 Release、上传完整资产，再公开发布 `v3.10.2-ns1` 等独立标签。中途失败不会对 VPS 提供一个半成品公开 Release。
10. VPS 的 `check` 只检查和下载；`update` 必须给出明确标签和刚校验的完整 SHA256 才会停服更新。

未来正式版如果保留相同关键源码结构，会自动继续构建。**赞助结构、关键文件或捆绑 Xray 版本变化时会暂停，需要维护者审查补丁；无法同时保证“任何未来源码变化都全自动适配”和“严格验证绝不误改”。你无需再在手机上编译；这类变化应在仓库中修维护规则。** 文件清单检查不能识别所有换名后的广告代码，仍需对上游重大变更进行审查。

## 第一次把维护文件放入现有 Fork

推荐建立独立的 `maintenance-no-sponsor` 分支，只放维护工具，并把它设为默认分支。原 `main` 和 `no-sponsor-v3.10.0-fixed` 分支继续保留。这避免把上游原工作流带入新的自动维护入口。

GitHub 的 schedule 运行默认分支中的工作流；所以只往旧的非默认分支上传文件，不足以启用定时维护。[GitHub 官方说明](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)。

在 Windows 解压本包后，打开该文件夹的 PowerShell：

```powershell
gh auth login
gh auth setup-git
.\Publish-ToFork.ps1
```

上一条只显示操作范围。确认后执行：

```powershell
.\Publish-ToFork.ps1 -Publish
```

该命令创建新分支、上传本包文件、修改默认分支并触发第一次构建。不会修改服务器。如果让助手执行这一阶段，需要你明确授权这三项仓库写入操作，并先完成 GitHub 登录；不要把访问令牌粘贴到聊天。

打开 [Fork 的 Actions](https://github.com/aishuishuishui277/3x-ui/actions)，如出现 Fork 工作流未启用提示，先点击启用。仓库设置若限制 Actions 权限，需要允许本工作流的 `contents: write`；构建 job 仅有读权限，发布 job 和每 28 天记录一次定时检查的 job 才有写权限。不需要配置 VPS 密钥、PAT 或 SSH Secret。

每 28 天自动提交一份定时检查活动记录，以维持空闲 Fork 的仓库活动。若分支保护禁止机器人推送，需要允许这条维护分支上的工作流写入，或自行承担定时任务因长期无仓库活动而被停用的维护。公开仓库空闲 60 天时 schedule 可能自动关闭，见 [GitHub 官方说明](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows)。

仓库已有同名维护分支时，发布脚本会停止，不会覆盖它。后续修改直接向该分支提交维护文件即可。

## 第一次构建及下载

默认跟踪最新正式版。若希望先对当前 3.10.0 做同版本去广告，手工触发一次：

```powershell
gh workflow run no-sponsor.yml --repo aishuishuishui277/3x-ui --ref maintenance-no-sponsor -f upstream_tag=v3.10.0
gh run list --repo aishuishuishui277/3x-ui --workflow no-sponsor.yml --limit 5
```

等待通过，打开 [Releases](https://github.com/aishuishuishui277/3x-ui/releases)。每版提供：

- `x-ui-panel-linux-amd64.tar.gz`：自定义面板、可选 Xray、内嵌 manifest、GPL 许可证。不是原版完整安装包。
- `source-patched.tar.gz`：对应修改源码及维护脚本，满足可核查与重建需要。
- `SHA256SUMS`、`manifest.json`、`patch-report.json`、`validation.json`。

发布标签不标记为仓库的 `latest`，避免干扰旧版上游更新器；服务器脚本会筛选并比较 `vX.Y.Z-nsN` 标签。已有同版已公开构建不覆盖。修改补丁后若需要重新发布同一上游版，在 `track.py` 中把 `ns1` 增为 `ns2`。

## 在美国 VPS 上安装更新工具：只做一次

需要 Debian 12/13 或有当前 Python 3.11+ 安全更新的 Debian，systemd、root 管理权限，原版根用户运行的服务。脚本拒绝 Docker、非 AMD64、非 SQLite、软链接主程序、目录重叠等未经适配安装。

**以下仓库地址需在上一步上传成功后才存在。** 在 VPS SSH 会话运行：

```bash
sudo apt-get update
sudo apt-get install -y git python3 curl ca-certificates
sudo git clone --depth 1 --branch maintenance-no-sponsor \
  https://github.com/aishuishuishui277/3x-ui.git /opt/3x-ui-maintenance
sudo bash /opt/3x-ui-maintenance/server/install.sh
```

只安装 `/usr/local/sbin/xui-maintain` 和私有备份目录，不覆盖面板，也不停服。可以先审阅 `/opt/3x-ui-maintenance/server/xui-maintain.py`，并把克隆提交与已批准的维护提交核对。

用你实际的本机面板入口初始化，包含端口、秘密路径、末尾 `/`。例如面板在本机 HTTP 2053、入口路径是 `/my-panel/`：

```bash
sudo xui-maintain init --health-url http://127.0.0.1:2053/my-panel/
sudo xui-maintain inspect
```

不要原样使用示例路径。若面板只监听某个内网 IP，HTTP 检查可通过 `localhost` 加 `--resolve localhost:2053:实际监听IP` 指向它。

面板直接使用 HTTPS 或经本机反向代理时，使用证书对应域名，并将该域名解析到本机的实际监听地址：

```bash
sudo xui-maintain init \
  --health-url https://panel.example.com:2053/my-panel/ \
  --resolve panel.example.com:2053:127.0.0.1
```

如果本机反代监听 443，则 URL 和 `--resolve` 一并使用 443。`example.com` 必须替换。检查不会用 `-k` 跳过证书校验，因此证书读取失败后悄悄退回 HTTP 的情况会被拦住。

`init` 从正在运行的 systemd 主进程读取真实执行目录和 `XUI_DB_FOLDER`/`XUI_BIN_FOLDER`，不盲信默认路径；配置写到 root 私有的 `/etc/x-ui-maintainer.json`。它不修改现有 unit、drop-in、`/etc/default/x-ui`、面板账号、端口或节点设置。路径或健康检查不通过时先修正初始化，服务仍保持原状。

## 每次更新：检查、批准一次即可

先下载并验证最新自定义正式构建，**此命令不会停止服务**：

```bash
sudo xui-maintain check
```

或者先给当前原版 3.10.0 做同版替换：

```bash
sudo xui-maintain check v3.10.0-ns1
```

成功后会打印标签、完整 SHA256 和可以直接复制的一条 `update` 命令。例如：

```bash
sudo xui-maintain update v3.10.0-ns1 --approve 刚才输出的64位SHA256
```

这就是批准部署：没有正确 SHA256 就拒绝执行。默认只换面板，**现有 Xray 26.10.10 和 Geo 文件保留**。不下载或执行上游 `install.sh`/`update.sh`，不会重新生成 sandbox。

操作顺序为：检查现有服务、数据库、Xray 配置和空间 → 确认包校验/架构/版本 → 停服 → SQLite Backup API 备份（包含 WAL 已提交数据）→ 备份原面板、整个 bin、数据库附属文件及 unit 文本 → 写恢复记录 → 原子替换面板 → 启动 → 检查登录页、空赞助接口、Xray 子进程、数据库完整性、Reality 配置指纹，并再次检测稳定状态。

出现异常会停止新服务，恢复旧面板、旧 SQLite、原 bin 配置并启动旧服务。备份保存在 `/var/lib/x-ui-maintainer/backups/`，权限受限；它可能包含私钥、UUID、密码和节点配置，别上传到公开仓库。流量计数等数据库状态随回滚恢复到备份时间。

**面板健康不等于远端 Reality 端到端成功。** 更新完成后用原客户端实际连接一次，检查出口、访问和订阅；若失败直接执行下节回滚。更新和回滚都会重启面板及其 Xray 子进程，现有连接会短暂中断。未来版本若新功能要求新核心，保留旧核心模式可能无法使用该功能；当前不会静默升级核心来解决。

若明确需要把核心也换为本次包中已核查的 26.10.10：

```bash
sudo xui-maintain update v3.10.2-ns1 --approve 对应SHA256 --with-bundled-xray
```

只替换 Xray 可执行文件，Geo 文件继续保留。上游改为新核心版本时构建会停止，需审查 `package.py` 的核心版本策略后再放行。

## 一条命令回滚

```bash
sudo xui-maintain backups
sudo xui-maintain rollback 实际备份ID --approve-rollback
```

回滚使用本机备份，不依赖 GitHub，也允许当前服务无法启动或当前数据库损坏。执行前会另存当前文件到 `rescue-*` 目录，保留诊断材料。备份校验失败就停止；如果恢复后的健康检查仍失败，保留已恢复状态和 rescue，检查日志。

如果更新期间 VPS 断电、进程被 `kill -9` 或 SSH 环境导致不可捕获中断，不能承诺进程自动执行清理。更新前已写的 `pending.json` 会保留恢复位置；重新登录后执行：

```bash
sudo xui-maintain recover --approve-rollback
```

可捕获异常、SIGTERM 和 Ctrl+C 走自动恢复；再次发生中断或磁盘故障时应检查 pending/backup，不能当作正常更新成功。

若在停服后的初始备份阶段就断电，可能尚未生成 pending；此时程序尚未替换主程序，可先用 `sudo systemctl start x-ui` 启动原版本，再检查备份目录。完整备份及恢复记录会在替换前刷新到磁盘，但磁盘本身损坏仍需独立备份。

## 维护及失败处理

| 现象 | 操作 |
|---|---|
| `Unknown sponsor source fingerprint` | 查看新的上游赞助源码差异；修改补丁和已审查指纹，跑测试后提交维护分支。不要关闭指纹检查 |
| `Bundled core changed` | 核对新核心与当前节点及配置兼容性，明确选择后再调整打包策略 |
| 前端/Go 测试失败 | 看失败日志并修复；旧公开构建、线上版本保持原样 |
| 官方下载失败或 403/限流 | 工作流重新运行；不绕过 SHA256，不用未知镜像替代 |
| unit 权限、路径、TLS、Xray 配置错误 | `inspect`、`systemctl status x-ui`、`journalctl -u x-ui -n 100`；按现有 sandbox 解决，不自动放宽限制 |
| `Unfinished update` | 检查 pending 状态，运行 `recover --approve-rollback` |
| 同标签已发布但资产不全 | 人工检查 Release，勿盲目覆盖公开资产；可用新的 ns 修订号重新构建 |

GitHub 中可设置工作流失败通知；成功构建和所有失败都有 Actions 日志。不要继续使用面板里的原版“更新面板”、上游 `x-ui update` 或原 `install.sh`，这些入口仍可能装回官方带赞助版本。本工具不会更改原项目的更新逻辑。

自动构建不向 VPS 推送文件，不保存服务器密钥；批准部署由服务器命令负责。本包未设置任何后台自动部署 timer，也没有在 Codex 中创建提醒或定时任务。

SHA256 用于发现下载损坏和校验所批准的包，不是独立于 GitHub 仓库权限的签名。构建报告会记录上游提交、维护提交和 Actions 运行链接；首次使用应核对这些记录。备份不自动删除，定期查看磁盘空间并保留至少一个已确认可用的备份。
# Xray 核心维护扩展（2026-10-20）

已增加与面板方案共存的 XTLS 官方核心候选工作流、REALITY + Vision 实际本地传输测试、独立批准更新和只恢复核心的回滚。现有 VPS 不需要重新部署面板。安装与使用见 [XRAY-UPDATE.zh-CN.md](XRAY-UPDATE.zh-CN.md)。

