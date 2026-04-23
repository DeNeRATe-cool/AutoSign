from pathlib import Path

from autosign_cli.config.manager import ConfigManager


def test_ensure_environment_creates_config_and_log_dir(tmp_path: Path):
    manager = ConfigManager(base_dir=tmp_path / ".autosign")
    manager.ensure_environment()

    assert manager.config_path.exists()
    assert manager.log_dir.exists()

    data = manager.load()
    assert data["accounts"] == []
    assert len(data["account_examples"]) == 2


def test_add_and_delete_user(tmp_path: Path):
    manager = ConfigManager(base_dir=tmp_path / ".autosign")
    manager.ensure_environment()

    manager.add_user("23370001", "secret")
    rows = manager.list_users()
    assert len(rows) == 1
    assert rows[0]["username"] == "23370001"

    manager.delete_user("23370001")
    assert manager.list_users() == []


def test_config_file_permission_is_user_only(tmp_path: Path):
    manager = ConfigManager(base_dir=tmp_path / ".autosign")
    manager.ensure_environment()

    mode = manager.config_path.stat().st_mode & 0o777
    assert mode in (0o600, 0o644)
