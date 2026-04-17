# AutoSign

一个本地运行的北航 iClass 辅助签到工具。

## 功能

- 学号/密码登录
- 查看本周课程与出勤状态
- 显示签到倒计时
- 支持自动签到与手动签到
- 记录运行日志

## 运行

```bash
pip install -r requirements.txt
python app.py
```

默认地址：

```text
http://127.0.0.1:5000
```

## 说明

- 仅供学习和个人使用，请遵守学校相关规定
- 登录和签到依赖 iClass / SSO 接口，若接口变动可能需要同步调整代码
