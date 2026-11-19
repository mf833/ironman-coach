"""Run insights: plain math on what your watch recorded. No AI.

For each run:
  - time in each heart-rate zone, and whether that matched the plan
  - heart-rate drift (aerobic decoupling): did your heart rate creep up while pace stayed the same?
  - pace, heart rate, cadence, fastest and slowest splits

Across runs:
  - easy-run efficiency: how fast you run at the same heart rate, now vs a month ago.
    That's real fitness, separate from just finishing sessions.
"""
from __future__ import annotations

from datetime import date, timedelta
from statistics import mean, median

from .zones import zones_in

M_PER_MI, M_PER_KM = 1609.34, 1000.0


def normalize_zone_secs(raw) -> list[float] | None:
    """Garmin hrTimeInZones list or intervals.icu icu_hr_zone_times -> 5 numbers (Z1..Z5)."""
    if not raw:
        return None
    if isinstance(raw, list) and raw and isinstance(raw[0], dict):
        z = [0.0] * 5
        for r in raw:
            n = int(r.get("zoneNumber", 0))
            if 1 <= n <= 5:
                z[n - 1] += float(r.get("secsInZone") or 0)
        return z
    vals = [float(x or 0) for x in raw]
    if len(vals) > 5:  # intervals.icu often uses 7 zones; fold the top ones into Z5
        vals = vals[:4] + [sum(vals[4:])]
    return (vals + [0.0] * 5)[:5]


def normalize_laps(raw) -> list[dict]:
    laps = (raw or {}).get("lapDTOs") or (raw or {}).get("laps") or []
    out = []
    for l in laps:
        m = l.get("distance") or l.get("distance_meters") or 0
        s = l.get("duration") or l.get("duration_seconds") or 0
        hr = l.get("averageHR") or l.get("avg_hr_bpm")
        cad = l.get("averageRunCadence") or l.get("avg_cadence")
        if m and s:
            out.append({"m": float(m), "s": float(s), "hr": hr, "cad": cad})
    return out


def decoupling_from_laps(laps: list[dict]) -> float | None:
    """Pace:HR drift between the first and second half, in %. Positive = HR rose relative to pace."""
    laps = [l for l in laps if l.get("hr")]
    total = sum(l["s"] for l in laps)
    if total < 30 * 60 or len(laps) < 2:
        return None
    half, t = total / 2, 0.0
    a, b = [], []
    for l in laps:
        (a if t + l["s"] / 2 <= half else b).append(l)
        t += l["s"]
    if not a or not b:
        return None

    def ef(group):
        dist, secs = sum(l["m"] for l in group), sum(l["s"] for l in group)
        hr = sum(l["hr"] * l["s"] for l in group) / secs
        return (dist / secs) / hr

    e1, e2 = ef(a), ef(b)
    return round((e1 - e2) / e1 * 100, 1)


def fmt_pace(sec_per_unit: float) -> str:
    sec = int(round(sec_per_unit))
    return f"{sec // 60}:{sec % 60:02d}"


