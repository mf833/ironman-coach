"""`ironman demo`: try everything with made-up data, no watch needed.

Builds a demo runner 6 weeks into the 16-week marathon plan: easy pace improving,
a missed workout, easy runs that drifted too hard, steady long runs, and a short,
low-HRV night. Lives in its own folder, so it never touches your real data.
"""
from __future__ import annotations

import json
import random
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

HOME = Path.home() / ".ironman-demo"
ROOT = Path(__file__).resolve().parent.parent
RUN_ZONES = {"1": [0, 129], "2": [130, 150], "3": [151, 163], "4": [164, 175], "5": [176, 195]}


def build(today: date | None = None) -> Path:
    from . import plan as P
    rnd = random.Random(7)
    today = today or date.today()
    monday = today - timedelta(days=today.weekday())
    race = monday + timedelta(weeks=9, days=6)  # week 7 of 16 is this week; race is the Sunday of week 16
    (HOME / "plans").mkdir(parents=True, exist_ok=True)
    (HOME / "data").mkdir(exist_ok=True)
    shutil.copyfile(ROOT / "plans" / "marathon-16wk.csv", HOME / "plans" / "my-plan.csv")
    (HOME / "config.json").write_text(json.dumps({
        "race": {"name": "Demo City Marathon", "date": race.isoformat()}, "plan": "plans/my-plan.csv",
        "units": "mi", "baseline": {"bike_min": 60, "run_min": 60, "swim_yd": 1000}}, indent=2))
    (HOME / "data" / "state.json").unlink(missing_ok=True)

    plan = P.load_plan(HOME / "plans" / "my-plan.csv", race, "Demo City Marathon")
    acts, details = [], {}
    missed = today - timedelta(days=2)
    past = [s for s in plan if s.sport == "run" and s.day < today]
    easy_runs = [s for s in past if s.kind == "easy"]
    too_hard = {s.id for s in easy_runs[-3:-1]}  # two of the last three easy runs ran hot
    for n, s in enumerate(past):
        if s.day == missed:
            continue
        weeks_in = (s.day - P.plan_start()).days / 7
        easy_pace = 12.0 - 0.11 * weeks_in  # min/mi at ~145 bpm, improving
        mins = s.amount * rnd.uniform(0.95, 1.05)
        if s.kind in ("intervals", "test"):
            pace, hr, zones = easy_pace - 1.4, 160, [0.15, 0.35, 0.3, 0.2, 0]
        elif s.id in too_hard:
            pace, hr, zones = easy_pace - 0.9, 158, [0.05, 0.4, 0.45, 0.1, 0]
        else:
            pace, hr, zones = easy_pace + rnd.uniform(-0.15, 0.15), 145, [0.2, 0.75, 0.05, 0, 0]
        miles = mins / pace
        aid = 9_000_000 + n
        acts.append({"id": aid, "name": f"Demo {s.title}", "type": "running", "sport": "run",
                     "date": s.day.isoformat(), "minutes": round(mins, 1), "meters": round(miles * 1609.34, 1),
                     "avg_hr": hr})
        laps, left = [], miles
        drift = 0.03 if s.kind == "long" else 0.05
        i = 0
        while left > 0.3:
            d = min(1.0, left)
            lap_hr = hr * (1 + drift * i / max(1, miles - 1))
            laps.append({"m": d * 1609.34, "s": d * pace * 60, "hr": round(lap_hr), "cad": 166})
            left -= d
            i += 1
        details[str(aid)] = {"zone_secs": [z * mins * 60 for z in zones], "laps": laps}

    # six weeks of steady easy running before the plan, so fitness isn't starting from zero
    d = P.plan_start() - timedelta(days=42)
    k = 0
    while d < P.plan_start():
        if d.weekday() in (1, 3, 6):
            mins = 60 if d.weekday() == 6 else 40
            aid = 8_000_000 + k
            acts.append({"id": aid, "name": "Demo easy run", "type": "running", "sport": "run", "date": d.isoformat(),
                         "minutes": mins, "meters": round(mins / 12.2 * 1609.34, 1), "avg_hr": 145})
            details[str(aid)] = {"zone_secs": [0.2 * mins * 60, 0.8 * mins * 60, 0, 0, 0], "laps": []}
            k += 1
        d += timedelta(days=1)

    days = {}
    for k in range(8):
        d = today - timedelta(days=k)
        short = k == 0
        days[d.isoformat()] = {"date": d.isoformat(),
                               "hrv": {"last_night": 33 if short else 44, "weekly_avg": 41, "balanced_low": 38,
                                       "balanced_upper": 50, "low_upper": 34, "status": "UNBALANCED" if short else "BALANCED"},
                               "rhr": 52, "rhr_7d": 51, "sleep_h": 5.4 if short else 7.6}
    cache = {"source": "demo", "synced_at": datetime.now().isoformat(timespec="seconds"),
             "activities": sorted(acts, key=lambda a: a["date"]), "details": details, "days": days,
             "hr_zones": {"running": RUN_ZONES, "default": RUN_ZONES}, "garmin_ftp": None}
    (HOME / "data" / "garmin_cache.json").write_text(json.dumps(cache, indent=2))
    return HOME
