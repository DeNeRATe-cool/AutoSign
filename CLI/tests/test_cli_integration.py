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