def run_insight(a: dict, detail: dict | None, session=None, units: str = "mi") -> dict:
    """One run's report card."""
    unit_m = M_PER_MI if units == "mi" else M_PER_KM
    detail = detail or {}
    zone_secs = detail.get("zone_secs")
    laps = detail.get("laps") or []
    secs = a["minutes"] * 60
    out = {"id": a["id"], "date": a["date"], "name": a["name"], "minutes": a["minutes"],
           "dist": round(a["meters"] / unit_m, 2) if a["meters"] else None, "units": units,
           "pace": fmt_pace(secs / (a["meters"] / unit_m)) if a["meters"] else None,
           "avg_hr": a.get("avg_hr"), "zone_pct": None, "planned": None, "verdict": [], "decoupling": None}
    cad = [l["cad"] for l in laps if l.get("cad")]
    if cad:
        c = sum(cad) / len(cad)
        out["cadence"] = round(c * 2 if c < 120 else c)  # strides/min -> steps/min
    if laps:
        paces = [(l["s"] / (l["m"] / unit_m), i + 1) for i, l in enumerate(laps) if l["m"] > unit_m * 0.5]
        if paces:
            out["fastest"] = (fmt_pace(min(paces)[0]), min(paces)[1])
            out["slowest"] = (fmt_pace(max(paces)[0]), max(paces)[1])
    dec = detail.get("decoupling")
    out["decoupling"] = round(dec, 1) if isinstance(dec, (int, float)) else decoupling_from_laps(laps)

    if zone_secs and sum(zone_secs):
        tot = sum(zone_secs)
        out["zone_pct"] = [round(100 * z / tot) for z in zone_secs]
    if session is not None:
        planned = zones_in(session.detail) or ([1, 2] if session.kind in ("easy", "long", "recovery", "brick") else [])
        out["planned"] = planned
        out["session_kind"] = session.kind
        out["session_title"] = session.title
        if out["zone_pct"] and planned and session.kind in ("easy", "long", "recovery", "brick"):
            top = max(planned)
            above = sum(out["zone_pct"][top:])
            inside = sum(out["zone_pct"][z - 1] for z in planned)
            out["above_pct"], out["in_target_pct"] = above, inside
            if above >= 25:
                out["verdict"].append(f"Planned Z{min(planned)}-Z{top}, but {above}% was above Z{top}. "
                                      "This easy run was too hard: slow down until it feels conversational.")
            else:
                out["verdict"].append(f"Planned Z{min(planned)}-Z{top}: {inside}% in target. Nicely controlled.")
    d = out["decoupling"]
    if d is not None and a["minutes"] >= 45:
        if d < 0:
            out["verdict"].append(f"Heart-rate drift {d}%: negative, so you got faster at the same effort. Great pacing.")
        elif d < 5:
            out["verdict"].append(f"Heart-rate drift {d}%: under 5%, so your aerobic engine held steady.")
        elif d < 10:
            out["verdict"].append(f"Heart-rate drift {d}%: moderate. Normal for long or hot runs.")
        else:
            out["verdict"].append(f"Heart-rate drift {d}%: high. Usually starting too fast, under-fueling, or heat.")
    return out


def recent_insights(activities: list, details: dict, statuses: dict, today: date, units="mi", days=42) -> list[dict]:
    by_act = {}
    for st in statuses.values():
        for a in st.activities:
            by_act[a["id"]] = st.session
    lo = (today - timedelta(days=days)).isoformat()
    runs = [a for a in activities if a["sport"] == "run" and a["date"] >= lo and a["minutes"] >= 10]
    runs.sort(key=lambda a: a["date"], reverse=True)
    return [run_insight(a, details.get(str(a["id"])), by_act.get(a["id"]), units) for a in runs]


def easy_efficiency(insights: list[dict], today: date) -> dict | None:
    """Pace at the same heart rate on easy runs: last 2 weeks vs 3-6 weeks ago."""
    easy = [i for i in insights if i.get("avg_hr") and i.get("dist") and i["minutes"] >= 20 and i.get("zone_pct")
            and (i["zone_pct"][0] + i["zone_pct"][1]) >= 60]
    if not easy:
        return None

    def ef(i):  # distance per minute per beat
        return (i["dist"] / i["minutes"]) / i["avg_hr"]

    cut = (today - timedelta(days=14)).isoformat()
    now = [ef(i) for i in easy if i["date"] >= cut]
    then = [ef(i) for i in easy if i["date"] < cut]
    ref_hr = round(median(i["avg_hr"] for i in easy))
    pace_at = lambda e: fmt_pace(60 / (e * ref_hr))
    out = {"ref_hr": ref_hr, "runs": len(easy), "units": easy[0]["units"]}
    if now:
        out["now"] = pace_at(mean(now))
    if then:
        out["then"] = pace_at(mean(then))
    if now and then:
        out["change_pct"] = round((mean(now) / mean(then) - 1) * 100, 1)
    return out
