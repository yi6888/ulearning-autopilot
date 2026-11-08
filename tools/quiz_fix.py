#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""补交未记录的单元小测：作答 -> 提交 -> 点“上一小节”触发上报 -> 验证。

    python tools/quiz_fix.py 1,3,5      # 0-based 章索引
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
from ulearning.player import click_page, list_pages  # noqa: E402

ANSWERS = {
    0: ["B", "C", "AC", "ABCDE", "T"],
    1: ["D", "C", "ABCD", "ABC", "T"],
    2: ["B", "C", "AB", "ACD", "T"],
    3: ["A", "D", "ABC", "ABCD", "T"],
    4: ["C", "A", "ABC", "ABC", "T"],
    5: ["B", "C", "BC", "ACD", "F"],
}

STATE_JS = r"""
() => {
  const qs = [...document.querySelectorAll('.question-wrapper')];
  return {
    judged: /回答正确|回答错误/.test(document.body.innerText),
    right: qs.filter(w => w.classList.contains('right')).length,
    canSubmit: !!document.querySelector('.question-operation-area .btn-submit'),
    chance: (document.body.innerText.match(/限答\d+次|剩余\d+次/) || [''])[0],
    qcount: qs.length
  };
}
"""


def log(*a):
    print(*a, flush=True)


def answer(lp, plan):
    qs = lp.evaluate(r"""() => [...document.querySelectorAll('.question-element-node')].map((n, qi) => ({
        qi, judge: !!n.querySelector('.choice-btn'),
        letters: [...n.querySelectorAll('.choice-item .option')].map(o => o.innerText.replace('.', '').trim())
    }))""")
    if len(plan) != len(qs):
        return f"题数不符 {len(qs)}/{len(plan)}"
    for q, ans in zip(qs, plan):
        node = lp.locator(".question-element-node").nth(q["qi"])
        if q["judge"]:
            node.locator(".choice-btn.right-btn" if ans == "T" else ".choice-btn.wrong-btn").first.click()
            time.sleep(0.4)
        else:
            for idx, letter in enumerate(q["letters"]):
                if letter in list(ans):
                    node.locator(".choice-item").nth(idx).click()
                    time.sleep(0.3)
    return "ok"


def main():
    targets = []
    for a in sys.argv[1:]:
        targets += [int(x) for x in a.split(",") if x.strip()]
    if not targets:
        targets = [1, 3, 5]

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

        for ci in targets:
            plan = ANSWERS[ci]
            log(f"\n=========== 专题{ci + 1}: {chs[ci]['name'][:28]}  {','.join(plan)}")
            lp, quiz = open_quiz(ctx, pg, ci)
            if lp is None:
                log("   打不开")
                continue
            try:
                st = lp.evaluate(STATE_JS)
                log(f"   前: 题{st['qcount']} 已判={st['judged']} 可提交={st['canSubmit']} {st['chance']}")
                if st["judged"]:
                    log("   已判，跳过")
                else:
                    log("   勾选:", answer(lp, plan))
                    sel = lp.evaluate("""() => [...document.querySelectorAll('.question-element-node')].map(n =>
                        n.querySelectorAll('.choice-item .radio.selected, .choice-item .checkbox.selected').length
                        + n.querySelectorAll('.choice-btn.selected').length)""")
                    log("   每题选中数:", sel)
                    btn = lp.locator(".question-operation-area .btn-submit")
                    if not btn.count():
                        log("   !! 无提交按钮")
                        continue
                    btn.first.click()
                    log("   已点提交")
                    time.sleep(6)
                    for t in ("确定", "确认提交"):
                        try:
                            el = lp.get_by_text(t, exact=True)
                            if el.count() and el.first.is_visible():
                                el.first.click()
                                time.sleep(2)
                                break
                        except Exception:
                            pass
                    time.sleep(2)
                    st2 = lp.evaluate(STATE_JS)
                    log(f"   后: 已判={st2['judged']} 对{st2['right']}/{st2['qcount']}")

                # 关键：点“上一小节”把答题记录提交上去
                pages = list_pages(lp, ci)
                qi = next((i for i, x in enumerate(pages) if "单元小测" in x["name"]), None)
                if qi is not None and qi > 0:
                    log("   点上一小节:", click_page(lp, qi - 1))
                    lp.wait_for_timeout(8000)
                # 再回测验页确认是否已判
                if qi is not None:
                    click_page(lp, qi)
                    lp.wait_for_timeout(6000)
                    st3 = lp.evaluate(STATE_JS)
                    log(f"   复查: 已判={st3['judged']} 对{st3['right']}/{st3['qcount']} 可提交={st3['canSubmit']}")
            except Exception as e:
                log(f"   异常 {type(e).__name__}: {e}")
            finally:
                try:
                    lp.close()
                except Exception:
                    pass
                pg.wait_for_timeout(1200)
                C.open_textbook(pg, "167069")

        log("\n=== 课件进度 ===")
        for i, c in enumerate(C.open_textbook(pg, "167069")):
            log(f"  [{i}] {c['name'][:30]:<32} {c['pct']:<6} {c['time']}")
        log("\n完成，浏览器保持 180 秒")
        pg.wait_for_timeout(180000)
    return 0


if __name__ == "__main__":
    sys.exit(main())
