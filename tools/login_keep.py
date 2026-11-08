#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""打开登录窗口并保持不关：登录成功 -> 打印课程 -> 一直挂着等你下一步指令。

    python tools/login_keep.py --profile profile-auto2
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402

from ulearning import browser as B  # noqa: E402
from ulearning import course as C  # noqa: E402

AUTH = ("AUTHORIZATION", "token", "USER_INFO", "USERINFO", "lms_user_org")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def main():
    prof = sys.argv[sys.argv.index("--profile") + 1] if "--profile" in sys.argv else "profile-auto2"
    clone = "--clone" in sys.argv

    with sync_playwright() as p:
        if clone:
            B.clone_profile("msedge", ROOT / prof)
        ctx = B.launch(p, ROOT / prof, "msedge", headless=False)
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.set_default_timeout(15000)
        pg.goto(C.LOGIN, wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(2000)
        try:
            pg.bring_to_front()
        except Exception:
            pass
        log("窗口已打开，配置目录:", prof)
        log("请在新窗口里登录另一个账号（扫码/账号密码都行）")

        base = set(n for _, n in B.ul_cookies(ctx))
        deadline = time.time() + 900
        ok = False
        while time.time() < deadline:
            names = set(n for _, n in B.ul_cookies(ctx))
            hit = [n for n in names if n in AUTH and n not in base]
            if hit:
                log("[+] 登录成功:", ", ".join(sorted(hit)))
                ok = True
                break
            pg.wait_for_timeout(2000)

        if not ok:
            log("!! 15 分钟内没检测到登录")
            return 1

        B.persist_auth_cookies(ctx, 30)
        pg.wait_for_timeout(1500)
        try:
            pg.goto(C.COURSE_LIST, wait_until="domcontentloaded", timeout=45000)
            pg.wait_for_timeout(4000)
            courses = C.list_courses(pg)
            log(f"课程 {len(courses)} 门：")
            for c in courses:
                print("   -", c["text"][:90], flush=True)
        except Exception as e:
            log("列课程失败:", str(e)[:80])

        log("浏览器保持打开 30 分钟，你可以直接在里面操作；我这边可以继续下指令")
        try:
            pg.wait_for_timeout(1800000)
        except Exception:
            pass
        return 0


if __name__ == "__main__":
    sys.exit(main())
