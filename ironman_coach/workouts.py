"""Turn a plan session into a Garmin workout (swim/run) or a Zwift .zwo file (bike)."""
from __future__ import annotations

import re
from pathlib import Path
from xml.sax.saxutils import escape

from .plan import Session
from .swimsets import breakdown

YARD = {"unitId": 230, "unitKey": "yard", "factor": 91.44}
SPORT = {"swim": {"sportTypeId": 4, "sportTypeKey": "swimming"},
         "run": {"sportTypeId": 1, "sportTypeKey": "running"}}
STEP = {"warmup": 1, "cooldown": 2, "interval": 3, "recovery": 4, "rest": 5, "repeat": 6, "main": 8}
FREE = {"strokeTypeId": 6, "strokeTypeKey": "free"}
NO_STROKE = {"strokeTypeId": 0}
DRILL = {"drillTypeId": 3, "drillTypeKey": "drill"}


class _Order:
    def __init__(self):
        self.n = 0

    def __call__(self):
        self.n += 1
        return self.n


def _step(order, kind, cond, value=None, desc=None, **extra):
    conds = {"distance": 3, "time": 2, "lap.button": 1, "fixed.rest": 8}
    s = {"type": "ExecutableStepDTO", "stepOrder": order(),
         "stepType": {"stepTypeId": STEP[kind], "stepTypeKey": kind},
         "endCondition": {"conditionTypeId": conds[cond], "conditionTypeKey": cond},
         "endConditionValue": float(value or 0)}
    if desc:
        s["description"] = desc[:255]
    s.update(extra)
    return s


def _repeat(order, n, steps_fn):
    grp = {"type": "RepeatGroupDTO", "stepOrder": order(), "stepType": {"stepTypeId": 6, "stepTypeKey": "repeat"},
           "numberOfIterations": n, "smartRepeat": False, "skipLastRestStep": True,
           "endCondition": {"conditionTypeId": 7, "conditionTypeKey": "iterations"}, "endConditionValue": float(n)}
    grp["workoutSteps"] = steps_fn()
    return grp


def _secs(rest: str) -> int:
    m = re.match(r"(\d+)", rest or "")
    return int(m.group(1)) if m else 0


