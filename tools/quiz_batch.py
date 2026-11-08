#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""一个浏览器会话里连续提交多个单元的测验（登录态失效很快，必须一次做完）。

    python tools/quiz_batch.py --chapters "3:A,D,ABC,ABCD,T|4:C,A,ABC,ABC,T|5:B,C,BC,ACD,F"
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from playwright.sync_api import sync_playwright  # noqa: E402

from quiz import PARSE_JS, open_quiz  # noqa: E402
from ulearning import browser as B  # noqa: E402
from ulearning import course as C  # noqa: E402
from ulearning.log import LOG  # noqa: E402


def answer_and_submit(lp, plan):
    data = lp.evaluate(PARSE_JS)
    qs = data["questions"] if isinstance(data, dict) else data
    if len(plan) != len(qs):
        LOG.err(f"答案数 {len(plan)} != 题数 {len(qs)}，跳过")
        return False
    for q, ans in zip(qs, plan):
        node = lp.locator(".question-element-node").nth(q["qi"])
        if q["type"].startswith("判断"):
            sel = ".choice-btn.right-btn" if ans == "T" else ".choice-btn.wrong-btn"
            node.locator(sel).first.click()
            time.sleep(0.4)
        else:
            for o in q["options"]:
                if o["letter"] and o["letter"] in list(ans):
                    node.locator(".choice-item").nth(o["i"]).click()
                    time.sleep(0.3)
        LOG.dim(f"   第{q['qi'] + 1}题 -> {ans}")

    chk = lp.evaluate("""() => [...document.querySelectorAll('.question-element-node')].map(n => ({
        selOpts: n.querySelectorAll('.choice-item .radio.selected, .choice-item .checkbox.selected').length,
        selBtn: n.querySelectorAll('.choice-btn.selected').length }))""")
    bad = [(q["qi"] + 1, len(list(a)), (c["selBtn"] if q["type"].startswith("判断") else c["selOpts"]))
           for q, a, c in zip(qs, plan, chk)]
    bad = [x for x in bad if x[1] != x[2]]
    if bad:
        LOG.err(f"选中数量不符，未提交：{bad}")
        return False

    btn = lp.locator(".question-operation-area .btn-submit")
    if btn.count() == 0:
        LOG.err("找不到全局提交按钮")
        return False
    btn.first.click()
    LOG.ok("已提交")
    lp.wait_for_timeout(6000)
    for txt in ("确定", "确认提交", "继续"):
        try:
            el = lp.get_by_text(txt, exact=True)
            if el.count() and el.first.is_visible():
                el.first.click()
                lp.wait_for_timeout(2500)
                break
        except Exception:
            pass
    lp.wait_for_timeout(4000)
    res = lp.evaluate("""() => ({right: document.querySelectorAll('.question-wrapper.right').length,
                                wrong: document.querySelectorAll('.question-wrapper.wrong').length})""")
    LOG.ok(f"判分: 对 {res['right']} / 错 {res['wrong']}")
    return True


def main():
    spec = sys.argv[sys.argv.index("--chapters") + 1] if "--chapters" in sys.argv else ""
    jobs = []
    for part in spec.split("|"):
        if not part.strip():
            continue
        idx, ans = part.split(":", 1)
        jobs.append((int(idx), [x.strip().upper() for x in ans.split(",")]))
    if not jobs:
        LOG.err("没有任务")
        return 1

    with sync_playwright() as p:
        ctx = B.launch(p, Path(r"E:\Deepseek_WorkPlace\chat\ulearning-monitor\profile-auto"),
                       "msedge", headless=False)
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.goto(C.COURSE_LIST, wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(3000)
        if not C.course_ok(pg):
            LOG.err("登录态失效，先跑 python -m ulearning login")
            ctx.close()
            return 2
        chs = C.open_textbook(pg, "167069")
        LOG.ok(f"专题 {len(chs)} 个")

        ok = 0
        for idx, plan in jobs:
            LOG.ok(f"=== 专题{idx + 1}: {chs[idx]['name'][:30]} 答案 {','.join(plan)}")
            lp, quiz = open_quiz(ctx, pg, idx)
            if lp is None:
                LOG.err("   打不开测验，跳过")
                continue
            try:
                if answer_and_submit(lp, plan):
                    ok += 1
            finally:
                try:
                    lp.close()
                except Exception:
                    pass
                pg.wait_for_timeout(1500)

        LOG.ok(f"完成 {ok}/{len(jobs)}")
        ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
