#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""注入内核自测：用本地模拟课程页跑一遍，验证卡死/弹题/下一节都被识别。

    python tests/test_detector.py

默认用本机 Chrome；没有 Chrome 时回落到 Playwright 自带 chromium：
    ULEARN_CHANNEL=chromium python tests/test_detector.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
INJECT = (ROOT / "ulearning" / "inject.js").read_text(encoding="utf-8")
PAGE = (ROOT / "tests" / "fake-course.html").resolve().as_uri()
CHANNEL = os.environ.get("ULEARN_CHANNEL", "chrome")

EVENTS: list[dict] = []
FAILS: list[str] = []
PG = None


def check(name, cond, detail=""):
    print(("  \033[92mPASS\033[0m " if cond else "  \033[91mFAIL\033[0m ") + name + ("  " + detail if detail else ""))
    if not cond:
        FAILS.append(name)


def types():
    return [e["type"] for e in EVENTS]


def wait_for(t, timeout=12.0):
    end = time.time() + timeout
    while time.time() < end:
        if t in types():
            return True
        PG.wait_for_timeout(150)
    return False


def launch(p):
    kw = dict(headless=True, args=["--mute-audio"])
    if CHANNEL and CHANNEL not in ("chromium", "none"):
        kw["channel"] = CHANNEL
    try:
        return p.chromium.launch(**kw)
    except Exception:
        kw.pop("channel", None)
        return p.chromium.launch(**kw)


def run():
    global PG
    with sync_playwright() as p:
        br = launch(p)
        ctx = br.new_context(viewport={"width": 1280, "height": 800})
        ctx.expose_binding("__report", lambda src, s: EVENTS.append(json.loads(s)))
        ctx.add_init_script(
            "window.__ULEARN_CFG={autoMute:true,autoResume:true,autoNext:true,"
            "stuckSec:4,watchQuiz:true,pauseOnQuiz:true};" + INJECT)
        pg = ctx.new_page()
        PG = pg
        pg.goto(PAGE)
        pg.wait_for_timeout(1200)

        print("\n[1] 内核注入与播放器绑定")
        check("READY 已发出", wait_for("READY"))
        check("VIDEO_BOUND 已发出", wait_for("VIDEO_BOUND"))

        print("\n[2] 自动播放 + 静音")
        pg.evaluate("() => document.getElementById('v').play()")
        check("PLAY 事件", wait_for("PLAY"))
        check("muted=true", pg.evaluate("() => document.getElementById('v').muted") is True)

        print("\n[3] 卡死检测（冻结进度，阈值 4s）")
        pg.evaluate("() => document.getElementById('btn-stuck').click()")
        check("STUCK 被识别", wait_for("STUCK", 15))
        pg.evaluate("() => document.getElementById('v').pause()")

        print("\n[4] 弹题检测")
        pg.evaluate("() => document.getElementById('btn-quiz').click()")
        ok = wait_for("QUIZ", 10)
        check("QUIZ 被识别", ok)
        q = next((e for e in EVENTS if e["type"] == "QUIZ"), None)
        if q:
            check("题干含“单选题”", "单选" in q["extra"].get("text", ""))
        check("弹题时自动暂停", pg.evaluate("() => document.getElementById('v').paused") is True)
        pg.evaluate("() => document.getElementById('btn-submit').click()")
        check("QUIZ_GONE 已识别", wait_for("QUIZ_GONE", 8))

        print("\n[5] 接近结尾 -> 自动下一节")
        EVENTS.clear()
        pg.evaluate("() => { const v=document.getElementById('v'); document.getElementById('btn-stuck').click(); v.play(); v.currentTime = 117.5; }")
        check("NEAR_END 被识别", wait_for("NEAR_END", 15))
        check("NEXT 已点击", wait_for("NEXT", 12))
        pg.wait_for_timeout(600)
        cur = pg.evaluate("() => document.getElementById('cur').textContent")
        check("章节推进到第 2 节", "第 2 节" in cur, cur)
        EVENTS.clear()
        pg.evaluate("() => document.getElementById('v').dispatchEvent(new Event('ended'))")
        check("ENDED 处理已接通", wait_for("ENDED", 6))

        print("\n[6] 暂停自动续播")
        EVENTS.clear()
        pg.evaluate("() => document.getElementById('v').pause()")
        check("暂停后可自动恢复", any(e["type"] in ("PAUSE", "RESUME") for e in EVENTS) or wait_for("PLAY", 10))
        pg.wait_for_timeout(2500)
        check("最终处于播放状态", pg.evaluate("() => !document.getElementById('v').paused"))

        print("\n[7] 事件统计")
        cnt: dict[str, int] = {}
        for e in EVENTS:
            cnt[e["type"]] = cnt.get(e["type"], 0) + 1
        print("     ", json.dumps(cnt, ensure_ascii=False))
        br.close()


if __name__ == "__main__":
    print("=" * 58)
    print("  优学院检测内核 —— 本地模拟页自测  (channel=%s)" % CHANNEL)
    print("=" * 58)
    try:
        run()
    except Exception as e:
        import traceback
        traceback.print_exc()
        FAILS.append(f"异常: {e}")
    print("\n" + "=" * 58)
    if FAILS:
        print(f"  结果：{len(FAILS)} 项未通过 -> {FAILS}")
        sys.exit(1)
    print("  结果：全部通过")
