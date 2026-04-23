#!/usr/bin/env python3
"""
批量遍历学号区间，按上课时间窗口与目标出勤状态筛选课程并输出。

依赖项目内的 IClassClient（SSO 登录 + 按日拉取课表）。

用法 A —— 修改下方 CONFIG 后直接运行：
  python scripts/batch_scan_attendance.py

用法 B —— 命令行覆盖配置：
  python scripts/batch_scan_attendance.py \\
    --start-id 20371001 --end-id 20371005 \\
    --password ABC \\
    --time-start 202604211003 --time-end 202604211103 \\
    --status 正常签到

进度：默认在 stderr 显示 tqdm 进度条（需 pip install tqdm）；未安装时用简易文本进度；
重定向结果时可加 --no-progress 关闭进度输出。

时间格式：YYYYMMDDHHMM（12 位，上海时区），可与 iclass_client._parse_dt 一致；
也可使用 14 位 YYYYMMDDHHMMSS。

课程筛选：默认认为「上课时间」与给定区间有交集即命中（课间重叠）。
出勤状态别名：正常签到/正常出勤 → 正常出勤；迟到签到/迟到 → 迟到；未出勤。
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

try:
    from tqdm import tqdm
except ImportError:  # pragma: no cover - 运行时建议 pip install tqdm
    tqdm = None  # type: ignore[misc, assignment]

# 保证可从仓库根目录导入 autosign
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from autosign.iclass_client import SHANGHAI_TZ, IClassApiError, IClassClient
from autosign.models import ClassSession

# ------------ 可直接修改的默认配置 ------------
CONFIG: dict[str, object] = {
    "start_id": "23371001",
    "end_id": "23371400",
    "password": "ABC",
    # 上课时间筛选区间（上海时区）
    "time_start": "202604200000",
    "time_end": "202604202359",
    # 目标出勤：正常签到 | 正常出勤 | 迟到签到 | 迟到 | 未出勤
    "target_status": "未出勤",
    "use_vpn": False,
    "verify_ssl": True,
    # 每个学号请求之间的间隔（秒），降低风控风险
    "delay_seconds": 0.4,
}


_STATUS_ALIASES: dict[str, set[str]] = {
    "正常出勤": {"正常出勤", "正常签到", "正常"},
    "迟到": {"迟到", "迟到签到", "迟签"},
    "未出勤": {"未出勤", "缺席", "旷课"},
}


def _resolve_target_attendance(user_phrase: str) -> str:
    phrase = (user_phrase or "").strip()
    for canonical, aliases in _STATUS_ALIASES.items():
        if phrase in aliases or phrase == canonical:
            return canonical
    raise ValueError(
        f"无法识别出勤状态 {user_phrase!r}，请使用："
        + "、".join(sorted(_STATUS_ALIASES))
    )


def _parse_window_bound(s: str) -> datetime:
    text = "".join(ch for ch in s.strip() if ch.isdigit())
    if len(text) >= 14:
        dt = datetime.strptime(text[:14], "%Y%m%d%H%M%S")
    elif len(text) >= 12:
        dt = datetime.strptime(text[:12], "%Y%m%d%H%M")
    else:
        raise ValueError(f"时间须为至少 12 位 YYYYMMDDHHMM 或 14 位带秒：{s!r}")
    return dt.replace(tzinfo=SHANGHAI_TZ)


def _iter_dates_inclusive(t0: datetime, t1: datetime) -> list[date]:
    if t1 < t0:
        raise ValueError("time_end 早于 time_start")
    d0, d1 = t0.date(), t1.date()
    out: list[date] = []
    cur = d0
    while cur <= d1:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def _iter_student_ids(start: str, end: str) -> list[str]:
    sa, sb = (start or "").strip(), (end or "").strip()
    if not sa or not sb:
        raise ValueError("学号起止不能为空")
    a, b = int(sa), int(sb)
    if a > b:
        raise ValueError("end_id 必须 >= start_id")
    width = max(len(sa), len(sb))
    return [str(i).zfill(width) for i in range(a, b + 1)]


def _interval_overlaps_window(sess: ClassSession, w0: datetime, w1: datetime) -> bool:
    """课程时间段与 [w0, w1] 有交集。"""
    return sess.start_time < w1 and sess.end_time > w0


def _scan_one_student(
    student_id: str,
    password: str,
    w0: datetime,
    w1: datetime,
    target_attendance: str,
    use_vpn: bool,
    verify_ssl: bool,
    *,
    date_iter: list[date] | None = None,
) -> list[tuple[str, ClassSession]]:
    client = IClassClient(use_vpn=use_vpn, verify_ssl=verify_ssl)
    client.login(student_id=student_id, password=password)
    matches: list[tuple[str, ClassSession]] = []
    dates = date_iter if date_iter is not None else _iter_dates_inclusive(w0, w1)
    for d in dates:
        for sess in client.get_schedule_by_date(d):
            if not _interval_overlaps_window(sess, w0, w1):
                continue
            if sess.attendance == target_attendance:
                matches.append((student_id, sess))
    return matches


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="按学号区间与时间窗扫描 iClass 出勤状态")
    p.add_argument("--start-id", default=None, dest="start_id", help="起始学号")
    p.add_argument("--end-id", default=None, dest="end_id", help="终止学号（含）")
    p.add_argument("--password", default=None, help="统一密码")
    p.add_argument("--time-start", default=None, dest="time_start", help="时间窗起点 YYYYMMDDHHMM")
    p.add_argument("--time-end", default=None, dest="time_end", help="时间窗终点 YYYYMMDDHHMM")
    p.add_argument(
        "--status",
        default=None,
        dest="target_status",
        help="目标状态：正常签到/正常出勤/迟到签到/迟到/未出勤",
    )
    p.add_argument("--use-vpn", action="store_true", help="经 WebVPN 访问 iClass")
    p.add_argument("--no-verify-ssl", action="store_true", help="关闭 SSL 校验（不推荐）")
    p.add_argument(
        "--delay",
        type=float,
        default=None,
        dest="delay_seconds",
        help="每个学号之间的间隔秒数",
    )
    p.add_argument(
        "--no-progress",
        action="store_true",
        help="关闭进度条（stdout 仍为 TSV）",
    )
    return p


def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()

    def pick_str(name: str, fallback_key: str) -> str:
        val = getattr(args, name)
        if val is not None and str(val).strip() != "":
            return str(val).strip()
        return str(CONFIG.get(fallback_key, "") or "").strip()

    start_id = pick_str("start_id", "start_id")
    end_id = pick_str("end_id", "end_id")
    password = pick_str("password", "password")
    time_start = pick_str("time_start", "time_start")
    time_end = pick_str("time_end", "time_end")
    target_status = pick_str("target_status", "target_status")
    use_vpn = bool(CONFIG.get("use_vpn", False)) or bool(args.use_vpn)
    verify_ssl = bool(CONFIG.get("verify_ssl", True)) and not bool(args.no_verify_ssl)
    delay = float(CONFIG.get("delay_seconds", 0.4) if args.delay_seconds is None else args.delay_seconds)
    show_progress = not args.no_progress

    try:
        target_attendance = _resolve_target_attendance(target_status)
        w0 = _parse_window_bound(time_start)
        w1 = _parse_window_bound(time_end)
        student_ids = _iter_student_ids(start_id, end_id)
    except ValueError as exc:
        print(f"参数错误：{exc}", file=sys.stderr)
        return 2

    print(
        "学号\t课程名\t教师\t开始\t结束\t出勤",
        flush=True,
    )

    if show_progress and tqdm is None:
        print("提示：安装 tqdm 可显示进度条（pip install tqdm）", file=sys.stderr)

    exit_code = 0
    total = len(student_ids)
    date_list = _iter_dates_inclusive(w0, w1)

    def _fallback_progress(i: int, sid: str) -> None:
        pct = (i + 1) / total * 100 if total else 100.0
        print(f"\r[进度] {i + 1}/{total} ({pct:.1f}%) 当前 {sid}", end="", file=sys.stderr, flush=True)

    pbar = None
    if show_progress and tqdm is not None:
        pbar = tqdm(
            student_ids,
            desc="扫描学号",
            unit="人",
            total=total,
            file=sys.stderr,
            dynamic_ncols=True,
            bar_format="{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]",
        )

    for idx, sid in enumerate(student_ids if pbar is None else pbar):
        if show_progress and tqdm is None and total > 0:
            _fallback_progress(idx, sid)
        elif pbar is not None:
            pbar.set_postfix_str(sid, refresh=False)
        try:
            rows = _scan_one_student(
                sid,
                password,
                w0,
                w1,
                target_attendance,
                use_vpn=use_vpn,
                verify_ssl=verify_ssl,
                date_iter=date_list,
            )
            for student_id, sess in rows:
                print(
                    f"{student_id}\t{sess.course_name}\t{sess.teacher}\t"
                    f"{sess.start_time.isoformat()}\t{sess.end_time.isoformat()}\t"
                    f"{sess.attendance}",
                    flush=True,
                )
        except IClassApiError as exc:
            exit_code = 1
            print(f"# 跳过 {sid}：{exc}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            exit_code = 1
            print(f"# 跳过 {sid}：{exc}", file=sys.stderr)
        if delay > 0:
            time.sleep(delay)

    if show_progress and tqdm is None and total > 0:
        print(file=sys.stderr)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
