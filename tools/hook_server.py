#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""webhook 接收端 + 实时看板（标准库实现，不用装框架）

启动：
    E:\\Python\\python.exe hook_server.py --port 8765

然后在检测器上加 --webhook http://127.0.0.1:8765/hook
浏览器打开 http://127.0.0.1:8765/ 看实时状态，10 秒自动刷新。
"""
import argparse
import json
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"
LOGS.mkdir(parents=True, exist_ok=True)
EVENTS = []          # 内存里保留最近 400 条
MAX = 400

PAGE = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>优学院网课检测看板</title>
<style>
*{box-sizing:border-box}
body{margin:0;background:#0d1117;color:#c9d1d9;font:14px/1.6 "Microsoft YaHei",system-ui,sans-serif}
header{padding:16px 24px;border-bottom:1px solid #21262d;display:flex;align-items:center;gap:14px}
h1{font-size:16px;margin:0;font-weight:600}
.pill{font-size:12px;padding:2px 10px;border-radius:99px;background:#1f6feb22;color:#58a6ff;border:1px solid #1f6feb55}
main{display:grid;grid-template-columns:320px 1fr;gap:18px;padding:18px 24px;align-items:start}
.card{background:#161b22;border:1px solid #21262d;border-radius:10px;padding:14px 16px}
.card h2{font-size:13px;margin:0 0 10px;color:#8b949e;font-weight:600;letter-spacing:.4px}
.kv{display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px dashed #21262d}
.kv:last-child{border:0}
.kv b{color:#e6edf3;font-weight:600}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #21262d;vertical-align:top}
th{color:#8b949e;font-weight:600;font-size:12px;position:sticky;top:0;background:#161b22}
td.t{white-space:nowrap;color:#6e7681;font-family:Consolas,monospace;font-size:12px}
.tag{font-size:11px;padding:1px 7px;border-radius:5px;font-weight:600;white-space:nowrap}
.QUIZ{background:#f8514922;color:#ff7b72;border:1px solid #f8514966}
.STUCK,.WATCHDOG_STUCK,.WATCHDOG_IDLE{background:#d2992222;color:#e3b341;border:1px solid #d2992266}
.PLAY,.READY,.NEXT,.ADVANCE{background:#2ea04322;color:#3fb950;border:1px solid #2ea04366}
.PAUSE,.NAV,.RATE,.ENDED{background:#1f6feb22;color:#58a6ff;border:1px solid #1f6feb66}
.other{background:#30363d55;color:#8b949e;border:1px solid #30363d}
.scroll{max-height:66vh;overflow:auto}
.mono{font-family:Consolas,monospace;font-size:12px;color:#8b949e}
.bar{height:8px;background:#21262d;border-radius:5px;overflow:hidden;margin:8px 0}
.bar i{display:block;height:100%;background:linear-gradient(90deg,#238636,#3fb950)}
</style></head><body>
<header><h1>优学院网课检测看板</h1><span class="pill" id="dot">连接中</span>
<span class="mono" id="upd"></span></header>
<main>
  <div>
    <div class="card"><h2>实时状态</h2><div id="stat" class="mono">等待检测器上报…</div></div>
    <div class="card" style="margin-top:14px"><h2>事件计数</h2><div id="cnt" class="mono">-</div></div>
  </div>
  <div class="card"><h2>事件流</h2>
    <div class="scroll"><table><thead><tr><th style="width:70px">时间</th><th style="width:150px">类型</th><th>内容</th></tr></thead>
    <tbody id="rows"></tbody></table></div>
  </div>
</main>
<script>
const cls = t => ['QUIZ','STUCK','WATCHDOG_STUCK','WATCHDOG_IDLE','PLAY','READY','NEXT','ADVANCE','PAUSE','NAV','RATE','ENDED'].includes(t) ? t : 'other';
function fmt(s){ if(s==null) return '-'; s=Math.floor(s); return String(Math.floor(s/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0'); }
async function pull(){
  try{
    const j = await (await fetch('/api/state')).json();
    document.getElementById('dot').textContent = '在线';
    document.getElementById('upd').textContent = '更新于 ' + j.updated;
    const s = j.status && j.status.stats || {};
    if(s.hasVideo!==undefined){
      const pct = s.duration ? (s.time/s.duration*100) : 0;
      document.getElementById('stat').innerHTML =
        `<div class="kv"><span>播放进度</span><b>${fmt(s.time)} / ${fmt(s.duration)}</b></div>
         <div class="bar"><i style="width:${pct.toFixed(1)}%"></i></div>
         <div class="kv"><span>状态</span><b>${s.quiz?'⚠ 弹题待答':(s.paused?'已暂停':'播放中')}</b></div>
         <div class="kv"><span>倍速 / 卡住</span><b>${s.rate}x / ${s.stuck}</b></div>
         <div class="kv"><span>页面</span><b style="font-size:11px">${(s.path||'').slice(0,34)}</b></div>`;
    }
    if(j.status && j.status.counts){
      document.getElementById('cnt').innerHTML = Object.entries(j.status.counts)
        .sort((a,b)=>b[1]-a[1]).map(([k,v])=>`<div class="kv"><span>${k}</span><b>${v}</b></div>`).join('') || '-';
    }
    document.getElementById('rows').innerHTML = j.events.map(e =>
      `<tr><td class="t">${e.ts}</td><td><span class="tag ${cls(e.type)}">${e.type}</span></td>
       <td>${(e.msg||'').replace(/[<>&]/g, c=>({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]))}
       ${e.extra&&Object.keys(e.extra).length?'<div class="mono">'+JSON.stringify(e.extra).slice(0,160)+'</div>':''}</td></tr>`).join('');
  }catch(e){ document.getElementById('dot').textContent='离线'; }
}
pull(); setInterval(pull, 3000);
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code, body: bytes, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "POST,GET,OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        if self.path.startswith("/api/state"):
            status = {}
            f = LOGS / "status.json"
            if f.exists():
                try:
                    status = json.loads(f.read_text(encoding="utf-8"))
                except Exception:
                    pass
            body = json.dumps({
                "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "status": status,
                "events": EVENTS[::-1][:80],
            }, ensure_ascii=False).encode("utf-8")
            return self._send(200, body)
        return self._send(404, b'{"err":"not found"}')

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            ev = json.loads(raw.decode("utf-8"))
        except Exception:
            ev = {"type": "RAW", "msg": raw[:200].decode("utf-8", "ignore")}
        ev.setdefault("ts", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        EVENTS.append(ev)
        while len(EVENTS) > MAX:
            EVENTS.pop(0)
        with (LOGS / "webhook.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        tag = ev.get("type", "?")
        print(f"[{ev['ts'][11:]}] {tag:<14} {ev.get('msg','')}")
        return self._send(200, b'{"ok":true}')

    def log_message(self, *a):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    srv = ThreadingHTTPServer((a.host, a.port), H)
    print(f"看板:  http://{a.host}:{a.port}/")
    print(f"hook:  http://{a.host}:{a.port}/hook")
    print("Ctrl+C 退出")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()

