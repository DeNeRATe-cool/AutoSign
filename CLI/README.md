# autosign-buaa-cli

北航 iClass 自动签到命令行工具。

## 功能

- 自动创建 `~/.autosign/config.yaml` 与 `~/.autosign/log/`
- 多账号串行签到（每分钟轮询）
- 登录策略：直连失败自动回退 WebVPN
- 课程状态识别：`未签到` / `正常出勤` / `迟到签到`
- 签到窗口判定与自动签到：
  - 开课前 10 分钟内：可签到
  - 开课后至下课前：可迟到签到
- 运行日志按天落盘，重启后同日追加写入
- 提供账号管理、本周签到查询、开机自启管理命令

## 安装

### 从 PyPI 安装

```bash
pip install autosign-buaa-cli
```

### 本地开发安装

```bash
cd CLI
pip install -e .
```

## 初始化配置

首次执行任意命令会自动生成：

- `~/.autosign/config.yaml`
- `~/.autosign/log/`

默认 `config.yaml` 结构：

```yaml
accounts: []
account_examples:
  - username: "23370001"
    password: "your_password_1"
  - username: "23370002"
    password: "your_password_2"
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

## 命令用法

### 1) 启动自动签到

```bash
autosign run
```

说明：

- `run` 模式不会向终端输出日志
- 所有日志写入 `~/.autosign/log/YYYY-MM-DD.txt`

调试单轮（开发用）：

```bash
autosign run --once
```

### 2) 用户管理

添加/更新用户：

```bash
autosign user add --username 23370001 --password "your_password"
```

删除用户：

```bash
autosign user delete --username 23370001
```

查看用户：

```bash
autosign user list
```

### 3) 查看某用户本周签到情况

使用配置中的密码：

```bash
autosign week --username 23370001
```

临时覆盖密码：

```bash
autosign week --username 23370001 --password "temp_password"
```

### 4) 开机自启

启用：

```bash
autosign autostart enable
```

禁用：

```bash
autosign autostart disable
```

状态：

```bash
autosign autostart status
```

指定平台模式（跨平台配置说明/排错时可用）：

```bash
autosign autostart enable --mode macos
autosign autostart enable --mode linux
autosign autostart enable --mode windows
```

## 日志说明

日志文件：`~/.autosign/log/YYYY-MM-DD.txt`

日志内容包括：

- 登录方式（直连/VPN）
- 本周课程摘要
- 每节课签到状态
- 自动签到倒计时
- 可签到/可迟到签到判断
- 签到成功或失败详情（含接口错误）

## 安全说明

- 密码按你的需求保存在 `config.yaml` 明文中
- 程序会尝试将配置文件权限设为 `600`
- 日志中会脱敏密码字段

## 常见问题

### 1) 登录一直失败

日志出现“请检查网络连接”时，表示直连与 VPN 都失败。请检查：

- 当前网络环境
- 学校认证服务状态
- 账号密码是否正确

### 2) 开机自启启用失败

请先执行：

```bash
autosign autostart status
```

工具会输出对应系统的手动配置指引。

## 免责声明

仅供学习与个人使用，请遵守学校及平台相关规定。
