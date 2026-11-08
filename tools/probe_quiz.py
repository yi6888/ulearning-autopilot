#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""探测「单元小测」页面结构（只看不答，不会消耗次数）。

    python tools/probe_quiz.py --chapter-idx 0
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402

from ulearning import browser as B  # noqa: E402
from ulearning import course as C  # noqa: E402
from ulearning.log import LOG  # noqa: E402
from ulearning.player import click_page, list_pages  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chapter-idx", type=int, default=0)
    ap.add_argument("--profile", default=r"E:\Deepseek_WorkPlace\chat\ulearning-monitor\profile-auto")
    a = ap.parse_args()

    out = ROOT / "logs"
    out.mkdir(exist_ok=True)

    with sync_playwright() as p:
        ctx = B.launch(p, Path(a.profile), "msedge", headless=False)
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.goto(C.COURSE_LIST, wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(2500)
        C.open_textbook(pg, "167069")

        lp = C.open_chapter(ctx, pg, a.chapter_idx)
        if lp is None:
            LOG.err("没打开学习页")
            return 1
        lp.wait_for_timeout(6000)

        pages = list_pages(lp, a.chapter_idx)
        LOG.ok(f"页 {len(pages)} 个")
        for x in pages:
            print(f"   [{x['i']}] {x['name'][:40]}  complete={x['complete']}")

        quiz = next((x for x in pages if "单元小测" in x["name"]), None)
        if not quiz:
            LOG.err("没找到单元小测节点")
            return 2

        LOG.ok(f"打开：{quiz['name']}")
        click_page(lp, quiz["i"])
        lp.wait_for_timeout(8000)

        info = lp.evaluate("""() => ({
            url: location.href,
            title: document.title,
            text: (document.body.innerText || '').slice(0, 4000),
            iframes: [...document.querySelectorAll('iframe')].map(f => ({src: f.src.slice(0,160), id: f.id, cls: f.className})),
            radios: document.querySelectorAll('input[type=radio]').length,
            checks: document.querySelectorAll('input[type=checkbox]').length,
            inputs: document.querySelectorAll('input[type=text],textarea').length,
            buttons: [...document.querySelectorAll('button,a')].map(b => (b.innerText||'').trim()).filter(Boolean).slice(0, 30)
        })""")
        (out / "quiz-probe.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
        (out / "quiz-dom.html").write_text(lp.evaluate("() => document.body.innerHTML")[:400000], encoding="utf-8")

        print("=== url:", info["url"][:150])
        print("=== radios/checks/inputs:", info["radios"], info["checks"], info["inputs"])
        print("=== iframes:", json.dumps(info["iframes"], ensure_ascii=False)[:400])
        print("=== buttons:", info["buttons"])
        print("=== text ===")
        print(info["text"][:2500])

        lp.screenshot(path=str(ROOT / "shots" / "quiz-probe.png"), timeout=10000, animations="disabled")
        ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
