"""Offline contracts for the university requests used by the standalone client."""

import json
from datetime import date
from urllib.parse import parse_qs, quote, urlencode, urlparse

import pytest

from autosign_cli.core import iclass_client as module
from autosign_cli.core.iclass_client import AuthContext, IClassApiError, IClassClient

requests = module.requests


STUDENT_ID = "23370001"
LOGIN_NAME = "opaque+identity/token="
USER_ID = "iclass-user-1"
SESSION_ID = "iclass-session-1"
MY_CENTER = f"{module.DIRECT_8346}/?type=jumpMyCenter"
SSO_FORM_URL = f"{module.SSO_LOGIN_URL}?{urlencode({'service': MY_CENTER})}"
AUTH_PAYLOAD = {
    "STATUS": "0",
    "result": {"id": USER_ID, "sessionId": SESSION_ID, "realName": "Test User"},
}
SIGN_PAYLOAD = {"STATUS": "0", "result": {"stuSignStatus": "1"}}


def response(url, *, payload=None, text="", status=200, location=None):
    result = requests.Response()
    result.url = url
    result.status_code = status
    result.encoding = "utf-8"
    result._content = (json.dumps(payload) if payload is not None else text).encode()
    if location is not None:
        result.headers["Location"] = location
    return result


class OfflineSession:
    def __init__(self):
        self.verify = True
        self.cookies = requests.cookies.RequestsCookieJar()
        self.calls = []
        self.handler = None

    def _request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        assert self.handler is not None, "Network response was not configured"
        return self.handler(method, url, kwargs)

    def get(self, url, **kwargs):
        return self._request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self._request("POST", url, **kwargs)

    def close(self):
        pass


def make_client(monkeypatch, *, use_vpn=False, authenticated=False):
    session = OfflineSession()
    monkeypatch.setattr(module.requests, "Session", lambda: session)
    client = IClassClient(use_vpn=use_vpn)
    if authenticated:
        client.auth = AuthContext(STUDENT_ID, USER_ID, SESSION_ID, "Test User")
    return client, session


def install_direct_login(session, *, auth_payload=AUTH_PAYLOAD,
                         login_name=LOGIN_NAME, weak_status=None, bare_action=False):
    """Model SSO form submission, CAS callback and a relative MyCenter redirect."""
    post_count = 0
    login_name_query = quote(login_name, safe="+=/")
    form = (
        f'<form action="/login?{urlencode({"service": MY_CENTER})}">'
        '<input name="execution" value="login-execution"></form>'
    )
    if bare_action:
        form = '<form action="/login"><input name="execution" value="login-execution"></form>'

    def handler(method, url, kwargs):
        nonlocal post_count
        path = urlparse(url).path
        if method == "GET" and urlparse(url).hostname == "sso.buaa.edu.cn":
            assert kwargs.get("allow_redirects") is False
            service = (kwargs.get("params") or {}).get("service")
            if service is None:
                service = parse_qs(urlparse(url).query).get("service", [None])[0]
            assert service == MY_CENTER
            return response(SSO_FORM_URL, text=form)
        if method == "POST" and urlparse(url).hostname == "sso.buaa.edu.cn":
            assert kwargs.get("allow_redirects") is False
            assert parse_qs(urlparse(url).query).get("service") == [MY_CENTER]
            assert kwargs["headers"]["Referer"] == SSO_FORM_URL
            post_count += 1
            if post_count == 1:
                assert kwargs["data"]["username"] == STUDENT_ID
                assert kwargs["data"]["password"] == "test-password"
                assert kwargs["data"]["execution"] == "login-execution"
                if weak_status is not None:
                    weak_form = (
                        '<form id="continueForm" action="/login?'
                        + urlencode({"service": MY_CENTER})
                        + '"><input name="execution" value="weak-execution"></form>'
                    )
                    if bare_action:
                        weak_form = '<form id="continueForm" action="/login"><input name="execution" value="weak-execution"></form>'
                    return response(url, text=weak_form, status=weak_status)
            else:
                assert kwargs["data"]["execution"] == "weak-execution"
                assert kwargs["data"]["_eventId"] == "ignoreAndContinue"
                assert "password" not in kwargs["data"]
            return response(url, status=302,
                            location=f"{module.DIRECT_8346}/cas-login?ticket=test-ticket")
        if method == "GET" and path == "/cas-login":
            assert kwargs.get("allow_redirects") is False
            return response(url, status=302,
                            location=f"/?type=jumpMyCenter&LOGINNAME={login_name_query}#/MyCenter")
        if method == "GET" and path == "/app/user/login.action":
            assert kwargs["params"] == {
                "phone": login_name,
                "password": "",
                "userLevel": "1",
                "verificationType": "2",
                "verificationUrl": "",
            }
            return response(url, payload=auth_payload)
        if method == "GET" and url.startswith(module.DIRECT_8346):
            # A client may stop when it sees loginName or fetch that last page.
            assert kwargs.get("allow_redirects") is False
            return response(url, status=302,
                            location=f"{module.DIRECT_8346}/?loginName={login_name_query}")
        raise AssertionError(f"Unexpected request: {method} {url}")

    session.handler = handler


