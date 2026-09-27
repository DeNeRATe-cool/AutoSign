from __future__ import annotations

import time
import warnings
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

# Suppress noisy urllib OpenSSL runtime warning in CLI contexts.
warnings.filterwarnings(
    "ignore",
    message="urllib3 v2 only supports OpenSSL 1.1.1+.*",
)

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
DIRECT_8081 = "http://iclass.buaa.edu.cn:8081"
VPN_SSO = VPN_CAS_LOGIN_URL.split("/login?", 1)[0]
REDIRECT_LIMIT = 8
SUCCESS_STATUSES = {"0", "200", "success"}


class IClassApiError(RuntimeError):
    pass


class _SessionExpired(IClassApiError):
    pass


@dataclass
class AuthContext:
    student_id: str
    user_id: str
    session_header: str
    user_name: str


class IClassClient:
    def __init__(self, use_vpn: bool = False, verify_ssl: bool = True) -> None:
        self.use_vpn = use_vpn
        self.session = requests.Session()
        self.session.verify = verify_ssl
        self.auth: AuthContext | None = None
        self._server_offset_ms: int = 0
        self._login_name: str | None = None

    def login(self, student_id: str, password: str) -> AuthContext:
        # Never reuse another account's cookies or a previous loginName.
        self.auth = None
        self._login_name = None
        self._server_offset_ms = 0
        self.session.cookies.clear()
        if not student_id or not password:
            raise IClassApiError("学号和密码不能为空")

        entry_url = VPN_CAS_LOGIN_URL if self.use_vpn else SSO_LOGIN_URL
        entry_params = None if self.use_vpn else {
            "service": f"{DIRECT_8346}/?type=jumpMyCenter"
        }
        response = self._request(
            "get", entry_url, "打开统一认证", params=entry_params,
            allow_redirects=False,
        )
        response = self._follow_redirect(response)
        execution = self._parse_execution(response.text)
        if not self._login_name and execution:
            soup = BeautifulSoup(response.text, "html.parser")
            form = soup.find("form", {"id": "fm1"}) or soup.find("form")
            payload = {
                str(field["name"]): str(field.get("value", ""))
                for field in (form.find_all("input", {"type": "hidden"}) if form else [])
                if field.get("name")
            }
            payload.update({
                "username": student_id, "password": password,
                "submit": "登录", "execution": execution, "_eventId": "submit",
            })
            payload.setdefault("type", "username_password")
            action = str(form.get("action", "")) if form else ""
            login_url = self._resolve_redirect_url(response.url, action) if action else response.url
            # A form action such as /login must not drop the CAS service target.
            if not urlparse(login_url).query and urlparse(response.url).query:
                login_url += "?" + urlparse(response.url).query
            headers = {"Referer": response.url}
            response = self._request(
                "post", login_url, "统一认证登录", data=payload, headers=headers,
                allow_redirects=False,
            )
            # CAS may return the password-expiry continuation as HTTP 200 or 401.
            if BeautifulSoup(response.text, "html.parser").find("form", {"id": "continueForm"}):
                response = self._handle_weak_password(login_url, response, headers)
            if response.status_code == 401:
                raise IClassApiError("统一认证拒绝登录，请检查账号密码或验证码（HTTP 401）")
            response = self._follow_redirect(response)

        if not self._login_name:
            # WebVPN first lands on its portal. iClass needs its own SSO jump.
            response = self._request(
                "get", f"{self._service_home()}/?type=jumpMyCenter",
                "获取 iClass 登录标识", allow_redirects=False,
            )
            self._follow_redirect(response)
        if not self._login_name:
            raise IClassApiError(
                "SSO 登录后未取得 iClass loginName，请检查账号密码、验证码或统一认证状态"
            )
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
        date_str = target_date.strftime("%Y%m%d")
        for attempt in range(2):
            assert self.auth
            try:
                response = self._request(
                    "get", f"{self._base_8347()}/app/course/get_stu_course_sched.action",
                    "查询课表", params={"id": self.auth.user_id, "dateStr": date_str},
                    headers=self._headers(), allow_redirects=False,
                )
                data = self._read_json(response, "查询课表")
                self._check_session(data)
                sessions = self._parse_schedule_response(data, target_date)
                if sessions is None:
                    raise IClassApiError(self._error_message(data, f"获取 {date_str} 课表失败"))
                return sessions
            except _SessionExpired:
                if attempt:
                    raise
                self._refresh_auth_context()
        raise IClassApiError("查询课表失败")

    @staticmethod
    def is_sign_success(data: Any) -> bool:
        return (
            isinstance(data, dict)
            and str(data.get("STATUS")) in SUCCESS_STATUSES
            and isinstance(data.get("result"), dict)
            and str(data["result"].get("stuSignStatus")) == "1"
        )

    def sign_now(self, schedule_id: str, timestamp_ms: int | None = None) -> dict[str, Any]:
        self._ensure_login()
        if not schedule_id:
            raise IClassApiError("schedule_id 不能为空")
        for attempt in range(2):
            assert self.auth
            try:
                # Do not derive a timestamp from the start of a long-running poll.
                ts = timestamp_ms if timestamp_ms is not None and not attempt else self.get_server_timestamp_ms()
                response = self._request(
                    "post", self._sign_endpoints()[0], "签到",
                    params={"courseSchedId": schedule_id, "timestamp": str(ts)},
                    data={"id": self.auth.user_id}, headers=self._headers(),
                    allow_redirects=False,
                )
                data = self._read_json(response, "签到")
                self._check_session(data)
                if not self.is_sign_success(data):
                    raise IClassApiError(self._error_message(data, "签到未成功确认（缺少 stuSignStatus=1）"))
                return data
            except _SessionExpired:
                if attempt:
                    raise
                self._refresh_auth_context()
        raise IClassApiError("签到失败")

    def get_server_timestamp_ms(self) -> int:
        self._ensure_login()
        response = self._request(
            "get", self._timestamp_endpoints()[0], "获取签到服务器时间",
            allow_redirects=False,
        )
        data = self._read_json(response, "获取签到服务器时间")
        self._check_session(data)
        if "STATUS" in data and str(data["STATUS"]) not in SUCCESS_STATUSES:
            raise IClassApiError(self._error_message(data, "获取签到服务器时间失败"))
        timestamp = str(data.get("timestamp", ""))
        if not timestamp.isdigit() or int(timestamp) <= 0:
            raise IClassApiError("签到服务器未返回有效 timestamp，已取消本次签到")
        # The upstream timestamp is opaque: do not convert seconds or guess locally.
        return int(timestamp)

    def get_adjusted_timestamp_ms(self, now: datetime | None = None) -> int:
        now = now or datetime.now(tz=SHANGHAI_TZ)
        return int(now.timestamp() * 1000) + int(self._server_offset_ms)

    def _fetch_auth_context(self, student_id: str) -> AuthContext:
        login_api = f"{self._base_8347()}/app/user/login.action"
        if not self._login_name:
            raise IClassApiError("缺少 SSO loginName，不能用学号代替 iClass 登录标识")
        params = {
            "phone": self._login_name,
            "password": "",
            "verificationType": "2",
            "verificationUrl": "",
            "userLevel": "1",
        }
        resp = self._request("get", login_api, "iClass 用户登录", params=params, allow_redirects=False)
        data = self._read_json(resp, "iClass 用户登录")

        if str(data.get("STATUS")) not in SUCCESS_STATUSES:
            raise IClassApiError(self._error_message(data, "iClass 用户登录失败"))

        result = data.get("result")
        if not isinstance(result, dict):
            raise IClassApiError("iClass 返回的用户信息结构异常")

        user_id = str(result.get("id") or "").strip()
        if not user_id:
            raise IClassApiError("iClass 用户信息缺少 id")

        session_header = str(
            result.get("sessionId")
            or result.get("sessionid")
            or ""
        ).strip()
        if not session_header:
            raise IClassApiError("iClass 用户信息缺少 sessionId")

        user_name = str(result.get("realName") or student_id)

        date_header = resp.headers.get("Date")
        if date_header:
            try:
                server_ts = datetime.strptime(date_header, "%a, %d %b %Y %H:%M:%S GMT").replace(tzinfo=ZoneInfo("UTC"))
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

    def _parse_schedule_response(self, data: Any, target_date: date | None = None) -> list[ClassSession] | None:
        if not isinstance(data, dict):
            return None

        status = str(data.get("STATUS", ""))
        # Live iClass uses STATUS=2 without an error for days with no courses.
        # Do not hide a business error or malformed/nonempty result under this code.
        if (
            status == "2"
            and not data.get("ERRMSG")
            and str(data.get("ERRCODE") or "0") == "0"
            and data.get("result") in (None, [])
        ):
            return []
        if status not in SUCCESS_STATUSES:
            return None

        rows = data.get("result")
        if not isinstance(rows, list):
            return None

        sessions: list[ClassSession] = []
        for row in rows:
            if not isinstance(row, dict):
                continue

            schedule_id = str(row.get("id") or row.get("courseSchedId") or "").strip()
            if not schedule_id:
                continue

            start = self._parse_dt(row.get("classBeginTime"), target_date)
            end = self._parse_dt(row.get("classEndTime"), target_date)
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
                    raw_status=str(row.get("signStatus", row.get("stuSignStatus", "0"))),
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
        action = str(continue_form.get("action", ""))
        continue_url = self._resolve_redirect_url(response.url or entry_url, action) if action else (response.url or entry_url)
        if not urlparse(continue_url).query and urlparse(response.url or entry_url).query:
            continue_url += "?" + urlparse(response.url or entry_url).query
        return self._request(
            "post", continue_url, "继续统一认证登录", data=continue_data,
            headers=headers, allow_redirects=False,
        )

    def _follow_redirect(self, response: requests.Response) -> requests.Response:
        for _ in range(REDIRECT_LIMIT):
            self._maybe_capture_login_name(response.url)
            if self._login_name or response.status_code not in (301, 302, 303, 307, 308):
                return response
            location = response.headers.get("Location")
            if not location:
                raise IClassApiError("登录后重定向缺少 Location")
            target = self._resolve_redirect_url(response.url, location)
            self._maybe_capture_login_name(target)
            if self._login_name:
                return response
            response = self._request("get", target, "跟随认证跳转", allow_redirects=False)
        self._maybe_capture_login_name(response.url)
        if not self._login_name and response.status_code in (301, 302, 303, 307, 308):
            raise IClassApiError("统一认证重定向次数过多")
        return response

    def _resolve_redirect_url(self, current_url: str, location: str) -> str:
        mappings = ((VPN_8346, DIRECT_8346), (VPN_8347, DIRECT_8347),
                    (VPN_SSO, "https://sso.buaa.edu.cn"))
        location = location.strip()
        if location.startswith(("/https/", "/http/", "/https-", "/http-")):
            return urljoin("https://d.buaa.edu.cn", location)
        # Resolve relative paths against the original upstream origin before wrapping.
        for vpn, direct in mappings:
            if self._matches_base(current_url, vpn):
                current_url = direct + current_url[len(vpn):]
                break
        target = urljoin(current_url, location)
        if self.use_vpn:
            for vpn, direct in mappings:
                if self._matches_base(target, direct):
                    return vpn + target[len(direct):]
        return target

    def _service_home(self) -> str:
        return VPN_8346 if self.use_vpn else DIRECT_8346

    def _base_8347(self) -> str:
        return VPN_8347 if self.use_vpn else DIRECT_8347

    def _looks_like_iclass(self, url: str) -> bool:
        parsed = urlparse(url)
        return parsed.hostname == "iclass.buaa.edu.cn" or any(
            self._matches_base(url, base) for base in (VPN_8346, VPN_8347)
        )

    @staticmethod
    def _matches_base(url: str, base: str) -> bool:
        return url == base or any(url.startswith(base + delimiter) for delimiter in ("/", "?", "#"))

    def _maybe_capture_login_name(self, url: str) -> None:
        if not self._looks_like_iclass(url):
            return
        # loginName may contain bare '+' in base64. parse_qs would corrupt it.
        for part in urlparse(url).query.split("&"):
            key, separator, value = part.partition("=")
            if separator and key.lower() == "loginname" and value:
                self._login_name = unquote(value)
                return

    def _request(self, method: str, url: str, operation: str, **kwargs: Any) -> requests.Response:
        try:
            return getattr(self.session, method)(url, timeout=20, **kwargs)
        except requests.RequestException as exc:
            # Exception URLs may contain CAS tickets or the encrypted loginName.
            raise IClassApiError(f"{operation}网络请求失败（{type(exc).__name__}）") from None

    def _read_json(self, response: requests.Response, operation: str) -> dict[str, Any]:
        if response.status_code in (401, 403):
            raise _SessionExpired(f"{operation}登录状态失效（HTTP {response.status_code}）")
        if response.status_code in (301, 302, 303, 307, 308):
            target = urlparse(self._resolve_redirect_url(response.url, response.headers.get("Location", "")))
            if (target.hostname == "sso.buaa.edu.cn" and target.path == "/login") or (
                target.hostname == "d.buaa.edu.cn"
                and (target.path == "/login" or target.path == urlparse(VPN_SSO).path + "/login")
            ):
                raise _SessionExpired(f"{operation}被重定向到统一认证，请重新登录")
        if not 200 <= response.status_code < 300:
            raise IClassApiError(f"{operation}失败（HTTP {response.status_code}）")
        try:
            data = response.json()
        except ValueError:
            raise IClassApiError(f"{operation}返回非 JSON 响应，请检查统一认证或网络状态") from None
        if not isinstance(data, dict):
            raise IClassApiError(f"{operation}返回的数据结构异常")
        return data

    @staticmethod
    def _error_message(data: dict[str, Any], operation: str) -> str:
        message = str(data.get("ERRMSG") or "服务器未提供错误信息")
        code = str(data.get("ERRCODE") or data.get("STATUS") or "未知")
        return f"{operation}: {message}（错误码 {code}）"

    def _check_session(self, data: dict[str, Any]) -> None:
        if str(data.get("STATUS")) not in SUCCESS_STATUSES and "登录" in str(data.get("ERRMSG", "")):
            raise _SessionExpired(self._error_message(data, "iClass 登录状态失效"))

    def _refresh_auth_context(self) -> None:
        self._ensure_login()
        assert self.auth
        student_id = self.auth.student_id
        self.auth = None
        self._login_name = None
        response = self._request(
            "get", f"{self._service_home()}/?type=jumpMyCenter",
            "刷新 iClass 登录标识", allow_redirects=False,
        )
        self._follow_redirect(response)
        if not self._login_name:
            raise IClassApiError("统一认证会话已失效，请重新登录")
        self._fetch_auth_context(student_id)

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
        base = VPN_8347 if self.use_vpn else DIRECT_8081
        return [f"{base}/app/common/get_timestamp.action"]

    def _sign_endpoints(self) -> list[str]:
        if self.use_vpn:
            return [f"{VPN_8347}/app/course/stu_scan_sign.action"]
        return [f"{DIRECT_8081}/eschool/app/course/stu_scan_sign.action"]

    def _parse_dt(self, value: Any, target_date: date | None = None) -> datetime | None:
        if value is None:
            return None

        text = str(value).strip()
        if not text:
            return None

        if target_date is not None:
            for pattern in ("%H:%M:%S", "%H:%M"):
                try:
                    parsed_time = datetime.strptime(text, pattern).time()
                    return datetime.combine(target_date, parsed_time, tzinfo=SHANGHAI_TZ)
                except ValueError:
                    continue

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
