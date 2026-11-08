"""学习页（ua.ulearning.cn/learnCourse）层：小节列表、点开、**看完到 100%** 再走。

站点结构（实测，改版用 tools/probe.py 重新抓）：

    .chapter-item#chapterNNN
      .section-list
        .section-item#sectionNNN
          .page-name                ← 点击进入该页
            .text / span            ← 小节名，如 "1-1.何为长征"
          .page-name.complete       ← 服务端记录的完成标记（关键）
          i.iconfont.finish         ← 完成对勾

判定“看完”不能只看 currentTime，必须以页面上的 `.page-name.complete` 为准：
优学院按“累计观看时长 ≥ 视频时长”在服务端记账，本地播到结尾但没记满时不会变绿。
"""
from __future__ import annotations

import re
import time

from .dom import dismiss_tips, force_play, vstat, wait_video
from .log import LOG

LIST_PAGES_JS = r"""
(ci) => {
  // 按专题(index)限定范围：学习页一次性渲染了整门课的目录树，
  // 不限定就会把别的专题的小节也点一遍。
  const items = [...document.querySelectorAll('.chapter-item')];
  const root = (ci === null || ci === undefined || ci < 0) ? document : items[ci];
  if (!root) return [];
  const out = [];
  root.querySelectorAll('.page-item').forEach((n, i) => {
    const nm = n.querySelector('.page-name');
    const span = n.querySelector('.text span');
    const txt = (span ? span.innerText : (n.querySelector('.text') || {}).innerText) || '';
    out.push({
      i,
      id: n.id || '',
      name: (txt || '').trim().replace(/\s+/g, ' ').slice(0, 60),
      complete: !!(nm && nm.classList.contains('complete')),
      active: !!(nm && nm.classList.contains('active')),
      finishIcon: !!n.querySelector('i.finish'),
    });
  });
  window.__PAGES__ = [...root.querySelectorAll('.page-item')];
  return out;
}"""

CLICK_PAGE_JS = r"""
(i) => {
  const a = window.__PAGES__ || [...document.querySelectorAll('.page-item')];
  const it = a[i];
  if (!it) return null;
  const nm = it.querySelector('.page-name');
  if (!nm) return null;
  window.__END_INFO__ = null;            // 切页前清掉上一次的结束标记
  nm.scrollIntoView({ block: 'center' });
  nm.click();
  return ((it.querySelector('.text') || {}).innerText || '').trim().replace(/\s+/g, ' ').slice(0, 60);
}"""

PAGE_STATE_JS = r"""
(i) => {
  const a = window.__PAGES__ || [...document.querySelectorAll('.page-item')];
  const it = a[i];
  if (!it) return null;
  const nm = it.querySelector('.page-name');
  const span = it.querySelector('.text span');
  return {
    complete: !!(nm && nm.classList.contains('complete')),
    active: !!(nm && nm.classList.contains('active')),
    finishIcon: !!it.querySelector('i.finish'),
    name: ((span ? span.innerText : (it.querySelector('.text') || {}).innerText) || '').trim().slice(0, 60),
  };
}"""

# 播放器左下角的状态标签：未观看 / 已看完（viewProgress >= 95 时出现）
PLAYER_LABEL_JS = r"""
() => {
  const vis = n => { const r = n.getBoundingClientRect(), c = getComputedStyle(n);
    return r.width > 8 && r.height > 6 && c.display !== 'none'
           && c.visibility !== 'hidden' && +c.opacity > 0.05; };
  for (const n of document.querySelectorAll('span,div,em,i')) {
    const t = (n.innerText || '').trim();
    if (!t || t.length > 8) continue;
    if (/已看完|已完成|已学完/.test(t) && vis(n)) return t;
  }
  return null;
}"""


def player_label(lp):
    """返回播放器左下角的完成标签文本（已看完/已完成）或 None。"""
    try:
        return lp.evaluate(PLAYER_LABEL_JS)
    except Exception:
        return None


# 不是“看视频”的节点：单元小测、讨论、作业等，跳过
SKIP_RE = re.compile(r"小测|测验|测试|作业|讨论|答疑|考试")

# 注入到页面：视频 ended 的瞬间暂停并记录位置。
# 优学院播放器结束后会自动从头循环，靠轮询永远抓不到 t≈duration 的那一刻。
END_HOOK_JS = r"""
(() => {
  if (window.__END_HOOK__) return; window.__END_HOOK__ = true;
  window.__END_INFO__ = null;
  document.addEventListener('ended', (e) => {
    const v = e.target;
    if (!v || v.tagName !== 'VIDEO') return;
    if (!(v.duration > 1) || v.currentTime < 1) return;   // 忽略占位/零长视频
    window.__END_INFO__ = { t: +v.currentTime.toFixed(2), dur: +v.duration.toFixed(2), at: Date.now() };
    try { v.pause(); } catch (_) {}
  }, true);
})();
"""


def list_pages(lp, chapter_idx: int | None = None) -> list[dict]:
    try:
        return lp.evaluate(LIST_PAGES_JS, chapter_idx)
    except Exception as e:
        LOG.warn("list_pages 失败:", str(e)[:80])
        return []


def page_state(lp, i: int):
    try:
        return lp.evaluate(PAGE_STATE_JS, i)
    except Exception:
        return None


def click_page(lp, i: int):
    try:
        return lp.evaluate(CLICK_PAGE_JS, i)
    except Exception as e:
        LOG.warn("click_page 失败:", str(e)[:70])
        return None