@pytest.mark.parametrize("login_name", ["opaque+identity/token=", "opaque%identity+="])
def test_login_exchanges_sso_login_name_and_preserves_service(monkeypatch, login_name):
    client, session = make_client(monkeypatch)
    install_direct_login(session, login_name=login_name)

    auth = client.login(STUDENT_ID, "test-password")

    assert auth.user_id == USER_ID
    assert auth.session_header == SESSION_ID
    assert auth.student_id == STUDENT_ID
    app_calls = [call for call in session.calls if "/app/user/login.action" in call[1]]
    assert len(app_calls) == 1
    assert app_calls[0][2]["params"]["phone"] != STUDENT_ID


@pytest.mark.parametrize("status", [200, 401])
def test_login_handles_weak_password_continue_form(monkeypatch, status):
    client, session = make_client(monkeypatch)
    install_direct_login(session, weak_status=status)
    monkeypatch.setattr(module.time, "sleep", lambda *_: None)

    assert client.login(STUDENT_ID, "test-password").session_header == SESSION_ID
    assert len([call for call in session.calls if call[0] == "POST"]) == 2


def test_bare_form_actions_preserve_cas_service_including_continuation(monkeypatch):
    client, session = make_client(monkeypatch)
    install_direct_login(session, weak_status=200, bare_action=True)
    monkeypatch.setattr(module.time, "sleep", lambda *_: None)
    assert client.login(STUDENT_ID, "test-password").session_header == SESSION_ID


def test_vpn_login_name_without_trailing_slash(monkeypatch):
    client, session = make_client(monkeypatch, use_vpn=True)

    def handler(method, url, kwargs):
        if url.endswith("/app/user/login.action"):
            assert kwargs["params"]["phone"] == LOGIN_NAME
            return response(url, payload=AUTH_PAYLOAD)
        return response(url, status=302, location=module.VPN_8346 + "?loginName=" + LOGIN_NAME)

    session.handler = handler
    assert client.login(STUDENT_ID, "test-password").session_header == SESSION_ID


def test_time_only_schedule_uses_requested_date_and_keeps_zero_status(monkeypatch):
    client, session = make_client(monkeypatch, authenticated=True)
    session.handler = lambda method, url, kwargs: response(url, payload={"STATUS": "0", "result": [{
        "id": "schedule-1", "classBeginTime": "08:00", "classEndTime": "09:40:00",
        "signStatus": 0, "stuSignStatus": 1,
    }]})
    target = date(2026, 9, 27)
    rows = client.get_schedule_by_date(target)
    assert len(rows) == 1
    assert rows[0].start_time.date() == target
    assert (rows[0].start_time.hour, rows[0].end_time.minute) == (8, 40)
    assert rows[0].raw_status == "0"


