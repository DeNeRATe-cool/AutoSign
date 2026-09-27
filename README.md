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
