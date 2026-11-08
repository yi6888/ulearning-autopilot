#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""六章测验一次过：作答 -> 提交 -> 点左侧下一个专题（触发上报） -> 下一章。

独立进程运行：
    Start-Process -WindowStyle Hidden E:\\Python\\python.exe -ArgumentList "tools\\quiz_all_flow.py"
日志：logs/run.log
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

ANSWERS = {
    0: ["B", "C", "AC", "ABCDE", "T"],
    1: ["D", "C", "ABCD", "ABC", "T"],
    2: ["B", "C", "AB", "ACD", "T"],
    3: ["A", "D", "ABC", "ABCD", "T"],
    4: ["C", "A", "ABC", "ABC", "T"],
    5: ["B", "C", "BC", "ACD", "F"],
}

STATE_JS = r"""
() => ({
  right: document.querySelectorAll('.question-wrapper.right').length,
  wrong: document.querySelectorAll('.question-wrapper.wrong').length,
  judged: /回答正确|回答错误/.test(document.body.innerText),
  qcount: document.querySelectorAll('.question-element-node').length,
  canSubmit: !!document.querySelector('.question-operation-area .btn-submit'),
  score: (document.body.innerText.match(/得分[^\n]{0,12}/) || [''])[0],
  chance: (document.body.innerText.match(/剩余[^\n]{0,14}|限答\d+次/) || [''])[0]
})
"""


def log(*a):
    print(*a, flush=True)


def answer(lp, plan):
    qs = lp.evaluate(r"""() => [...document.querySelectorAll('.question-element-node')].map((n, qi) => ({
        qi, judge: !!n.querySelector('.choice-btn'),
        type: ((n.querySelector('.question-type-tag') || {}).innerText || '').trim(),
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
    with sync_playwright() as p:
        ctx = B.launch(p, Path(r"E:\Deepseek_WorkPlace\chat\ulearning-monitor\profile-auto"),
                       "msedge", headless=False)
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.set_default_timeout(15000)
        pg.goto(C.COURSE_LIST, wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(2500)
        if not C.course_ok(pg):
            log("!! 登录失效，请先 python -m ulearning login")
            return 1
        chs = C.open_textbook(pg, "167069")
        log(f"专题 {len(chs)} 个")

        for ci in range(len(chs)):
            plan = ANSWERS.get(ci)
            if not plan:
                continue
            log(f"\n=========== 专题{ci + 1}: {chs[ci]['name'][:30]}  答案 {','.join(plan)}")
            lp, quiz = open_quiz(ctx, pg, ci)
            if lp is None:
                log("   打不开，跳过")
                continue
            try:
                st = lp.evaluate(STATE_JS)
                log(f"   答题前: 题{st['qcount']} 已判={st['judged']} 可提交={st['canSubmit']} {st['chance']}")
                if st["judged"]:
                    log("   已判过，跳过提交")
                else:
                    log("   勾选:", answer(lp, plan))
                    btn = lp.locator(".question-operation-area .btn-submit")
                    if not btn.count():
                        log("   !! 没有提交按钮")
                        continue
                    btn.first.click()
                    log("   已提交")
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
                    time.sleep(3)
                    st2 = lp.evaluate(STATE_JS)
                    log(f"   提交后: 对{st2['right']} 错{st2['wrong']} 已判={st2['judged']} {st2['score']}")

                # 在页内点下一个专题，把得分推上去
                n = lp.locator(".chapter-name").count()
                if n > 1:
                    lp.locator(".chapter-name").nth(min(ci + 1, n - 1)).click()
                    time.sleep(8)
                    log("   已切到另一个专题（触发上报）")
            except Exception as e:
                log(f"   异常 {type(e).__name__}: {e}")
            finally:
                try:
                    lp.close()
                except Exception:
                    pass
                pg.wait_for_timeout(1200)
                C.open_textbook(pg, "167069")

        log("\n=== 回读课件进度 ===")
        for i, c in enumerate(C.open_textbook(pg, "167069")):
            log(f"  [{i}] {c['name'][:32]:<34} {c['pct']:<6} {c['time']}")

        log("\n全部处理完毕，浏览器保持打开 300 秒")
        pg.wait_for_timeout(300000)
    return 0


if __name__ == "__main__":
    sys.exit(main())
