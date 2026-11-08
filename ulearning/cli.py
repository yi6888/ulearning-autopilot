"""命令行入口：python -m ulearning <command>"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .log import LOG
from .runner import RunOptions, Session


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="ulearning",
        description="优学院网课自动驾驶：登录一次，之后自动按专题看完课件。",
    )
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--browser", "-b", default="msedge", choices=["msedge", "edge", "chrome", "chromium"])
        p.add_argument("--profile", default="profile-auto", help="配置目录（默认 profile-auto）")
        p.add_argument("--headless", action="store_true")
        p.add_argument("--speed", type=float, default=1.0, help="播放倍速，默认 1.0（>1 可能被平台按实际时长判不足）")
        p.add_argument("--cookie-days", type=int, default=30)
        p.add_argument("--quiet", action="store_true")

    p_run = sub.add_parser("run", help="选课并自动刷完课件")
    p_run.add_argument("--course-name", "-c", default="", help="课程名关键词，如 形势与政策（三）")
    p_run.add_argument("--course-idx", type=int, default=0, help="没给名字时按序号选，从 0 开始")
    p_run.add_argument("--max-chapters", type=int, default=0, help="只刷前 N 个专题，0=全部")
    common(p_run)

    p_list = sub.add_parser("list", help="只登录并列出课程，不播放")
    p_list.add_argument("--course-name", "-c", default="")
    common(p_list)

    p_login = sub.add_parser("login", help="只登录并保存登录态（30 天有效）")
    common(p_login)

    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    opts = RunOptions(
        browser=args.browser,
        headless=args.headless,
        profile_dir=Path(args.profile),
        speed=args.speed,
        cookie_days=args.cookie_days,
    )
    if getattr(args, "course_name", ""):
        opts.course_name = args.course_name
    if getattr(args, "course_idx", 0):
        opts.course_idx = args.course_idx
    if getattr(args, "max_chapters", 0):
        opts.max_chapters = args.max_chapters

    if args.quiet:
        LOG.quiet = True

    if args.cmd in ("list", "login"):
        opts.dry_run = True

    LOG.ok(f"ulearning-autopilot v{__version__}")
    rc = Session(opts).run()
    if args.cmd == "login" and rc == 0:
        LOG.ok("登录态已保存，下次可直接 run")
    return rc


if __name__ == "__main__":
    sys.exit(main())

