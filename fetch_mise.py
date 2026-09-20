#!/usr/bin/env python3
"""Mise Park (San Jose PRNS) availability snapshotter.

每个「时段」抓一次（默认每天 11:00 和 23:00），记录预订网站当下显示的占用情况，
并重新生成 index.html —— 补上网站因为 4 天封锁规则而不再显示的那部分历史。
"""
import csv, json, os, time, urllib.request
from datetime import date, datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

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

# 球场所在时区。**不要**依赖 TZ 环境变量 + time.tzset()：
# Railway 的运行镜像里没有系统 tzdata，tzset() 会静默回落到 UTC，
# 于是"今天"和 11:00/23:00 全部按 UTC 算（差 7 小时）。
# 这里显式用 ZoneInfo，并在 requirements.txt 里装 tzdata 包自带数据库，
# 跟基础镜像无关；夏令时切换（2026-11-01 PDT→PST）也会自动跟上。
TZINFO = ZoneInfo(os.environ.get("MISE_TZ", "America/Los_Angeles"))


def now_local():
    return datetime.now(TZINFO)


def today_local():
    return now_local().date()


HERE = os.path.dirname(os.path.abspath(__file__))
# 数据落盘位置。本地默认跟脚本同目录；Railway 上设 MISE_DATA=/data 指向挂载的 Volume。
STORE = os.environ.get("MISE_DATA", HERE)
DATA = os.path.join(STORE, "data")
HIST = os.path.join(STORE, "history.csv")
CHANGES = os.path.join(STORE, "changes.csv")
CHANGES_STATE = os.path.join(STORE, "changes_state.json")
HTML = os.path.join(STORE, "index.html")

STATUS = {0: "bookable", 5: "past", 7: "too-soon", 8: "too-far"}


# ---------- 时段 ----------

def _slots(around):
    """给定日期前后各一天的全部计划时刻（带时区，夏令时自动正确）。"""
    return [datetime.combine(d, dtime(h, 0), tzinfo=TZINFO)
            for d in (around - timedelta(days=1), around, around + timedelta(days=1))
            for h in RUN_HOURS]


def current_slot(now=None):
    """当下所属的抓取时段（最近一个已经到点的计划时刻）。"""
    now = now or now_local()
    past = [t for t in _slots(now.date()) if t <= now]
    return max(past) if past else min(_slots(now.date()))


