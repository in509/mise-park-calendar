#!/usr/bin/env python3
"""Railway 上跑的常驻服务：每天抓一次快照，同时把页面提供出去。"""
import http.server, json, os, socketserver, threading, time, traceback
from datetime import datetime, timezone

import fetch_mise as fm   # 时区由 fetch_mise.TZINFO（ZoneInfo）统一负责

PORT = int(os.environ.get("PORT", 8080))
CHECK_EVERY = 300          # 每 5 分钟检查一次"当前时段抓过了吗"
STATE = {"last_ok": None, "last_error": None, "runs": 0, "started": None}


def log(msg):
    print(f"[{fm.now_local():%Y-%m-%d %H:%M:%S %Z}] {msg}", flush=True)


def snapshot_if_needed():
    """当前时段还没抓就抓一次。

    文件名用「时段」而不是「实际时间」命名，所以重启、重新部署都不会重复抓；
    而且停机期间错过的时段，一上线就会立刻补上最近的那个。
    """
    slot = fm.current_slot()
    if os.path.exists(fm.slot_path(slot)):
        return False
    log(f"抓取时段 {fm.slot_id(slot)} …")
    snaps = fm.run_once(slot)
    STATE["last_ok"] = fm.now_local().isoformat(timespec="seconds")
    STATE["last_slot"] = fm.slot_id(slot)
    STATE["last_error"] = None
    STATE["runs"] += 1
    log(f"完成，共 {len(snaps)} 份快照")
    return True


def worker():
    while True:
        try:
            snapshot_if_needed()
        except Exception as e:
            STATE["last_error"] = f"{type(e).__name__}: {e}"
            log("抓取失败: " + STATE["last_error"])
            traceback.print_exc()
        time.sleep(CHECK_EVERY)


WAITING = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="15"><title>Mise Park 场地占用记录</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#faf9f7;color:#1a1a18;
font:15px/1.6 ui-sans-serif,-apple-system,"PingFang SC",sans-serif;padding:24px}
@media(prefers-color-scheme:dark){body{background:#171614;color:#f0eeea}}
div{max-width:30rem;text-align:center}h1{font-size:19px;margin:0 0 8px}
p{color:#6b6862;font-size:14px;margin:6px 0}code{font-size:12px}</style></head>
<body><div><h1>正在抓取第一份数据…</h1>
<p>页面会自动刷新。如果一直停在这里，看 <code>/status</code> 查原因。</p>
<p style="font-size:12px">%s</p></div></body></html>"""


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=fm.STORE, **kw)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()

    def _send(self, body, ctype="text/html; charset=utf-8", code=200):
        raw = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/status":
            snaps = sorted(f for f in os.listdir(fm.DATA)) if os.path.isdir(fm.DATA) else []
            return self._send(json.dumps({
                **STATE,
                "snapshots": len(snaps),
                "days": len({f[9:19] for f in snaps}),
                "first": snaps[0][9:19] if snaps else None,
                "latest": snaps[-1][9:-5] if snaps else None,
                "now": fm.now_local().isoformat(timespec="seconds"),
                "now_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "utc_offset": fm.now_local().strftime("%z"),
                "current_slot": fm.slot_id(fm.current_slot()),
                "next_run": fm.next_slot().isoformat(timespec="minutes"),
                "run_hours": fm.RUN_HOURS,
                "tz": str(fm.TZINFO),
                "store": fm.STORE,
                "resources": [n for _, n in fm.RESOURCES],
            }, ensure_ascii=False, indent=1), "application/json; charset=utf-8")
        if path == "/healthz":
            return self._send("ok", "text/plain")
        if path in ("/", "/index.html") and not os.path.exists(fm.HTML):
            err = STATE["last_error"] or "启动中…"
            return self._send(WAITING % err, code=503)
        return super().do_GET()

    def log_message(self, *a):
        pass


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def rebuild_page():
    """用当前模板重新生成页面（不联网）。

    index.html 是产物，存在 Volume 里；改了模板或视图逻辑后如果不重建，
    就得等下一次抓取才能看见 —— 最长 12 小时。所以每次启动都重建一次。
    """
    snaps = fm.load_snapshots()
    if not snaps:
        return
    fm.write_history(snaps)
    fm.build_html(fm.build_view(snaps))
    log(f"已用当前模板重新生成页面（{len(snaps)} 份快照）")


if __name__ == "__main__":
    os.makedirs(fm.DATA, exist_ok=True)
    STATE["started"] = fm.now_local().isoformat(timespec="seconds")
    try:
        rebuild_page()
    except Exception as e:
        log(f"启动时重建页面失败: {type(e).__name__}: {e}")
    log(f"数据目录 {fm.STORE} · 每天 {fm.RUN_HOURS} 点抓取 · 监听 :{PORT}")
    threading.Thread(target=worker, daemon=True).start()
    Server(("0.0.0.0", PORT), Handler).serve_forever()