@pytest.mark.parametrize("result", [
    {"id": USER_ID},
    {"id": USER_ID, "sessionId": None},
    {"id": USER_ID, "sessionId": ""},
    {"id": USER_ID, "sessionId": "  "},
    {"sessionId": SESSION_ID},
])
def test_login_requires_real_user_id_and_session_id(monkeypatch, result):
    client, session = make_client(monkeypatch)
    install_direct_login(session, auth_payload={"STATUS": "0", "result": result})

    with pytest.raises(IClassApiError):
        client.login(STUDENT_ID, "test-password")
    assert client.auth is None


def test_login_clears_previous_identity_when_new_sso_login_fails(monkeypatch):
    client, session = make_client(monkeypatch, authenticated=True)
    client._login_name = "previous-user-login-name"
    session.cookies.set("previous-user-cookie", "stale")
    session.handler = lambda method, url, kwargs: response(url, text="Invalid SSO page")

    with pytest.raises(IClassApiError):
        client.login("different-user", "test-password")

    assert client.auth is None
    assert client._login_name is None
    assert "previous-user-cookie" not in session.cookies
    assert not any("/app/user/login.action" in call[1] for call in session.calls)


def test_login_cannot_use_student_id_when_sso_never_returns_login_name(monkeypatch):
    client, session = make_client(monkeypatch)

    def handler(method, url, kwargs):
        assert "/app/user/login.action" not in url, "Missing loginName must not fall back to student id"
        if urlparse(url).hostname == "sso.buaa.edu.cn":
            return response(SSO_FORM_URL, status=302, location=MY_CENTER)
        return response(url, text="MyCenter page without a login identity")

    session.handler = handler
    with pytest.raises(IClassApiError):
        client.login(STUDENT_ID, "test-password")
    assert client.auth is None


def test_login_bounds_sso_redirect_loop(monkeypatch):
    client, session = make_client(monkeypatch)
    session.handler = lambda method, url, kwargs: response(
        url, status=302, location=SSO_FORM_URL
    )

    with pytest.raises(IClassApiError):
        client.login(STUDENT_ID, "test-password")
    assert len(session.calls) <= 10
    assert all(kwargs.get("allow_redirects") is False for _, _, kwargs in session.calls)


@pytest.mark.parametrize("callback_location", [
    f"{module.DIRECT_8346}/cas-login?ticket=test-ticket",
    f"{urlparse(module.VPN_8346).path}/cas-login?ticket=test-ticket",
    "/cas-login?ticket=test-ticket",
])
def test_vpn_login_fetches_my_center_after_gateway_login(monkeypatch, callback_location):
    client, session = make_client(monkeypatch, use_vpn=True)
    observed_my_center = False

    def handler(method, url, kwargs):
        nonlocal observed_my_center
        assert urlparse(url).hostname == "d.buaa.edu.cn"
        if method == "GET" and url == module.VPN_CAS_LOGIN_URL:
            return response(url, text='<form><input name="execution" value="execution"></form>')
        if method == "POST" and url == module.VPN_CAS_LOGIN_URL:
            return response(url, status=302, location="https://d.buaa.edu.cn/")
        if method == "GET" and url == "https://d.buaa.edu.cn/":
            return response(url, text="WebVPN gateway")
        if method == "GET" and url == f"{module.VPN_8346}/cas-login?ticket=test-ticket":
            return response(url, status=302, location=(
                f"{module.DIRECT_8346}/?loginName={quote(LOGIN_NAME, safe='')}&type=jumpMyCenter"
            ))
        if method == "GET" and url.startswith(module.VPN_8346):
            observed_my_center = True
            assert "type=jumpMyCenter" in url or (kwargs.get("params") or {}).get("type") == "jumpMyCenter"
            return response(url, status=302, location=callback_location)
        if method == "GET" and url == f"{module.VPN_8347}/app/user/login.action":
            assert observed_my_center
            assert kwargs["params"]["phone"] == LOGIN_NAME
            return response(url, payload=AUTH_PAYLOAD)
        raise AssertionError(f"Unexpected request: {method} {url}")

    session.handler = handler
    assert client.login(STUDENT_ID, "test-password").session_header == SESSION_ID
    assert observed_my_center


