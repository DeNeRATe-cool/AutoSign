from __future__ import annotations

import os
from uuid import uuid4

from flask import Flask, jsonify, redirect, render_template, request, session, url_for

from autosign.auto_sign import AutoSignService
from autosign.iclass_client import IClassApiError, IClassClient

app = Flask(__name__)
app.secret_key = os.environ.get("AUTOSIGN_SECRET_KEY", "autosign-dev-secret")

service = AutoSignService(sync_interval_seconds=20)


def _logged_in() -> bool:
    token = session.get("runtime_token")
    if not token:
        return False

    try:
        service.get_week_sessions(token)
        return True
    except Exception:  # noqa: BLE001
        session.clear()
        return False


@app.get("/")
def index():
    if _logged_in():
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.post("/login")
def login():
    student_id = (request.form.get("student_id") or "").strip()
    password = request.form.get("password") or ""
    use_vpn = bool(request.form.get("use_vpn"))
    verify_ssl = bool(request.form.get("verify_ssl"))

    if not student_id or not password:
        return render_template(
            "login.html",
            error="请输入学号和密码",
            student_id=student_id,
            use_vpn=use_vpn,
            verify_ssl=verify_ssl,
        )

    client = IClassClient(use_vpn=use_vpn, verify_ssl=verify_ssl)
    try:
        auth = client.login(student_id=student_id, password=password)
    except Exception as exc:  # noqa: BLE001
        return render_template(
            "login.html",
            error=f"登录失败：{exc}",
            student_id=student_id,
            use_vpn=use_vpn,
            verify_ssl=verify_ssl,
        )

    token = str(uuid4())
    service.register_user(token, client)

    session["runtime_token"] = token
    session["student_id"] = student_id
    session["user_name"] = auth.user_name
    session["use_vpn"] = use_vpn

    return redirect(url_for("dashboard"))


@app.get("/dashboard")
def dashboard():
    if not _logged_in():
        return redirect(url_for("index"))

    return render_template(
        "dashboard.html",
        user_name=session.get("user_name", "同学"),
        student_id=session.get("student_id", ""),
        use_vpn=session.get("use_vpn", False),
    )


@app.get("/api/week")
def api_week():
    if not _logged_in():
        return jsonify({"ok": False, "message": "未登录"}), 401

    token = session["runtime_token"]
    try:
        rows = service.get_week_sessions(token)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "message": str(exc)}), 400

    return jsonify({"ok": True, "data": rows})


@app.get("/api/runtime")
def api_runtime():
    if not _logged_in():
        return jsonify({"ok": False, "message": "未登录"}), 401

    token = session["runtime_token"]
    try:
        notifications = service.get_pending_notifications(token)
        events = service.get_recent_events(token)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "message": str(exc)}), 400

    return jsonify({"ok": True, "notifications": notifications, "events": events})


@app.post("/api/prompt-action")
def api_prompt_action():
    if not _logged_in():
        return jsonify({"ok": False, "message": "未登录"}), 401

    body = request.get_json(silent=True) or {}
    key = str(body.get("key") or "").strip()
    action = str(body.get("action") or "").strip()
    if not key or action not in {"sign_now", "later"}:
        return jsonify({"ok": False, "message": "参数错误"}), 400

    token = session["runtime_token"]
    try:
        result = service.handle_prompt_action(token, key, action)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "message": str(exc)}), 400

    code = 200 if result.get("ok") else 400
    return jsonify(result), code


@app.post("/api/sign-now")
def api_sign_now():
    if not _logged_in():
        return jsonify({"ok": False, "message": "未登录"}), 401

    body = request.get_json(silent=True) or {}
    key = str(body.get("key") or "").strip() or None
    schedule_id = str(body.get("scheduleId") or "").strip() or None

    if not key and not schedule_id:
        return jsonify({"ok": False, "message": "请提供 key 或 scheduleId"}), 400

    token = session["runtime_token"]
    try:
        result = service.manual_sign(token, key, schedule_id)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "message": str(exc)}), 400

    code = 200 if result.get("ok") else 400
    return jsonify(result), code


@app.post("/logout")
def logout():
    token = session.get("runtime_token")
    if token:
        service.unregister_user(token)
    session.clear()
    return jsonify({"ok": True})


@app.errorhandler(IClassApiError)
def handle_api_error(exc: IClassApiError):
    return jsonify({"ok": False, "message": str(exc)}), 400


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
