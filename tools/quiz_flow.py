#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""完整答题流程：作答 -> 提交 -> 点左侧另一个专题（触发得分上传）-> 回读验证。

    python tools/quiz_flow.py --chapter 0 --answers "B,C,AC,ABCDE,T"
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

STATE_JS = r"""
() => ({
  right: document.querySelectorAll('.question-wrapper.right').length,
  wrong: document.querySelectorAll('.question-wrapper.wrong').length,
  judged: /回答正确|回答错误/.test(document.body.innerText),
  qcount: document.querySelectorAll('.question-element-node').length,
  canSubmit: !!document.querySelector('.question-operation-area .btn-submit'),
  score: (document.body.innerText.match(/得分[^\n]{0,12}/) || [''])[0],
  chance: (document.body.innerText.match(/剩余[^\n]{0,12}|限答\d次/) || [''])[0]
})
"""


def log(*a):
    print(*a, flush=True)


def answer(lp, plan):
    qs = lp.evaluate(r"""() => [...document.querySelectorAll('.question-element-node')].map((n, qi) => ({
        qi, type: ((n.querySelector('.question-type-tag') || {}).innerText || '').trim(),
        judge: !!n.querySelector('.choice-btn'),
        letters: [...n.querySelectorAll('.choice-item .option')].map(o => o.innerText.replace('.', '').trim())
    }))""")
    if len(plan) != len(qs):
        return f"题数不符 {len(qs)} vs {len(plan)}"
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
    ci = int(sys.argv[sys.argv.index("--chapter") + 1]) if "--chapter" in sys.argv else 0
    plan = [x.strip().upper() for x in sys.argv[sys.argv.index("--answers") + 1].split(",")] \
        if "--answers" in sys.argv else []

    with sync_playwright() as p:
        ctx = B.launch(p, Path(r"E:\Deepseek_WorkPlace\chat\ulearning-monitor\profile-auto"),
                       "msedge", headless=False)
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.set_default_timeout(15000)
        pg.goto(C.COURSE_LIST, wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(2500)
        C.open_textbook(pg, "167069")

        lp, quiz = open_quiz(ctx, pg, ci)
        if lp is None:
            log("打不开测验")
            return 1
        before = lp.evaluate(STATE_JS)
        log(f"答题前: 题{before['qcount']} 对{before['right']} 错{before['wrong']} "
            f"已判={before['judged']} 可提交={before['canSubmit']} {before['chance']}")

        if plan:
            log("勾选:", answer(lp, plan))
            chk = lp.evaluate("""() => [...document.querySelectorAll('.question-element-node')].map(n =>
                n.querySelectorAll('.choice-item .radio.selected, .choice-item .checkbox.selected').length)""")
            log("每题选中:", chk)
            btn = lp.locator(".question-operation-area .btn-submit")
            if btn.count():
                btn.first.click()
                log("已点提交")
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

        after = lp.evaluate(STATE_JS)
        log(f"提交后: 对{after['right']} 错{after['wrong']} 已判={after['judged']} "
            f"可提交={after['canSubmit']} {after['score']} {after['chance']}")

        # 关键：点左侧另一个专题，触发得分上传
        names = lp.locator(".chapter-name").count()
        log(f"左侧专题节点 {names} 个，点第 {2 if names > 1 else 1} 个触发上传")
        try:
            lp.locator(".chapter-name").nth(1 if names > 1 else 0).click()
            time.sleep(8)
            log("已切换专题")
        except Exception as e:
            log("切换失败:", e)

        lp.wait_for_timeout(3000)
        log("浏览器保持打开 120 秒")
        lp.wait_for_timeout(120000)
        return 0


if __name__ == "__main__":
    sys.exit(main())
