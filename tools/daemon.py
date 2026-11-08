#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""常驻控制器：浏览器只开一次，之后靠文件下指令，不关窗口。

指令文件  logs/cmd.json   {"seq":1,"action":"quiz","chapter":3,"answers":["A","D","ABC","ABCD","T"],"submit":true}
结果文件  logs/cmd_out.txt （每次覆盖，含 seq，便于确认是哪条指令的结果）

支持 action：
    ping      检查登录态
    chapters  列出六个专题的进度
    quiz      打开指定专题的单元小测，按 answers 勾选（submit=true 才提交）
    quit      关闭浏览器并退出
"""
from __future__ import annotations

import json
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

CMD = ROOT / "logs" / "cmd.json"
OUT = ROOT / "logs" / "cmd_out.txt"
PROFILE = Path(r"E:\Deepseek_WorkPlace\chat\ulearning-monitor\profile-auto")

PARSE_JS = r"""
() => [...document.querySelectorAll('.question-element-node')].map((node, qi) => {
  const type = (node.querySelector('.question-type-tag') || {}).innerText || '';
  const tEl = node.querySelector('.question-title-html');
  const opts = [];
  node.querySelectorAll('.choice-item').forEach((it, i) => {
    opts.push({ i, letter: ((it.querySelector('.option') || {}).innerText || '').replace('.', '').trim(),
                text: (((it.querySelector('.text') || {}).innerText) || '').trim().slice(0, 120) });
  });
  return { qi, type: type.trim(), title: tEl ? tEl.innerText.trim().slice(0, 160) : '',
           options: opts, judge: !!node.querySelector('.choice-btn') };
});
"""


def out(seq, *lines):
    txt = "\n".join(str(x) for x in lines)
    OUT.write_text(f"seq={seq}\n{txt}\n", encoding="utf-8")
    print(f"[seq {seq}]", txt[:400], flush=True)


def evaluate_quiz(lp, answers, submit):
    qs = lp.evaluate(PARSE_JS)
    if answers and len(answers) != len(qs):
        return [f"答案数 {len(answers)} != 题数 {len(qs)}"], None
    if answers:
        for q, ans in zip(qs, answers):
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
        chk = lp.evaluate("""() => [...document.querySelectorAll('.question-element-node')].map(n => ({
            selOpts: n.querySelectorAll('.choice-item .radio.selected, .choice-item .checkbox.selected').length,
            selBtn: n.querySelectorAll('.choice-btn.selected').length }))""")
        bad = [(q["qi"] + 1, len(list(a)), (c["selBtn"] if q["type"].startswith("判断") else c["selOpts"]))
               for q, a, c in zip(qs, answers, chk)]
        bad = [x for x in bad if x[1] != x[2]]
        if bad:
            return [f"选中数量不符，未提交：{bad}"], None
        if submit:
            btn = lp.locator(".question-operation-area .btn-submit")
            if btn.count() == 0:
                return ["找不到提交按钮"], None
            btn.first.click()
            time.sleep(6)
            for t in ("确定", "确认提交", "继续"):
                try:
                    el = lp.get_by_text(t, exact=True)
                    if el.count() and el.first.is_visible():
                        el.first.click()
                        time.sleep(2)
                        break
                except Exception:
                    pass
            time.sleep(3)
    res = lp.evaluate("""() => ({right: document.querySelectorAll('.question-wrapper.right').length,
                                wrong: document.querySelectorAll('.question-wrapper.wrong').length,
                                judged: /回答正确|回答错误/.test(document.body.innerText)})""")
    return [], res


def main():
    with sync_playwright() as p:
        ctx = B.launch(p, PROFILE, "msedge", headless=False)
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.set_default_timeout(15000)          # 任何点击/等待都不超过 15s，避免整个控制器卡死
        pg.goto(C.COURSE_LIST, wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(3000)
        out(0, "ready", f"logged_in={C.course_ok(pg)}", pg.url[:100])

        last_seq = 0
        while True:
            time.sleep(2)
            if not CMD.exists():
                continue
            try:
                cmd = json.loads(CMD.read_text(encoding="utf-8"))
            except Exception:
                continue
            seq = int(cmd.get("seq", 0))
            if seq <= last_seq:
                continue
            last_seq = seq
            action = cmd.get("action", "ping")
            try:
                if action == "quit":
                    out(seq, "bye")
                    ctx.close()
                    return 0
                if action == "ping":
                    out(seq, "ping", f"logged_in={C.course_ok(pg)}", pg.url[:100])
                    continue
                if action == "chapters":
                    chs = C.open_textbook(pg, "167069")
                    out(seq, "chapters", *[f"{c['name'][:30]:<32} {c['pct']:<6} {c['time']}" for c in chs])
                    continue
                if action == "quiz":
                    C.open_textbook(pg, "167069")     # 必须先停在课件目录表，否则点不到“开始学习”
                    ci = int(cmd["chapter"])
                    answers = cmd.get("answers") or []
                    lp, quiz = open_quiz(ctx, pg, ci)
                    if lp is None:
                        out(seq, f"专题{ci + 1} 打不开（可能登录失效）")
                        continue
                    try:
                        lines, res = evaluate_quiz(lp, answers, bool(cmd.get("submit")))
                        qs = lp.evaluate(PARSE_JS)
                        head = [f"[{q['qi'] + 1}] {q['type']} {q['title'][:70]}" for q in qs]
                        out(seq, f"专题{ci + 1} {quiz['name']}", *head, *lines,
                            f"结果 right={res['right']} wrong={res['wrong']} judged={res['judged']}" if res else "")
                    finally:
                        try:
                            lp.close()      # 只关学习页标签，浏览器主窗口保持
                        except Exception:
                            pass
                    continue
            except Exception as e:
                out(seq, "error", f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    sys.exit(main())

