from datetime import datetime
from zoneinfo import ZoneInfo

from autosign_cli.core.models import ClassSession


def _dt(h: int, m: int = 0):
    return datetime(2026, 4, 23, h, m, tzinfo=ZoneInfo("Asia/Shanghai"))


def test_attendance_mapping():
    s0 = ClassSession("1", "c1", "课程A", "教师A", _dt(8), _dt(9), "0")
    s1 = ClassSession("2", "c2", "课程B", "教师B", _dt(10), _dt(11), "1")
    s2 = ClassSession("3", "c3", "课程C", "教师C", _dt(12), _dt(13), "2")

    assert s0.attendance == "未签到"
    assert s1.attendance == "正常出勤"
    assert s2.attendance == "迟到签到"


def test_class_key_includes_start_time_for_duplicate_schedule_id():
    morning = ClassSession("same", "c", "课", "师", _dt(8), _dt(9), "0")
    afternoon = ClassSession("same", "c", "课", "师", _dt(14), _dt(15), "0")

    assert morning.key != afternoon.key
