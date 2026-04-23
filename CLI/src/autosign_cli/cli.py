from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Sequence
from zoneinfo import ZoneInfo

from autosign_cli.config.manager import ConfigManager
from autosign_cli.core.iclass_client import IClassClient
from autosign_cli.runtime.autostart import AutostartError, AutostartManager
from autosign_cli.runtime.logging import DailyFileLogger
from autosign_cli.runtime.scheduler import AutoSignRunner, login_with_fallback


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="autosign", description="BUAA iClass 自动签到 CLI")
    parser.add_argument("--home", default=None, help="配置目录（默认 ~/.autosign）")

    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="启动自动签到服务")
    run_p.add_argument("--once", action="store_true", help="仅执行一轮（测试与调试用）")

    user_p = sub.add_parser("user", help="用户管理")
    user_sub = user_p.add_subparsers(dest="user_cmd", required=True)

    add_p = user_sub.add_parser("add", help="添加或更新账号")
    add_p.add_argument("--username", required=True)
    add_p.add_argument("--password", required=True)

    del_p = user_sub.add_parser("delete", help="删除账号")
    del_p.add_argument("--username", required=True)

    user_sub.add_parser("list", help="查看账号")

    week_p = sub.add_parser("week", help="查看某用户本周签到情况")
    week_p.add_argument("--username", required=True)
    week_p.add_argument("--password", default=None, help="可选：临时密码覆盖配置")

    auto_p = sub.add_parser("autostart", help="开机自启设置")
    auto_sub = auto_p.add_subparsers(dest="auto_cmd", required=True)

    en_p = auto_sub.add_parser("enable", help="启用开机自启")
    en_p.add_argument("--mode", default="auto", choices=["auto", "macos", "linux", "windows"])

    dis_p = auto_sub.add_parser("disable", help="禁用开机自启")
    dis_p.add_argument("--mode", default="auto", choices=["auto", "macos", "linux", "windows"])

    st_p = auto_sub.add_parser("status", help="查看开机自启状态")
    st_p.add_argument("--mode", default="auto", choices=["auto", "macos", "linux", "windows"])

    return parser


def _build_manager(home: str | None) -> ConfigManager:
    return ConfigManager(base_dir=Path(home) if home else None)


def _build_logger(manager: ConfigManager) -> DailyFileLogger:
    cfg = manager.load()
    logger_cfg = cfg.get("logger", {})
    return DailyFileLogger(
        log_dir=manager.log_dir,
        enabled=bool(logger_cfg.get("enabled", True)),
        level=str(logger_cfg.get("level", "INFO")),
    )


def _cmd_run(manager: ConfigManager, once: bool) -> int:
    logger = _build_logger(manager)
    runner = AutoSignRunner(config_manager=manager, logger=logger)
    if once:
        runner.process_once()
        return 0

    try:
        runner.run_forever()
    except KeyboardInterrupt:
        logger.info("收到中断信号，服务退出")
    return 0


def _cmd_user(manager: ConfigManager, args: argparse.Namespace) -> int:
    if args.user_cmd == "add":
        manager.add_user(args.username, args.password)
        print(f"已添加/更新用户: {args.username}")
        return 0

    if args.user_cmd == "delete":
        deleted = manager.delete_user(args.username)
        if deleted:
            print(f"已删除用户: {args.username}")
            return 0
        print(f"用户不存在: {args.username}")
        return 1

    users = manager.list_users()
    if not users:
        print("当前无账号")
        return 0

    print("用户名\t密码")
    for row in users:
        print(f"{row['username']}\t******")
    return 0


def _cmd_week(manager: ConfigManager, args: argparse.Namespace) -> int:
    username = args.username.strip()
    password = args.password

    if not password:
        for row in manager.list_users():
            if row["username"] == username:
                password = row["password"]
                break

    if not password:
        print("未找到该用户密码，请使用 --password 或先执行 user add")
        return 1

    try:
        client, mode = login_with_fallback(
            username,
            password,
            lambda use_vpn: IClassClient(use_vpn=use_vpn, verify_ssl=True),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"登录失败：{exc}")
        print("请检查网络连接")
        return 1

    now = datetime.now(tz=ZoneInfo("Asia/Shanghai"))
    sessions = client.get_week_schedule(now=now)
    print(f"登录方式: {mode}")
    print("课程名\t开始\t结束\t签到状态")
    for row in sessions:
        print(f"{row.course_name}\t{row.start_time.isoformat()}\t{row.end_time.isoformat()}\t{row.attendance}")

    return 0


def _cmd_autostart(manager: ConfigManager, args: argparse.Namespace) -> int:
    helper = AutostartManager(base_dir=manager.base_dir)

    try:
        if args.auto_cmd == "enable":
            result = helper.enable(mode=args.mode)
            manager.update_autostart(enabled=True, mode=args.mode)
            print(result)
            return 0
        if args.auto_cmd == "disable":
            result = helper.disable(mode=args.mode)
            manager.update_autostart(enabled=False, mode="off")
            print(result)
            return 0

        mode, status = helper.status(mode=args.mode)
        print(f"mode={mode} status={status}")
        if status == "disabled":
            print(helper.manual_instructions(mode=mode))
        return 0
    except AutostartError as exc:
        print(f"自动配置失败: {exc}")
        print(helper.manual_instructions(mode=args.mode))
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    manager = _build_manager(args.home)
    manager.ensure_environment()

    if args.command == "run":
        return _cmd_run(manager, once=args.once)
    if args.command == "user":
        return _cmd_user(manager, args)
    if args.command == "week":
        return _cmd_week(manager, args)
    if args.command == "autostart":
        return _cmd_autostart(manager, args)

    parser.print_help()
    return 1