@pytest.mark.parametrize("use_vpn", [False, True])
def test_schedule_uses_get_and_real_session_header(monkeypatch, use_vpn):
    client, session = make_client(monkeypatch, use_vpn=use_vpn, authenticated=True)
    expected_base = module.VPN_8347 if use_vpn else module.DIRECT_8347

    def handler(method, url, kwargs):
        assert method == "GET"
        assert url == f"{expected_base}/app/course/get_stu_course_sched.action"
        assert kwargs["params"] == {"id": USER_ID, "dateStr": "20260927"}
        assert kwargs["headers"]["sessionId"] == SESSION_ID
        return response(url, payload={"STATUS": 0, "result": [{
            "id": "schedule-1", "courseName": "Test Class",
            "classBeginTime": "2026-09-27 08:00:00", "classEndTime": "2026-09-27 09:40:00",
            "signStatus": "2",
        }]})

    session.handler = handler
    result = client.get_schedule_by_date(date(2026, 9, 27))
    assert len(result) == 1
    assert result[0].schedule_id == "schedule-1"
    assert result[0].raw_status == "2"


@pytest.mark.parametrize("payload,status,text", [
    ({"STATUS": "1", "ERRCODE": "106", "ERRMSG": "用户不存在！"}, 200, ""),
    ({"STATUS": "2", "ERRMSG": "upstream rejected request"}, 200, ""),
    ({"STATUS": "0", "result": {}}, 200, ""),
    ({"STATUS": "0", "result": []}, 500, ""),
    (None, 200, "<html>SSO login</html>"),
])
def test_schedule_errors_are_not_reported_as_empty_days(monkeypatch, payload, status, text):
    client, session = make_client(monkeypatch, authenticated=True)
    session.handler = lambda method, url, kwargs: response(url, payload=payload, status=status, text=text)

    with pytest.raises(IClassApiError):
        client.get_schedule_by_date(date(2026, 9, 27))


def test_empty_successful_schedule_remains_valid(monkeypatch):
    client, session = make_client(monkeypatch, authenticated=True)
    session.handler = lambda method, url, kwargs: response(url, payload={"STATUS": "0", "result": []})
    assert client.get_schedule_by_date(date(2026, 9, 27)) == []


@pytest.mark.parametrize("payload", [
    {"STATUS": "2"},
    {"STATUS": 2, "result": []},
    {"STATUS": "2", "result": None, "ERRCODE": "0", "ERRMSG": ""},
])
def test_live_empty_day_status_does_not_abort_week(monkeypatch, payload):
    client, session = make_client(monkeypatch, authenticated=True)
    session.handler = lambda method, url, kwargs: response(url, payload=payload)
    assert client.get_week_schedule() == []
    assert len(session.calls) == 7


@pytest.mark.parametrize("payload", [
    {"STATUS": "2", "ERRCODE": "106"},
    {"STATUS": "2", "result": {}},
    {"STATUS": "2", "result": [{"id": "unexpected-course"}]},
])
def test_empty_day_status_does_not_hide_other_errors(monkeypatch, payload):
    client, session = make_client(monkeypatch, authenticated=True)
    session.handler = lambda method, url, kwargs: response(url, payload=payload)
    with pytest.raises(IClassApiError):
        client.get_schedule_by_date(date(2026, 9, 27))


