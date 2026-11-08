"""课程层：课程列表、课件(教材)目录、打开学习页。

站点结构（2026-11 实测，改版后按 docs/TROUBLESHOOTING.md 改选择器）：
    courseweb.ulearning.cn/ulearning/index.html#/index/courseList     课程列表
    courseweb.ulearning.cn/ulearning/index.html#/course/textbook?courseId=N   课件目录表
    ua.ulearning.cn/learnCourse/learnCourse.html?chapterId=N          学习页（新窗口）
"""
from __future__ import annotations

import re
import time

from .dom import click_by_text
from .log import LOG

BASE = "https://courseweb.ulearning.cn/ulearning/index.html"
COURSE_LIST = f"{BASE}#/index/courseList"
TEXTBOOK = f"{BASE}#/course/textbook?courseId={{}}"
UNITS = f"{BASE}#/course/units?courseId={{}}"
LOGIN = "https://umooc.ulearning.cn/pc.html#/login"

LIST_COURSES_JS = r"""
() => {
  const out = [], seen = new Set();
  for (const n of document.querySelectorAll('div,li,a,section')) {
    const t = (n.innerText || '').trim().replace(/\s+/g, ' ');
    if (!/《.*》/.test(t) || t.length > 200) continue;
    const r = n.getBoundingClientRect();
    if (r.width < 150 || r.height < 36) continue;
    const key = t.slice(0, 40);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ text: t.slice(0, 120), cls: String(n.className || '').slice(0, 80), tag: n.tagName });
  }
  return out;
}"""

# 课件目录表：每行一个专题，右侧按钮“开始学习 / 继续学习”
LIST_CHAPTERS_JS = r"""
() => [...document.querySelectorAll('table.directory-table tbody tr[id^="chapterTr"]')].map((r, i) => {
  const nm = r.querySelector('.tabchapter-name');
  const tds = r.querySelectorAll('td');
  const btn = r.querySelector('button');
  const m = (tds[1] ? tds[1].innerText : '').match(/\d+%/);
  return { i, id: r.id, name: nm ? nm.innerText.trim() : '',
           pct: m ? m[0] : '', time: tds[2] ? tds[2].innerText.trim() : '',
           btn: btn ? btn.innerText.trim() : '' };
});
"""

OPEN_CHAPTER_JS = r"""
(i) => {
  const rows = [...document.querySelectorAll('table.directory-table tbody tr[id^="chapterTr"]')];
  const r = rows[i];
  if (!r) return null;
  const b = r.querySelector('button');
  if (!b) return null;
  b.scrollIntoView({ block: 'center' });
  b.click();
  const nm = r.querySelector('.tabchapter-name');
  return { name: nm ? nm.innerText.trim() : '', btn: b.innerText.trim() };
}
"""

COURSE_OK_JS = r"""
() => {
  const t = (document.body.innerText || '').slice(0, 800);
  if (/登录已过期|请登录/.test(t)) return false;
  if (location.href.includes('timeout')) return false;
  return /课程|学习|已选|学期|进行中/.test(t);
}
"""


def course_ok(pg) -> bool:
    try:
        return bool(pg.evaluate(COURSE_OK_JS))
    except Exception:
        return False


def list_courses(pg) -> list[dict]:
    try:
        return pg.evaluate(LIST_COURSES_JS)
    except Exception:
        return []


def pick_course(pg, name: str | None = None, idx: int = 0) -> str | None:
    """按课程名（模糊包含）优先；没给名字或没命中就按序号。"""
    if name:
        hit = click_by_text(pg, name, maxlen=200)
        if hit:
            LOG.ok(f"选课命中「{name}」-> {hit[:50]}")
            return hit
        LOG.warn(f"「{name}」没命中，退回第 {idx + 1} 门")
    courses = list_courses(pg)
    if idx >= len(courses):
        return None
    hit = click_by_text(pg, courses[idx]["text"][:24], maxlen=240)
    return hit


def course_id_from(pg) -> str | None:
    try:
        u = pg.url or ""
        m = re.search(r"courseId=(\d+)", u)
        if m:
            return m.group(1)
        return pg.evaluate(r"""
        () => {
          const m = (location.hash || '').match(/courseId=(\d+)/);
          if (m) return m[1];
          const a = document.querySelector('a[href*="courseId="]');
          if (a) { const mm = a.getAttribute('href').match(/courseId=(\d+)/); return mm ? mm[1] : null; }
          return null;
        }""")
    except Exception:
        return None


def open_textbook(pg, course_id: str) -> list[dict]:
    pg.evaluate("(h) => { location.hash = h; }", f"#/course/textbook?courseId={course_id}")
    return wait_chapters(pg, timeout=30)


def wait_chapters(pg, timeout: float = 30) -> list[dict]:
    end = time.time() + timeout
    while time.time() < end:
        try:
            rows = pg.evaluate(LIST_CHAPTERS_JS)
        except Exception:
            rows = []
        if rows:
            return rows
        time.sleep(1)
    return []


def list_chapters(pg) -> list[dict]:
    try:
        return pg.evaluate(LIST_CHAPTERS_JS)
    except Exception:
        return []


def open_chapter(ctx, book_pg, i: int):
    """点“开始学习”，学习页由站点 window.open 弹出，等它出现。"""
    try:
        with ctx.expect_page(timeout=25000) as pi:
            LOG.dim("   " + str(book_pg.evaluate(OPEN_CHAPTER_JS, i)))
        lp = pi.value
        lp.wait_for_load_state("domcontentloaded", timeout=30000)
        LOG.dim("   学习页:", lp.url[:100])
        return lp
    except Exception as e:
        LOG.warn("   没等到学习页窗口:", str(e)[:90])
        found = [x for x in ctx.pages if "learnCourse" in (x.url or "")]
        return found[-1] if found else None
