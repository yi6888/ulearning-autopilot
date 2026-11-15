"""编排层：登录 -> 选课 -> 专题循环 -> 小节循环。"""
from __future__ import annotations

import json
import queue
import re
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import browser as B
from . import course as C
from .dom import dismiss_tips
from .log import LOG
from .player import (END_HOOK_JS, SKIP_RE, click_page, list_pages, play_to_end,
                     player_label)

AUTH_RE = re.compile(r"authorization|token|auth|ticket|session|uid|userinfo|user_info|lms_", re.I)
LOGIN_TIMEOUT_S = 600  # 登录等待上限：无头模式下无有效登录态时不至于静默挂死


class WebhookSender:
    """把事件非阻塞地 POST 到看板（tools/hook_server.py），发送失败不拖累刷课主流程。"""

    def __init__(self, url: str):
        self.url = url.strip() if url else ""
        self._q: queue.Queue = queue.Queue()
        if self.url:
            threading.Thread(target=self._loop, daemon=True).start()

    def send(self, payload: dict) -> None:
        if self.url:
            self._q.put(payload)

    def _loop(self) -> None:
        while True:
            item = self._q.get()
            try:
                req = urllib.request.Request(
                    self.url,
                    data=json.dumps(item, ensure_ascii=False).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                urllib.request.urlopen(req, timeout=5)
            except Exception:
                pass


@dataclass
class RunOptions:
    course_name: str = ""          # 课程名关键词，如 “形势与政策（三）”
    course_idx: int = 0            # 没给名字时按序号
    browser: str = "msedge"        # msedge / chrome
    headless: bool = False
    profile_dir: Path = field(default_factory=lambda: Path("profile-auto"))
    logdir: Path = field(default_factory=lambda: Path("logs"))
    shotdir: Path = field(default_factory=lambda: Path("shots"))
    speed: float = 1.0            # 平台按实际时长记账，>1 可能被判“观看时长不足”
    cookie_days: int = 30
    dry_run: bool = False          # 只列课程/专题，不播放
    max_chapters: int = 0          # 0 = 全部
    webhook: str = ""              # 事件实时转发目标（可选）


class Session:
    def __init__(self, opts: RunOptions):
        self.o = opts
        LOG.set_logdir(self.o.logdir)
        self.o.shotdir.mkdir(parents=True, exist_ok=True)
        self.events: list[dict] = []
        self.cookies_persisted = False
        self.cid = ""
        self.failed: list[str] = []
        self.webhook = WebhookSender(self.o.webhook)

    # ---------------- 事件（内核回调） ----------------
    def on_report(self, src, payload: str):
        try:
            ev = json.loads(payload)
        except Exception:
            return
        typ = ev.get("type", "?")
        self.events.append(ev)
        LOG.event(typ, ev.get("msg", ""), ev.get("extra"))
        self.webhook.send(ev)
        if typ == "QUIZ":
            page = src.get("page") if isinstance(src, dict) else None
            if page is not None:
                try:
                    path = self.o.shotdir / f"quiz-{ev.get('ts', 0)}.png"
                    page.screenshot(path=str(path), timeout=8000, animations="disabled")
                    LOG.dim(f"   弹题截图: {path}")
                except Exception:
                    pass
        if typ not in ("READY", "RATE", "PLAY"):
            LOG.dim(f"   [{typ}] {ev.get('msg', '')[:80]}")

    def on_page(self, pg):
        LOG.dim("[新窗口]", (pg.url or "about:blank")[:90])

    # ---------------- 登录 ----------------
    def ensure_login(self, ctx, pg) -> bool:
        if C.course_ok(pg) and "courseList" in (pg.url or ""):
            B.persist_auth_cookies(ctx, self.o.cookie_days)
            return True

        pg.goto(C.LOGIN, wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(1500)
        try:
            pg.bring_to_front()
        except Exception:
            pass

        base = {n for _, n in B.ul_cookies(ctx)}
        LOG("=" * 60)
        LOG("窗口就绪，请在浏览器里登录优学院（账号密码 / 微信扫码）")
        LOG("登录期间我不会操作页面")
        LOG("=" * 60)

        deadline = time.time() + LOGIN_TIMEOUT_S
        while True:
            names = {n for _, n in B.ul_cookies(ctx)}
            auth = sorted(n for n in (names - base) if AUTH_RE.search(n))
            if auth or C.course_ok(pg):
                LOG.ok("[+] 登录成功" + (": " + ", ".join(auth) if auth else ""))
                pg.wait_for_timeout(1200)
                break
            if time.time() > deadline:
                LOG.err(f"登录等待超过 {LOGIN_TIMEOUT_S}s，退出（无头模式下请先跑 python -m ulearning login 存好登录态）")
                return False
            pg.wait_for_timeout(2000)

        B.persist_auth_cookies(ctx, self.o.cookie_days)
        self.cookies_persisted = True

        try:
            pg.goto(C.COURSE_LIST, wait_until="domcontentloaded", timeout=45000)
            pg.wait_for_timeout(3500)
        except Exception as e:
            LOG.warn("跳课程列表失败:", str(e)[:80])
        return C.course_ok(pg)

    # ---------------- 主流程 ----------------
    def run(self) -> int:
        from playwright.sync_api import sync_playwright

        inject = (Path(__file__).with_name("inject.js")).read_text(encoding="utf-8")
        kernel_cfg = json.dumps({
            "autoMute": True, "autoResume": True, "autoNext": False,
            "speed": self.o.speed, "stuckSec": 20, "pauseOnQuiz": True,
        })
        init = [f"window.__ULEARN_CFG={kernel_cfg};\n{inject}", END_HOOK_JS]

        B.clone_profile(self.o.browser, self.o.profile_dir)
        with sync_playwright() as p:
            LOG.dim(f"浏览器: {self.o.browser}   配置: {self.o.profile_dir}")
            ctx = B.launch(p, self.o.profile_dir, self.o.browser, self.o.headless,
                           init_scripts=init,
                           expose={"__report": self.on_report},
                           on_page=self.on_page)
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                pg.goto(C.COURSE_LIST, wait_until="domcontentloaded", timeout=60000)
                pg.wait_for_timeout(3000)
            except Exception:
                pass

            if not self.ensure_login(ctx, pg):
                LOG.err("登录未完成，退出")
                ctx.close()
                return 2

            courses = C.list_courses(pg)
            LOG.ok(f"课程 {len(courses)} 门")
            for c in courses:
                print("   -", c["text"][:80])

            if self.o.dry_run:
                ctx.close()
                return 0

            C.pick_course(pg, self.o.course_name or None, self.o.course_idx)
            pg.wait_for_timeout(4000)
            cid = C.course_id_from(pg)
            if not cid:
                LOG.err("拿不到 courseId，退出")
                ctx.close()
                return 3
            LOG.ok(f"courseId = {cid}")
            self.cid = cid

            chapters = C.open_textbook(pg, cid)
            LOG.ok(f"专题 {len(chapters)} 个")
            for ch in chapters:
                print(f"   [{ch['i']}] {ch['name'][:46]:<46} {ch['pct']:<5} {ch['time']}")

            self.play_all(ctx, pg, chapters)
            try:
                ctx.close()
            except Exception:
                pass
            if self.failed:
                LOG.err(f"有 {len(self.failed)} 个小节未确认完成: {', '.join(self.failed[:10])}"
                        + ("…" if len(self.failed) > 10 else ""))
                LOG.dim("事件统计: " + LOG.summary())
                return 1
            LOG.ok("全部完成 | " + LOG.summary())
            return 0

    def play_all(self, ctx, book_pg, chapters: list[dict]):
        todo = [c for c in chapters if c["pct"] not in ("100%",)]
        if self.o.max_chapters:
            todo = todo[: self.o.max_chapters]
        LOG.ok(f"待学专题 {len(todo)} 个，倍速 {self.o.speed}x")

        for ch in todo:
            LOG("-" * 56)
            LOG.ok(f"专题：{ch['name']}")
            lp = C.open_chapter(ctx, book_pg, ch["i"])
            if lp is None:
                LOG.warn("   没打开学习页，跳过")
                continue
            try:
                lp.wait_for_timeout(5000)
                dismiss_tips(lp, "进入学习页")
                pages = list_pages(lp, ch["i"])
                LOG.dim(f"   小节 {len(pages)} 个: " + " / ".join(p["name"] for p in pages))
                done = sum(1 for p in pages if p["complete"])
                LOG.ok(f"   已完成 {done}/{len(pages)}")

                for i, p in enumerate(pages):
                    if SKIP_RE.search(p["name"]):
                        LOG.dim(f"   跳过（非课件） {p['name']}")
                        continue
                    if p["complete"]:
                        LOG.dim(f"   ✓ 已完成，跳过 {p['name']}")
                        continue

                    LOG.ok(f"   ▶ {p['name']}  ← 开始播放")
                    status, st = play_to_end(lp, p, self.o.speed)
                    tail = f" {st['t']:.0f}/{st['dur']:.0f}s" if st else ""
                    LOG((f"     播放结束: {status}{tail}"), level="ok" if status == "end" else "warn")
                    if status == "closed":
                        return
                    if status != "end":
                        self.failed.append(p["name"])
                        continue

                    # 平台规则：看完后先显示“已看完”，**点下一个视频时**才把上一个上报上去。
                    # 所以这里不再关窗重开，而是等标签 → 点下一个 → 回读上一节的标记。
                    waited = 0
                    while waited < 15 and not player_label(lp):
                        lp.wait_for_timeout(1000)
                        waited += 1
                    LOG.ok(f"     已看完标记: {player_label(lp) or '未出现'}")

                    if i + 1 < len(pages):
                        nxt = pages[i + 1]
                        click_page(lp, nxt["i"])
                        lp.wait_for_timeout(5000)
                        fresh = list_pages(lp, ch["i"])
                        cur = fresh[i] if i < len(fresh) else None
                        if cur and (cur["complete"] or cur["finishIcon"]):
                            LOG.ok(f"     ✓ 上一节已记为完成：{cur['name']}")
                        else:
                            LOG.warn(f"     上报后仍未打勾：{p['name']}（继续，下次打开会再核对）")
                            self.failed.append(p["name"])
            finally:
                try:
                    if lp is not book_pg:
                        lp.close()
                except Exception:
                    pass
                book_pg.wait_for_timeout(1200)
                C.open_textbook(book_pg, self.cid or (C.course_id_from(book_pg) or ""))








