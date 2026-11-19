"""Garmin Connect sync.

Uses the `garminconnect` library with the tokens in ~/.garminconnect (the same
place your Garmin MCP keeps them). Everything is normalized into small dicts so
the rules engine never touches Garmin's raw formats.
"""
from __future__ import annotations

import getpass
import os
from datetime import date, datetime, timedelta

TOKENSTORE = os.path.expanduser(os.environ.get("GARMINTOKENS", "~/.garminconnect"))

SPORT_MAP = {
    "swim": ("swim", "lap_swimming", "open_water_swimming"),
    "bike": ("cycl", "ride", "biking", "bike", "spinning", "recumbent"),
    "run": ("run",),
    "strength": ("strength", "hiit"),
}


def sport_of(type_key: str) -> str | None:
    t = (type_key or "").lower()
    for sport, keys in SPORT_MAP.items():
        if any(k in t for k in keys):
            return sport
    return None


def normalize_activity(a: dict) -> dict | None:
    type_key = (a.get("activityType") or {}).get("typeKey") or a.get("type", "")
    sport = sport_of(type_key)
    if sport is None:
        return None
    start = a.get("startTimeLocal") or a.get("start_time") or ""
    return {
        "id": a.get("activityId") or a.get("id"),
        "name": a.get("activityName") or a.get("name") or type_key,
        "type": type_key,
        "sport": sport,
        "date": start[:10],
        "minutes": round((a.get("duration") or a.get("duration_seconds") or 0) / 60, 1),
        "meters": round(a.get("distance") or a.get("distance_meters") or 0, 1),
        "avg_hr": a.get("averageHR") or a.get("avg_hr_bpm"),
    }


def normalize_day(day: str, hrv: dict | None, summary: dict | None, sleep: dict | None) -> dict:
    out = {"date": day}
    s = (hrv or {}).get("hrvSummary") or {}
    base = s.get("baseline") or {}
    out["hrv"] = {
        "last_night": s.get("lastNightAvg"),
        "weekly_avg": s.get("weeklyAvg"),
        "balanced_low": base.get("balancedLow"),
        "balanced_upper": base.get("balancedUpper"),
        "low_upper": base.get("lowUpper"),
        "status": s.get("status"),
    } if s else None
    summary = summary or {}
    out["rhr"] = summary.get("restingHeartRate")
    out["rhr_7d"] = summary.get("lastSevenDaysAvgRestingHeartRate")
    secs = ((sleep or {}).get("dailySleepDTO") or {}).get("sleepTimeSeconds") or summary.get("sleepingSeconds")
    out["sleep_h"] = round(secs / 3600, 2) if secs else None
    return out


def connect(interactive: bool = False):
    from garminconnect import Garmin  # imported lazily so tests don't need it

    if interactive:
        email = input("Garmin email: ").strip()
        password = getpass.getpass("Garmin password: ")
        api = Garmin(email=email, password=password, prompt_mfa=lambda: input("MFA code: ").strip())
        os.makedirs(TOKENSTORE, exist_ok=True)
        api.login(TOKENSTORE)
        return api
    api = Garmin()
    api.login(TOKENSTORE)
    return api


def sync(days_back: int = 42, api=None) -> dict:
    """Pull recent activities and daily recovery data. Returns the cache dict."""
    api = api or connect()
    today = date.today()
    start = today - timedelta(days=days_back)
    raw = api.get_activities_by_date(start.isoformat(), today.isoformat())
    activities = [x for x in (normalize_activity(a) for a in raw or []) if x]

    days = {}
    for i in range(8):  # last week of recovery data is enough for the rules
        d = (today - timedelta(days=i)).isoformat()
        def safe(fn):
            try:
                return fn(d)
            except Exception:
                return None
        days[d] = normalize_day(d, safe(api.get_hrv_data), safe(api.get_user_summary), safe(api.get_sleep_data))

    from .zones import normalize_ftp, normalize_hr_zones
    try:
        hr_zones = normalize_hr_zones(api.get_heart_rate_zones())
    except Exception:
        hr_zones = {}
    try:
        ftp = normalize_ftp(api.get_cycling_ftp())
    except Exception:
        ftp = None

    return {
        "hr_zones": {k: {str(z): v for z, v in zs.items()} for k, zs in hr_zones.items()},
        "garmin_ftp": ftp,
        "synced_at": datetime.now().isoformat(timespec="seconds"),
        "activities": sorted(activities, key=lambda a: a["date"]),
        "days": days,
    }
