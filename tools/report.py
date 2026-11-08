#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""逐题读取单元小测的「你的答案 / 正确答案」，并在读完每章后点「上一小节」触发上报。

    python tools/report.py > logs/report.log 2>&1
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from playwright.sync_api import sync_playwright  # noqa: E402

from quiz import open_quiz  # noqa: E402
from ulearning import browser as B  # noqa: E402
from ulearning import course as C  # noqa: E402
from ulearning.player import click_page, list_pages  # noqa: E402

EXTRACT_JS = r"""
() => [...document.querySelectorAll('.question-wrapper')].map(w => {
  const t = (w.innerText || '').replace(/\s+/g, ' ');
  const yn = (t.match(/你的答案[：:]\s*([A-E,\s、]+|正确|错误)/) || [])[1] || '';
  const cn = (t.match(/正确答案[：:]\s*([A-E,\s、]+|正确|错误)/) || [])[1] || '';
  const sort = ((w.querySelector('.question-sort') || {}).innerText || '').trim();
  const type = ((w.querySelector('.question-type-tag') || {}).innerText || '').trim();
  const title = ((w.querySelector('.question-title-html') || {}).innerText || '').trim().slice(0, 60);
  return { sort, type, title,
           mine: yn.trim(), correct: cn.trim(),
           right: w.classList.contains('right'), wrong: w.classList.contains('wrong'),
           judged: /回答正确|回答错误/.test(t) }
});
"""


def log(*a):
    print(*a, flush=True)


def main():
    with sync_playwright() as p:
        ctx = B.launch(p, Path(r"E:\Deepseek_WorkPlace\chat\ulearning-monitor\profile-auto"),
                       "msedge", headless=False)
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.set_default_timeout(15000)
        pg.goto(C.COURSE_LIST, wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(2500)
        if not C.course_ok(pg):
            log("!! 登录失效")
            return 1
        chs = C.open_textbook(pg, "167069")

        summary = []
        for ci in range(len(chs)):
            lp, quiz = open_quiz(ctx, pg, ci)
            if lp is None:
                log(f"专题{ci + 1}: 打不开")
                continue
            try:
                qs = lp.evaluate(EXTRACT_JS)
                judged = any(q["judged"] for q in qs)
                ok = sum(1 for q in qs if q["right"] and q["judged"])
                bad = [q for q in qs if q["judged"] and not q["right"]]
                log(f"\n=== 专题{ci + 1} {chs[ci]['name'][:26]}  已判={judged}  对{ok}/{len(qs)}")
                for q in qs:
                    mark = "✓" if q["right"] else ("✗" if q["judged"] else "?")
                    log(f"   {mark} [{q['sort']}] {q['type']} {q['title'][:44]}")
                    if q["judged"]:
                        log(f"        你的: {q['mine'] or '-'}   正确: {q['correct'] or '-'}")
                summary.append((ci + 1, chs[ci]["name"][:20], judged, ok, len(qs)))

                # 点“上一小节”触发上报
                pages = list_pages(lp, ci)
                qi = next((i for i, x in enumerate(pages) if "单元小测" in x["name"]), None)
                if qi is not None and qi > 0:
                    click_page(lp, qi - 1)
                    lp.wait_for_timeout(6000)
                    log("   已点上一小节（触发上报）")
            except Exception as e:
                log(f"   异常 {type(e).__name__}: {e}")
            finally:
                try:
                    lp.close()
                except Exception:
                    pass
                pg.wait_for_timeout(1200)
                C.open_textbook(pg, "167069")

        log("\n=== 汇总 ===")
        for n, name, judged, ok, total in summary:
            log(f"  专题{n} {name:<22} 已判={judged}  {ok}/{total}")
        log("\n=== 课件进度 ===")
        for i, c in enumerate(C.open_textbook(pg, "167069")):
            log(f"  [{i}] {c['name'][:30]:<32} {c['pct']:<6} {c['time']}")

        log("\n完成，浏览器保持 180 秒")
        pg.wait_for_timeout(180000)
    return 0


if __name__ == "__main__":
    sys.exit(main())
