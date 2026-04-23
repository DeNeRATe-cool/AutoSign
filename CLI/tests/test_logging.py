from pathlib import Path

from autosign_cli.runtime.logging import DailyFileLogger


def test_daily_log_file_appends(tmp_path: Path):
    logger = DailyFileLogger(log_dir=tmp_path / "log", enabled=True, level="INFO")

    logger.info("line1")
    logger.info("line2")

    files = sorted((tmp_path / "log").glob("*.txt"))
    assert len(files) == 1

    text = files[0].read_text(encoding="utf-8")
    assert "line1" in text
    assert "line2" in text
