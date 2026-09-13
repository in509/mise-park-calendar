#!/usr/bin/env python3
"""Mise Park (San Jose PRNS) availability snapshotter.

每个「时段」抓一次（默认每天 11:00 和 23:00），记录预订网站当下显示的占用情况，
并重新生成 index.html —— 补上网站因为 4 天封锁规则而不再显示的那部分历史。
"""
import csv, json, os, time, urllib.request
from datetime import date, datetime, time as dtime, timedelta

BASE = "https://anc.apm.activecommunities.com/sanjoseparksandrec"
RESOURCES = [
    (257, "North"),   # Mise Soccer Field North (Half)
    (648, "South"),   # Mise Soccer Field South (Half)
    (258, "Full"),    # Mise Softball Field (Full Field)
]
NAMES = {str(r): n for r, n in RESOURCES}
DAYS_AHEAD = 60
CHUNK_DAYS = 40  # the API refuses ranges longer than 44 days

# 每天抓取的时刻（本地时间的整点）。可用 MISE_RUN_HOURS=11,23 覆盖。
RUN_HOURS = sorted({int(h) for h in
                    os.environ.get("MISE_RUN_HOURS", "11,23").split(",") if h.strip()})

HERE = os.path.dirname(os.path.abspath(__file__))
# 数据落盘位置。本地默认跟脚本同目录；Railway 上设 MISE_DATA=/data 指向挂载的 Volume。
STORE = os.environ.get("MISE_DATA", HERE)
DATA = os.path.join(STORE, "data")
HIST = os.path.join(STORE, "history.csv")
HTML = os.path.join(STORE, "index.html")

STATUS = {0: "bookable", 5: "past", 7: "too-soon", 8: "too-far"}


# ---------- 时段 ----------

def current_slot(now=None):
    """当下所属的抓取时段（最近一个已经到点的计划时刻）。"""
    now = now or datetime.now()
    cands = [datetime.combine(d, dtime(h, 0))
             for d in (now.date(), now.date() - timedelta(days=1))
             for h in RUN_HOURS]
    past = [t for t in cands if t <= now]
    return max(past) if past else min(cands)


def next_slot(now=None):
    now = now or datetime.now()
    cands = [datetime.combine(d, dtime(h, 0))
             for d in (now.date(), now.date() + timedelta(days=1))
             for h in RUN_HOURS]
    return min(t for t in cands if t > now)


def slot_id(slot):
    return slot.strftime("%Y-%m-%d-%H%M")


def slot_path(slot):
    return os.path.join(DATA, f"snapshot-{slot_id(slot)}.json")


# ---------- 抓取 ----------

def fetch(rid, start, end):
    url = (f"{BASE}/rest/reservation/resource/availability/daily/{rid}"
           f"?start_date={start}&end_date={end}&customer_id=0&company_id=0"
           f"&locale=en-US&ui_random={int(time.time() * 1000)}")
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"),
        "Referer": f"{BASE}/reservation/landing/search/detail/{rid}?locale=en-US",
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        payload = json.loads(r.read().decode("utf-8"))
    code = payload.get("headers", {}).get("response_code")
    if code != "0000":
        raise RuntimeError(f"resource {rid} {start}..{end}: "
                           f"{code} {payload.get('headers', {}).get('response_message')}")
    return payload["body"]["details"]["daily_details"]


def fetch_range(rid, first, last):
    """The API caps a request at 44 days, so walk it in chunks."""
    days, cur = [], first
    while cur <= last:
        stop = min(cur + timedelta(days=CHUNK_DAYS - 1), last)
        days += fetch(rid, cur.isoformat(), stop.isoformat())
        cur = stop + timedelta(days=1)
        if cur <= last:
            time.sleep(1)
    return days


def hm(t):
    return t[:5]


def to_min(t):
    h, m = int(t[:2]), int(t[3:5])
    return h * 60 + m


def take_snapshot(slot=None):
    slot = slot or current_slot()
    today = date.today()
    snap = {
        "snapshot_id": slot_id(slot),
        "snapshot_date": today.isoformat(),
        "slot": slot.isoformat(timespec="minutes"),
        "snapshot_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "range": [today.isoformat(), (today + timedelta(days=DAYS_AHEAD)).isoformat()],
        "resources": {},
    }
    for rid, name in RESOURCES:
        days = {}
        for d in fetch_range(rid, today, today + timedelta(days=DAYS_AHEAD)):
            days[d["date"]] = {
                "status": d["status"],
                "free": [[hm(t["start_time"]), hm(t["end_time"])]
                         for t in d.get("times", []) if t.get("available")],
            }
        snap["resources"][str(rid)] = {"name": name, "days": days}
        time.sleep(1)
    return snap


# ---------- 存储 ----------

