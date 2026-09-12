#!/usr/bin/env python3
"""Mise Park (San Jose PRNS) availability snapshotter.

Runs once a day, records what the reservation site currently shows for the
next N days, and regenerates index.html so you can see history that the
site itself throws away (dates inside the 4-day booking blackout).
"""
import csv, json, os, time, urllib.request
from datetime import date, datetime, timedelta

BASE = "https://anc.apm.activecommunities.com/sanjoseparksandrec"
RESOURCES = [
    (257, "Soccer Field North (Half)"),
    (648, "Soccer Field South (Half)"),
    (258, "Softball Field (Full Field)"),
]
DAYS_AHEAD = 60
CHUNK_DAYS = 40  # the API refuses ranges longer than 44 days
OPEN_START_MIN, OPEN_END_MIN = 8 * 60, 22 * 60

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
HIST = os.path.join(HERE, "history.csv")
HTML = os.path.join(HERE, "index.html")

STATUS = {0: "bookable", 5: "past", 7: "too-soon", 8: "too-far"}


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


def take_snapshot():
    today = date.today()
    start = today.isoformat()
    end = (today + timedelta(days=DAYS_AHEAD)).isoformat()
    snap = {
        "snapshot_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "snapshot_date": today.isoformat(),
        "range": [start, end],
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


def save_snapshot(snap):
    os.makedirs(DATA, exist_ok=True)
    path = os.path.join(DATA, f"snapshot-{snap['snapshot_date']}.json")
    with open(path, "w") as f:
        json.dump(snap, f, indent=1)
    return path


def update_history(snap):
    rows = {}
    if os.path.exists(HIST):
        with open(HIST, newline="") as f:
            for r in csv.DictReader(f):
                rows[(r["snapshot_date"], r["resource_id"], r["target_date"])] = r
    for rid, rdata in snap["resources"].items():
        for tdate, d in rdata["days"].items():
            rows[(snap["snapshot_date"], rid, tdate)] = {
                "snapshot_date": snap["snapshot_date"],
                "resource_id": rid,
                "resource_name": rdata["name"],
                "target_date": tdate,
                "status": STATUS.get(d["status"], str(d["status"])),
                "free_slots": "|".join(f"{a}-{b}" for a, b in d["free"]),
                "free_minutes": str(sum(to_min(b) - to_min(a) for a, b in d["free"])),
            }
    cols = ["snapshot_date", "resource_id", "resource_name", "target_date",
            "status", "free_slots", "free_minutes"]
    with open(HIST, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for k in sorted(rows):
            w.writerow(rows[k])


def load_snapshots():
    if not os.path.isdir(DATA):
        return []
    out = []
    for fn in sorted(os.listdir(DATA)):
        if fn.startswith("snapshot-") and fn.endswith(".json"):
            with open(os.path.join(DATA, fn)) as f:
                out.append(json.load(f))
    return out


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
        "snapshotCount": len(snaps),
        "firstSnapshot": snaps[0]["snapshot_date"],
        "prevSnapshot": prev["snapshot_date"] if prev else None,
        "resources": [{"id": str(r), "name": n} for r, n in RESOURCES],
        "latest": {rid: rd["days"] for rid, rd in latest["resources"].items()},
        "lastVisible": last_visible,
        "changes": changes,
    }


def build_html(view):
    tpl = open(os.path.join(HERE, "template.html")).read()
    with open(HTML, "w") as f:
        f.write(tpl.replace("/*__DATA__*/null", json.dumps(view, separators=(",", ":"))))


if __name__ == "__main__":
    snap = take_snapshot()
    print("saved", save_snapshot(snap))
    update_history(snap)
    snaps = load_snapshots()
    build_html(build_view(snaps))
    print(f"{len(snaps)} snapshot(s); wrote {HTML}")
