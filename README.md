📡 **产品集**

> **[AutoTD](https://github.com/DeNeRATe-cool/autoTD)**: BUAA TD 锻炼
> 
> **[AutoBoya](https://github.com/DeNeRATe-cool/AutoBoya)**: BUAA 博雅课程

<p align="center">
  <img src="./icon.svg" width="120" alt="AutoSign icon" />
</p>

<h1 align="center">AutoSign</h1>

<p align="center">
  北航 iClass 自动签到工具集（支持 CLI/Web 版本）
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

- 支持多账号管理
- 定时轮询，串行签到
- 支持**校园网直连**与 **VPN 登陆**
- 完整签到窗口判定：开课前 10 分钟到下课
- **全自动后台签到**，`run` 默认后台启动，不占用当前终端
- 支持命令行用户配置与签到状态查询
- 提供跨平台**开机自启**管理（macOS/Linux/Windows）

## 安装

### 从 PyPI 安装

```bash
pip install autosign-buaa-cli
```

版本更新方法：`python -m pip install --upgrade autosign-buaa-cli`。本次 iClass 接口适配版本为 `0.1.3`；更新后请重启后台服务以加载新代码：

```bash
autosign stop
autosign run
```

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

### 登录失败

表示直连与 VPN 两种登录路径均失败。建议依次检查：

- 当前网络状态
- 学校认证服务可用性
- 账号密码是否正确

错误信息会分别保留直连与 WebVPN 的失败原因。统一认证返回 401 时先检查密码或验证码；这与 iClass 的“用户不存在”（106）是不同阶段的问题。

### iClass 接口适配（2026-09-27）

请求协议依据 [UBAA 的服务器实现](https://github.com/BUAASubnet/UBAA/blob/e8a397fcb35a68147eee65a94c66ffb84e2f09fe/server/src/main/kotlin/cn/edu/ubaa/signin/SigninClient.kt) 和 [独立直连实现](https://github.com/BUAASubnet/UBAA/blob/e8a397fcb35a68147eee65a94c66ffb84e2f09fe/shared/src/commonMain/kotlin/cn/edu/ubaa/api/local/LocalSigninApi.kt) 核对。AutoSign 独立访问北航服务器，不依赖 UBAA 后端。

- 登录从 `:8346/?type=jumpMyCenter` 的认证跳转取得 `loginName`，保留其中的 `+`，再作为 `:8347/app/user/login.action` 的 `phone`。不再直接传学号，也不再将 `loginName` 当作 `sessionId`。
- 课表使用 `GET :8347/app/course/get_stu_course_sched.action`，携带查询参数 `id`、`dateStr` 和请求头 `sessionId`；兼容完整日期与时分格式。
- 每次签到前获取服务器 `timestamp`；时间查询失败即停止，不用本机时间替代。自动运行器不再传入轮询开始时计算的时间。
- 直连签到为 `POST http://iclass.buaa.edu.cn:8081/eschool/app/course/stu_scan_sign.action`；WebVPN 使用 8347 映射下的 `/app/course/stu_scan_sign.action`。`courseSchedId`、`timestamp` 放在查询参数，`id` 放在表单，`sessionId` 放在请求头。
- 仅当 `STATUS` 为 `0`、`200` 或 `success`，且 `result.stuSignStatus=1` 时确认成功。出勤状态以课表为准，不按本地时间推测正常或迟到。
- 明确的会话失效最多刷新一次；网络超时不会立即重复提交。课表错误不会被当作当天无课。

本次验证命令：

```bash
cd CLI
python -m pip install -e . pytest
python -m pytest
```

测试使用模拟 HTTP 响应验证请求约定、异常响应和调度行为，不提交真实签到。源码适配与离线测试通过不等于已完成本人账号的真实签到验证。

### 开机自启启用失败

执行：

```bash
autosign autostart status
```

程序会输出当前平台的手动配置指引。
