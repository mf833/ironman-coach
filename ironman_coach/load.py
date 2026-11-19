"""Training load and fatigue: zone-weighted minutes, smoothed into fitness and fatigue.

load of a session   = sum over zones of (minutes in zone i) x i          (Edwards TRIMP)
fatigue  (ATL) today = ATL yesterday + (load today - ATL yesterday) / 7  (7-day average)
fitness  (CTL) today = CTL yesterday + (load today - CTL yesterday) / 42 (42-day average)
form     (TSB)       = CTL - ATL
ratio                = ATL / CTL
"""
from __future__ import annotations

from datetime import date, timedelta


def session_load(a: dict, detail: dict | None, hr_zones: dict) -> float:
    zs = (detail or {}).get("zone_secs")
    if zs and sum(zs):
        return round(sum((s / 60) * (i + 1) for i, s in enumerate(zs)), 1)
    zone = 2  # no zone data (e.g. most swims): count it as steady Z2
    hr = a.get("avg_hr")
    prof = hr_zones.get({"bike": "cycling", "run": "running"}.get(a["sport"], "default")) or hr_zones.get("default")
    if hr and prof:
        for z in range(5, 0, -1):
            lo = prof.get(str(z), prof.get(z, [0]))[0]
            if hr >= lo:
                zone = z
                break
    if a["sport"] == "strength":
        zone = 2
    return round(a["minutes"] * zone, 1)


def fatigue_series(activities: list, details: dict, hr_zones: dict, today: date, days: int = 90) -> dict:
    daily = {}
    for a in activities:
        daily[a["date"]] = daily.get(a["date"], 0) + session_load(a, details.get(str(a["id"])), hr_zones)
    start = today - timedelta(days=days)
    atl = ctl = 0.0
    first = min(daily) if daily else today.isoformat()
    history_days = (today - date.fromisoformat(first)).days if daily else 0
    d = start
    while d <= today:
        load = daily.get(d.isoformat(), 0)
        atl += (load - atl) / 7
        ctl += (load - ctl) / 42
        d += timedelta(days=1)
    return {"atl": round(atl, 1), "ctl": round(ctl, 1), "tsb": round(ctl - atl, 1),
            "ratio": round(atl / ctl, 2) if ctl > 0 else None, "history_days": history_days,
            "last7": round(sum(v for k, v in daily.items() if k > (today - timedelta(days=7)).isoformat()), 0)}
