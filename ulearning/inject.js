/* 注入到页面上下文的检测内核（Playwright 版）
 * 与 userscript 同源逻辑，去掉 HUD 与 GM API，事件通过 window.__report 回传 Python。
 */
(function () {
  if (window.__ULEARN_MONITOR__) return;

  const CFG = Object.assign({
    autoResume: true,
    autoNext: true,
    autoMute: true,
    speed: 1,
    stuckSec: 25,
    watchQuiz: true,
    pauseOnQuiz: true,
    tickMs: 1000
  }, window.__ULEARN_CFG || {});

  const state = {
    video: null, lastTime: -1, lastMoveAt: Date.now(),
    stuckCount: 0, quizOpen: false, quizText: '', path: location.pathname,
    events: 0, started: Date.now()
  };

  function report(type, msg, extra) {
    state.events++;
    const payload = { type, msg, extra: extra || {}, url: location.href, ts: Date.now() };
    try { if (typeof window.__report === 'function') window.__report(JSON.stringify(payload)); } catch (e) { }
    console.log('[ULEARN]', type, msg);
  }

  function findVideo() {
    // 关键：切换小节后旧播放器实例可能还留在 DOM 里。
    // 只认“可见且面积最大”的视频，否则会把上一个视频当成当前视频来播/暂停。
    const vis = [...document.querySelectorAll('video')].filter(v => {
      const r = v.getBoundingClientRect();
      const cs = getComputedStyle(v);
      return r.width > 50 && r.height > 30 && cs.visibility !== 'hidden' && cs.display !== 'none';
    });
    if (vis.length) {
      return vis.sort((a, b) => (b.clientWidth * b.clientHeight) - (a.clientWidth * a.clientHeight))[0];
    }
    return document.querySelector('video');
  }

  function visible(n) {
    if (!n || !n.getBoundingClientRect) return false;
    const r = n.getBoundingClientRect(), cs = getComputedStyle(n);
    return r.width > 60 && r.height > 30 && cs.display !== 'none' && cs.visibility !== 'hidden' && +cs.opacity > 0.1;
  }

  function bind() {
    const v = findVideo();
    if (!v || v === state.video) return;
    state.video = v; state.lastTime = -1; state.lastMoveAt = Date.now();
    if (CFG.autoMute) v.muted = true;
    if (CFG.speed && CFG.speed !== 1) { try { v.playbackRate = CFG.speed; } catch (e) { } }

    v.addEventListener('play', e => { if (e.target === state.video) report('PLAY', '播放 @' + v.currentTime.toFixed(1)); });
    v.addEventListener('pause', e => {
      if (e.target !== state.video) return;           // 忽略旧播放器实例的暂停
      if (state.quizOpen) return report('PAUSE_QUIZ', '弹题暂停');
      report('PAUSE', '暂停 @' + v.currentTime.toFixed(1));
      if (CFG.autoResume) setTimeout(() => { if (!state.quizOpen && v.paused) v.play().catch(e => report('RESUME_FAIL', String(e))); }, 1200);
    });
    v.addEventListener('ended', e => { if (e.target === state.video) { report('ENDED', '本节结束'); next(); } });
    v.addEventListener('ratechange', e => { if (e.target === state.video) report('RATE', v.playbackRate + 'x'); });
    report('VIDEO_BOUND', '锁定播放器', { duration: Math.round(v.duration || 0), w: v.clientWidth, h: v.clientHeight });
  }

  const QUIZ_SEL = ['.pop-quiz', '.quiz-popup', '.question-box', '.question-dialog', '.el-dialog',
    '.ant-modal', '.layui-layer', '.modal-dialog', '[class*="quiz"]', '[class*="question"]', '[id*="question"]'];
  const QUIZ_RE = /单\s*选\s*题|多\s*选\s*题|判\s*断\s*题|请\s*作\s*答|提\s*交\s*答\s*案|继续\s*学\s*习|小\s*测|课\s*堂\s*测\s*试|答\s*对|答\s*错/;

  function quiz() {
    if (!CFG.watchQuiz) return;
    let hit = null;
    outer:
    for (const s of QUIZ_SEL) {
      let ns; try { ns = document.querySelectorAll(s); } catch (e) { continue; }
      for (const n of ns) {
        if (!visible(n)) continue;
        const t = (n.innerText || '').slice(0, 500);
        if (t.length < 4) continue;
        if (QUIZ_RE.test(t) || n.querySelector('input[type=radio],input[type=checkbox]')) { hit = { el: n, txt: t }; break outer; }
      }
    }
    if (hit && !state.quizOpen) {
      state.quizOpen = true; state.quizText = hit.txt;
      report('QUIZ', '检测到弹题', { text: hit.txt.slice(0, 300) });
      if (CFG.pauseOnQuiz && state.video) try { state.video.pause(); } catch (e) { }
    } else if (!hit && state.quizOpen) {
      state.quizOpen = false; state.quizText = '';
      report('QUIZ_GONE', '弹题消失');
      if (state.video) state.video.play().catch(() => { });
    }
  }

  let lastNext = 0;
  function next() {
    if (!CFG.autoNext || Date.now() - lastNext < 15000) return;
    const c = [...document.querySelectorAll('a,button,li,div,span')].filter(n => {
      if (!visible(n)) return false;
      const t = (n.innerText || n.title || '').trim();
      return t.length <= 12 && /下一节|下一课|下一章|继续学习|下一页|下一个/.test(t) && !n.disabled;
    });
    if (!c.length) return report('NEXT_MISS', '未找到下一节按钮');
    lastNext = Date.now();
    report('NEXT', '点击下一节: ' + c[0].innerText.trim());
    c[0].click();
  }

  /* ---- 防“走神”计时暂停 ----
     优学院会在一段时间没有交互后弹「计时学习已暂停 / 走神太久啦」，
     视频还在放但学时不再累计，必须点「继续学习」。 ---- */
  let tickCount = 0;

  function visible(n) {
    const r = n.getBoundingClientRect(), c = getComputedStyle(n);
    return r.width > 10 && r.height > 8 && c.display !== 'none'
           && c.visibility !== 'hidden' && +c.opacity > 0.05;
  }

  function guardIdle() {
    const txt = (document.body && document.body.innerText) || '';
    if (!/计时学习已暂停|走神太久|计时君停止工作|已暂停计时/.test(txt)) return;
    const btn = [...document.querySelectorAll('button,a,div,span')].find(n =>
      /^(继续学习|继续计时|继续观看|继续)$/.test((n.innerText || '').trim()) && visible(n));
    if (btn) {
      try {
        btn.click();
        report('IDLE_RESUME', '检测到“计时已暂停”，已点继续学习');
      } catch (e) { }
    }
  }

  function keepAlive() {
    // 低频模拟操作，让平台的空闲计时器不那么容易触发
    try {
      document.dispatchEvent(new MouseEvent('mousemove', {
        clientX: 200 + Math.random() * 300, clientY: 150 + Math.random() * 200, bubbles: true
      }));
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Shift', bubbles: true }));
    } catch (e) { }
  }

  function tick() {
    bind();
    // 每个 tick 重新找“当前真正在用的那个视频”，切换小节后自动重新绑定
    const act = findVideo();
    if (act && act !== state.video) { state.video = null; bind(); }
    const v = state.video;
    if (v) {
      const t = v.currentTime, playing = !v.paused && !v.ended;
      if (playing) {
        if (Math.abs(t - state.lastTime) > 0.05) { state.lastTime = t; state.lastMoveAt = Date.now(); state.stuckCount = 0; }
        else if (Date.now() - state.lastMoveAt > CFG.stuckSec * 1000 * Math.min(state.stuckCount + 1, 4)) {
          state.stuckCount++;
          report('STUCK', '进度 ' + CFG.stuckSec + 's 未前进', { at: +t.toFixed(1), n: state.stuckCount });
          state.lastMoveAt = Date.now();
          try { v.play(); } catch (e) { }
        }
      } else if (!state.quizOpen && Date.now() - state.lastMoveAt > (CFG.stuckSec + 20) * 1000) {
        state.lastMoveAt = Date.now();
        report('IDLE', '长时间暂停，强制推进');
        v.play().catch(() => { });
      }
      // 只报告，不自己跳下一节：是否算看完由 Python 侧核验“已完成”标记后决定
      if (v.duration && t > 0 && v.duration - t < 2.5 && !v.ended) report('NEAR_END', '接近结束', { at: +t.toFixed(1), dur: +v.duration.toFixed(1) });
    }
    if (state.path !== location.pathname) {
      state.path = location.pathname; state.video = null; state.lastTime = -1;
      report('NAV', '页面跳转');
    }
    quiz();
    guardIdle();
    if (++tickCount % 20 === 0) keepAlive();
  }

  window.__ULEARN_MONITOR__ = {
    state, CFG, next, tick,
    stats: () => {
      const v = state.video;
      return {
        hasVideo: !!v,
        time: v ? +v.currentTime.toFixed(2) : null,
        duration: v && isFinite(v.duration) ? +v.duration.toFixed(1) : null,
        paused: v ? v.paused : null,
        rate: v ? v.playbackRate : null,
        quiz: state.quizOpen,
        quizText: state.quizText.slice(0, 300),
        stuck: state.stuckCount,
        path: location.pathname,
        events: state.events
      };
    }
  };

  setInterval(tick, CFG.tickMs);
  report('READY', '内核注入完成');
})();

