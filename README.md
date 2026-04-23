<p align="center">
  <img src="./icon.svg" width="120" alt="AutoSign icon" />
</p>

<h1 align="center">AutoSign</h1>

<p align="center">
  北航 iClass 自动签到工具集（默认分支：CLI）
</p>

<p align="center">
  <a href="https://pypi.org/project/autosign-buaa-cli/"><img alt="PyPI" src="https://img.shields.io/pypi/v/autosign-buaa-cli"></a>
  <a href="https://pypi.org/project/autosign-buaa-cli/"><img alt="Python" src="https://img.shields.io/pypi/pyversions/autosign-buaa-cli"></a>
  <a href="https://github.com/DeNeRATe-cool/AutoSign/stargazers"><img alt="Stars" src="https://img.shields.io/github/stars/DeNeRATe-cool/AutoSign?style=flat"></a>
  <a href="https://github.com/DeNeRATe-cool/AutoSign/commits/CLI"><img alt="Last Commit" src="https://img.shields.io/github/last-commit/DeNeRATe-cool/AutoSign/CLI"></a>
</p>

## 项目导航

- `CLI` 分支（当前）：命令行自动签到工具，适合常驻后台运行。
- `Web` 分支：浏览器控制台版本，适合可视化查看与手动操作。

快速跳转：
- CLI: [https://github.com/DeNeRATe-cool/AutoSign/tree/CLI](https://github.com/DeNeRATe-cool/AutoSign/tree/CLI)
- Web: [https://github.com/DeNeRATe-cool/AutoSign/tree/Web](https://github.com/DeNeRATe-cool/AutoSign/tree/Web)

## CLI 版本亮点

- 多账号串行签到（每 1 分钟轮询）
- 登录回退策略（直连失败自动尝试 WebVPN）
- 完整签到窗口判定：
  - 开课前 10 分钟内：可签到
  - 开课后至下课前：可迟到签到
- `run` 默认后台启动，不占用当前终端
- 支持 `autosign stop` 一键关闭后台进程
- 倒计时展示为时分秒（`HH时MM分SS秒`）
- 自动创建运行目录：`~/.autosign/config.yaml` 与 `~/.autosign/log/`
- 提供跨平台开机自启管理（macOS/Linux/Windows）

## 安装

### 从 PyPI 安装

```bash
pip install autosign-buaa-cli
```

已验证版本：`autosign-buaa-cli==0.1.2`（PyPI 安装与命令冒烟测试通过）。

### 本地开发安装

```bash
cd CLI
pip install -e .
```

## 快速开始

### 1) 启动自动签到服务

```bash
autosign run
```

关闭后台服务：

```bash
autosign stop
```

调试单轮执行：

```bash
autosign run --once
```

### 2) 管理账号

```bash
autosign user add --username 23370001 --password "your_password"
autosign user list
autosign user delete --username 23370001
```

### 3) 查看某账号本周签到情况

```bash
autosign week --username 23370001
autosign week --username 23370001 --password "temp_password"
```

### 4) 管理开机自启

```bash
autosign autostart enable
autosign autostart status
autosign autostart disable
```

## 命令速查

| 命令 | 说明 |
| --- | --- |
| `autosign run` | 后台启动自动签到循环（命令立即返回） |
| `autosign stop` | 停止后台自动签到进程 |
| `autosign run --once` | 仅执行一轮，便于调试 |
| `autosign user add` | 添加或更新账号 |
| `autosign user list` | 列出已配置账号（密码脱敏） |
| `autosign user delete` | 删除账号 |
| `autosign week` | 查询本周课程与签到状态 |
| `autosign autostart enable/disable/status` | 开机自启管理 |

## 配置与日志

首次执行命令会自动初始化：

- `~/.autosign/config.yaml`
- `~/.autosign/log/YYYY-MM-DD.txt`

默认配置示例：

```yaml
accounts:
  # - username: "23370001"
  #   password: "your_password_1"
  # - username: "23370002"
  #   password: "your_password_2"
logger:
  enabled: true
  level: INFO
runtime:
  interval_seconds: 60
  timezone: Asia/Shanghai
autostart:
  enabled: false
  mode: off
```

`run` 模式行为：
- 默认以后台进程运行，命令立即返回
- 日志按天归档，同日重启追加写入
- 倒计时以时分秒格式记录（`HH时MM分SS秒`）
- 输出包含登录模式、课程状态、倒计时、签到结果与错误上下文

## 目录结构（CLI 分支）

```text
.
├── CLI/                 # Python 包与测试
│   ├── src/autosign_cli/
│   └── tests/
├── icon.svg             # 仓库图标
└── README.md            # 仓库首页（当前文件）
```

## 安全与合规

- 密码按配置要求保存在本地 `config.yaml`（明文）
- 程序会尝试将配置文件权限收敛为 `600`
- 日志会对敏感字段做脱敏处理
- 本项目仅供学习与个人使用，请遵守学校及平台规范

## 常见问题

### 登录失败且提示“请检查网络连接”

表示直连与 VPN 两种登录路径均失败。建议依次检查：

- 当前网络状态
- 学校认证服务可用性
- 账号密码是否正确

### 开机自启启用失败

执行：

```bash
autosign autostart status
```

程序会输出当前平台的手动配置指引。
