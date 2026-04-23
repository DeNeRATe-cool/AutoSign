from __future__ import annotations

import traceback
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any


LEVELS = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
}


class DailyFileLogger:
    def __init__(self, log_dir: Path, enabled: bool = True, level: str = "INFO") -> None:
        self.log_dir = Path(log_dir)
        self.enabled = enabled
        self.level_name = str(level).upper()
        self.level = LEVELS.get(self.level_name, 20)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def debug(self, message: str, meta: dict[str, Any] | None = None) -> None:
        self._write("DEBUG", message, meta=meta)

    def info(self, message: str, meta: dict[str, Any] | None = None) -> None:
        self._write("INFO", message, meta=meta)

    def warning(self, message: str, meta: dict[str, Any] | None = None) -> None:
        self._write("WARNING", message, meta=meta)

    def error(self, message: str, meta: dict[str, Any] | None = None, exc: Exception | None = None) -> None:
        self._write("ERROR", message, meta=meta, exc=exc)

    def _write(
        self,
        level_name: str,
        message: str,
        meta: dict[str, Any] | None = None,
        exc: Exception | None = None,
    ) -> None:
        if not self.enabled:
            return
        if LEVELS[level_name] < self.level:
            return

        now = datetime.now()
        log_file = self.log_dir / f"{now.strftime('%Y-%m-%d')}.txt"

        line = f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] [{level_name}] {message}"
        if meta:
            safe_items = []
            for k, v in meta.items():
                if "password" in str(k).lower():
                    safe_items.append(f"{k}=******")
                else:
                    safe_items.append(f"{k}={v}")
            if safe_items:
                line += " | " + ", ".join(safe_items)

        if exc is not None:
            line += f" | exception={exc}"
            line += "\n" + traceback.format_exc().rstrip("\n")

        with self._lock:
            with log_file.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
