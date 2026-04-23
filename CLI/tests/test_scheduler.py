from datetime import datetime
from zoneinfo import ZoneInfo

from autosign_cli.core.models import ClassSession
from autosign_cli.runtime.scheduler import (
    SessionAction,
    decide_session_action,
    login_with_fallback,
)


def _dt(h: int, m: int = 0):
    return datetime(2026, 4, 23, h, m, tzinfo=ZoneInfo("Asia/Shanghai"))


def _session(start_h: int, end_h: int):
    return ClassSession(
        schedule_id="s1",
        course_id="c1",
        course_name="高数",
        teacher="张老师",
        start_time=_dt(start_h),
        end_time=_dt(end_h),
        raw_status="0",
    )


def test_session_action_windows():
    session = _session(10, 12)

    action_before = decide_session_action(_dt(9, 30), session)
    action_presign = decide_session_action(_dt(9, 55), session)
    action_late = decide_session_action(_dt(10, 30), session)
    action_closed = decide_session_action(_dt(12, 1), session)

    assert action_before.action == SessionAction.COUNTDOWN
    assert action_before.countdown_seconds > 0
    assert action_presign.action == SessionAction.CAN_SIGN
    assert action_late.action == SessionAction.CAN_LATE_SIGN
    assert action_closed.action == SessionAction.CLOSED


class _DummyClient:
    def __init__(self, should_fail: bool):
        self.should_fail = should_fail
        self.use_vpn = False

    def login(self, student_id: str, password: str):
        if self.should_fail:
            raise RuntimeError("login failed")
        return {"student_id": student_id}


def test_login_with_fallback_direct_then_vpn_success():
    clients = {
        False: _DummyClient(should_fail=True),
        True: _DummyClient(should_fail=False),
    }

    def factory(use_vpn: bool):
        return clients[use_vpn]

    client, mode = login_with_fallback("23370001", "pwd", factory)

    assert client is clients[True]
    assert mode == "vpn"
