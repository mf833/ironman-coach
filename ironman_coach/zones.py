"""Turn "Z2" into numbers you can actually ride or run at."""
from __future__ import annotations

import re

# Coggan power zones, % of FTP (the standard most plans, Zwift and Garmin use).
POWER = {1: (0, 55), 2: (56, 75), 3: (76, 90), 4: (91, 105), 5: (106, 120)}
FEEL = {
    1: ("RPE 1-2", "very easy, could do this all day"),
    2: ("RPE 3-4", "easy, full sentences"),
    3: ("RPE 5-6", "steady, short sentences"),
    4: ("RPE 7-8", "hard, a few words at a time"),
    5: ("RPE 9", "very hard, no talking"),
}


def normalize_hr_zones(raw) -> dict:
    """Garmin zone floors -> {"cycling": {1: (lo, hi), ...}, "running": {...}, "default": {...}}."""
    out = {}
    for prof in raw or []:
        floors = [prof.get(f"zone{i}Floor") for i in range(1, 6)]
        if not all(floors):
            continue
        top = prof.get("maxHeartRateUsed") or floors[-1] + 15
        zones = {i + 1: (floors[i], (floors[i + 1] - 1) if i < 4 else top) for i in range(5)}
        out[(prof.get("sport") or "DEFAULT").lower()] = zones
    return out


def normalize_ftp(raw) -> int | None:
    items = raw if isinstance(raw, list) else [raw]
    for it in items:
        if not isinstance(it, dict):
            continue
        for k, v in it.items():
            if "functionalthresholdpower" in k.lower().replace("_", "") and isinstance(v, (int, float)):
                return int(v)
    return None


def zones_in(text: str) -> list[int]:
    """Which zones a workout description mentions: 'Z1 building to Z2', 'Z3-Z4', 'Z2/Z3'."""
    found = set()
    for m in re.finditer(r"Z(\d)(?:\s*(?:-|/|to|building to|increasing to|building into)\s*Z?(\d))?", text):
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else a
        found.update(range(min(a, b), max(a, b) + 1))
    return sorted(z for z in found if 1 <= z <= 5)


def fmt_pace(sec: float) -> str:
    sec = int(round(sec))
    return f"{sec // 60}:{sec % 60:02d}"


def zone_rows(sport: str, zones: list[int], ftp: int | None, hr: dict, swim_t: float | None) -> list[tuple]:
    """Rows of (zone, target, heart rate, feel) for the zones a session uses."""
    hr_prof = hr.get({"bike": "cycling", "run": "running"}.get(sport, "default")) or hr.get("default") or {}
    rows = []
    for z in zones:
        rpe, feel = FEEL[z]
        target = ""
        if sport == "bike" and ftp:
            lo, hi = POWER[z]
            target = f"{round(ftp * lo / 100)}-{round(ftp * hi / 100)} W" if lo else f"under {round(ftp * hi / 100)} W"
        if sport == "swim" and swim_t:
            off = {1: (15, 25), 2: (8, 15), 3: (3, 8), 4: (0, 3), 5: (-5, 0)}[z]
            target = f"{fmt_pace(swim_t + off[0])}-{fmt_pace(swim_t + off[1])} /100yd"
        lo_hi = hr_prof.get(z)
        bpm = f"{lo_hi[0]}-{lo_hi[1]} bpm" if lo_hi and sport != "swim" else ""
        rows.append((f"Z{z}", target, bpm, f"{rpe} · {feel}"))
    return rows