# ---- swim -------------------------------------------------------------------------
def swim_workout(s: Session, drill_names: list[list[str]]) -> dict:
    """drill_names: for each drills row in order, the drills to use."""
    o = _Order()
    steps = []
    drill_rows = iter(drill_names)
    part_kind = {"Warm-up": "warmup", "Main set": "main", "Cool-down": "cooldown", "Set": "main"}
    current = "main"
    for r in breakdown(s.detail, s.amount)[0]:
        if r["part"]:
            current = part_kind.get(r["part"], "main")
        m = re.match(r"(\d+) x (\d+)", r["set"])
        rest = _secs(r["rest"])
        if "drills" in r["how"]:
            n, d = int(m.group(1)), int(m.group(2))
            names = next(drill_rows, ["Drill"])
            per = max(1, n // len(names))
            for name in names:
                def body(name=name, d=d):
                    return [_step(o, current, "distance", d, f"{name}: 25 drill / 25 easy", strokeType=FREE,
                                  drillType=DRILL, preferredEndConditionUnit=YARD),
                            _step(o, "rest", "fixed.rest", rest or 15, strokeType=NO_STROKE)]
                steps.append(_repeat(o, per, body))
        elif m:
            n, d = int(m.group(1)), int(m.group(2))
            desc = r["how"] if r["how"] not in ("steady", "easy") else None
            def body(d=d, desc=desc, rest=rest):
                inner = [_step(o, current, "distance", d, desc, strokeType=FREE, preferredEndConditionUnit=YARD)]
                inner.append(_step(o, "rest", "fixed.rest", rest, strokeType=NO_STROKE) if rest
                             else _step(o, "rest", "lap.button", strokeType=NO_STROKE))
                return inner
            steps.append(_repeat(o, n, body))
        elif r["set"].startswith("Ladder"):
            for d in [int(x) for x in r["set"].split()[1].split("-")]:
                steps.append(_step(o, current, "distance", d, None, strokeType=FREE, preferredEndConditionUnit=YARD))
                steps.append(_step(o, "rest", "fixed.rest", rest or 20, strokeType=NO_STROKE))
        else:
            steps.append(_step(o, current, "distance", r["yd"], r["how"] if r["how"] != "easy" else None,
                               strokeType=FREE, preferredEndConditionUnit=YARD))
    return {"workoutName": f"{s.day:%b %d} {s.title} {s.amount:,}yd", "description": s.detail[:1000],
            "sportType": SPORT["swim"], "poolLength": 25.0, "poolLengthUnit": YARD,
            "workoutSegments": [{"segmentOrder": 1, "sportType": SPORT["swim"], "workoutSteps": steps}]}


# ---- run & bike structure ------------------------------------------------------------
def structure(detail: str, total_min: int) -> list[tuple] | None:
    """Parse into [(kind, minutes, zone, note)] or repeats ('repeat', n, [(..),(..)]).
    Returns None for sessions that are just time at an easy zone."""
    d = detail
    zone_of = lambda t, default=2: int(re.search(r"Z(\d)", t).group(1)) if re.search(r"Z(\d)", t) else default

    if "TEST" in d:
        return [("warmup", 20 if "FTP" in d else 10, 2, "include the short hard efforts"),
                ("interval", 20 if "FTP" in d else 30, 5 if "FTP" in d else 4, "TEST: hard and even"),
                ("cooldown", 10, 1, "")]

    m = re.search(r"(\d+)\s*min Z\d[^/]*running\s*/\s*(\d+)\s*min walk", d)
    if m:  # run/walk
        run_m, walk_m = int(m.group(1)), int(m.group(2))
        n = max(1, total_min // (run_m + walk_m))
        return [("repeat", n, [("interval", run_m, zone_of(d), "run"), ("recovery", walk_m, 1, "walk")])]

    m = re.search(r"(\d+)x(\d+)\s*(min|s)\b([^,;]*)", d)
    if m:
        n, on, unit, tail = int(m.group(1)), int(m.group(2)), m.group(3), m.group(4)
        on_min = on if unit == "min" else on / 60
        zone = zone_of(tail, 4 if "hill" in tail else 3)
        rec = re.search(r"(\d+)\s*min\s*(?:easy|recovery|at 90 rpm|90 rpm|Z1|walk)", d[m.end():] + " " + tail)
        off = int(rec.group(1)) if rec else (2 if "hill" in tail else max(1, on_min / 2))
        if "hill" in tail and "walk" in d:
            off = max(off, on_min)
        at = re.search(r"(?:[Aa]t|[Ff]rom|start after)\s*(\d+)\s*min", d)
        warm = int(at.group(1)) if at else 15
        note = "hill" if "hill" in tail else ("low cadence" if "rpm" in tail else "")
        main = n * (on_min + off)
        cool = max(5, total_min - warm - main)
        return [("warmup", warm, 2, ""), ("repeat", n, [("interval", on_min, zone, note), ("recovery", off, 1, "easy")]),
                ("cooldown", cool, 1, "")]

    m = re.search(r"[Aa]t (\d+) min:\s*(\d+) min (?:at )?Z(\d)", d)
    if m:
        warm, on, z = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return [("warmup", warm, 2, ""), ("interval", on, z, ""), ("cooldown", max(5, total_min - warm - on), 2, "")]

    m = re.search(r"(\d+) min Z1, (\d+) min Z(\d)", d)
    if m:
        a, b, z = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return [("warmup", a, 1, ""), ("interval", b, z, ""), ("cooldown", max(5, total_min - a - b), 1, "")]
    return None


def run_workout(s: Session, plan: list) -> dict:
    o = _Order()

    def mk(kind, mins, zone, note):
        return _step(o, kind, "time", round(mins * 60), note or None,
                     targetType={"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone"}, zoneNumber=zone)

    steps = []
    for item in plan:
        if item[0] == "repeat":
            steps.append(_repeat(o, item[1], lambda body=item[2]: [mk(*b) for b in body]))
        else:
            steps.append(mk(*item))
    return {"workoutName": f"{s.day:%b %d} {s.title} {s.label()}", "description": s.detail[:1000],
            "sportType": SPORT["run"],
            "workoutSegments": [{"segmentOrder": 1, "sportType": SPORT["run"], "workoutSteps": steps}]}


POWER_MID = {1: 0.50, 2: 0.65, 3: 0.83, 4: 0.98, 5: 1.10}


def zwo(s: Session) -> str:
    total = s.amount
    plan = structure(s.detail, total) or [("warmup", 10, 2, ""), ("steady", max(5, total - 15), 2, ""),
                                         ("cooldown", 5, 1, "")]
    cad = re.search(r"(\d+)-(\d+) rpm", s.detail)
    parts = []
    for item in plan:
        if item[0] == "repeat":
            on, off = item[2]
            attrs = (f'Repeat="{item[1]}" OnDuration="{round(on[1] * 60)}" OffDuration="{round(off[1] * 60)}" '
                     f'OnPower="{POWER_MID[on[2]]}" OffPower="{POWER_MID[off[2]]}"')
            if cad and on[3] == "low cadence":
                attrs += f' Cadence="{cad.group(1)}" CadenceResting="90"'
            parts.append(f"    <IntervalsT {attrs}/>")
        elif item[0] == "warmup":
            parts.append(f'    <Warmup Duration="{round(item[1] * 60)}" PowerLow="0.45" PowerHigh="{POWER_MID[item[2]]}"/>')
        elif item[0] == "cooldown":
            parts.append(f'    <Cooldown Duration="{round(item[1] * 60)}" PowerLow="{POWER_MID[2]}" PowerHigh="0.45"/>')
        elif "TEST" in (item[3] or ""):
            parts.append(f'    <FreeRide Duration="{round(item[1] * 60)}" FlatRoad="1"/>')
        else:
            parts.append(f'    <SteadyState Duration="{round(item[1] * 60)}" Power="{POWER_MID[item[2]]}"/>')
    name = f"{s.day:%b %d} {s.title} {s.label()}"
    return ("<workout_file>\n  <author>ironman</author>\n"
            f"  <name>{escape(name)}</name>\n  <description>{escape(s.detail)}</description>\n"
            "  <sportType>bike</sportType>\n  <tags><tag name=\"IRONMAN\"/></tags>\n  <workout>\n"
            + "\n".join(parts) + "\n  </workout>\n</workout_file>\n")


def zwift_folder() -> Path | None:
    root = Path.home() / "Documents" / "Zwift" / "Workouts"
    try:
        ids = [p for p in root.iterdir() if p.is_dir() and p.name.isdigit()]
    except OSError:
        return None
    return ids[0] if ids else None