def _play_loop(lp, speed: float, stall: float = 30.0):
    """播放到结尾，返回 (原因, 状态)。不负责判断是否算完成。"""
    last_t, last_move, retries = -1.0, time.time(), 0
    while True:
        if lp.is_closed():
            return "closed", None
        st = vstat(lp)
        if not st:
            time.sleep(3)
            continue
        t, dur = st["t"] or 0, st["dur"] or 0
        print(f"\r   {t:7.1f}/{dur:7.1f}s  {st['rate']}x  {'暂停' if st['paused'] else '播放'}  "
              f"(video×{st.get('count', 1)})   ", end="", flush=True)

        ended = lp.evaluate("() => window.__END_INFO__")
        if ended:
            print()
            return "end", {**st, "t": ended["t"], "dur": ended["dur"]}
        if dur and t >= dur - 0.2:
            print()
            # 播放器会在结束后自动从头循环，心跳就永远停在“差一点点”上。
            # 到结尾立刻手动暂停，逼平台上报最终位置。
            try:
                lp.evaluate("() => { const v = document.querySelector('video'); if (v) { try { v.pause(); } catch (e) {} } }")
            except Exception:
                pass
            return "end", st
        if abs(t - last_t) > 0.05:
            last_t, last_move, retries = t, time.time(), 0
            continue
        if time.time() - last_move <= stall:
            time.sleep(2)
            continue
        retries += 1
        last_move = time.time()
        dismiss_tips(lp, "播放中断")
        force_play(lp, speed)
        if retries > 3:
            print()
            return "stuck", st
        time.sleep(2)


def play_to_end(lp, page: dict, speed: float = 1.0) -> tuple[str, dict | None]:
    """点开一个小节并播到结尾，不做完成判定。"""
    idx = page["i"]
    old = (vstat(lp) or {}).get("src")
    name = click_page(lp, idx)
    if not name:
        return "miss", None
    st = wait_video(lp, old_src=old, timeout=20, speed=speed)
    if not st:
        dismiss_tips(lp, "等视频")
        st = wait_video(lp, old_src=None, timeout=12, speed=speed)
    if not st:
        return "no_video", None
    dismiss_tips(lp, "开播前")
    force_play(lp, speed)
    time.sleep(1.5)
    dismiss_tips(lp, "开播后")
    return _play_loop(lp, speed)


def watch_page(lp, page: dict, speed: float = 1.0, verify_timeout: float = 20.0,
               max_retry: int = 3, chapter_idx: int | None = None) -> tuple[str, dict | None]:
    """点开一个页并确保它变成“已完成”。

    返回 (结果, 末状态)：
        done        —— 服务端已记完成
        play_only   —— 播到结尾但页面仍未标完成（重试 max_retry 次后）
        no_video    —— 这一页不是视频（PPT/文档等），需要单独处理
        closed      —— 学习页被关
    """
    idx = page["i"]
    old = (vstat(lp) or {}).get("src")
    name = click_page(lp, idx)
    if not name:
        return "miss", None

    for attempt in range(1, max_retry + 1):
        st = wait_video(lp, old_src=old, timeout=20, speed=speed)
        if not st:
            dismiss_tips(lp, "等视频")
            st = wait_video(lp, old_src=old, timeout=12, speed=speed)
        if not st:
            st = wait_video(lp, old_src=None, timeout=8, speed=speed)   # 重复点同一页时 src 不会变
        if not st:
            return "no_video", None

        dismiss_tips(lp, "开播前")
        force_play(lp, speed)
        time.sleep(2)
        dismiss_tips(lp, "开播后")

        reason, st = _play_loop(lp, speed)
        if reason == "closed":
            return "closed", st

        # —— 播到结尾后先就地看一眼（有的页面会实时打勾），没有再刷新 ——
        lp.wait_for_timeout(1500)
        for _ in range(5):
            ps0 = page_state(lp, idx)
            if (ps0 and (ps0["complete"] or ps0["finishIcon"])) or player_label(lp):
                LOG.ok(f"     100% 已确认：{page.get('name','')}")
                return "done", st
            lp.wait_for_timeout(1200)

        # 服务端记录不会自动刷新到界面，重载一次学习页把它拉下来
        try:
            lp.reload(wait_until="domcontentloaded", timeout=45000)
            lp.wait_for_timeout(4000)
            # 刷新后页面会自动续播上一个视频，立刻按停，避免看起来"又在从头播"
            try:
                lp.evaluate("() => document.querySelectorAll('video').forEach(v => { try { v.pause(); } catch (e) {} })")
            except Exception:
                pass
            dismiss_tips(lp, "刷新后")
            refreshed = list_pages(lp, chapter_idx)
        except Exception as e:
            LOG.warn("     刷新学习页失败:", str(e)[:70])
            refreshed = []

        def is_done():
            ps = (refreshed[idx] if idx < len(refreshed) else None) or page_state(lp, idx)
            lb = player_label(lp)
            return (ps if (ps and (ps["complete"] or ps["finishIcon"])) else None), lb

        ps, label = is_done()
        if ps or label:
            LOG.ok(f"     100% 已确认：{(ps or page).get('name','')} {('[' + label + ']') if label else ''}")
            return "done", st

        # 再给服务端一点时间（心率上报是异步的）
        end = time.time() + verify_timeout
        while time.time() < end:
            time.sleep(3)
            ps, label = is_done()
            if ps or label:
                LOG.ok(f"     100% 已确认：{(ps or page).get('name','')} {('[' + label + ']') if label else ''}")
                return "done", st

        LOG.warn(f"     刷新后仍未标完成（第 {attempt}/{max_retry} 次），补看一遍这一节")
        if refreshed and idx < len(refreshed):
            click_page(lp, idx)
            wait_video(lp, old_src=None, timeout=15, speed=speed)
            dismiss_tips(lp, "补看")
            force_play(lp, speed)
        old = None
        time.sleep(2)

    return "play_only", st










