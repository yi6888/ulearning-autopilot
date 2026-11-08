#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""抓学习页的进度上报接口：搞清“完成”到底由什么字段决定。

    python tools/capture_net.py --chapter-idx 0 --page 4 --seconds 90
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402

from ulearning import browser as B  # noqa: E402
from ulearning import course as C  # noqa: E402
from ulearning.log import LOG  # noqa: E402
from ulearning.player import click_page, list_pages  # noqa: E402

KEY = ("progress", "record", "study", "heartbeat", "duration", "play", "log", "stat")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--course", default="167069")
    ap.add_argument("--chapter-idx", type=int, default=0)
    ap.add_argument("--page", type=int, default=4)
    ap.add_argument("--seconds", type=int, default=90)
    ap.add_argument("--profile", default=r"E:\Deepseek_WorkPlace\chat\ulearning-monitor\profile-auto")
    a = ap.parse_args()

    out = ROOT / "logs" / "net.jsonl"
    out.parent.mkdir(exist_ok=True)
    fh = out.open("a", encoding="utf-8")

    with sync_playwright() as p:
        ctx = B.launch(p, Path(a.profile), "msedge", headless=False)
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.goto(C.COURSE_LIST, wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(3000)
        C.open_textbook(pg, a.course)      # 必须先到课件目录表，才能点“开始学习”

        lp = C.open_chapter(ctx, pg, a.chapter_idx)
        if lp is None:
            LOG.err("没打开学习页")
            return 1
        lp.wait_for_timeout(6000)

        def on_resp(r):
            url = r.url
            if "ulearning" not in url:
                return
            if r.request.resource_type not in ("xhr", "fetch", "websocket"):
                return
            body = None
            try:
                body = r.text()[:600]
            except Exception:
                pass
            rec = {"ts": datetime.now().strftime("%H:%M:%S"), "status": r.status,
                   "method": r.request.method, "url": url[:180],
                   "post": (r.request.post_data or "")[:400], "resp": body}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            LOG.dim(f"   [{r.request.method}] {r.status} {url[:100]}")

        lp.on("response", on_resp)

        pages = list_pages(lp, a.chapter_idx)
        LOG.ok(f"页 {len(pages)} 个，点第 {a.page} 个：{pages[a.page]['name'] if a.page < len(pages) else '?'}")
        click_page(lp, a.page)
        lp.wait_for_timeout(4000)
        try:
            lp.evaluate("() => { const v=document.querySelector('video'); if(v){ v.muted=true; v.play().catch(()=>{}); } }")
        except Exception:
            pass

        LOG.ok(f"录 {a.seconds}s 网络…")
        for i in range(a.seconds // 10):
            lp.wait_for_timeout(10000)
            st = lp.evaluate("""() => { const v=document.querySelector('video');
                return v ? {t:+v.currentTime.toFixed(1), d:Math.round(v.duration), p:v.paused} : null; }""")
            LOG(f"    {st}")
        fh.close()
        LOG.ok("写出 logs/net.jsonl")
        ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())