@pytest.mark.parametrize("use_vpn", [False, True])
@pytest.mark.parametrize("timestamp", [1713600000, "1713600000123"])
@pytest.mark.parametrize("api_status,sign_status", [(0, 1), ("0", "1"), (200, "1"), ("success", 1)])
def test_sign_uses_server_timestamp_and_exact_upstream_contract(
    monkeypatch, use_vpn, timestamp, api_status, sign_status
):
    client, session = make_client(monkeypatch, use_vpn=use_vpn, authenticated=True)
    base = module.VPN_8347 if use_vpn else "http://iclass.buaa.edu.cn:8081"
    sign_path = "app/course/stu_scan_sign.action" if use_vpn else "eschool/app/course/stu_scan_sign.action"

    def handler(method, url, kwargs):
        if method == "GET":
            assert url == f"{base}/app/common/get_timestamp.action"
            return response(url, payload={"timestamp": timestamp})
        assert method == "POST"
        assert url == f"{base}/{sign_path}"
        assert kwargs["params"] == {"courseSchedId": "schedule-1", "timestamp": str(timestamp)}
        assert kwargs["data"] == {"id": USER_ID}
        assert kwargs["headers"]["sessionId"] == SESSION_ID
        return response(url, payload={"STATUS": api_status, "result": {"stuSignStatus": sign_status}})

    session.handler = handler
    result = client.sign_now("schedule-1")
    assert str(result["result"]["stuSignStatus"]) == "1"
    assert [call[0] for call in session.calls] == ["GET", "POST"]


def test_explicit_timestamp_compatibility_skips_clock_request(monkeypatch):
    client, session = make_client(monkeypatch, authenticated=True)

    def handler(method, url, kwargs):
        assert method == "POST"
        assert kwargs["params"]["timestamp"] == "1713600000123"
        return response(url, payload=SIGN_PAYLOAD)

    session.handler = handler
    assert client.sign_now("schedule-1", timestamp_ms=1713600000123) == SIGN_PAYLOAD
    assert len(session.calls) == 1


@pytest.mark.parametrize("clock_payload", [
    {}, {"timestamp": None}, {"timestamp": ""}, {"timestamp": "invalid"},
    {"timestamp": 0}, {"timestamp": -1}, {"timestamp": True}, {"timestamp": 1.5},
])
def test_invalid_server_timestamp_never_falls_back_to_local_clock(monkeypatch, clock_payload):
    client, session = make_client(monkeypatch, authenticated=True)

    def handler(method, url, kwargs):
        assert method == "GET", "A malformed server clock must prevent signing"
        return response(url, payload=clock_payload)

    session.handler = handler
    with pytest.raises(IClassApiError):
        client.sign_now("schedule-1")
    assert len(session.calls) == 1


@pytest.mark.parametrize("payload,status,text", [
    ({"timestamp": "1713600000"}, 500, ""),
    (None, 200, "<html>clock unavailable</html>"),
])
def test_unavailable_clock_prevents_sign_submission(monkeypatch, payload, status, text):
    client, session = make_client(monkeypatch, authenticated=True)

    def handler(method, url, kwargs):
        assert method == "GET"
        return response(url, payload=payload, status=status, text=text)

    session.handler = handler
    with pytest.raises(IClassApiError):
        client.sign_now("schedule-1")
    assert len(session.calls) == 1


@pytest.mark.parametrize("payload,status,text", [
    ({"STATUS": "0", "result": {"stuSignStatus": "0"}}, 200, ""),
    ({"STATUS": "0", "result": {"stuSignStatus": "2"}}, 200, ""),
    ({"STATUS": "0", "result": {}}, 200, ""),
    ({"STATUS": "0"}, 200, ""),
    ({"STATUS": "1", "result": {"stuSignStatus": "1"}}, 200, ""),
    ({"STATUS": "1", "ERRMSG": "当前时间不是上课时间！"}, 200, ""),
    (SIGN_PAYLOAD, 500, ""),
    (None, 200, "<html>upstream unavailable</html>"),
])
def test_sign_does_not_report_false_success_or_retry_business_failures(monkeypatch, payload, status, text):
    client, session = make_client(monkeypatch, authenticated=True)
    session.handler = lambda method, url, kwargs: response(url, payload=payload, status=status, text=text)

    with pytest.raises(IClassApiError):
        client.sign_now("schedule-1", timestamp_ms=1713600000123)
    assert len(session.calls) == 1


