"""Training plans as CSV files.

A plan is a CSV with one row per session:

    week,day,sport,amount,kind,phase,title,detail
    1,Tue,swim,1500,intervals,Base,,WU 200 easy + 4x50 drills; main 8x100 on 20s rest; CD 200 easy
    1,Sat,bike,90,long,Base,,15 min Z1, then Z2

- week: 1..N. The last week is race week; the race date in config.json decides the calendar.
- day: Mon..Sun
- sport: swim | bike | run | strength | race
- amount: minutes, or yards for swims (0 for race)
- kind (optional): easy | long | intervals | test | straight | brick | recovery
- phase, title (optional). detail: the workout, with zones like Z2, Z3-Z4.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path

SWIM_MIN_PER_100YD = 2.4  # rough time estimate incl. rest, for weekly hours
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
KINDS = {"easy", "long", "intervals", "test", "straight", "brick", "recovery", "race"}

# Set by load_plan(); read through the helper functions below.
_CAL = {"start": date(2026, 1, 5), "race": date(2026, 5, 23), "labels": [], "weeks": 20, "race_name": "Race"}


@dataclass(frozen=True)
class Session:
    sport: str            # swim | bike | run | strength | race
    amount: int           # minutes (bike/run/strength) or yards (swim)
    title: str
    detail: str = ""
    kind: str = "easy"
    key: bool = False     # long sessions, tests, straight swims: worth protecting
    id: str = ""
    day: date | None = None
    week: int = 0
    note: str = ""        # set when an adjustment changed this session

    @property
    def unit(self) -> str:
        return "yd" if self.sport == "swim" else "min"

    @property
    def minutes(self) -> float:
        if self.sport == "swim":
            return self.amount / 100 * SWIM_MIN_PER_100YD
        return float(self.amount)

    def label(self) -> str:
        if self.sport == "swim":
            return f"{self.amount:,} yd"
        return fmt_minutes(self.amount)


def fmt_minutes(m: float) -> str:
    m = int(round(m))
    h, mm = divmod(m, 60)
    if h and mm:
        return f"{h}:{mm:02d}"
    if h:
        return f"{h}:00"
    return f"{mm} min"


TITLES = {
    "swim": {"straight": "Straight swim", "test": "Swim test"},
    "bike": {"long": "Long ride", "intervals": "Bike intervals", "test": "FTP test", "recovery": "Recovery ride"},
    "run": {"long": "Long run", "intervals": "Run intervals", "test": "Run test", "brick": "Brick run",
            "recovery": "Easy run"},
}
DEFAULT_TITLE = {"swim": "Swim", "bike": "Bike", "run": "Run", "strength": "Strength", "race": "Race day"}


def _kind(row_kind: str, sport: str, detail: str) -> str:
    k = (row_kind or "").strip().lower()
    if k in KINDS:
        return k
    if sport == "race":
        return "race"
    if "TEST" in detail:
        return "test"
    if "straight" in detail.lower():
        return "straight"
    if re.search(r"\d+x\d+|Z[345]", detail):
        return "intervals"
    return "easy"


class PlanError(ValueError):
    pass


def load_plan(path: str | Path, race_date: date, race_name: str = "Race") -> list[Session]:
    """Read a plan CSV and lay it out so the last week is race week."""
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for n, r in enumerate(csv.DictReader(f), start=2):
            r = {(k or "").strip().lower(): (v or "").strip() for k, v in r.items()}
            if not r.get("week"):
                continue
            try:
                week, day = int(r["week"]), DAYS.index(r["day"][:3].lower())
                sport = r["sport"].lower()
                amount = int(float(r.get("amount") or 0))
            except (KeyError, ValueError) as e:
                raise PlanError(f"{path}, line {n}: couldn't read week/day/sport/amount ({e})") from None
            if sport not in DEFAULT_TITLE:
                raise PlanError(f"{path}, line {n}: sport must be swim, bike, run, strength or race")
            rows.append((week, day, sport, amount, r))
    if not rows:
        raise PlanError(f"{path} has no sessions")

    n_weeks = max(r[0] for r in rows)
    race_monday = race_date - timedelta(days=race_date.weekday())
    start = race_monday - timedelta(weeks=n_weeks - 1)
    labels = [""] * n_weeks
    out: list[Session] = []
    counters: dict = {}
    for week, d, sport, amount, r in sorted(rows, key=lambda x: (x[0], x[1])):
        if r.get("phase") and not labels[week - 1]:
            labels[week - 1] = r["phase"]
        detail = r.get("detail", "")
        kind = _kind(r.get("kind", ""), sport, detail)
        title = r.get("title") or TITLES.get(sport, {}).get(kind) or DEFAULT_TITLE[sport]
        day = start + timedelta(weeks=week - 1, days=d)
        if sport == "race":
            day, title = race_date, r.get("title") or race_name
        i = counters.get((day, sport), 0)
        counters[(day, sport)] = i + 1
        out.append(Session(sport, amount, title, detail, kind,
                           key=kind in ("long", "test", "straight", "race"),
                           id=f"{day.isoformat()}-{sport}-{i}", day=day, week=week))
    if not any(s.sport == "race" for s in out):
        out.append(Session("race", 0, race_name, "Race day. Start easy, fuel early, trust the training.", "race",
                           key=True, id=f"{race_date.isoformat()}-race-0", day=race_date, week=n_weeks))
    _CAL.update(start=start, race=race_date, labels=labels, weeks=n_weeks, race_name=race_name)
    return sorted(out, key=lambda s: (s.day, s.id))


def apply_overrides(plan: list[Session], overrides: dict) -> list[Session]:
    """Apply accepted adjustments. overrides: {session_id: {field: value}}."""
    out = []
    for s in plan:
        o = overrides.get(s.id)
        if not o:
            out.append(s)
            continue
        if o.get("dropped"):
            continue
        changes = {k: v for k, v in o.items() if k in ("sport", "amount", "title", "detail", "kind", "note")}
        if "day" in o:
            changes["day"] = date.fromisoformat(o["day"])
        out.append(replace(s, **changes))
    return sorted(out, key=lambda s: (s.day, s.id))


def plan_start() -> date:
    return _CAL["start"]


def race_day() -> date:
    return _CAL["race"]


def race_name() -> str:
    return _CAL["race_name"]


def num_weeks() -> int:
    return _CAL["weeks"]


def week_label(w: int) -> str:
    labels = _CAL["labels"]
    if w == num_weeks():
        return labels[w - 1] or "Race week"
    return labels[w - 1] if 1 <= w <= len(labels) else ""


def week_of(d: date) -> int:
    return (d - plan_start()).days // 7 + 1


def week_dates(week: int) -> tuple[date, date]:
    start = plan_start() + timedelta(weeks=week - 1)
    return start, start + timedelta(days=6)
