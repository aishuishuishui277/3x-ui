# 当前 Fork 已配置完成后的 VPS 操作

维护分支及定时工作流已上线，无需再 Fork、编译或通过 Termux SCP。以下步骤仅在你批准服务器部署后执行；本次尚未连接 VPS。

可下载构建：

- 当前原版 3.10.0 的同版本去广告：[v3.10.0-ns1](https://github.com/aishuishuishui277/3x-ui/releases/tag/v3.10.0-ns1)。
- 升级到新正式版：[v3.10.2-ns1](https://github.com/aishuishuishui277/3x-ui/releases/tag/v3.10.2-ns1)。

两个版本均通过完整构建门槛。先选择 3.10.0-ns1 可把第一次变更限制在去广告；默认不替换现有 Xray 26.10.10。

## 一次性安装更新工具

在美国 Debian x86_64 VPS 的 SSH 会话中：

```bash
sudo apt-get update
sudo apt-get install -y git python3 curl ca-certificates
sudo git clone --depth 1 --branch maintenance-no-sponsor \
  https://github.com/aishuishuishui277/3x-ui.git /opt/3x-ui-maintenance
sudo bash /opt/3x-ui-maintenance/server/install.sh
```

如果 `/opt/3x-ui-maintenance` 已存在，先确认它是本仓库的维护分支，再使用 `git pull --ff-only` 更新，不覆盖其他目录。安装工具本身不会停止或替换面板。

将下面示例中的端口和秘密入口路径换为实际值，末尾保留 `/`：

```bash
sudo xui-maintain init --health-url http://127.0.0.1:2053/实际入口路径/
sudo xui-maintain inspect
sudo xui-maintain check v3.10.0-ns1
```

HTTPS 的域名/证书和本机反代配置方法见 `README.zh-CN.md`。初始化读取正在运行的服务路径，检查数据库、核心和现有服务；不修改 unit、sandbox、节点、账号或端口。共享系统目录会被拒绝。

## 批准一次面板更新

`check` 输出的 SHA256 必须与下面完全相同。确认部署后执行这一条，服务会短暂重启：

```bash
sudo xui-maintain update v3.10.0-ns1 \
  --approve 744c1ef7d9d5b242f84e6773d1c2c021c30a3b57a163298d022f5585e8396971
```

默认保留 Xray/Geo，备份 SQLite（包括 WAL）、旧面板和核心配置，健康检查失败则自动恢复。成功后在原手机/客户端实际连接 Reality 并访问目标网站。

若远端客户端连接有问题，使用更新输出的备份 ID：

```bash
sudo xui-maintain backups
sudo xui-maintain rollback 实际备份ID --approve-rollback
```

## 以后每次更新

```bash
sudo xui-maintain check
```

它自动寻找最新已验证的去广告构建、下载并校验，打印一条含真实 SHA256 的批准命令。执行打印出的命令即可；不用重新 Fork、修改或编译。GitHub 每 6 小时检查上游；已发布同版本跳过重复编译，补丁结构变化或任何验证失败则停止发布。

不要点击原版面板“更新面板”或运行原版 `x-ui update`，这些入口仍可能装回官方带赞助构建。使用 `xui-maintain` 维护本版本。
