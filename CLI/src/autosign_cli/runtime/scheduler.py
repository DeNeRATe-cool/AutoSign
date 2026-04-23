from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable
from zoneinfo import ZoneInfo

from autosign_cli.config.manager import ConfigManager
from autosign_cli.core.iclass_client import IClassClient
from autosign_cli.core.models import ClassSession
from autosign_cli.runtime.logging import DailyFileLogger


class SessionAction(str, Enum):
    COUNTDOWN = "countdown"
    CAN_SIGN = "can_sign"
    CAN_LATE_SIGN = "can_late_sign"
    CLOSED = "closed"
    ALREADY_SIGNED = "already_signed"


@dataclass
class SessionDecision:
    action: SessionAction
    countdown_seconds: int = 0


def decide_session_action(now: datetime, session: ClassSession) -> SessionDecision:
    if session.attendance != "未签到":
        return SessionDecision(action=SessionAction.ALREADY_SIGNED)

    pre_sign_start = session.start_time - timedelta(minutes=10)
    if now < pre_sign_start:
        return SessionDecision(
            action=SessionAction.COUNTDOWN,
            countdown_seconds=max(0, int((pre_sign_start - now).total_seconds())),
        )
    if pre_sign_start <= now < session.start_time:
        return SessionDecision(action=SessionAction.CAN_SIGN)
    if session.start_time <= now <= session.end_time:
        return SessionDecision(action=SessionAction.CAN_LATE_SIGN)
    return SessionDecision(action=SessionAction.CLOSED)


def login_with_fallback(
    username: str,
    password: str,
    client_factory: Callable[[bool], IClassClient],
) -> tuple[IClassClient, str]:
    direct_client = client_factory(False)
    try:
        direct_client.login(username, password)
        return direct_client, "direct"
    except Exception:
        pass

    vpn_client = client_factory(True)
    vpn_client.login(username, password)
    return vpn_client, "vpn"


class AutoSignRunner:
    def __init__(self, config_manager: ConfigManager, logger: DailyFileLogger) -> None:
        self.config_manager = config_manager
        self.logger = logger

    def process_once(self) -> None:
        cfg = self.config_manager.load()
        runtime = cfg.get("runtime", {})
        tz_name = str(runtime.get("timezone", "Asia/Shanghai"))
        now = datetime.now(tz=ZoneInfo(tz_name))

        accounts = cfg.get("accounts", [])
        if not accounts:
            self.logger.info("当前未配置账号，跳过本轮签到")
            return

        for row in accounts:
            if not isinstance(row, dict):
                continue
            username = str(row.get("username", "")).strip()
            password = str(row.get("password", ""))
            if not username or not password:
                self.logger.warning("跳过账号：用户名或密码为空", meta={"username": username})
                continue

            self._process_user(now, username, password)

    def run_forever(self) -> None:
        while True:
            cfg = self.config_manager.load()
            interval = int(cfg.get("runtime", {}).get("interval_seconds", 60) or 60)
            if interval <= 0:
                interval = 60

            try:
                self.process_once()
            except Exception as exc:  # noqa: BLE001
                self.logger.error("运行循环异常", exc=exc)

            time.sleep(interval)

    def _process_user(self, now: datetime, username: str, password: str) -> None:
        try:
            client, mode = login_with_fallback(
                username,
                password,
                lambda use_vpn: IClassClient(use_vpn=use_vpn, verify_ssl=True),
            )
            self.logger.info("登录成功", meta={"username": username, "mode": mode})
        except Exception as exc:  # noqa: BLE001
            self.logger.error(
                "请检查网络连接",
                meta={"username": username},
                exc=exc,
            )
            return

        try:
            sessions = client.get_week_schedule(now=now)
        except Exception as exc:  # noqa: BLE001
            self.logger.error("获取本周课表失败", meta={"username": username}, exc=exc)
            return

        self.logger.info("本周课程拉取完成", meta={"username": username, "count": len(sessions)})

        for session in sessions:
            self.logger.info(
                "课程签到状态",
                meta={
                    "username": username,
                    "course": session.course_name,
                    "start": session.start_time.isoformat(),
                    "end": session.end_time.isoformat(),
                    "attendance": session.attendance,
                },
            )

            decision = decide_session_action(now, session)
            if decision.action == SessionAction.COUNTDOWN:
                self.logger.info(
                    "自动签到倒计时",
                    meta={
                        "username": username,
                        "course": session.course_name,
                        "seconds": decision.countdown_seconds,
                    },
                )
                continue
            if decision.action == SessionAction.CAN_SIGN:
                self.logger.info("可签到", meta={"username": username, "course": session.course_name})
                self._sign_course(client, session, now, late=False, username=username)
                continue
            if decision.action == SessionAction.CAN_LATE_SIGN:
                self.logger.info("可迟到签到", meta={"username": username, "course": session.course_name})
                self._sign_course(client, session, now, late=True, username=username)
                continue

    def _sign_course(self, client: IClassClient, session: ClassSession, now: datetime, late: bool, username: str) -> None:
        try:
            ts = client.get_adjusted_timestamp_ms(now)
            resp = client.sign_now(session.schedule_id, ts)
            status = str(resp.get("STATUS", "")) if isinstance(resp, dict) else ""
            if status == "0":
                if late:
                    self.logger.info("迟到签到成功", meta={"username": username, "course": session.course_name})
                    session.raw_status = "2"
                else:
                    self.logger.info("正常签到成功", meta={"username": username, "course": session.course_name})
                    session.raw_status = "1"
                return

            errmsg = resp.get("ERRMSG", "未知错误") if isinstance(resp, dict) else "响应格式异常"
            self.logger.error(
                "签到失败",
                meta={
                    "username": username,
                    "course": session.course_name,
                    "errmsg": errmsg,
                    "response": resp,
                },
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.error(
                "签到请求异常",
                meta={"username": username, "course": session.course_name},
                exc=exc,
            )
