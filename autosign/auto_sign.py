from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
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
    prompted: set[str] = field(default_factory=set)
    auto_attempted: set[str] = field(default_factory=set)
    events: deque[RuntimeEvent] = field(default_factory=lambda: deque(maxlen=200))
    last_sync_at: datetime | None = None
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
            prompt = state.pending_prompts.pop(key, None)
            if prompt is None:
                return {"ok": False, "message": "提醒已过期或不存在"}

            if action == "later":
                self._append_event(state, "info", f"用户选择稍后处理：{prompt.course_name}")
                return {"ok": True, "message": "已标记为稍后，系统将在开课前 5 分钟自动签到"}

            if action != "sign_now":
                return {"ok": False, "message": "不支持的操作"}

            state.auto_attempted.add(key)
            return self._do_sign(state, prompt.schedule_id, reason="用户确认立即签到")

    def manual_sign(self, token: str, key: str | None, schedule_id: str | None) -> dict[str, Any]:
        state = self._get_state(token)
        with state.lock:
            if key:
                session = state.week_sessions.get(key)
                if session is None:
                    return {"ok": False, "message": "课程不存在"}
                schedule_id = session.schedule_id
                state.auto_attempted.add(key)
            elif not schedule_id:
                return {"ok": False, "message": "缺少 schedule_id"}

            return self._do_sign(state, schedule_id, reason="用户手动签到")

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
                if session.attendance != "未出勤":
                    state.pending_prompts.pop(key, None)
                    continue

                minutes = (session.start_time - now).total_seconds() / 60

                if 5 < minutes <= 10 and key not in state.prompted and key not in state.auto_attempted:
                    state.prompted.add(key)
                    state.pending_prompts[key] = PromptNotification(
                        key=key,
                        schedule_id=session.schedule_id,
                        course_name=session.course_name,
                        start_time=session.start_time,
                        created_at=now,
                    )
                    self._append_event(
                        state,
                        "info",
                        f"课程 {session.course_name} 将在 10 分钟内开始，等待用户确认是否立即签到",
                    )

                if -30 <= minutes <= 5 and key not in state.auto_attempted:
                    state.auto_attempted.add(key)
                    state.pending_prompts.pop(key, None)
                    self._do_sign(state, session.schedule_id, reason="开课前 5 分钟自动签到")

    def _refresh_week(self, state: UserRuntimeState, force: bool = False) -> None:
        now = datetime.now(tz=SHANGHAI_TZ)
        if not force and state.last_sync_at is not None:
            if (now - state.last_sync_at).total_seconds() < 60:
                return

        sessions = state.client.get_week_schedule(now=now)
        state.week_sessions = {item.key: item for item in sessions}
        state.last_sync_at = now

    def _do_sign(self, state: UserRuntimeState, schedule_id: str, reason: str) -> dict[str, Any]:
        try:
            resp = state.client.sign_now(schedule_id)
        except Exception as exc:  # noqa: BLE001
            message = f"{reason}失败: {exc}"
            self._append_event(state, "error", message)
            return {"ok": False, "message": message}

        status = str(resp.get("STATUS", "")) if isinstance(resp, dict) else ""
        if status == "0":
            self._append_event(state, "success", f"{reason}成功")
            self._refresh_week(state, force=True)
            return {"ok": True, "message": f"{reason}成功", "data": resp}

        errmsg = resp.get("ERRMSG", "未知错误") if isinstance(resp, dict) else "响应格式异常"
        message = f"{reason}失败: {errmsg}"
        self._append_event(state, "error", message)
        return {"ok": False, "message": message, "data": resp}

    def _append_event(self, state: UserRuntimeState, level: str, message: str, meta: dict | None = None) -> None:
        state.events.append(
            RuntimeEvent(
                level=level,
                message=message,
                at=datetime.now(tz=SHANGHAI_TZ),
                meta=meta or {},
            )
        )
