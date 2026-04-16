# AutoSign

本项目是一个 **Python 本地运行的北航 iClass 辅助网站**：

- 学号/密码登录（SSO + iClass）
- 展示本周课表（周视图）
- 展示每节课出勤状态：`正常出勤 / 迟到 / 未出勤`
- 运行中自动提醒签到：
  - 开课前 10 分钟：弹窗询问是否立即签到
  - 开课前 5 分钟：自动调用签到 API

## 1. 环境准备

```bash
git clone xxx.git
cd xxx
pip install -r requirements.txt
```

## 2. 运行

```bash
python app.py
```

默认访问：[http://127.0.0.1:5000](http://127.0.0.1:5000)

## 3. 注意

- 仅供学习交流，请遵守学校相关规定
- 不支持补签或提前签到，仅针对上课签到时间的自动签到
- iClass/SSO 接口若变动，需同步调整解析逻辑
