#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""单元小测自动作答。

    # 只看题、看选项、看解析（不会提交）
    python tools/quiz.py --chapter-idx 0

    # 指定答案并提交（限答1次，提交前会再打印一遍计划）
    python tools/quiz.py --chapter-idx 0 --answers "B,C,AC,ABCDE,T" --submit
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402

from ulearning import browser as B  # noqa: E402
from ulearning import course as C  # noqa: E402
from ulearning.log import LOG  # noqa: E402
from ulearning.player import click_page, list_pages  # noqa: E402

PARSE_JS = r"""
() => {
  const qs = [];
  document.querySelectorAll('.question-element-node').forEach((node, qi) => {
    const w = node.querySelector('.question-wrapper') || node;
    const type = (node.querySelector('.question-type-tag') || {}).innerText || '';
    const titleEl = node.querySelector('.question-title-html');
    const title = titleEl ? titleEl.innerText.trim().replace(/\s+/g, ' ') : '';
    const opts = [];
    node.querySelectorAll('.option').forEach((o, i) => {
      const t = (o.innerText || '').trim().replace(/\s+/g, ' ');
      const letter = (t.match(/^([A-Z])/) || [])[1] || '';
      opts.push({ i, letter, text: t.slice(0, 120), cls: String(o.className || '') });
    });
    const done = !!w.querySelector('.question-result, .answer-area, .question-analysis');
    qs.push({ qi, type: type.trim(), title: title.slice(0, 160), options: opts,
              submitted: w.classList.contains('finished'), cls: String(w.className || '') });
  });
  return {
    questions: qs,
    hasGlobalSubmit: !!document.querySelector('.question-operation-area .btn-submit'),
    bodyHasAnswer: /正确答案/.test(document.body.innerText)
  };
}
"""


