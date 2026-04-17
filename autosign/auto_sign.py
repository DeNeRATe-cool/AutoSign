from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .iclass_client import IClassApiError, IClassClient
from .models import ClassSession, PromptNotification, RuntimeEvent

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


@dataclass
class UserRuntimeState:
    client: IClassClient
    week_sessions: dict[str, ClassSession] = field(default_factory=dict)
    pending_prompts: dict[str, PromptNotification] = field(default_factory=dict)
    pre_sign_next_attempt_at: dict[str, datetime] = field(default_factory=dict)
    pre_sign_window_logged: set[str] = field(default_factory=set)
    pre_sign_stop_logged: set[str] = field(default_factory=set)
    late_sign_hint_logged: set[str] = field(default_factory=set)
    completed_sign_keys: set[str] = field(default_factory=set)
    attendance_overrides: dict[str, str] = field(default_factory=dict)
    events: deque[RuntimeEvent] = field(default_factory=lambda: deque(maxlen=200))
    last_sync_at: datetime | None = None
    last_sync_week_anchor: date | None = None
    lock: threading.RLock = field(default_factory=threading.RLock)


class AutoSignService:
    def __init__(self, sync_interval_seconds: int = 20) -> None:
        self.sync_interval_seconds = sync_interval_seconds
        self.users: dict[str, UserRuntimeState] = {}
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=2)

    def register_user(self, token: str, client: IClassClient) -> None:
        state = UserRuntimeState(client=client)
        with self._lock:
            self.users[token] = state
        self._append_event(state, "info", "登录成功，自动签到服务已启动")
        self._refresh_week(state, force=True)

    def unregister_user(self, token: str) -> None:
        with self._lock:
            self.users.pop(token, None)

    def get_week_sessions(self, token: str) -> list[dict[str, Any]]:
        state = self._get_state(token)
        with state.lock:
            return [s.to_dict() for s in sorted(state.week_sessions.values(), key=lambda x: x.start_time)]

    def get_pending_notifications(self, token: str) -> list[dict[str, Any]]:
        state = self._get_state(token)
        with state.lock:
            return [n.to_dict() for n in sorted(state.pending_prompts.values(), key=lambda x: x.start_time)]

    def get_recent_events(self, token: str) -> list[dict[str, Any]]:
        state = self._get_state(token)
        with state.lock:
            return [event.to_dict() for event in list(state.events)]

    def handle_prompt_action(self, token: str, key: str, action: str) -> dict[str, Any]:
        state = self._get_state(token)
        with state.lock:
            if key in state.completed_sign_keys:
                return {"ok": False, "message": "当前课程已签到"}

            prompt = state.pending_prompts.pop(key, None)
            if prompt is None:
                return {"ok": False, "message": "提醒已过期或不存在"}

            if action == "later":
                self._append_event(state, "info", f"用户选择稍后处理：{prompt.course_name}")
                return {"ok": True, "message": "已标记为稍后，系统将在开课前窗口继续自动尝试签到"}

            if action != "sign_now":
                return {"ok": False, "message": "不支持的操作"}

            session = state.week_sessions.get(prompt.key)
            timestamp_ms = None
            attendance_raw_status: str | None = None
            if session is not None:
                now = datetime.now(tz=SHANGHAI_TZ)
                if not self._is_signable_now(now, session.start_time, session.end_time):
                    return {"ok": False, "message": "当前不在签到窗口，无法签到"}
                timestamp_ms = state.client.get_adjusted_timestamp_ms(now)
                attendance_raw_status = "2" if now >= session.start_time else "1"
            return self._do_sign(
                state,
                prompt.schedule_id,
                reason="用户确认立即签到",
                timestamp_ms=timestamp_ms,
                session_key=key,
                attendance_raw_status=attendance_raw_status,
                event_meta={
                    "course": prompt.course_name,
                    "now": now.isoformat(),
                    "window_start": (session.start_time - timedelta(minutes=10)).isoformat(),
                    "window_end": session.end_time.isoformat(),
                }
                if session is not None
                else None,
            )

    def manual_sign(self, token: str, key: str | None, schedule_id: str | None) -> dict[str, Any]:
        state = self._get_state(token)
        with state.lock:
            reason = "用户手动签到"
            timestamp_ms: int | None = None
            attendance_raw_status: str | None = None
            if key:
                if key in state.completed_sign_keys:
                    return {"ok": False, "message": "当前课程已签到"}
                session = state.week_sessions.get(key)
                if session is None:
                    return {"ok": False, "message": "课程不存在"}
                schedule_id = session.schedule_id
                now = datetime.now(tz=SHANGHAI_TZ)
                if session.attendance != "未出勤":
                    self._append_event(
                        state,
                        "info",
                        f"手动签到被拒绝：{session.course_name} 当前状态为{session.attendance}，无需重复签到",
                        meta={
                            "course": session.course_name,
                            "start_time": session.start_time.isoformat(),
                            "end_time": session.end_time.isoformat(),
                            "now": now.isoformat(),
                            "attendance": session.attendance,
                        },
                    )
                    return {"ok": False, "message": "当前课程已签到"}

                if not self._is_signable_now(now, session.start_time, session.end_time):
                    self._append_event(
                        state,
                        "info",
                        f"手动签到被拒绝：{session.course_name} 当前时间不在签到窗口",
                        meta={
                            "course": session.course_name,
                            "start_time": session.start_time.isoformat(),
                            "end_time": session.end_time.isoformat(),
                            "now": now.isoformat(),
                            "window_start": (session.start_time - timedelta(minutes=10)).isoformat(),
                            "window_end": session.end_time.isoformat(),
                        },
                    )
                    return {"ok": False, "message": "当前不在签到窗口，无法签到"}

                if now >= session.start_time:
                    reason = "用户手动迟到签到"
                timestamp_ms = state.client.get_adjusted_timestamp_ms(now)
                attendance_raw_status = "2" if now >= session.start_time else "1"
            elif not schedule_id:
                return {"ok": False, "message": "缺少 schedule_id"}
            else:
                timestamp_ms = state.client.get_adjusted_timestamp_ms()

            return self._do_sign(
                state,
                schedule_id,
                reason=reason,
                timestamp_ms=timestamp_ms,
                session_key=key if key else None,
                attendance_raw_status=attendance_raw_status,
                event_meta={
                    "course": session.course_name if key and session else schedule_id,
                    "now": now.isoformat() if key else datetime.now(tz=SHANGHAI_TZ).isoformat(),
                    "window_start": (session.start_time - timedelta(minutes=10)).isoformat() if key and session else None,
                    "window_end": session.end_time.isoformat() if key and session else None,
                },
            )

    def _get_state(self, token: str) -> UserRuntimeState:
        with self._lock:
            state = self.users.get(token)
        if state is None:
            raise IClassApiError("登录状态已失效，请重新登录")
        return state

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            with self._lock:
                items = list(self.users.items())
            for _, state in items:
                try:
                    self._tick_user(state)
                except Exception as exc:  # noqa: BLE001
                    self._append_event(state, "error", f"自动任务异常: {exc}")
            self._stop_event.wait(self.sync_interval_seconds)

    def _tick_user(self, state: UserRuntimeState) -> None:
        with state.lock:
            self._refresh_week(state)
            now = datetime.now(tz=SHANGHAI_TZ)

            for session in sorted(state.week_sessions.values(), key=lambda x: x.start_time):
                key = session.key
                if key in state.completed_sign_keys:
                    state.pending_prompts.pop(key, None)
                    state.pre_sign_next_attempt_at.pop(key, None)
                    state.pre_sign_window_logged.discard(key)
                    state.pre_sign_stop_logged.discard(key)
                    state.late_sign_hint_logged.discard(key)
                    continue

                if session.attendance != "未出勤":
                    state.pending_prompts.pop(key, None)
                    state.pre_sign_next_attempt_at.pop(key, None)
                    state.pre_sign_window_logged.discard(key)
                    state.pre_sign_stop_logged.discard(key)
                    state.late_sign_hint_logged.discard(key)
                    continue

                state.pending_prompts.pop(key, None)
                pre_sign_start = session.start_time - timedelta(minutes=10)
                sign_window_end = session.end_time

                if now > sign_window_end and key not in state.late_sign_hint_logged:
                    state.late_sign_hint_logged.add(key)
                    self._append_event(
                        state,
                        "info",
                        f"课程 {session.course_name} 已结束，当前时间 {now.strftime('%H:%M:%S')} 已超出签到窗口，显示为无法签到",
                        meta={
                            "course": session.course_name,
                            "start_time": session.start_time.isoformat(),
                            "end_time": session.end_time.isoformat(),
                            "now": now.isoformat(),
                            "window_start": pre_sign_start.isoformat(),
                            "window_end": sign_window_end.isoformat(),
                            "status": "无法签到",
                        },
                    )
                    continue

                if now < pre_sign_start:
                    continue

                if pre_sign_start <= now <= sign_window_end:
                    if key not in state.pre_sign_window_logged:
                        state.pre_sign_window_logged.add(key)
                        self._append_event(
                            state,
                            "info",
                            f"课程 {session.course_name} 进入自动签到窗口：{pre_sign_start.strftime('%H:%M:%S')} - {sign_window_end.strftime('%H:%M:%S')}，每 1 分钟尝试一次，当前时间 {now.strftime('%H:%M:%S')}",
                            meta={
                                "course": session.course_name,
                                "start_time": session.start_time.isoformat(),
                                "end_time": session.end_time.isoformat(),
                                "now": now.isoformat(),
                                "window_start": pre_sign_start.isoformat(),
                                "window_end": sign_window_end.isoformat(),
                                "status": "可签到",
                            },
                        )

                    next_attempt_at = state.pre_sign_next_attempt_at.get(key)
                    if next_attempt_at is None or now >= next_attempt_at:
                        if now < session.start_time:
                            window_stage = "开课前"
                            target_desc = f"距开课约 {max(0, int((session.start_time - now).total_seconds() // 60))} 分钟"
                        else:
                            window_stage = "开课后"
                            target_desc = f"距结课约 {max(0, int((session.end_time - now).total_seconds() // 60))} 分钟"

                        self._append_event(
                            state,
                            "info",
                            f"自动签到尝试：{session.course_name}，{window_stage}，当前时间 {now.strftime('%H:%M:%S')}，{target_desc}",
                            meta={
                                "course": session.course_name,
                                "start_time": session.start_time.isoformat(),
                                "end_time": session.end_time.isoformat(),
                                "now": now.isoformat(),
                                "window_start": pre_sign_start.isoformat(),
                                "window_end": sign_window_end.isoformat(),
                                "status": "尝试签到",
                                "window_stage": window_stage,
                            },
                        )
                        result = self._do_sign(
                            state,
                            session.schedule_id,
                            reason=f"{window_stage}自动签到",
                            timestamp_ms=state.client.get_adjusted_timestamp_ms(now),
                            session_key=key,
                            attendance_raw_status="2" if now >= session.start_time else "1",
                            event_meta={
                                "course": session.course_name,
                                "now": now.isoformat(),
                                "window_start": pre_sign_start.isoformat(),
                                "window_end": sign_window_end.isoformat(),
                                "window_stage": window_stage,
                            },
                        )
                        if result.get("ok"):
                            state.pre_sign_next_attempt_at.pop(key, None)
                            continue
                        state.pre_sign_next_attempt_at[key] = now + timedelta(minutes=1)
                    continue

                state.pre_sign_next_attempt_at.pop(key, None)
                if key in state.pre_sign_window_logged and key not in state.pre_sign_stop_logged:
                    state.pre_sign_stop_logged.add(key)
                    self._append_event(
                        state,
                        "info",
                        f"课程 {session.course_name} 当前时间 {now.strftime('%H:%M:%S')} 不在签到窗口，停止自动签到尝试",
                        meta={
                            "course": session.course_name,
                            "start_time": session.start_time.isoformat(),
                            "end_time": session.end_time.isoformat(),
                            "now": now.isoformat(),
                            "window_start": pre_sign_start.isoformat(),
                            "window_end": sign_window_end.isoformat(),
                            "status": "无法签到",
                        },
                    )

    def _refresh_week(self, state: UserRuntimeState, force: bool = False) -> None:
        now = datetime.now(tz=SHANGHAI_TZ)
        current_week_anchor = now.date() - timedelta(days=now.weekday())
        if not force and state.last_sync_at is not None:
            if state.last_sync_week_anchor == current_week_anchor and (now - state.last_sync_at).total_seconds() < 60:
                return

        sessions = state.client.get_week_schedule(now=now)
        state.week_sessions = {item.key: item for item in sessions}
        active_keys = set(state.week_sessions)
        for key in list(state.pre_sign_next_attempt_at):
            if key not in active_keys:
                state.pre_sign_next_attempt_at.pop(key, None)
        state.pre_sign_window_logged.intersection_update(active_keys)
        state.pre_sign_stop_logged.intersection_update(active_keys)
        state.late_sign_hint_logged.intersection_update(active_keys)
        state.completed_sign_keys.intersection_update(active_keys)
        state.attendance_overrides = {
            key: raw_status
            for key, raw_status in state.attendance_overrides.items()
            if key in active_keys
        }
        for key, raw_status in state.attendance_overrides.items():
            session = state.week_sessions.get(key)
            if session is not None:
                session.raw_status = raw_status
        state.pending_prompts = {k: v for k, v in state.pending_prompts.items() if k in active_keys}
        state.last_sync_at = now
        state.last_sync_week_anchor = current_week_anchor

    def _do_sign(
        self,
        state: UserRuntimeState,
        schedule_id: str,
        reason: str,
        timestamp_ms: int | None = None,
        session_key: str | None = None,
        attendance_raw_status: str | None = None,
        event_meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            resp = state.client.sign_now(schedule_id, timestamp_ms=timestamp_ms)
        except Exception as exc:  # noqa: BLE001
            message = f"{reason}失败: {exc}"
            self._append_event(
                state,
                "error",
                message,
                meta={
                    **(event_meta or {}),
                    "schedule_id": schedule_id,
                    "timestamp_ms": timestamp_ms,
                    "reason": reason,
                },
            )
            return {"ok": False, "message": message}

        status = str(resp.get("STATUS", "")) if isinstance(resp, dict) else ""
        if status == "0":
            if session_key is not None:
                state.completed_sign_keys.add(session_key)
                state.pending_prompts.pop(session_key, None)
                state.pre_sign_next_attempt_at.pop(session_key, None)
                state.pre_sign_window_logged.discard(session_key)
                state.pre_sign_stop_logged.discard(session_key)
                state.late_sign_hint_logged.discard(session_key)
            if session_key is not None and attendance_raw_status is not None:
                state.attendance_overrides[session_key] = attendance_raw_status
                session = state.week_sessions.get(session_key)
                if session is not None:
                    session.raw_status = attendance_raw_status
            self._append_event(
                state,
                "success",
                f"{reason}成功",
                meta={
                    **(event_meta or {}),
                    "schedule_id": schedule_id,
                    "timestamp_ms": timestamp_ms,
                    "reason": reason,
                    "response_status": status,
                },
            )
            self._refresh_week(state, force=True)
            return {"ok": True, "message": f"{reason}成功", "data": resp}

        errmsg = resp.get("ERRMSG", "未知错误") if isinstance(resp, dict) else "响应格式异常"
        message = f"{reason}失败: {errmsg}"
        self._append_event(
            state,
            "error",
            message,
            meta={
                **(event_meta or {}),
                "schedule_id": schedule_id,
                "timestamp_ms": timestamp_ms,
                "reason": reason,
                "response_status": status or None,
                "response": resp if isinstance(resp, dict) else None,
            },
        )
        return {"ok": False, "message": message, "data": resp}

    def _is_signable_now(self, now: datetime, start_time: datetime, end_time: datetime) -> bool:
        return (start_time - timedelta(minutes=10)) <= now <= end_time

    def _append_event(self, state: UserRuntimeState, level: str, message: str, meta: dict | None = None) -> None:
        state.events.append(
            RuntimeEvent(
                level=level,
                message=message,
                at=datetime.now(tz=SHANGHAI_TZ),
                meta=meta or {},
            )
        )
