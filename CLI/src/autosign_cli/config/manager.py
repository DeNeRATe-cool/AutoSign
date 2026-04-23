from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG: dict[str, Any] = {
    "accounts": [],
    "logger": {
        "enabled": True,
        "level": "INFO",
    },
    "runtime": {
        "interval_seconds": 60,
        "timezone": "Asia/Shanghai",
    },
    "autostart": {
        "enabled": False,
        "mode": "off",
    },
}


class ConfigManager:
    def __init__(self, base_dir: Path | None = None) -> None:
        if base_dir is None:
            home_override = os.environ.get("AUTOSIGN_HOME")
            base_dir = Path(home_override) if home_override else (Path.home() / ".autosign")
        self.base_dir = Path(base_dir)
        self.config_path = self.base_dir / "config.yaml"
        self.log_dir = self.base_dir / "log"
        self.run_dir = self.base_dir / "run"
        self.pid_path = self.run_dir / "autosign.pid"

    def ensure_environment(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.run_dir.mkdir(parents=True, exist_ok=True)

        if not self.config_path.exists():
            self._write_default_config_with_comments()
        else:
            self._secure_file(self.config_path)

    def load(self) -> dict[str, Any]:
        self.ensure_environment()
        raw = self.config_path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw) or {}
        accounts = data.get("accounts")
        if not isinstance(accounts, list):
            accounts = []

        merged = {
            "accounts": accounts,
            "logger": {**DEFAULT_CONFIG["logger"], **(data.get("logger") or {})},
            "runtime": {**DEFAULT_CONFIG["runtime"], **(data.get("runtime") or {})},
            "autostart": {**DEFAULT_CONFIG["autostart"], **(data.get("autostart") or {})},
        }
        return merged

    def save(self, data: dict[str, Any]) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
        self.config_path.write_text(text, encoding="utf-8")
        self._secure_file(self.config_path)

    def list_users(self) -> list[dict[str, str]]:
        data = self.load()
        users: list[dict[str, str]] = []
        for row in data.get("accounts", []):
            if isinstance(row, dict):
                username = str(row.get("username", "")).strip()
                password = str(row.get("password", ""))
                if username:
                    users.append({"username": username, "password": password})
        return users

    def add_user(self, username: str, password: str) -> None:
        username = username.strip()
        if not username:
            raise ValueError("username 不能为空")

        data = self.load()
        accounts = [a for a in data.get("accounts", []) if isinstance(a, dict)]

        replaced = False
        for item in accounts:
            if str(item.get("username", "")).strip() == username:
                item["password"] = password
                replaced = True
                break

        if not replaced:
            accounts.append({"username": username, "password": password})

        data["accounts"] = accounts
        self.save(data)

    def delete_user(self, username: str) -> bool:
        username = username.strip()
        data = self.load()
        before = len(data.get("accounts", []))
        data["accounts"] = [
            item
            for item in data.get("accounts", [])
            if str(item.get("username", "")).strip() != username
        ]
        after = len(data["accounts"])
        self.save(data)
        return after != before

    def update_autostart(self, enabled: bool, mode: str) -> None:
        data = self.load()
        data["autostart"]["enabled"] = enabled
        data["autostart"]["mode"] = mode
        self.save(data)

    def read_pid(self) -> int | None:
        self.ensure_environment()
        if not self.pid_path.exists():
            return None

        text = self.pid_path.read_text(encoding="utf-8").strip()
        if not text:
            return None

        try:
            return int(text)
        except ValueError:
            return None

    def write_pid(self, pid: int) -> None:
        self.ensure_environment()
        self.pid_path.write_text(str(int(pid)), encoding="utf-8")
        self._secure_file(self.pid_path)

    def clear_pid(self) -> None:
        if self.pid_path.exists():
            self.pid_path.unlink()

    def _secure_file(self, path: Path) -> None:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def _write_default_config_with_comments(self) -> None:
        content = (
            "accounts:\n"
            "  # - username: \"23370001\"\n"
            "  #   password: \"your_password_1\"\n"
            "  # - username: \"23370002\"\n"
            "  #   password: \"your_password_2\"\n"
            "logger:\n"
            "  enabled: true\n"
            "  level: INFO\n"
            "runtime:\n"
            "  interval_seconds: 60\n"
            "  timezone: Asia/Shanghai\n"
            "autostart:\n"
            "  enabled: false\n"
            "  mode: off\n"
        )
        self.config_path.write_text(content, encoding="utf-8")
        self._secure_file(self.config_path)
