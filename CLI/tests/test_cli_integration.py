import io
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from autosign_cli.cli import main
from autosign_cli.config.manager import ConfigManager
from autosign_cli.core.iclass_client import IClassApiError


def test_run_once_is_silent(tmp_path: Path):
    manager = ConfigManager(base_dir=tmp_path / ".autosign")
    manager.ensure_environment()

    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(["--home", str(tmp_path / ".autosign"), "run", "--once"])

    assert code == 0
    assert out.getvalue() == ""
    assert err.getvalue() == ""


def test_user_commands_print_result(tmp_path: Path):
    out = io.StringIO()
    err = io.StringIO()

    with redirect_stdout(out), redirect_stderr(err):
        assert main(["--home", str(tmp_path / ".autosign"), "user", "add", "--username", "23370001", "--password", "abc"]) == 0
        assert main(["--home", str(tmp_path / ".autosign"), "user", "list"]) == 0

    txt = out.getvalue()
    assert "23370001" in txt
    assert err.getvalue() == ""


def test_run_starts_background_and_stop_cleans_pid(tmp_path: Path, monkeypatch):
    home = tmp_path / ".autosign"

    monkeypatch.setattr("autosign_cli.cli._spawn_background_runner", lambda manager: 24680)
    monkeypatch.setattr("autosign_cli.cli._is_process_alive", lambda pid: pid == 24680)
    monkeypatch.setattr("autosign_cli.cli._terminate_process", lambda pid, timeout_seconds=5.0: True)

    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        run_code = main(["--home", str(home), "run"])
        stop_code = main(["--home", str(home), "stop"])

    assert run_code == 0
    assert stop_code == 0
    text = out.getvalue()
    assert "后台服务已启动" in text
    assert "后台服务已停止" in text
    assert ConfigManager(base_dir=home).read_pid() is None
    assert err.getvalue() == ""


def test_stop_is_idempotent_when_not_running(tmp_path: Path):
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(["--home", str(tmp_path / ".autosign"), "stop"])

    assert code == 0
    assert "未运行" in out.getvalue()
    assert err.getvalue() == ""


@pytest.mark.parametrize("failure_stage, expected_message", [
    ("login", "登录失败"),
    ("schedule", "获取本周课表失败"),
])
def test_week_failure_is_visible_and_returns_nonzero(tmp_path, monkeypatch, capsys, failure_stage, expected_message):
    class _FailingClient:
        def get_week_schedule(self, now):
            raise IClassApiError("上游请求未成功")

    def fake_login(username, password, client_factory):
        assert username == "23370001"
        assert password == "test-only-password"
        if failure_stage == "login":
            raise IClassApiError("上游请求未成功")
        return _FailingClient(), "direct"

    monkeypatch.setattr("autosign_cli.cli.login_with_fallback", fake_login)

    code = main([
        "--home", str(tmp_path / ".autosign"), "week",
        "--username", "23370001", "--password", "test-only-password",
    ])

    captured = capsys.readouterr()
    assert code == 1
    assert expected_message in captured.out
    assert "上游请求未成功" in captured.out
    assert "课程名" not in captured.out
    assert "test-only-password" not in captured.out
    assert "Traceback" not in captured.out
    assert captured.err == ""


def test_week_with_successful_empty_schedule_still_succeeds(tmp_path, monkeypatch, capsys):
    class _EmptyClient:
        def get_week_schedule(self, now):
            return []

    monkeypatch.setattr(
        "autosign_cli.cli.login_with_fallback",
        lambda username, password, client_factory: (_EmptyClient(), "vpn"),
    )

    code = main([
        "--home", str(tmp_path / ".autosign"), "week",
        "--username", "23370001", "--password", "test-only-password",
    ])

    captured = capsys.readouterr()
    assert code == 0
    assert "登录方式: vpn" in captured.out
    assert "课程名" in captured.out
    assert "失败" not in captured.out
    assert captured.err == ""