def next_slot(now=None):
    now = now or now_local()
    return min(t for t in _slots(now.date()) if t > now)


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
    today = today_local()
    snap = {
        "snapshot_id": slot_id(slot),
        "snapshot_date": today.isoformat(),
        "slot": slot.isoformat(timespec="minutes"),
        "snapshot_at": now_local().isoformat(timespec="seconds"),
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
    """2026-09-12-1100 → 09-12 11:00（场次标签）"""
    return f"{sid[5:10]} {sid[11:13]}:{sid[13:15]}" if len(sid) >= 15 else sid


def at(snap):
    """实际抓取时刻 → 09-13 00:07。

    跟场次标签可能差很远：容器重启后会补抓错过的场次，
    那时"场次 09-12 23:00"实际是 09-13 00:07 跑的。页面要显示后者。
    """
    ts = snap.get("snapshot_at") or ""
    return ts[5:16].replace("T", " ") if len(ts) >= 16 else nice(snap["snapshot_id"])


# ---------- 变更日志 ----------

CHANGE_COLS = ["noticed_at", "from_slot", "to_slot", "resource_id", "resource_name",
               "target_date", "kind", "start", "end"]


def diff_snaps(prev, cur):
    """两份相邻快照之间，每个场地每个日期的占用变化。"""
    rows = []
    for rid, rdata in cur["resources"].items():
        pdays = prev["resources"].get(rid, {}).get("days", {})
        for tdate in sorted(rdata["days"]):
            d, p = rdata["days"][tdate], pdays.get(tdate)
            # 两边都得是"可订"状态才有可比性；进出封锁期不算预订变化
            if not p or d["status"] != 0 or p["status"] != 0:
                continue
            if d["free"] == p["free"]:
                continue                      # 绝大多数日期在这里短路，很快
            now_m, was_m = free_minutes(d["free"]), free_minutes(p["free"])
            for kind, ivs in (("booked", merge(was_m - now_m)),
                              ("freed", merge(now_m - was_m))):
                for a, b in ivs:
                    rows.append({
                        "noticed_at": cur.get("snapshot_at", ""),
                        "from_slot": prev["snapshot_id"],
                        "to_slot": cur["snapshot_id"],
                        "resource_id": rid,
                        "resource_name": NAMES.get(rid, rdata["name"]),
                        "target_date": tdate,
                        "kind": kind, "start": a, "end": b,
                    })
    return rows


def update_changes(snaps):
    """把新出现的相邻快照对的变化追加进 changes.csv。

    只算没算过的对，所以每次抓取只做一次 diff，不会随历史变长而变慢。
    用单独的 state 文件记进度 —— 某一对"没有任何变化"时不会写出任何行，
    光看 CSV 无法区分"算过但没变化"和"还没算"。
    """
    last_done = None
    if os.path.exists(CHANGES) and os.path.exists(CHANGES_STATE):
        try:
            last_done = json.load(open(CHANGES_STATE)).get("last_processed")
        except Exception:
            last_done = None

    pairs = list(zip(snaps, snaps[1:]))
    if last_done:
        pairs = [(a, b) for a, b in pairs if b["snapshot_id"] > last_done]

    new_rows = []
    for prev, cur in pairs:
        new_rows += diff_snaps(prev, cur)

    fresh = not (os.path.exists(CHANGES) and last_done)
    with open(CHANGES, "w" if fresh else "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CHANGE_COLS)
        if fresh:
            w.writeheader()
        for r in new_rows:
            w.writerow(r)
    if len(snaps) > 1:
        json.dump({"last_processed": snaps[-1]["snapshot_id"]}, open(CHANGES_STATE, "w"))
    return len(new_rows)


def load_change_log(max_events=60, max_items=800):
    """读回变更日志，按"第几次抓取发现的"分组，最新在前。"""
    if not os.path.exists(CHANGES):
        return []
    with open(CHANGES, newline="") as f:
        rows = list(csv.DictReader(f))
    by_slot = {}
    for r in rows:
        g = by_slot.setdefault(r["to_slot"],
                               {"at": r["noticed_at"], "from": r["from_slot"], "items": {}})
        key = (r["resource_id"], r["target_date"])
        it = g["items"].setdefault(key, {"rid": r["resource_id"],
                                         "date": r["target_date"], "booked": [], "freed": []})
        it[r["kind"]].append([r["start"], r["end"]])
    out, used = [], 0
    for slot in sorted(by_slot, reverse=True)[:max_events]:
        g = by_slot[slot]
        items = sorted(g["items"].values(), key=lambda x: (x["date"], x["rid"]))
        if used + len(items) > max_items and out:
            break
        used += len(items)
        ts = g["at"]
        out.append({"at": ts[5:16].replace("T", " ") if len(ts) >= 16 else nice(slot),
                    "from": nice(g["from"]), "to": nice(slot), "items": items})
    return out


def build_view(snaps):
    today = today_local()
    latest = snaps[-1]
    prev = snaps[-2] if len(snaps) > 1 else None

    last_visible = {}
    for s in snaps:
        for rid, rdata in s["resources"].items():
            for tdate, d in rdata["days"].items():
                if d["status"] == 0:
                    last_visible.setdefault(rid, {})[tdate] = {
                        "snap": s["snapshot_date"], "free": d["free"]}

    return {
        "generated": latest["snapshot_at"],
        "today": today.isoformat(),
        "daysAhead": DAYS_AHEAD,
        "runCount": len(snaps),
        # 按场次日期算，跟文件名一致（snapshot_date 是抓取当天，跨零点补抓时会对不上）
        "dayCount": len({s["snapshot_id"][:10] for s in snaps}),
        "firstSnapshot": snaps[0]["snapshot_id"][:10],
        "latestAt": at(latest),
        "prevAt": at(prev) if prev else None,
        "latestSlot": nice(latest["snapshot_id"]),
        "prevSlot": nice(prev["snapshot_id"]) if prev else None,
        "runHours": RUN_HOURS,
        "resources": [{"id": str(r), "name": n} for r, n in RESOURCES],
        "latest": {rid: rd["days"] for rid, rd in latest["resources"].items()},
        "lastVisible": last_visible,
        "changeLog": load_change_log(),
        "changeTotal": sum(1 for _ in open(CHANGES)) - 1 if os.path.exists(CHANGES) else 0,
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
    update_changes(snaps)
    build_html(build_view(snaps))
    return snaps


if __name__ == "__main__":
    snaps = run_once()
    print(f"{len(snaps)} 份快照（{len({s['snapshot_date'] for s in snaps})} 天）→ {HTML}")
