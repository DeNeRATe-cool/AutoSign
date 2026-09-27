# AutoSign BUAA CLI

北航 iClass 自动签到命令行工具，支持多账号、校园网直连及 WebVPN、后台运行和开机自启。

## 安装与升级

需要 Python 3.9 或更高版本。

```bash
python -m pip install --upgrade autosign-buaa-cli
```

如果使用 Conda，请先激活安装 AutoSign 的环境。升级后，重新启动已有的后台服务以加载新版程序。

## 使用

```bash
autosign user add --username YOUR_STUDENT_ID --password YOUR_PASSWORD
autosign week --username YOUR_STUDENT_ID
autosign run
autosign stop
```

`autosign week` 只查询课表与签到状态。`autosign run` 启动后台自动签到，`autosign run --once` 执行一轮自动签到。自动任务在开课前 10 分钟到下课之间尝试提交，最终结果以学校服务器为准。

配置与日志默认保存在 `~/.autosign/`。账号密码以明文存入本地配置；请保管好该目录，不要将它提交到代码仓库。

## 0.1.3 更新

- 通过统一认证跳转取得 iClass `loginName`，修正直接使用学号导致的登录兼容问题。
- 对齐校园网与 WebVPN 的签到路径和请求参数，提交前获取服务器时间。
- 校验服务器的签到确认字段，避免把未成功的请求记录为成功。
- 支持会话刷新、仅含时分的课程时间，以及无课日期的特殊返回状态。
- 改善登录和课表错误提示；出勤状态以学校课表为准。

本项目独立访问北航服务器，不依赖 UBAA 后端。接口适配依据 [UBAA 的原始服务器请求实现](https://github.com/BUAASubnet/UBAA/blob/e8a397fcb35a68147eee65a94c66ffb84e2f09fe/server/src/main/kotlin/cn/edu/ubaa/signin/SigninClient.kt)。

完整说明与源码：[AutoSign CLI 分支](https://github.com/DeNeRATe-cool/AutoSign/tree/CLI)。

请遵守学校及平台的使用规范。
