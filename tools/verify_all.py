#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""逐个专题读取单元小测判定，并触发“切章节上传得分”，最后回读课件进度。

    python tools/verify_all.py > logs/verify.log 2>&1
"""
from __future__ import annotations

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

READ_JS = r"""
() => ({
  right: document.querySelectorAll('.question-wrapper.right').length,
  wrong: document.querySelectorAll('.question-wrapper.wrong').length,
  judged: /回答正确|回答错误/.test(document.body.innerText),
  qcount: document.querySelectorAll('.question-element-node').length,
  hasSubmit: !!document.querySelector('.question-operation-area .btn-submit')
})
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
        pg.wait_for_timeout(3000)
        if not C.course_ok(pg):
            log("!! 登录失效")
            ctx.close()
            return 1

        chs = C.open_textbook(pg, "167069")
        log("=== 课件进度 ===")
        for i, c in enumerate(chs):
            log(f"  [{i}] {c['name'][:34]:<36} {c['pct']:<6} {c['time']}")

        log("\n=== 单元小测判定 ===")
        for ci in range(len(chs)):
            try:
                lp, quiz = open_quiz(ctx, pg, ci)
                if lp is None:
                    log(f"  专题{ci + 1}: 打不开")
                    continue
                r = lp.evaluate(READ_JS)
                log(f"  专题{ci + 1}: 题{r['qcount']} 对{r['right']} 错{r['wrong']} "
                    f"已判={r['judged']} 可提交={r['hasSubmit']}")
                lp.close()                      # 只关学习页，浏览器留着
                pg.wait_for_timeout(1000)
            except Exception as e:
                log(f"  专题{ci + 1}: 异常 {type(e).__name__} {e}")

        # 再回一次课件表：切章节会把最后一节的得分推上去
        log("\n=== 回读课件进度（触发上传后）===")
        chs2 = C.open_textbook(pg, "167069")
        for i, c in enumerate(chs2):
            log(f"  [{i}] {c['name'][:34]:<36} {c['pct']:<6} {c['time']}")

        log("\n完成，浏览器保持打开，3 分钟后自动退出")
        pg.wait_for_timeout(180000)
        return 0


if __name__ == "__main__":
    sys.exit(main())
