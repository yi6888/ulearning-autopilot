"""页面通用操作：可见性判断、按文本点击、关闭遮挡提示、读视频状态。"""
from __future__ import annotations

import time

from .log import LOG

VISIBLE_JS = """
(n) => {
  const r = n.getBoundingClientRect(), c = getComputedStyle(n);
  return r.width > 8 && r.height > 8 && c.display !== 'none'
         && c.visibility !== 'hidden' && +c.opacity > 0.05;
}
"""

CLICK_BY_TEXT_JS = r"""
([kw, maxlen]) => {
  const vis = n => { const r = n.getBoundingClientRect(), c = getComputedStyle(n);
    return r.width > 20 && r.height > 10 && c.display !== 'none'
           && c.visibility !== 'hidden' && +c.opacity > 0.05; };
  const cands = [...document.querySelectorAll('div,li,a,section,span')].filter(n => {
    const t = (n.innerText || '').trim().replace(/\s+/g, ' ');
    if (!t || t.length > maxlen || !t.includes(kw)) return false;
    return vis(n);
  });
  if (!cands.length) return null;
  const inner = cands.filter(n => !cands.some(m => m !== n && n.contains(m)));
  const el = (inner.length ? inner : cands)[0];
  el.scrollIntoView({ block: 'center' });
  el.click();
  return (el.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 120);
}"""

DISMISS_JS = r"""
() => {
  const vis = n => { const r = n.getBoundingClientRect(), c = getComputedStyle(n);
    return r.width > 10 && r.height > 8 && c.display !== 'none'
           && c.visibility !== 'hidden' && +c.opacity > 0.05; };
  const clicked = [];
  for (const w of ['跳过所有提示', '继续学习', '继续计时', '我知道了', '知道了', '确定', '关闭提示']) {
    const els = [...document.querySelectorAll('a,button,div,span')]
      .filter(n => (n.innerText || '').trim() === w && vis(n));
    for (const el of els.slice(0, 3)) {
      try { el.click(); clicked.push(w); } catch (e) { }
    }
  }
  return clicked;
}"""

VSTAT_JS = r"""
() => {
  // 切换小节后旧播放器实例可能还在 DOM 里：只认可见且面积最大的那个
  const all = [...document.querySelectorAll('video')];
  const vis = all.filter(v => {
    const r = v.getBoundingClientRect(), c = getComputedStyle(v);
    return r.width > 50 && r.height > 30 && c.visibility !== 'hidden' && c.display !== 'none';
  });
  const v = (vis.length ? vis.sort((a, b) =>
      (b.clientWidth * b.clientHeight) - (a.clientWidth * a.clientHeight))[0] : all[0]);
  if (!v) return null;
  return { t: v.currentTime, dur: v.duration, paused: v.paused, ended: v.ended,
           rate: v.playbackRate, ready: v.readyState, count: all.length,
           src: (v.currentSrc || v.src || '').slice(0, 120) };
}"""


def click_by_text(pg, keyword: str, maxlen: int = 200):
    try:
        return pg.evaluate(CLICK_BY_TEXT_JS, [keyword, maxlen])
    except Exception as e:
        LOG.warn("click_by_text 失败:", str(e)[:80])
        return None


def dismiss_tips(pg, tag: str = "") -> list[str]:
    """关闭“知道了 / 跳过所有提示 / 退出学习”这类遮挡层。
    优学院首播会弹“视频观看时长≥视频时长才能算完成，进度条不能拖拽”，不点掉视频不播。
    """
    try:
        got = pg.evaluate(DISMISS_JS)
    except Exception:
        return []
    if got:
        LOG.dim(f"   关闭提示{('(' + tag + ')') if tag else ''}: {', '.join(sorted(set(got)))}")
    return got


def vstat(pg):
    try:
        return pg.evaluate(VSTAT_JS)
    except Exception:
        return None


def force_play(pg, speed: float = 1.0, muted: bool = True) -> None:
    try:
        pg.evaluate("""([sp, mu]) => {
            const all = [...document.querySelectorAll('video')];
            const vis = all.filter(v => {
              const r = v.getBoundingClientRect(), c = getComputedStyle(v);
              return r.width > 50 && r.height > 30 && c.visibility !== 'hidden' && c.display !== 'none';
            });
            const v = (vis.length ? vis.sort((a, b) =>
                (b.clientWidth * b.clientHeight) - (a.clientWidth * a.clientHeight))[0] : all[0]);
            if (!v) return;
            if (mu) v.muted = true;
            try { if (Math.abs(v.playbackRate - sp) > 0.01) v.playbackRate = sp; } catch (e) {}
            if (v.paused) v.play().catch(()=>{});
        }""", [speed, muted])
    except Exception:
        pass


def wait_video(pg, old_src: str | None = None, timeout: float = 20, speed: float = 1.0):
    """等新视频就绪；等待期间就顺手按播放，避免出现长时间停在 00:00 的黑屏期。"""
    end = time.time() + timeout
    while time.time() < end:
        st = vstat(pg)
        if st and (st.get("dur") or 0) > 0 and (st.get("ready") or 0) >= 2:
            force_play(pg, speed)
            return st
        force_play(pg, speed)
        time.sleep(1)
    return None



