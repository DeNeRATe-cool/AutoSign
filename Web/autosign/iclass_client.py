from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

import requests
from bs4 import BeautifulSoup
from zoneinfo import ZoneInfo

from .models import ClassSession

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")

SSO_LOGIN_URL = "https://sso.buaa.edu.cn/login"
VPN_CAS_LOGIN_URL = (
    "https://d.buaa.edu.cn/https/77726476706e69737468656265737421e3e44ed225256951300d8db9d6562d/login"
    "?service=https%3A%2F%2Fd.buaa.edu.cn%2Flogin%3Fcas_login%3Dtrue"
)

VPN_8346 = (
    "https://d.buaa.edu.cn/https-8346/"
    "77726476706e69737468656265737421f9f44d9d342326526b0988e29d51367ba018"
)
VPN_8347 = (
    "https://d.buaa.edu.cn/https-8347/"
    "77726476706e69737468656265737421f9f44d9d342326526b0988e29d51367ba018"
)
DIRECT_8346 = "https://iclass.buaa.edu.cn:8346"
DIRECT_8347 = "https://iclass.buaa.edu.cn:8347"


class IClassApiError(RuntimeError):
    pass


@dataclass
class AuthContext:
    student_id: str
    user_id: str
    session_header: str
    user_name: str


class IClassClient:
    """iClass API 客户端。

    关键流程：
    1) 通过 BUAA SSO 登录拿到 iClass 可用 cookie
    2) 调用 /app/user/login.action 拿 user_id + sessionId
    3) 用 sessionId + id 继续查询课表/签到
    """

    def __init__(self, use_vpn: bool = False, verify_ssl: bool = True) -> None:
        self.use_vpn = use_vpn
        self.session = requests.Session()
        self.session.verify = verify_ssl
        self.auth: AuthContext | None = None
        self._server_offset_ms: int = 0
        self._login_name: str | None = None

    def login(self, student_id: str, password: str) -> AuthContext:
        if not student_id or not password:
            raise IClassApiError("学号和密码不能为空")

        entry_url = VPN_CAS_LOGIN_URL if self.use_vpn else SSO_LOGIN_URL
        entry_params = None if self.use_vpn else {"service": f"{self._service_home()}/"}

        resp = self.session.get(entry_url, params=entry_params, allow_redirects=True, timeout=20)

        if self._looks_like_iclass(resp.url):
            self._maybe_capture_login_name(resp.url)
            return self._fetch_auth_context(student_id)

        execution = self._parse_execution(resp.text)
        if not execution:
            raise IClassApiError("无法从 SSO 页面解析 execution，可能是登录页面结构变化")

        payload = {
            "username": student_id,
            "password": password,
            "submit": "登录",
            "type": "username_password",
            "execution": execution,
            "_eventId": "submit",
        }

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
            ),
            "Referer": entry_url,
            "Content-Type": "application/x-www-form-urlencoded",
        }

        login_resp = self.session.post(
            entry_url,
            data=payload,
            headers=headers,
            allow_redirects=False,
            timeout=20,
        )

        if login_resp.status_code == 401:
            login_resp = self._handle_weak_password(entry_url, login_resp, headers)

        final_resp = self._follow_redirect(login_resp)
        if final_resp is not None:
            self._maybe_capture_login_name(final_resp.url)

        if not self._looks_like_iclass(getattr(final_resp, "url", "")):
            # VPN 情况下可能先回到 d.buaa.edu.cn，需要再探测一次 iClass service
            probe = self.session.get(f"{self._service_home()}/", allow_redirects=True, timeout=20)
            self._maybe_capture_login_name(probe.url)
            if not self._looks_like_iclass(probe.url):
                raise IClassApiError(f"SSO 登录后未成功进入 iClass，最终 URL: {probe.url}")

        return self._fetch_auth_context(student_id)

    def get_week_schedule(self, now: datetime | None = None) -> list[ClassSession]:
        self._ensure_login()
        now = now or datetime.now(tz=SHANGHAI_TZ)
        monday = now.date() - timedelta(days=now.weekday())

        sessions: list[ClassSession] = []
        for i in range(7):
            day = monday + timedelta(days=i)
            sessions.extend(self.get_schedule_by_date(day))

        unique: dict[str, ClassSession] = {}
        for item in sessions:
            unique[item.key] = item

        return sorted(unique.values(), key=lambda x: x.start_time)

    def get_schedule_by_date(self, target_date: date) -> list[ClassSession]:
        self._ensure_login()
        assert self.auth
        date_str = target_date.strftime("%Y%m%d")

        endpoint = f"{self._base_8347()}/app/course/get_stu_course_sched.action"
        headers = self._headers()

        # 方案 A：优先对齐公开仓库的请求方式（POST + query params + sessionId）
        url_a = f"{endpoint}?id={quote(self.auth.user_id)}"
        resp = self.session.post(
            url_a,
            params={"dateStr": date_str},
            headers=headers,
            timeout=20,
        )
        data = self._to_json_or_none(resp)
        sessions = self._parse_schedule_response(data)
        if sessions is not None:
            return sessions

        # 方案 B：兼容旧实现（GET + id/dateStr + sessionId）
        resp = self.session.get(
            endpoint,
            params={"id": self.auth.user_id, "dateStr": date_str},
            headers=headers,
            timeout=20,
        )
        data = self._to_json_or_none(resp)
        sessions = self._parse_schedule_response(data)
        if sessions is None:
            raise IClassApiError(f"获取 {date_str} 课表失败")
        return sessions

    def sign_now(self, schedule_id: str, timestamp_ms: int | None = None) -> dict[str, Any]:
        self._ensure_login()
        assert self.auth
        if not schedule_id:
            raise IClassApiError("schedule_id 不能为空")

        ts = timestamp_ms if timestamp_ms is not None else self.get_adjusted_timestamp_ms()

        endpoints = self._sign_endpoints()
        headers = self._headers()
        last_error: str | None = None
        payload = {
            "id": self.auth.user_id,
            "courseSchedId": schedule_id,
            "timestamp": str(ts),
        }

        for endpoint in endpoints:
            try:
                resp = self.session.post(
                    endpoint,
                    params=payload,
                    headers=headers,
                    timeout=20,
                    allow_redirects=False,
                )
                data = self._to_json_or_none(resp)
                if isinstance(data, dict):
                    return data
                last_error = f"{endpoint} 返回非 JSON, HTTP {resp.status_code}"
            except requests.RequestException as exc:
                last_error = f"{endpoint} 请求失败: {exc}"

        raise IClassApiError(last_error or "签到失败")

    def get_server_timestamp_ms(self) -> int:
        self._ensure_login()
        assert self.auth

        for endpoint in self._timestamp_endpoints():
            url = f"{endpoint}?id={quote(self.auth.user_id)}"
            try:
                resp = self.session.post(url, headers=self._headers(), timeout=15)
                data = self._to_json_or_none(resp)
                if not isinstance(data, dict):
                    continue

                ts = data.get("timestamp")
                if ts is None and isinstance(data.get("result"), dict):
                    ts = data["result"].get("timestamp")

                if ts is not None:
                    value = int(str(ts))
                    if value < 10_000_000_000:  # 秒转毫秒
                        value *= 1000
                    return value
            except (requests.RequestException, ValueError, TypeError):
                continue

        # fallback: 本地时间 + 登录时测得的偏移
        return int(time.time() * 1000) + int(self._server_offset_ms)

    def get_adjusted_timestamp_ms(self, now: datetime | None = None) -> int:
        now = now or datetime.now(tz=SHANGHAI_TZ)
        return int(now.timestamp() * 1000) + int(self._server_offset_ms)

    def _fetch_auth_context(self, student_id: str) -> AuthContext:
        login_api = f"{self._base_8347()}/app/user/login.action"
        params = {
            "phone": student_id,
            "password": "",
            "verificationType": "2",
            "verificationUrl": "",
            "userLevel": "1",
        }

        resp = self.session.get(login_api, params=params, timeout=20)
        data = self._to_json_or_none(resp)
        if not isinstance(data, dict) or str(data.get("STATUS")) != "0":
            raise IClassApiError(f"iClass 用户登录失败: {data}")

        result = data.get("result")
        if not isinstance(result, dict):
            raise IClassApiError("iClass 返回的用户信息结构异常")

        user_id = str(result.get("id", "")).strip()
        if not user_id:
            raise IClassApiError("iClass 用户信息缺少 id")

        session_header = str(
            result.get("sessionId")
            or result.get("sessionid")
            or self._login_name
            or ""
        ).strip()
        if not session_header:
            raise IClassApiError("iClass 用户信息缺少 sessionId")

        user_name = str(result.get("realName") or student_id)

        # 使用 Date 响应头估算服务器时间偏移
        date_header = resp.headers.get("Date")
        if date_header:
            try:
                server_ts = datetime.strptime(
                    date_header, "%a, %d %b %Y %H:%M:%S GMT"
                ).replace(tzinfo=ZoneInfo("UTC"))
                server_ms = int(server_ts.timestamp() * 1000)
                local_ms = int(time.time() * 1000)
                self._server_offset_ms = server_ms - local_ms
            except Exception:
                self._server_offset_ms = 0

        self.auth = AuthContext(
            student_id=student_id,
            user_id=user_id,
            session_header=session_header,
            user_name=user_name,
        )
        return self.auth

    def _parse_schedule_response(self, data: Any) -> list[ClassSession] | None:
        if not isinstance(data, dict):
            return None

        status = str(data.get("STATUS", ""))
        if status == "2":  # 无课程
            return []
        if status != "0":
            return None

        rows = data.get("result")
        if not isinstance(rows, list):
            return []

        sessions: list[ClassSession] = []
        for row in rows:
            if not isinstance(row, dict):
                continue

            schedule_id = str(row.get("id") or row.get("courseSchedId") or "").strip()
            if not schedule_id:
                continue

            start = self._parse_dt(row.get("classBeginTime"))
            end = self._parse_dt(row.get("classEndTime"))
            if start is None or end is None:
                continue

            sessions.append(
                ClassSession(
                    schedule_id=schedule_id,
                    course_id=str(row.get("courseId") or row.get("course_id") or ""),
                    course_name=str(row.get("courseName") or row.get("course_name") or "未知课程"),
                    teacher=str(row.get("teacherName") or row.get("teacher_name") or "未知教师"),
                    start_time=start,
                    end_time=end,
                    raw_status=str(row.get("signStatus") or row.get("stuSignStatus") or "0"),
                )
            )

        return sessions

    def _parse_execution(self, html: str) -> str | None:
        soup = BeautifulSoup(html, "html.parser")
        execution_input = soup.find("input", {"name": "execution"})
        if execution_input is None:
            return None
        return execution_input.get("value")

    def _handle_weak_password(
        self,
        entry_url: str,
        response: requests.Response,
        headers: dict[str, str],
    ) -> requests.Response:
        soup = BeautifulSoup(response.text, "html.parser")
        continue_form = soup.find("form", {"id": "continueForm"})
        if continue_form is None:
            raise IClassApiError("SSO 返回 401 且未找到 continueForm")

        execution_input = continue_form.find("input", {"name": "execution"})
        execution = execution_input.get("value") if execution_input else None
        if not execution:
            raise IClassApiError("SSO continueForm 缺少 execution")

        time.sleep(6)
        continue_data = {
            "execution": execution,
            "_eventId": "ignoreAndContinue",
        }
        return self.session.post(
            entry_url,
            data=continue_data,
            headers=headers,
            allow_redirects=False,
            timeout=20,
        )

    def _follow_redirect(self, response: requests.Response) -> requests.Response | None:
        if response.status_code not in (301, 302, 303, 307, 308):
            return response

        location = response.headers.get("Location")
        if not location:
            raise IClassApiError("登录后重定向缺少 Location")

        return self.session.get(location, allow_redirects=True, timeout=20)

    def _service_home(self) -> str:
        return VPN_8346 if self.use_vpn else DIRECT_8346

    def _base_8347(self) -> str:
        return VPN_8347 if self.use_vpn else DIRECT_8347

    def _looks_like_iclass(self, url: str) -> bool:
        return "iclass.buaa.edu.cn" in url or "d.buaa.edu.cn/https-834" in url

    def _maybe_capture_login_name(self, url: str) -> None:
        try:
            parsed = urlparse(url)
            query = parse_qs(parsed.query)
            login_name = query.get("loginName", [None])[0]
            if login_name:
                self._login_name = login_name
        except Exception:
            pass

    def _to_json_or_none(self, response: requests.Response) -> Any | None:
        try:
            return response.json()
        except ValueError:
            return None

    def _headers(self) -> dict[str, str]:
        assert self.auth is not None
        return {
            "Accept": "application/json",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 13; M2012K11AC Build/TKQ1.221114.001; wv) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/120.0.0.0 "
                "Mobile Safari/537.36 wxwork/4.1.30 MicroMessenger/7.0.1 Language/zh"
            ),
            "sessionId": self.auth.session_header,
        }

    def _timestamp_endpoints(self) -> list[str]:
        if self.use_vpn:
            return [f"{VPN_8347}/app/common/get_timestamp.action"]
        return [
            "http://iclass.buaa.edu.cn:8081/app/common/get_timestamp.action",
            f"{DIRECT_8346}/eschool/app/common/get_timestamp.action",
        ]

    def _sign_endpoints(self) -> list[str]:
        if self.use_vpn:
            return [f"{VPN_8347}/app/course/stu_scan_sign.action"]
        return [
            "http://iclass.buaa.edu.cn:8081/app/course/stu_scan_sign.action",
            f"{DIRECT_8346}/eschool/app/course/stu_scan_sign.action",
        ]

    def _parse_dt(self, value: Any) -> datetime | None:
        if value is None:
            return None

        text = str(value).strip()
        if not text:
            return None

        patterns = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y/%m/%d %H:%M:%S",
            "%Y/%m/%d %H:%M",
        ]
        for pattern in patterns:
            try:
                dt = datetime.strptime(text, pattern)
                return dt.replace(tzinfo=SHANGHAI_TZ)
            except ValueError:
                continue

        # 兼容纯数字格式 YYYYMMDDHHMMSS
        digits = "".join(ch for ch in text if ch.isdigit())
        if len(digits) >= 12:
            try:
                if len(digits) >= 14:
                    dt = datetime.strptime(digits[:14], "%Y%m%d%H%M%S")
                else:
                    dt = datetime.strptime(digits[:12], "%Y%m%d%H%M")
                return dt.replace(tzinfo=SHANGHAI_TZ)
            except ValueError:
                return None

        return None

    def _ensure_login(self) -> None:
        if self.auth is None:
            raise IClassApiError("尚未登录")
