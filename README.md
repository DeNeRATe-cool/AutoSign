# AutoSign（Web 版本）

北航 iClass 本地 Web 控制台签到工具（分支：`Web`）。

## 版本导航

- 当前分支（Web）：浏览器控制台版本
- CLI 版本请查看分支：[`CLI`](https://github.com/DeNeRATe-cool/AutoSign/tree/CLI)

## 功能

- 学号/密码登录
- 查看本周课程与出勤状态
- 显示签到倒计时
- 支持自动签到与手动签到
- 记录运行日志

## 运行

```bash
cd Web
pip install -r requirements.txt
python app.py
```

默认访问地址：

```text
http://127.0.0.1:5000
```

## 目录说明

- `Web/app.py`：Flask 入口
- `Web/autosign/`：iClass 客户端、签到逻辑、数据模型
- `Web/static/`：前端脚本与样式
- `Web/templates/`：登录页与控制台模板
- `Web/scripts/`：辅助脚本（查询/批量扫描）

## 使用说明

- 仅供学习和个人使用，请遵守学校相关规定
- 登录与签到依赖 iClass / SSO 接口，若接口变动可能需要同步调整代码

## iClass 接口适配（2026-09-27）

依据 [UBAA 的独立签到客户端](https://github.com/BUAASubnet/UBAA/blob/e8a397fcb35a68147eee65a94c66ffb84e2f09fe/shared/src/commonMain/kotlin/cn/edu/ubaa/api/local/LocalSigninApi.kt) 与同版本的 [服务器请求实现](https://github.com/BUAASubnet/UBAA/blob/e8a397fcb35a68147eee65a94c66ffb84e2f09fe/server/src/main/kotlin/cn/edu/ubaa/signin/SigninClient.kt) 对齐请求协议。本项目直接访问北航 SSO、WebVPN 和 iClass，不依赖 UBAA 后端。

- SSO 服务入口使用 `/?type=jumpMyCenter`；从认证跳转中提取 `loginName` 并保留其中的 `+`，作为 iClass 登录接口的 `phone`。直接将学号填入该字段与最新协议不符，可能返回“用户不存在”。
- 后续请求使用 iClass 返回的用户 `id` 和 `sessionId`，不会把 `loginName` 当作会话凭证。
- 课表使用 8347 端口的 `GET /app/course/get_stu_course_sched.action`，参数为 `id`、`dateStr`。
- 每次签到前通过 `GET /app/common/get_timestamp.action` 获取服务器时间。获取失败则停止本次提交，不使用本地时间替代。
- 直连签到使用 8081 端口的 `POST /eschool/app/course/stu_scan_sign.action`；WebVPN 使用 8347 映射下的 `POST /app/course/stu_scan_sign.action`。`courseSchedId`、`timestamp` 放在查询参数中，`id` 放在表单中，`sessionId` 放在请求头中。
- 只有 `STATUS` 为 `0`、`200` 或 `success`，且 `result.stuSignStatus` 为 `1` 才确认成功。课表尚未同步时显示“已签到（待同步）”，不会按本地时间推测正常出勤或迟到。
- 会话过期时尝试借助现有 SSO Cookie 刷新一次；统一认证也过期时需重新登录。首次课表同步失败会返回登录页错误，不会留下后台签到任务。

校外访问时在登录页选择 WebVPN。自动签到仍按已有策略，在开课前 10 分钟至结课之间每分钟尝试一次；最终是否允许签到由学校服务器决定。

## 离线验证

在仓库根目录运行：

```bash
python -m pip install -r Web/requirements-dev.txt
python -m pytest Web/tests -q
node Web/tests/test_browser_state.js
```

测试使用模拟 HTTP 响应，覆盖认证跳转、请求方法/路径/参数、失败响应与 Web 调度状态；不需要账号密码，也不会发送真实签到。离线通过不能代替本人账号在校园网络或 WebVPN 下的实际登录验证。
