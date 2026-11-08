#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把整门课 6 个「单元小测」的题目全部抓下来（只看，不选不提交）。"""
from __future__ import annotations

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

PARSE_JS = r"""
() => {
  const out = [];
  document.querySelectorAll('.question-element-node').forEach((node, qi) => {
    const type = (node.querySelector('.question-type-tag') || {}).innerText || '';
    const tEl = node.querySelector('.question-title-html');
    const title = tEl ? tEl.innerText.trim().replace(/\s+/g, ' ') : '';
    const opts = [];
    node.querySelectorAll('.choice-item').forEach((it, i) => {
      const letter = ((it.querySelector('.option') || {}).innerText || '').replace('.', '').trim();
      const txt = ((it.querySelector('.text') || {}).innerText || '').trim().replace(/\s+/g, ' ');
      opts.push({ i, letter, text: txt.slice(0, 200) });
    });
    const hasJudge = !!node.querySelector('.choice-btn');
    out.push({ qi, type: type.trim(), title, options: opts, judge: hasJudge });
  });
  return out;
}
"""


def main():
    ap_chapters = range(6)
    with sync_playwright() as p:
        ctx = B.launch(p, Path(r"E:\Deepseek_WorkPlace\chat\ulearning-monitor\profile-auto"),
                       "msedge", headless=False)
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.goto(C.COURSE_LIST, wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(3000)
        chs = C.open_textbook(pg, "167069")
        LOG.ok(f"专题 {len(chs)} 个")

        all_q = {}
        for ci in ap_chapters:
            name = chs[ci]["name"][:20] if ci < len(chs) else f"#{ci}"
            lp = C.open_chapter(ctx, pg, ci)
            if lp is None:
                LOG.warn(f"[{ci}] 打不开")
                continue
            lp.wait_for_timeout(5000)
            pages = list_pages(lp, ci)
            quiz = next((x for x in pages if "单元小测" in x["name"]), None)
            if not quiz:
                LOG.warn(f"[{ci}] 没找到单元小测")
                lp.close()
                continue
            click_page(lp, quiz["i"])
            lp.wait_for_timeout(7000)
            qs = lp.evaluate(PARSE_JS)
            all_q[ci] = {"chapter": chs[ci]["name"], "questions": qs}
            print(f"\n########## 专题{ci + 1}：{chs[ci]['name']}  ({len(qs)} 题)")
            for q in qs:
                print(f"\n[{q['qi'] + 1}] {q['type']}  {q['title']}")
                if q["judge"]:
                    print("     判断题：T=正确  F=错误")
                for o in q["options"]:
                    print(f"      {o['letter']}. {o['text'][:100]}")
            lp.close()
            pg.wait_for_timeout(1200)

        out = ROOT / "logs" / "quizzes.json"
        out.write_text(json.dumps(all_q, ensure_ascii=False, indent=1), encoding="utf-8")
        LOG.ok(f"已保存 {out}")
        ctx.close()


if __name__ == "__main__":
    main()
