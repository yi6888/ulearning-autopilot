#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""结构探测工具：站点改版后用它把真实 DOM 抓下来，再改选择器。

    python tools/probe.py --course 167069 --chapter 0
    python tools/probe.py --course 167069 --chapter 0 --dump dom.html

输出：
    logs/chapters.json   课件目录表（专题名 / 进度 / 按钮文案）
    logs/learn-items.json 学习页左侧小节列表
    logs/learn-info.json  视频元素信息（src/duration/分辨率/iframe）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright  # noqa: E402

from ulearning import browser as B  # noqa: E402
from ulearning import course as C  # noqa: E402
from ulearning.log import LOG  # noqa: E402
from ulearning.player import list_units  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOGS, SHOTS = ROOT / "logs", ROOT / "shots"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--course", "-c", required=True, help="courseId，从课程页 URL 里取")
    ap.add_argument("--chapter", type=int, default=0, help="第几个专题，从 0 开始")
    ap.add_argument("--unit", type=int, default=0, help="第几个小节，从 0 开始")
    ap.add_argument("--browser", "-b", default="msedge")
    ap.add_argument("--profile", default="profile-auto")
    ap.add_argument("--dump", default="", help="把学习页 HTML 存到这个路径")
    a = ap.parse_args()

    LOGS.mkdir(exist_ok=True, parents=True)
    SHOTS.mkdir(exist_ok=True, parents=True)
    B.clone_profile(a.browser, ROOT / a.profile)

    with sync_playwright() as p:
        ctx = B.launch(p, ROOT / a.profile, a.browser, headless=False, on_page=lambda pg: LOG.dim("[新窗口]", (pg.url or "")[:90]))
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.goto(C.COURSE_LIST, wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(3500)
        if not C.course_ok(pg):
            LOG.err("没登录，先跑 python -m ulearning login")
            ctx.close()
            return 1

        chapters = C.open_textbook(pg, a.course)
        (LOGS / "chapters.json").write_text(json.dumps(chapters, ensure_ascii=False, indent=1), encoding="utf-8")
        LOG.ok(f"专题 {len(chapters)} 个")
        for c in chapters:
            print(f"  [{c['i']}] {c['name'][:50]:<50} {c['pct']:<5} {c['btn']}")

        lp = C.open_chapter(ctx, pg, a.chapter)
        if lp is None:
            LOG.err("没打开学习页")
            ctx.close()
            return 2
        lp.wait_for_timeout(6000)

        units = list_units(lp)
        (LOGS / "learn-items.json").write_text(json.dumps(units, ensure_ascii=False, indent=1), encoding="utf-8")
        LOG.ok(f"小节 {len(units)} 个")
        for u in units:
            print(f"  [{u['i']}] {u['text']}")

        if units:
            view = lp.evaluate("""() => {
                const a = window.__LU__ || [];
                const el = a[%d];
                if (el) { el.scrollIntoView({block:'center'}); el.click(); }
                return true;
            }""" % a.unit)
            LOG.dim("clicked:", view)
            lp.wait_for_timeout(9000)

        info = lp.evaluate("""() => ({
            url: location.href,
            videos: [...document.querySelectorAll('video')].map(v => ({
                src: (v.currentSrc || v.src || '').slice(0, 120),
                dur: v.duration, t: v.currentTime, paused: v.paused,
                w: v.clientWidth, h: v.clientHeight, ready: v.readyState })),
            iframes: [...document.querySelectorAll('iframe')].map(f => f.src.slice(0, 140)),
            canvases: document.querySelectorAll('canvas').length,
            text: (document.body.innerText || '').slice(0, 800),
        })""")
        (LOGS / "learn-info.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(info, ensure_ascii=False, indent=1)[:1600])

        if a.dump:
            Path(a.dump).write_text(lp.evaluate("() => document.body.innerHTML")[:400000], encoding="utf-8")
            LOG.ok("HTML 已存", a.dump)

        lp.screenshot(path=str(SHOTS / "probe-learn.png"), timeout=8000, animations="disabled")
        ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
