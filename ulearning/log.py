"""统一日志：终端彩色行 + JSONL 落盘。"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

C = {
    "ok": "\033[92m", "warn": "\033[93m", "err": "\033[91m",
    "info": "\033[96m", "dim": "\033[90m", "end": "\033[0m",
}


class Log:
    def __init__(self, logdir: Path | None = None, quiet: bool = False, color: bool = True):
        self.quiet = quiet
        self.color = color and sys.stdout.isatty()
        self.counts: dict[str, int] = {}
        self.file = None
        if logdir:
            logdir.mkdir(parents=True, exist_ok=True)
            self.file = logdir / f"events-{datetime.now():%Y%m%d}.jsonl"

    def _paint(self, s, key):
        return f"{C[key]}{s}{C['end']}" if self.color else s

    def __call__(self, *parts, level: str = "info"):
        msg = " ".join(str(p) for p in parts)
        if not self.quiet:
            print(f"{datetime.now():%H:%M:%S} {self._paint(msg, level)}", flush=True)

    def ok(self, *p): self(*p, level="ok")
    def warn(self, *p): self(*p, level="warn")
    def err(self, *p): self(*p, level="err")
    def dim(self, *p): self(*p, level="dim")

    def event(self, typ: str, msg: str, extra: dict | None = None):
        self.counts[typ] = self.counts.get(typ, 0) + 1
        if self.file:
            rec = {"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                   "epoch": int(time.time()), "type": typ, "msg": msg, "extra": extra or {}}
            try:
                with self.file.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            except Exception:
                pass

    def summary(self) -> str:
        if not self.counts:
            return "（无事件）"
        return "  ".join(f"{k}×{v}" for k, v in sorted(self.counts.items(), key=lambda x: -x[1]))


LOG = Log()
