"""浏览器启动、独立配置克隆、登录态持久化。

设计要点：
1. 绝不直接使用你正在用的浏览器配置目录 —— 复制一份到 profile-* 再启动。
   浏览器运行中 Cookies 文件是独占锁（ERROR_SHARING_VIOLATION），
   所以克隆必须在浏览器关闭时进行；克隆不到就跳过，等你手动登录。
2. 优学院的 token / AUTHORIZATION 是会话级 cookie，关浏览器就没了。
   登录成功后把它们重写成 30 天有效，之后重启免登录。
"""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from .log import LOG

CHANNELS = {"msedge": "msedge", "edge": "msedge", "chrome": "chrome", "chromium": None}

# Playwright 默认会给浏览器塞这些参数；--no-sandbox 会让 Edge/Chrome 顶部弹
# “你使用的是不受支持的命令行标志”警告，去掉。--enable-automation 会暴露自动化特征，也去掉。
IGNORE_DEFAULT_ARGS = ["--no-sandbox", "--enable-automation"]

BASE_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
    "--mute-audio",
    "--autoplay-policy=no-user-gesture-required",
]

CLONE_ITEMS = [
    "Local State",
    r"Default\Preferences",
    r"Default\Secure Preferences",
    r"Default\Network\Cookies",
    r"Default\Network\Cookies-journal",
    r"Default\Network\Network Persistent State",
    r"Default\Local Storage",
    r"Default\Session Storage",
    r"Default\Web Data",
]

PROFILE_ROOTS = {
    "msedge": Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Edge/User Data",
    "chrome": Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/User Data",
}


def channel_of(name: str) -> str | None:
    return CHANNELS.get(name.lower(), name or None)


def clone_profile(browser: str, dst: Path, force: bool = False) -> bool:
    """把本机浏览器配置（含 cookie）复制到 dst。返回是否至少成功复制了 Cookies。"""
    src_root = PROFILE_ROOTS.get(browser)
    if not src_root or not src_root.exists():
        LOG.warn(f"[clone] 找不到 {browser} 配置目录，跳过")
        return False
    if dst.exists() and not force:
        return (dst / "Default/Network/Cookies").exists()
    (dst / "Default/Network").mkdir(parents=True, exist_ok=True)
    ok, fail, got_cookie = 0, 0, False
    for item in CLONE_ITEMS:
        src, target = src_root / item, dst / item
        if not src.exists():
            continue
        try:
            if src.is_dir():
                if target.exists():
                    shutil.rmtree(target, ignore_errors=True)
                shutil.copytree(src, target, dirs_exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, target)
            ok += 1
            if item.endswith("Cookies"):
                got_cookie = True
        except Exception:
            fail += 1
    LOG.dim(f"[clone] {browser}: 成功 {ok} 项" + (f"，{fail} 项被占用（浏览器可能正在运行）" if fail else ""))
    return got_cookie


def launch(p, user_data_dir: Path, browser: str = "msedge", headless: bool = False,
           init_scripts: list[str] | None = None, expose: dict | None = None,
           on_page=None, front: bool = True):
    """启动持久化上下文；自动注入内核脚本与 __report 绑定。"""
    channel = channel_of(browser)
    kwargs = dict(
        user_data_dir=str(user_data_dir),
        headless=headless,
        viewport={"width": 1500, "height": 940},
        locale="zh-CN",
        timezone_id="Asia/Shanghai",
        ignore_default_args=list(IGNORE_DEFAULT_ARGS),
        args=list(BASE_ARGS),
    )
    if channel:
        kwargs["channel"] = channel
    ctx = p.chromium.launch_persistent_context(**kwargs)

    ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
    for js in (init_scripts or []):
        ctx.add_init_script(js)
    for name, fn in (expose or {}).items():
        ctx.expose_binding(name, fn)
    if on_page:
        ctx.on("page", on_page)
    return ctx


def ul_cookies(ctx) -> dict:
    try:
        return {(c["domain"], c["name"]): c for c in ctx.cookies() if "ulearning" in c["domain"]}
    except Exception:
        return {}


def persist_auth_cookies(ctx, days: int = 30) -> list[str]:
    """把会话 cookie 改写成长期有效，重启浏览器后仍保持登录。"""
    cks = [c for c in ul_cookies(ctx).values()]
    if not cks:
        return []
    exp = int(time.time()) + days * 86400
    fixed = []
    for c in cks:
        item = {k: c[k] for k in ("name", "value", "domain", "path") if k in c}
        item["expires"] = exp
        item["httpOnly"] = bool(c.get("httpOnly"))
        item["secure"] = bool(c.get("secure"))
        if c.get("sameSite") in ("Strict", "Lax", "None"):
            item["sameSite"] = c["sameSite"]
        fixed.append(item)
    try:
        ctx.add_cookies(fixed)
        names = [c["name"] for c in fixed]
        LOG.dim(f"[cookie] {len(fixed)} 条改为 {days} 天有效: {', '.join(names)}")
        return names
    except Exception as e:
        LOG.warn("[cookie] 持久化失败:", str(e)[:100])
        return []
