#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""对指定账号把六个单元小测一次做完：作答 -> 提交 -> 点上一小节 -> 复查入库。

    python tools/quiz_do.py --profile <配置目录>
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

# 已核验过的标准答案（courseId 167069 的同一套题库）
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
  judged: /回答正确|回答错误/.test(document.body.innerText),
  right: [...document.querySelectorAll('.question-wrapper')].filter(w => w.classList.contains('right')).length,
  qcount: document.querySelectorAll('.question-wrapper').length,
  canSubmit: !!document.querySelector('.question-operation-area .btn-submit'),
  chance: (document.body.innerText.match(/限答\d+次|剩余\d+次/) || [''])[0]
})
"""

LIST_JS = r"""
() => [...document.querySelectorAll('.question-element-node')].map((n, qi) => ({
  qi,
  type: ((n.querySelector('.question-type-tag') || {}).innerText || '').trim(),
  judge: !!n.querySelector('.choice-btn'),
  title: ((n.querySelector('.question-title-html') || {}).innerText || '').trim().slice(0, 40),
  letters: [...n.querySelectorAll('.choice-item .option')].map(o => o.innerText.replace('.', '').trim())
}))
"""


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def answer(lp, plan):
    qs = lp.evaluate(LIST_JS)
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
    prof = sys.argv[sys.argv.index("--profile") + 1] if "--profile" in sys.argv else "profile-auto"
    with sync_playwright() as p:
        ctx = B.launch(p, ROOT / prof, "msedge", headless=False)
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.set_default_timeout(15000)
        pg.goto(C.COURSE_LIST, wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(3000)
        if not C.course_ok(pg):
            log("!! 登录失效")
            return 1
        cid = C.course_id_from(pg) or "167069"
        # 进课程
        C.pick_course(pg, "形势与政策（三）")
        pg.wait_for_timeout(3000)
        cid = C.course_id_from(pg) or cid
        chs = C.open_textbook(pg, cid)
        log(f"专题 {len(chs)} 个")

        results = []
        for ci in range(len(chs)):
            plan = ANSWERS[ci]
            lp, quiz = open_quiz(ctx, pg, ci)
            if lp is None:
                log(f"专题{ci + 1}: 打不开")
                results.append((ci + 1, "打不开", "-"))
                continue
            try:
                st = lp.evaluate(STATE_JS)
                titles = lp.evaluate(LIST_JS)
                log(f"\n=== 专题{ci + 1} {chs[ci]['name'][:24]}  题{st['qcount']} 已判={st['judged']} {st['chance']}")
                for q in titles:
                    log(f"    [{q['qi'] + 1}] {q['type']} {q['title']}")
                if st["judged"]:
                    log("    已判过，跳过")
                else:
                    log("    勾选:", answer(lp, plan))
                    btn = lp.locator(".question-operation-area .btn-submit")
                    if not btn.count():
                        log("    !! 无提交按钮")
                        results.append((ci + 1, "无提交按钮", "-"))
                        continue
                    btn.first.click()
                    log("    已提交")
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

                # 点上一小节触发上报
                pages = list_pages(lp, ci)
                qi = next((i for i, x in enumerate(pages) if "单元小测" in x["name"]), None)
                if qi is not None and qi > 0:
                    log("    点上一小节:", click_page(lp, qi - 1))
                    lp.wait_for_timeout(8000)
                    click_page(lp, qi)
                    lp.wait_for_timeout(6000)
                st2 = lp.evaluate(STATE_JS)
                log(f"    复查: 已判={st2['judged']} 对{st2['right']}/{st2['qcount']} 可提交={st2['canSubmit']}")
                results.append((ci + 1, f"对{st2['right']}/{st2['qcount']}", st2["judged"]))
            except Exception as e:
                log(f"    异常 {type(e).__name__}: {e}")
                results.append((ci + 1, f"异常 {type(e).__name__}", "-"))
            finally:
                try:
                    lp.close()
                except Exception:
                    pass
                pg.wait_for_timeout(1200)
                C.open_textbook(pg, cid)

        log("\n=== 汇总 ===")
        for n, score, judged in results:
            log(f"  专题{n}: {score}  入库={judged}")
        log("\n=== 课件进度 ===")
        for i, c in enumerate(C.open_textbook(pg, cid)):
            log(f"  [{i}] {c['name'][:30]:<32} {c['pct']:<6} {c['time']}")
        log("\n完成，浏览器保持 120 秒")
        pg.wait_for_timeout(120000)
    return 0


if __name__ == "__main__":
    sys.exit(main())
