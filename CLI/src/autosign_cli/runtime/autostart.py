from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

SERVICE_NAME = "autosign-cli"
WINDOWS_TASK_NAME = "AutoSignCLI"


class AutostartError(RuntimeError):
    pass


class AutostartManager:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.platform = platform.system().lower()

    def enable(self, mode: str = "auto") -> str:
        mode = self._normalize_mode(mode)
        if mode == "macos":
            return self._enable_macos()
        if mode == "linux":
            return self._enable_linux()
        if mode == "windows":
            return self._enable_windows()
        raise AutostartError(f"不支持的 mode: {mode}")

    def disable(self, mode: str = "auto") -> str:
        mode = self._normalize_mode(mode)
        if mode == "macos":
            return self._disable_macos()
        if mode == "linux":
            return self._disable_linux()
        if mode == "windows":
            return self._disable_windows()
        raise AutostartError(f"不支持的 mode: {mode}")

    def status(self, mode: str = "auto") -> tuple[str, str]:
        mode = self._normalize_mode(mode)
        if mode == "macos":
            plist = self._macos_plist_path()
            return mode, ("enabled" if plist.exists() else "disabled")
        if mode == "linux":
            unit = self._linux_unit_path()
            return mode, ("enabled" if unit.exists() else "disabled")
        if mode == "windows":
            return mode, self._windows_task_state()
        return mode, "unknown"

    def manual_instructions(self, mode: str = "auto") -> str:
        mode = self._normalize_mode(mode)
        if mode == "macos":
            return (
                "手动配置 macOS 启动项：\n"
                f"1) 创建 {self._macos_plist_path()}\n"
                f"2) ProgramArguments 使用: {sys.executable} -m autosign_cli run\n"
                "3) 执行 launchctl bootstrap gui/$(id -u) <plist路径>"
            )
        if mode == "linux":
            return (
                "手动配置 Linux systemd --user：\n"
                f"1) 创建 {self._linux_unit_path()}\n"
                f"2) ExecStart={sys.executable} -m autosign_cli run\n"
                "3) systemctl --user daemon-reload && systemctl --user enable --now autosign.service"
            )
        if mode == "windows":
            return (
                "手动配置 Windows 计划任务：\n"
                f"schtasks /Create /TN {WINDOWS_TASK_NAME} /SC ONLOGON /TR \"{sys.executable} -m autosign_cli run\" /F"
            )
        return "当前系统暂不支持自动配置，请使用手动方式。"

    def _normalize_mode(self, mode: str) -> str:
        normalized = (mode or "auto").strip().lower()
        if normalized == "auto":
            if self.platform == "darwin":
                return "macos"
            if self.platform == "linux":
                return "linux"
            if self.platform.startswith("win"):
                return "windows"
            raise AutostartError(f"无法识别当前平台: {self.platform}")
        return normalized

    def _enable_macos(self) -> str:
        plist_path = self._macos_plist_path()
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        content = f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">
<plist version=\"1.0\">
<dict>
  <key>Label</key>
  <string>com.autosign.cli</string>
  <key>ProgramArguments</key>
  <array>
    <string>{sys.executable}</string>
    <string>-m</string>
    <string>autosign_cli</string>
    <string>run</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>WorkingDirectory</key>
  <string>{self.base_dir}</string>
</dict>
</plist>
"""
        plist_path.write_text(content, encoding="utf-8")
        uid = str(os.getuid())
        subprocess.run(["launchctl", "bootout", f"gui/{uid}", str(plist_path)], check=False, capture_output=True)
        proc = subprocess.run(
            ["launchctl", "bootstrap", f"gui/{uid}", str(plist_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            proc2 = subprocess.run(["launchctl", "load", "-w", str(plist_path)], check=False, capture_output=True, text=True)
            if proc2.returncode != 0:
                raise AutostartError(proc.stderr.strip() or proc2.stderr.strip() or "launchctl 启用失败")
        return f"已启用 macOS 开机自启: {plist_path}"

    def _disable_macos(self) -> str:
        plist_path = self._macos_plist_path()
        uid = str(os.getuid())
        subprocess.run(["launchctl", "bootout", f"gui/{uid}", str(plist_path)], check=False, capture_output=True)
        subprocess.run(["launchctl", "unload", "-w", str(plist_path)], check=False, capture_output=True)
        if plist_path.exists():
            plist_path.unlink()
        return "已禁用 macOS 开机自启"

    def _enable_linux(self) -> str:
        unit = self._linux_unit_path()
        unit.parent.mkdir(parents=True, exist_ok=True)
        unit.write_text(
            "\n".join(
                [
                    "[Unit]",
                    "Description=AutoSign CLI",
                    "After=network-online.target",
                    "",
                    "[Service]",
                    "Type=simple",
                    f"ExecStart={sys.executable} -m autosign_cli run",
                    "Restart=always",
                    "RestartSec=10",
                    "",
                    "[Install]",
                    "WantedBy=default.target",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        if not self._has_cmd("systemctl"):
            raise AutostartError("未检测到 systemctl，请手动配置")

        for cmd in (
            ["systemctl", "--user", "daemon-reload"],
            ["systemctl", "--user", "enable", "--now", "autosign.service"],
        ):
            proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
            if proc.returncode != 0:
                raise AutostartError(proc.stderr.strip() or "systemctl 执行失败")
        return f"已启用 Linux 开机自启: {unit}"

    def _disable_linux(self) -> str:
        if self._has_cmd("systemctl"):
            subprocess.run(["systemctl", "--user", "disable", "--now", "autosign.service"], check=False, capture_output=True)
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=False, capture_output=True)
        unit = self._linux_unit_path()
        if unit.exists():
            unit.unlink()
        return "已禁用 Linux 开机自启"

    def _enable_windows(self) -> str:
        cmd = [
            "schtasks",
            "/Create",
            "/TN",
            WINDOWS_TASK_NAME,
            "/SC",
            "ONLOGON",
            "/TR",
            f'\"{sys.executable}\" -m autosign_cli run',
            "/F",
        ]
        proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if proc.returncode != 0:
            raise AutostartError(proc.stderr.strip() or proc.stdout.strip() or "schtasks 创建失败")
        return "已启用 Windows 开机自启"

    def _disable_windows(self) -> str:
        subprocess.run(["schtasks", "/Delete", "/TN", WINDOWS_TASK_NAME, "/F"], check=False, capture_output=True)
        return "已禁用 Windows 开机自启"

    def _windows_task_state(self) -> str:
        proc = subprocess.run(
            ["schtasks", "/Query", "/TN", WINDOWS_TASK_NAME],
            check=False,
            capture_output=True,
            text=True,
        )
        return "enabled" if proc.returncode == 0 else "disabled"

    def _macos_plist_path(self) -> Path:
        return Path.home() / "Library" / "LaunchAgents" / "com.autosign.cli.plist"

    def _linux_unit_path(self) -> Path:
        return Path.home() / ".config" / "systemd" / "user" / "autosign.service"

    def _has_cmd(self, name: str) -> bool:
        proc = subprocess.run(["which", name], check=False, capture_output=True)
        return proc.returncode == 0