def save_snapshot(snap):
    os.makedirs(DATA, exist_ok=True)
    path = os.path.join(DATA, f"snapshot-{snap['snapshot_id']}.json")
    with open(path, "w") as f:
        json.dump(snap, f, indent=1)
    return path


def load_snapshots():
    """按时段先后返回全部快照。"""
    if not os.path.isdir(DATA):
        return []
    out = []
    for fn in sorted(os.listdir(DATA)):
        if not (fn.startswith("snapshot-") and fn.endswith(".json")):
            continue
        with open(os.path.join(DATA, fn)) as f:
            s = json.load(f)
        # 兼容早期「一天一份」的文件
        s.setdefault("snapshot_id", fn[9:-5])
        s.setdefault("snapshot_date", s["snapshot_id"][:10])
        out.append(s)
    return sorted(out, key=lambda s: s["snapshot_id"])


def write_history(snaps):
    """每次都从全部快照重建 —— 永远跟 data/ 一致，也免去格式迁移。"""
    cols = ["snapshot_id", "snapshot_date", "resource_id", "resource_name",
            "target_date", "status", "free_slots", "free_minutes"]
    with open(HIST, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for s in snaps:
            for rid, rdata in s["resources"].items():
                for tdate in sorted(rdata["days"]):
                    d = rdata["days"][tdate]
                    w.writerow({
                        "snapshot_id": s["snapshot_id"],
                        "snapshot_date": s["snapshot_date"],
                        "resource_id": rid,
                        "resource_name": NAMES.get(rid, rdata["name"]),
                        "target_date": tdate,
                        "status": STATUS.get(d["status"], str(d["status"])),
                        "free_slots": "|".join(f"{a}-{b}" for a, b in d["free"]),
                        "free_minutes": sum(to_min(b) - to_min(a) for a, b in d["free"]),
                    })


# ---------- 视图 ----------

def merge(minutes):
    out = []
    for m in sorted(minutes):
        if out and m == out[-1][1]:
            out[-1][1] = m + 1
        else:
            out.append([m, m + 1])
    return [[f"{a // 60:02d}:{a % 60:02d}", f"{b // 60:02d}:{b % 60:02d}"] for a, b in out]


def free_minutes(free):
    s = set()
    for a, b in free:
        s.update(range(to_min(a), to_min(b)))
    return s


def nice(sid):
    """2026-09-12-1100 → 09-12 11:00"""
    return f"{sid[5:10]} {sid[11:13]}:{sid[13:15]}" if len(sid) >= 15 else sid


def build_view(snaps):
    today = date.today()
    latest = snaps[-1]
    prev = snaps[-2] if len(snaps) > 1 else None

    last_visible = {}
    for s in snaps:
        for rid, rdata in s["resources"].items():
            for tdate, d in rdata["days"].items():
                if d["status"] == 0:
                    last_visible.setdefault(rid, {})[tdate] = {
                        "snap": s["snapshot_date"], "free": d["free"]}

    changes = []
    if prev:
        for rid, rdata in latest["resources"].items():
            pdays = prev["resources"].get(rid, {}).get("days", {})
            for tdate, d in sorted(rdata["days"].items()):
                if tdate < today.isoformat() or d["status"] != 0:
                    continue
                p = pdays.get(tdate)
                if not p or p["status"] != 0:
                    continue
                now_m, was_m = free_minutes(d["free"]), free_minutes(p["free"])
                booked, freed = merge(was_m - now_m), merge(now_m - was_m)
                if booked or freed:
                    changes.append({"rid": rid, "date": tdate,
                                    "booked": booked, "freed": freed})

    return {
        "generated": latest["snapshot_at"],
        "today": today.isoformat(),
        "daysAhead": DAYS_AHEAD,
        "runCount": len(snaps),
        "dayCount": len({s["snapshot_date"] for s in snaps}),
        "firstSnapshot": snaps[0]["snapshot_date"],
        "latestLabel": nice(latest["snapshot_id"]),
        "prevLabel": nice(prev["snapshot_id"]) if prev else None,
        "runHours": RUN_HOURS,
        "resources": [{"id": str(r), "name": n} for r, n in RESOURCES],
        "latest": {rid: rd["days"] for rid, rd in latest["resources"].items()},
        "lastVisible": last_visible,
        "changes": changes,
    }


def build_html(view):
    tpl = open(os.path.join(HERE, "template.html")).read()
    with open(HTML, "w") as f:
        f.write(tpl.replace("/*__DATA__*/null", json.dumps(view, separators=(",", ":"))))


def run_once(slot=None):
    """抓一次 + 重建 CSV + 重新生成页面。"""
    snap = take_snapshot(slot)
    save_snapshot(snap)
    snaps = load_snapshots()
    write_history(snaps)
    build_html(build_view(snaps))
    return snaps


if __name__ == "__main__":
    snaps = run_once()
    print(f"{len(snaps)} 份快照（{len({s['snapshot_date'] for s in snaps})} 天）→ {HTML}")
