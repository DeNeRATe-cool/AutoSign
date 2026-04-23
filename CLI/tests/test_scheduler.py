from datetime import datetime
from zoneinfo import ZoneInfo

from autosign_cli.core.models import ClassSession
from autosign_cli.runtime.scheduler import (
    AutoSignRunner,
    SessionAction,
    decide_session_action,
    format_countdown_hms,
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


def test_format_countdown_hms():
    assert format_countdown_hms(9) == "00时00分09秒"
    assert format_countdown_hms(125) == "00时02分05秒"
    assert format_countdown_hms(3661) == "01时01分01秒"


def test_countdown_log_includes_hms_text(monkeypatch):
    class _DummyLogger:
        def __init__(self):
            self.records = []

        def info(self, message, meta=None):
            self.records.append(("info", message, meta or {}))

        def warning(self, message, meta=None):
            self.records.append(("warning", message, meta or {}))

        def error(self, message, meta=None, exc=None):
            self.records.append(("error", message, meta or {}))

    class _DummyConfigManager:
        def load(self):
            return {"runtime": {"timezone": "Asia/Shanghai"}, "accounts": []}

    class _DummyClientForWeek:
        def get_week_schedule(self, now):
            return [_session(10, 12)]

    logger = _DummyLogger()
    runner = AutoSignRunner(config_manager=_DummyConfigManager(), logger=logger)

    monkeypatch.setattr(
        "autosign_cli.runtime.scheduler.login_with_fallback",
        lambda username, password, client_factory: (_DummyClientForWeek(), "direct"),
    )

    runner._process_user(_dt(8, 0), "23370001", "pwd")

    countdown_records = [r for r in logger.records if r[1] == "自动签到倒计时"]
    assert countdown_records
    meta = countdown_records[0][2]
    assert meta["seconds"] == 6600
    assert meta["countdown"] == "01时50分00秒"
