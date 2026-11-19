"""intervals.icu sync: for Coros, Polar, Suunto, Wahoo, Apple Watch (via HealthFit), Garmin, and more.

Connect your watch to intervals.icu once (free), then copy your athlete ID and API
key from intervals.icu > Settings > Developer Settings. Everything is normalized into
the same shapes the Garmin sync produces.
"""
from __future__ import annotations

import base64
import json
import urllib.request
from datetime import date, datetime, timedelta
from statistics import mean, pstdev

from .insights import normalize_zone_secs

BASE = "https://intervals.icu/api/v1"
TYPES = {"run": ("run",), "bike": ("ride", "cycl"), "swim": ("swim",), "strength": ("weight", "strength")}


def sport_of(t: str) -> str | None:
    t = (t or "").lower()
    for sport, keys in TYPES.items():
        if any(k in t for k in keys):
            return sport
    return None


class Client:
    def __init__(self, athlete_id: str, api_key: str):
        self.athlete = athlete_id.strip()
        self.auth = "Basic " + base64.b64encode(f"API_KEY:{api_key.strip()}".encode()).decode()

    def get(self, path: str, **params):
        q = "&".join(f"{k}={v}" for k, v in params.items())
        req = urllib.request.Request(f"{BASE}{path}" + (f"?{q}" if q else ""),
                                     headers={"Authorization": self.auth, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())


def normalize_activity(a: dict) -> dict | None:
    sport = sport_of(a.get("type", ""))
    if not sport:
        return None
    return {"id": a.get("id"), "name": a.get("name") or a.get("type"), "type": a.get("type"), "sport": sport,
            "date": (a.get("start_date_local") or "")[:10],
            "minutes": round((a.get("moving_time") or a.get("elapsed_time") or 0) / 60, 1),
            "meters": round(a.get("distance") or 0, 1), "avg_hr": a.get("average_heartrate")}


def activity_detail(a: dict) -> dict:
    cad = a.get("average_cadence")
    return {"zone_secs": normalize_zone_secs(a.get("icu_hr_zone_times")), "decoupling": a.get("decoupling"),
            "laps": [], "cadence": cad}


def normalize_wellness(rows: list[dict], today: date) -> dict:
    """intervals.icu wellness rows -> the same per-day shape as the Garmin sync."""
    rows = sorted(rows or [], key=lambda r: r.get("id", ""))
    hrv_hist = [r["hrv"] for r in rows if r.get("hrv")]
    days = {}
    for i, r in enumerate(rows):
        d = r.get("id")
        if not d:
            continue
        prior = [x["hrv"] for x in rows[max(0, i - 28):i] if x.get("hrv")]
        hrv = None
        if r.get("hrv"):
            if len(prior) >= 7:
                m, sd = mean(prior), pstdev(prior) or 1
                hrv = {"last_night": round(r["hrv"]), "weekly_avg": round(mean(prior[-7:])),
                       "balanced_low": round(m - sd), "balanced_upper": round(m + sd), "low_upper": round(m - 2 * sd),
                       "status": None}
            else:
                hrv = {"last_night": round(r["hrv"]), "status": None}
        rhr7 = [x["restingHR"] for x in rows[max(0, i - 7):i] if x.get("restingHR")]
        days[d] = {"date": d, "hrv": hrv, "rhr": r.get("restingHR"),
                   "rhr_7d": round(mean(rhr7)) if rhr7 else None,
                   "sleep_h": round(r["sleepSecs"] / 3600, 2) if r.get("sleepSecs") else None}
    return days


def zones_from_settings(athlete: dict) -> tuple[dict, int | None]:
    """sportSettings -> ({"running": {1: (lo, hi)...}, "cycling": ...}, ftp)."""
    out, ftp = {}, None
    for s in athlete.get("sportSettings") or []:
        types = [t.lower() for t in s.get("types") or []]
        uppers = s.get("hr_zones") or []
        key = "running" if any("run" in t for t in types) else "cycling" if any("ride" in t for t in types) else None
        if any("ride" in t for t in types) and s.get("ftp"):
            ftp = int(s["ftp"])
        if key and len(uppers) >= 5:
            lows = [0] + [u + 1 for u in uppers[:4]]
            top = uppers[-1]
            out[key] = {str(i + 1): [lows[i], uppers[i] if i < 4 else top] for i in range(5)}
    if "running" in out:
        out.setdefault("default", out["running"])
    return out, ftp


def sync(cfg: dict, days_back: int = 90, client: Client | None = None) -> dict:
    ic = cfg.get("intervals") or {}
    client = client or Client(ic["athlete_id"], ic["api_key"])
    today = date.today()
    oldest = (today - timedelta(days=days_back)).isoformat()
    raw = client.get(f"/athlete/{client.athlete}/activities", oldest=oldest, newest=today.isoformat())
    acts, details = [], {}
    for a in raw or []:
        n = normalize_activity(a)
        if n:
            acts.append(n)
            details[str(n["id"])] = activity_detail(a)
    well = client.get(f"/athlete/{client.athlete}/wellness",
                      oldest=(today - timedelta(days=40)).isoformat(), newest=today.isoformat())
    try:
        hr_zones, ftp = zones_from_settings(client.get(f"/athlete/{client.athlete}"))
    except Exception:
        hr_zones, ftp = {}, None
    return {"source": "intervals", "synced_at": datetime.now().isoformat(timespec="seconds"),
            "activities": sorted(acts, key=lambda a: a["date"]), "details": details,
            "days": normalize_wellness(well, today), "hr_zones": hr_zones, "garmin_ftp": ftp}