def test_sign_network_timeout_does_not_submit_twice(monkeypatch):
    client, session = make_client(monkeypatch, authenticated=True)

    def handler(method, url, kwargs):
        raise requests.Timeout("Response was lost after sending the request")

    session.handler = handler
    with pytest.raises(IClassApiError):
        client.sign_now("schedule-1", timestamp_ms=1713600000123)
    assert len(session.calls) == 1


@pytest.mark.parametrize("expired_http_status", [200, 302, 401, 403])
def test_sign_refreshes_expired_iclass_session_once_and_gets_fresh_timestamp(monkeypatch, expired_http_status):
    client, session = make_client(monkeypatch, authenticated=True)
    clock_requests = 0
    sign_requests = 0
    app_logins = 0

    def handler(method, url, kwargs):
        nonlocal clock_requests, sign_requests, app_logins
        if "get_timestamp.action" in url:
            clock_requests += 1
            return response(url, payload={"timestamp": str(1713600000 + clock_requests)})
        if "stu_scan_sign.action" in url:
            sign_requests += 1
            if sign_requests == 1:
                if expired_http_status == 302:
                    return response(url, status=302, location=SSO_FORM_URL)
                if expired_http_status == 200:
                    return response(url, payload={"STATUS": "1", "ERRMSG": "请重新登录"})
                return response(url, status=expired_http_status, text="Session expired")
            assert kwargs["headers"]["sessionId"] == "refreshed-session"
            assert kwargs["params"]["timestamp"] == "1713600002"
            return response(url, payload=SIGN_PAYLOAD)
        if "app/user/login.action" in url:
            app_logins += 1
            assert kwargs["params"]["phone"] == LOGIN_NAME
            return response(url, payload={"STATUS": "0", "result": {
                "id": USER_ID, "sessionId": "refreshed-session",
            }})
        if url.startswith(module.DIRECT_8346):
            assert method == "GET"
            return response(url, status=302,
                            location=f"{module.DIRECT_8346}/?loginName={quote(LOGIN_NAME, safe='')}")
        raise AssertionError(f"Unexpected request during session refresh: {method} {url}")

    session.handler = handler
    assert client.sign_now("schedule-1") == SIGN_PAYLOAD
    assert (clock_requests, sign_requests, app_logins) == (2, 2, 1)


def test_repeated_session_rejection_is_bounded(monkeypatch):
    client, session = make_client(monkeypatch, authenticated=True)
    sign_requests = 0
    app_logins = 0

    def handler(method, url, kwargs):
        nonlocal sign_requests, app_logins
        if "get_timestamp.action" in url:
            return response(url, payload={"timestamp": "1713600000"})
        if "stu_scan_sign.action" in url:
            sign_requests += 1
            assert sign_requests <= 2, "Repeated session rejection must not cause an unbounded retry"
            return response(url, payload={"STATUS": "1", "ERRMSG": "请重新登录"})
        if "app/user/login.action" in url:
            app_logins += 1
            return response(url, payload=AUTH_PAYLOAD)
        if url.startswith(module.DIRECT_8346):
            return response(url, status=302,
                            location=f"{module.DIRECT_8346}/?loginName={quote(LOGIN_NAME, safe='')}")
        raise AssertionError(f"Unexpected request: {method} {url}")

    session.handler = handler
    with pytest.raises(IClassApiError):
        client.sign_now("schedule-1")
    assert (sign_requests, app_logins) == (2, 1)
