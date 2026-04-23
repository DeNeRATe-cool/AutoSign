#!/usr/bin/env python3
"""查询指定学号「今天（上海时区）」的课表与签到状态。

  python scripts/show_today_attendance.py 23371001

或使用 --password（会出现在 shell 历史里，不推荐）。"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from autosign.iclass_client import IClassApiError, IClassClient, SHANGHAI_TZ


def main() -> int:
    p = argparse.ArgumentParser(description="查询今日课表与签到状态（上海日期）")
    p.add_argument("student_id", help="学号")
    p.add_argument("--password", default="1", help="统一认证密码（优先于环境变量）")
    p.add_argument("--use-vpn", action="store_true", help="使用 WebVPN")
    p.add_argument("--no-verify-ssl", action="store_true")
    args = p.parse_args()

    pwd = (args.password or os.environ.get("ICLASS_PASSWORD") or "").strip()
    if not pwd:
        print(
            "请设置环境变量 ICLASS_PASSWORD，或使用 --password。",
            file=sys.stderr,
        )
        return 2

    today = datetime.now(tz=SHANGHAI_TZ).date()
    client = IClassClient(use_vpn=args.use_vpn, verify_ssl=not args.no_verify_ssl)
    try:
        auth = client.login(student_id=args.student_id.strip(), password=pwd)
    except IClassApiError as exc:
        print(f"登录失败: {exc}", file=sys.stderr)
        return 1

    print(f"# 日期 {today.isoformat()} | {auth.user_name} ({auth.student_id})", file=sys.stderr)
    sessions = client.get_schedule_by_date(today)
    print("课程名\t教师\t开始\t结束\t出勤\trawStatus")
    for s in sorted(sessions, key=lambda x: x.start_time):
        print(
            f"{s.course_name}\t{s.teacher}\t{s.start_time.isoformat()}\t"
            f"{s.end_time.isoformat()}\t{s.attendance}\t{s.raw_status}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