def open_quiz(ctx, book_pg, chapter_idx):
    for attempt in range(3):
        lp = C.open_chapter(ctx, book_pg, chapter_idx)
        if lp is None:
            time.sleep(2)
            continue
        lp.wait_for_timeout(6000)
        pages = []
        for _ in range(10):
            pages = list_pages(lp, chapter_idx)
            if pages:
                break
            lp.wait_for_timeout(1500)
        quiz = next((x for x in pages if "单元小测" in x["name"]), None)
        if quiz:
            click_page(lp, quiz["i"])
            lp.wait_for_timeout(7000)
            if lp.locator(".question-element-node").count():
                return lp, quiz
        # 兜底：直接点左侧目录里文本为“单元小测”的节点
        try:
            lp.get_by_text("单元小测", exact=True).first.click()
            lp.wait_for_timeout(7000)
            if lp.locator(".question-element-node").count():
                return lp, quiz or {"i": -1, "name": "单元小测"}
        except Exception:
            pass
        try:
            lp.close()
        except Exception:
            pass
        time.sleep(2)
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chapter-idx", type=int, default=0)
    ap.add_argument("--answers", default="", help="按题号顺序，如 B,C,AC,ABCDE,T（T=正确 F=错误）")
    ap.add_argument("--submit", action="store_true", help="真正提交（不可撤回）")
    ap.add_argument("--profile", default=r"E:\Deepseek_WorkPlace\chat\ulearning-monitor\profile-auto")
    a = ap.parse_args()

    plan = [x.strip().upper() for x in a.answers.split(",")] if a.answers else []

    with sync_playwright() as p:
        ctx = B.launch(p, Path(a.profile), "msedge", headless=False)
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.goto(C.COURSE_LIST, wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(2500)
        C.open_textbook(pg, "167069")

        lp, quiz = open_quiz(ctx, pg, a.chapter_idx)
        if lp is None or quiz is None:
            LOG.err("没找到单元小测")
            return 1

        data = lp.evaluate(PARSE_JS)
        (ROOT / "logs" / f"quiz-{a.chapter_idx}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

        LOG.ok(f"共 {len(data['questions'])} 题；已有答案面板={data['bodyHasAnswer']}；"
               f"全局提交按钮={data['hasGlobalSubmit']}")
        for q in data["questions"]:
            print(f"\n[{q['qi'] + 1}] ({q['type']}) {q['title'][:80]}")
            for o in q["options"]:
                print(f"     {o['letter'] or ('#' + str(o['i'])):<3} {o['text'][:70]}")
            if q["submitted"]:
                print("     —— 已提交/已判")

        if not plan:
            LOG.dim("\n未提供 --answers，仅查看，不提交")
            ctx.close()
            return 0

        if len(plan) != len(data["questions"]):
            LOG.err(f"答案数 {len(plan)} 与题数 {len(data['questions'])} 不匹配")
            ctx.close()
            return 2

        # 选答案：选项的真实点击目标是 .choice-item（.option 只是字母标签），
        # 选中态显示为 .choice-item 里的 .radio/.checkbox 加 selected；判断题是 .choice-btn.selected
        applied = []
        for q, ans in zip(data["questions"], plan):
            node = lp.locator(".question-element-node").nth(q["qi"])
            is_judge = q["type"].startswith("判断")
            hit = []
            if is_judge:
                sel = ".choice-btn.right-btn" if ans == "T" else ".choice-btn.wrong-btn"
                node.locator(sel).first.click()
                hit.append(ans)
                time.sleep(0.4)
            else:
                want = list(ans)
                for o in q["options"]:
                    if o["letter"] and o["letter"] in want:
                        node.locator(".choice-item").nth(o["i"]).click()
                        hit.append(o["letter"])
                        time.sleep(0.35)
            applied.append((q["qi"] + 1, ans, hit))
            LOG.dim(f"  第{q['qi'] + 1}题 选 {hit}")
            if set(hit) != set(list(ans)) if not is_judge else not hit:
                LOG.err(f"  第{q['qi'] + 1}题点击不完整：期望 {ans}，实际 {hit}")

        # 提交前自检：每题选中数量是否与答案一致
        chk = lp.evaluate("""() => [...document.querySelectorAll('.question-element-node')].map(n => ({
            selOpts: n.querySelectorAll('.choice-item .radio.selected, .choice-item .checkbox.selected').length,
            selBtn: n.querySelectorAll('.choice-btn.selected').length
        }))""")
        bad = []
        for q, ans, c in zip(data["questions"], plan, chk):
            want = 1 if q["type"].startswith("判断") else len(list(ans))
            got = c["selBtn"] if q["type"].startswith("判断") else c["selOpts"]
            if got != want:
                bad.append((q["qi"] + 1, want, got))
        if bad:
            LOG.err(f"选中数量不符，已中止提交：{bad}")
            ctx.close()
            return 4
        LOG.ok("自检通过：每题选中数量与答案一致")
        if not a.submit:
            LOG.warn("已勾选但未提交（加 --submit 才会提交）")
            lp.screenshot(path=str(ROOT / "shots" / f"quiz-{a.chapter_idx}-picked.png"), timeout=10000, animations="disabled")
            ctx.close()
            return 0

        btn = lp.locator(".question-operation-area .btn-submit")
        if btn.count() == 0:
            LOG.err("找不到全局提交按钮")
            ctx.close()
            return 3
        btn.first.click()
        LOG.ok("已点击提交，等待判分…")
        lp.wait_for_timeout(6000)

        # 可能的确认弹窗
        for txt in ("确定", "确认提交", "继续"):
            try:
                el = lp.get_by_text(txt, exact=True)
                if el.count() and el.first.is_visible():
                    el.first.click()
                    LOG.dim("确认弹窗:", txt)
                    lp.wait_for_timeout(2500)
                    break
            except Exception:
                pass

        lp.wait_for_timeout(4000)
        res = lp.evaluate("""() => {
            const nodes = [...document.querySelectorAll('.question-wrapper')];
            return {
                text: (document.body.innerText || '').slice(0, 2500),
                classes: nodes.map(n => String(n.className)),
                right: document.querySelectorAll('.question-wrapper.right').length,
                wrong: document.querySelectorAll('.question-wrapper.wrong').length,
            };
        }""")
        print("\n=== 判分结果 ===")
        print("right:", res["right"], "wrong:", res["wrong"])
        i = res["text"].find("共5题")
        print(res["text"][i:i + 1200] if i > 0 else res["text"][:1200])
        lp.screenshot(path=str(ROOT / "shots" / f"quiz-{a.chapter_idx}-result.png"), timeout=10000, animations="disabled")
        ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())



