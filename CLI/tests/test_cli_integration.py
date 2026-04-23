import io
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from autosign_cli.cli import main
from autosign_cli.config.manager import ConfigManager


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
