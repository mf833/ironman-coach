"""The rules engine.

Plain, testable rules. No AI here: every recommendation comes from a rule in
this file, and each one says which rule fired and why. See "How it works" in README.md.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from .plan import Session, fmt_minutes, week_dates, week_of, race_day

YD_PER_M = 1.09361


# ---- matching plan to what you actually did ------------------------------------
@dataclass
class Status:
    session: Session
    state: str          # done | partial | missed | moved | today | upcoming
    actual: float = 0.0  # minutes, or yards for swims
    activities: list = field(default_factory=list)

    @property
    def ratio(self) -> float:
        return self.actual / self.session.amount if self.session.amount else 1.0


def activity_amount(a: dict) -> float:
    if a["sport"] == "swim":
        return a["meters"] * YD_PER_M
    return a["minutes"]


def match(plan: list[Session], activities: list[dict], today: date, cfg: dict) -> tuple[dict, list]:
    t = cfg["thresholds"]
    by_day_sport = defaultdict(list)
    for a in activities:
        by_day_sport[(a["date"], a["sport"])].append(a)
    planned_keys = {(s.day.isoformat(), s.sport) for s in plan}

    statuses: dict[str, Status] = {}
    used = set()
    for s in plan:
        if s.sport == "race":
            continue
        acts = by_day_sport.get((s.day.isoformat(), s.sport), [])
        actual = sum(activity_amount(a) for a in acts)
        used.update(a["id"] for a in acts)
        statuses[s.id] = Status(s, _state(s, actual, today, t), actual, acts)

    # Did it a day early or late? Count it if that day had nothing of that sport planned.
    for st in statuses.values():
        if st.state != "missed":
            continue
        for delta in (-1, 1):
            d = (st.session.day + timedelta(days=delta)).isoformat()
            if (d, st.session.sport) in planned_keys:
                continue
            acts = [a for a in by_day_sport.get((d, st.session.sport), []) if a["id"] not in used]
            amt = sum(activity_amount(a) for a in acts)
            if acts and amt >= st.session.amount * t["partial_ratio"]:
                st.state, st.actual, st.activities = "moved", amt, acts
                used.update(a["id"] for a in acts)
                break

    extras = [a for a in activities if a["id"] not in used]
    return statuses, extras


def _state(s: Session, actual: float, today: date, t: dict) -> str:
    ratio = actual / s.amount if s.amount else 1
    if s.day > today:
        return "upcoming"
    if ratio >= t["done_ratio"]:
        return "done"
    if s.day == today:
        return "today" if ratio < t["partial_ratio"] else "partial"
    return "partial" if ratio >= t["partial_ratio"] else "missed"


# ---- recovery signals (shown individually, never blended into one score) -------
@dataclass
class Signal:
    name: str
    value: str
    level: int | None   # 0 normal, 1 slightly off, 2 clearly off, None = no data
    why: str


def recovery_signals(day: dict | None, note: str | None, cfg: dict) -> list[Signal]:
    t = cfg["thresholds"]
    day = day or {}
    out = []

    hrv = day.get("hrv")
    if hrv and hrv.get("last_night"):
        ln, lo, hi, low_up = hrv["last_night"], hrv.get("balanced_low"), hrv.get("balanced_upper"), hrv.get("low_upper")
        status = (hrv.get("status") or "").upper()
        rng = f" (your normal {lo}-{hi})" if lo and hi else ""
        if not (lo and hi) and status not in ("LOW", "POOR", "UNBALANCED", "BALANCED"):
            lvl, why = None, "building your baseline (needs a week of nights)"
        elif status in ("LOW", "POOR") or (low_up and ln < low_up):
            lvl, why = 2, "well below your normal range"
        elif status == "UNBALANCED" or (lo and ln < lo):
            lvl, why = 1, "a bit outside your normal range"
        else:
            lvl, why = 0, "inside your normal range"
        out.append(Signal("HRV", f"{ln} ms{rng}", lvl, why))
    else:
        out.append(Signal("HRV", "no data", None, "wear your watch to sleep"))

    sl = day.get("sleep_h")
    if sl:
        lvl = 2 if sl < t["sleep_very_low_h"] else 1 if sl < t["sleep_low_h"] else 0
        out.append(Signal("Sleep", f"{sl:.1f} h", lvl,
                          ["enough", "short", "very short"][lvl]))
    else:
        out.append(Signal("Sleep", "no data", None, ""))

    rhr, rhr7 = day.get("rhr"), day.get("rhr_7d")
    if rhr and rhr7:
        diff = rhr - rhr7
        lvl = 2 if diff >= t["rhr_high_bpm"] else 1 if diff >= t["rhr_elevated_bpm"] else 0
        out.append(Signal("Resting HR", f"{rhr} bpm (7-day {rhr7})", lvl,
                          "normal" if lvl == 0 else f"{diff:+d} bpm above your week"))
    else:
        out.append(Signal("Resting HR", "no data", None, ""))

    if note == "tired":
        out.append(Signal("You", "feel tired", 1, "feel tired"))
    return out


# ---- advice ---------------------------------------------------------------------
@dataclass
class Advice:
    id: str
    rule: str
    severity: str        # info | suggest | important
    title: str
    why: str
    instead: str = ""    # what to do if you take the change
    changes: dict = field(default_factory=dict)  # session_id -> override fields


def _round5(x: float) -> int:
    return max(5, int(5 * round(x / 5)))


def _round100(x: float) -> int:
    return max(100, int(100 * round(x / 100)))


def advise(plan, statuses, signals, today, state, cfg, activities=(), insights=(), fatigue=None) -> list[Advice]:
    notes = state.get("notes", {})
    out: list[Advice] = []
    out += rule_sick_or_pain(plan, statuses, today, notes)
    if not any(a.rule == "sick" for a in out):
        out += rule_recovery(plan, statuses, signals, today)
    out += rule_missed(plan, statuses, today)
    week = rule_week_compliance(plan, statuses, today, cfg, activities)
    out += week
    held = {sid for a in week for sid in a.changes}
    out += rule_long_session_gate(plan, activities, today, cfg, skip=held)
    out += rule_busy(plan, statuses, today, state.get("busy", {}))
    out += rule_run_insights(plan, statuses, today, list(insights))
    if fatigue:
        tired = rule_fatigue(plan, statuses, today, fatigue, cfg)
        if any(a.severity == "suggest" for a in tired):  # don't suggest going longer while easing off
            out = [a for a in out if a.rule != "insight" or not a.changes]
        out += tired
    dismissed = set(state.get("dismissed", []))
    return [a for a in out if a.id not in dismissed]


def _open_today(plan, statuses, today):
    return [s for s in plan if s.day == today and s.sport != "race"
            and statuses.get(s.id) and statuses[s.id].state in ("today", "partial")]


def rule_sick_or_pain(plan, statuses, today, notes) -> list[Advice]:
    """R1. Sick: rest. Pain: no running for 3 days, swap runs for easy rides."""
    out = []
    recent = {d: n for d, n in notes.items()
              if 0 <= (today - date.fromisoformat(d)).days <= 1}
    if "sick" in recent.values():
        todays = _open_today(plan, statuses, today)
        if todays:
            out.append(Advice(
                f"sick:{today}", "sick", "important", "Rest today, you're sick",
                "Training while sick slows recovery and can make it worse. Missing a day or two costs nothing.",
                "Skip today. When you feel better, come back with easy sessions for a day or two.",
                {s.id: {"dropped": True} for s in todays}))
    if "pain" in recent.values():
        runs = [s for s in plan if s.sport == "run" and today <= s.day <= today + timedelta(days=2)
                and statuses.get(s.id) and statuses[s.id].state in ("today", "upcoming")]
        if runs:
            out.append(Advice(
                f"pain:{today}", "pain", "important", "Swap your runs for easy rides for 3 days",
                "You logged pain. Running is the highest-impact sport, so it goes first. If pain changes how you move or lasts, see a professional.",
                "Ride easy (Z1-Z2) for the same time instead of each run.",
                {s.id: {"sport": "bike", "title": "Easy ride (instead of run)",
                        "detail": "Z1-Z2 only. Stop if it hurts.", "kind": "easy",
                        "note": "swapped from a run (pain)"} for s in runs}))
    return out


def rule_recovery(plan, statuses, signals, today) -> list[Advice]:
    """R2. Count how many recovery signals are off and scale today's session."""
    load = sum(s.level or 0 for s in signals)
    off = [f"{s.name} {s.why}" for s in signals if s.level]
    todays = _open_today(plan, statuses, today)
    if not todays or load == 0:
        return []
    why = "; ".join(off) + "."
    if load == 1:
        return [Advice(f"recovery1:{today}", "recovery", "info", "Train as planned",
                       f"One signal is slightly off ({why[:-1]}). One signal alone isn't a reason to change.")]
    if load >= 4:
        return [Advice(
            f"recovery4:{today}", "recovery", "important", "Make today a rest or very easy day",
            f"Several signals are clearly off: {why}",
            "Rest, or do 30 min very easy (Z1) if you want to move.",
            {s.id: {"amount": min(s.amount, 30 if s.sport != "swim" else 1000), "kind": "recovery",
                    "detail": "Very easy, Z1 only. Optional.", "note": "eased (recovery)"} for s in todays})]
    changes, parts = {}, []
    for s in todays:
        if s.kind in ("intervals", "test"):
            changes[s.id] = {"kind": "easy", "detail": f"Easy Z1-Z2 instead of: {s.detail}",
                             "note": "intervals made easy (recovery)"}
            parts.append(f"{s.title}: same time, all easy Z1-Z2, skip the intervals")
        elif s.kind == "long":
            new = _round5(s.amount * 0.75) if s.sport != "swim" else _round100(s.amount * 0.75)
            changes[s.id] = {"amount": new, "note": "shortened 25% (recovery)"}
            parts.append(f"{s.title}: cut to {fmt_minutes(new) if s.sport != 'swim' else f'{new:,} yd'}, keep it Z2")
    if not changes:
        return [Advice(f"recovery2:{today}", "recovery", "info", "Keep today truly easy",
                       f"A couple of signals are off: {why} Today is already easy, so no change needed.",
                       "Stay conversational and shorten it if you feel flat.")]
    return [Advice(f"recovery2:{today}", "recovery", "suggest", "Ease off today",
                   f"A couple of signals are off: {why}", "; ".join(parts) + ".", changes)]


def rule_missed(plan, statuses, today) -> list[Advice]:
    """R3. Don't make up missed work. Only key sessions get moved, and only to a free slot this week."""
    out = []
    recent = [st for st in statuses.values() if st.state == "missed"
              and 1 <= (today - st.session.day).days <= 3]
    small = [st for st in recent if not st.session.key]
    if small:
        names = ", ".join(f"{st.session.title} ({st.session.day:%a})" for st in small)
        out.append(Advice(f"missed-small:{today}", "missed", "info", "Missed sessions: let them go",
                          f"You missed {names}. Stacking extra work on later days raises fatigue for little gain."))
    for st in recent:
        if not st.session.key:
            continue
        s = st.session
        slot = _free_slot(plan, statuses, s, today)
        if slot:
            out.append(Advice(
                f"missed:{s.id}", "missed", "suggest", f"Move your missed {s.title.lower()} to {slot:%A}",
                f"{s.title} ({s.label()}) on {s.day:%a} was a key session, and {slot:%A} has room for it.",
                f"Do it {slot:%a} {slot:%b %d}. Don't double up with anything hard that day.",
                {s.id: {"day": slot.isoformat(), "note": f"moved from {s.day:%a %b %d}"}}))
        else:
            out.append(Advice(
                f"missed:{s.id}", "missed", "info", f"Missed {s.title.lower()}: skip it",
                f"No free slot this week without crowding other key sessions. The long-session check will keep your next one from jumping too far."))
    return out


def _free_slot(plan, statuses, s: Session, today: date) -> date | None:
    _, week_end = week_dates(s.week)
    key_days = {x.day for x in plan if x.key and x.id != s.id}
    load = defaultdict(float)
    for x in plan:
        load[x.day] += x.minutes
    d = today
    while d <= week_end:
        if d >= today and not ({d - timedelta(days=1), d, d + timedelta(days=1)} & key_days) and load[d] <= 60:
            return d
        d += timedelta(days=1)
    return None


def rule_week_compliance(plan, statuses, today, cfg, activities=()) -> list[Advice]:
    """R4. If last week went badly, hold this week's long sessions instead of progressing."""
    t = cfg["thresholds"]
    wk = week_of(today)
    if wk <= 1:
        return []
    last = [st for st in statuses.values() if st.session.week == wk - 1]
    planned = sum(st.session.minutes for st in last)
    if not planned:
        return []
    done = sum(min(st.actual / st.session.amount, 1.2) * st.session.minutes
               for st in last if st.session.amount)
    pct = done / planned
    if pct > t["week_high_compliance"]:
        return [Advice(f"week-high:{wk}", "week", "info", "Last week ran over plan",
                       f"You did about {pct:.0%} of last week's planned time. Fine now and then; don't make it the norm.")]
    if pct >= t["week_low_compliance"]:
        return []
    last_long = {sp: max([st.session.amount for st in last if st.session.sport == sp and st.session.kind == "long"], default=0)
                 for sp in ("bike", "run")}
    limits = gate_limits(plan, activities, today, cfg)
    changes, parts = {}, []
    for s in plan:
        if s.week == wk and s.kind == "long" and s.day >= today and last_long.get(s.sport) and s.amount > last_long[s.sport]:
            new = min(last_long[s.sport], limits.get(s.id, (10**6,))[0])
            changes[s.id] = {"amount": new, "note": "held back after a light week"}
            parts.append(f"{s.title} {s.day:%a}: {s.label()} -> {fmt_minutes(new)}")
    if not changes:
        return [Advice(f"week-low:{wk}", "week", "info", "Last week was light, keep going",
                       f"You did about {pct:.0%} of last week's plan. This week doesn't jump, so carry on.")]
    return [Advice(f"week-low:{wk}", "week", "suggest", "Repeat last week's long sessions",
                   f"You completed about {pct:.0%} of last week's planned time. Progressing on top of a missed week is how people get hurt or burned out.",
                   "; ".join(parts) + ".", changes)]


def gate_limits(plan, activities, today, cfg) -> dict:
    """{session_id: (limit, reference)} for long sessions / straight swims in the next 7 days."""
    ratio = cfg["thresholds"]["gate_ratio"]
    base = cfg["baseline"]
    lo = (today - timedelta(days=28)).isoformat()
    recent = defaultdict(float)
    for a in activities:
        if lo <= a["date"] < today.isoformat():
            recent[a["sport"]] = max(recent[a["sport"]], activity_amount(a))
    out = {}
    for s in plan:
        if not (today <= s.day <= today + timedelta(days=7)) or not s.key or s.kind not in ("long", "straight"):
            continue
        if s.sport == "swim":
            ref = max(recent["swim"], base["swim_yd"])
            out[s.id] = (_round100(ref * ratio), ref)
        elif s.sport in ("bike", "run"):
            ref = max(recent[s.sport], base[f"{s.sport}_min"])
            out[s.id] = (_round5(ref * ratio), ref)
    return out


def rule_long_session_gate(plan, activities, today, cfg, skip=()) -> list[Advice]:
    """R5. A long session shouldn't be more than ~25% beyond the longest you've done recently."""
    ratio = cfg["thresholds"]["gate_ratio"]
    limits = gate_limits(plan, activities, today, cfg)
    out = []
    for s in plan:
        if s.id not in limits or s.id in skip:
            continue
        limit, ref = limits[s.id]
        unit = (lambda v: f"{int(v):,} yd") if s.sport == "swim" else fmt_minutes
        if s.amount > limit:
            out.append(Advice(
                f"gate:{s.id}", "gate", "suggest", f"Cap {s.day:%a}'s {s.title.lower()} at {unit(limit)}",
                f"The plan says {s.label()}, but your longest {s.sport} in the last 4 weeks (or your starting baseline) "
                f"is about {unit(ref)}. That would be +{s.amount / ref - 1:.0%}; the cap is +{ratio - 1:.0%}.",
                f"Go {unit(limit)} this time. The plan catches up once you've done it.",
                {s.id: {"amount": limit, "note": f"capped from {s.label()} (long-session gate)"}}))
    return out


def rule_busy(plan, statuses, today, busy: dict) -> list[Advice]:
    """R6. You told me you only have N minutes on a day: shorten, keep the main set."""
    out = []
    for d, avail in busy.items():
        day = date.fromisoformat(d)
        if not (today <= day <= today + timedelta(days=7)):
            continue
        sessions = [s for s in plan if s.day == day and s.sport != "race"]
        total = sum(s.minutes for s in sessions)
        if not sessions or total <= avail:
            continue
        f = max(avail, 20) / total
        changes, parts = {}, []
        for s in sessions:
            new = _round100(s.amount * f) if s.sport == "swim" else _round5(s.amount * f)
            changes[s.id] = {"amount": new, "note": f"shortened to fit {avail} min"}
            parts.append(f"{s.title}: {s.label()} -> {new:,} yd" if s.sport == "swim" else f"{s.title}: {s.label()} -> {fmt_minutes(new)}")
        out.append(Advice(
            f"busy:{d}", "busy", "suggest", f"Shorten {day:%a}'s training to fit {avail} min",
            f"You have {avail} min on {day:%a}; the plan has about {fmt_minutes(total)}.",
            "; ".join(parts) + ". Cut warm-up and cool-down first and keep the main set.", changes))
    return out


def rule_run_insights(plan, statuses, today, insights) -> list[Advice]:
    """R7-R9. What your recent runs say: easy runs too hard, aerobic base ready, high drift."""
    out = []
    easy = [i for i in insights if i.get("session_kind") in ("easy", "long", "recovery") and "above_pct" in i][:3]
    hard = [i for i in easy if i["above_pct"] >= 25]
    if len(easy) >= 2 and len(hard) >= 2:
        out.append(Advice(f"easy-too-hard:{hard[0]['date']}", "insight", "info", "Your easy runs are too hard",
                          f"{len(hard)} of your last {len(easy)} easy runs spent 25%+ above the planned zone. "
                          "Easy days build the aerobic base only if they're actually easy; slow down or walk the hills."))
    longs = [i for i in insights if i.get("session_kind") == "long" and i.get("decoupling") is not None
             and i["minutes"] >= 60][:2]
    if longs and longs[0]["decoupling"] > 10:
        out.append(Advice(f"drift:{longs[0]['date']}", "insight", "info", "Big heart-rate drift on your last long run",
                          f"{longs[0]['decoupling']}% drift. Start the next one slower, eat from minute 30-45, and "
                          "drink to thirst. It's usually pacing, fuel or heat, not fitness."))
    elif len(longs) == 2 and all(i["decoupling"] < 5 for i in longs):
        nxt = next((s for s in plan if s.sport == "run" and s.kind == "long"
                    and today <= s.day <= today + timedelta(days=7)), None)
        if nxt:
            new = _round5(nxt.amount * 1.10)
            out.append(Advice(f"long-ready:{nxt.id}", "insight", "suggest", "Your aerobic base is holding up",
                              f"Your last two long runs drifted under 5% ({longs[0]['decoupling']}% and "
                              f"{longs[1]['decoupling']}%). If you feel good, you can go a little longer.",
                              f"{nxt.title} {nxt.day:%a}: {nxt.label()} -> {fmt_minutes(new)}. Optional.",
                              {nxt.id: {"amount": new, "note": "extended 10% (low drift on recent long runs)"}}))
    return out


def rule_fatigue(plan, statuses, today, f, cfg) -> list[Advice]:
    """R10. Fatigue (7-day load) much higher than fitness (42-day load): ease the next two days."""
    t = cfg["thresholds"]
    if f.get("ratio") is None or f["history_days"] < 28 or f["ctl"] < 10:
        return []
    r = f["ratio"]
    if r < t.get("fatigue_warn_ratio", 1.3):
        return []
    why = (f"Your fatigue (last 7 days, {f['atl']}) is {r}x your fitness (last 42 days, {f['ctl']}). "
           "Load ramping this fast is when people get hurt or run down.")
    if r < t.get("fatigue_high_ratio", 1.5):
        return [Advice(f"fatigue-warn:{today}", "fatigue", "info", "Fatigue is building", why +
                       " No change needed, just keep easy days easy.")]
    nxt = [s for s in plan if today <= s.day <= today + timedelta(days=1) and s.sport != "race"
           and statuses.get(s.id) and statuses[s.id].state in ("today", "upcoming", "partial")]
    changes, parts = {}, []
    for s in nxt:
        if s.kind in ("intervals", "test"):
            changes[s.id] = {"kind": "easy", "detail": f"Easy Z1-Z2 instead of: {s.detail}", "note": "made easy (fatigue)"}
            parts.append(f"{s.title} {s.day:%a}: all easy")
        elif s.sport != "swim":
            new = _round5(s.amount * 0.7)
            changes[s.id] = {"amount": new, "note": "shortened 30% (fatigue)"}
            parts.append(f"{s.title} {s.day:%a}: {s.label()} -> {fmt_minutes(new)}")
    if not changes:
        return []
    return [Advice(f"fatigue:{today}", "fatigue", "suggest", "Ease off for two days", why,
                   "; ".join(parts) + ".", changes)]


# ---- progress -------------------------------------------------------------------
def plan_peaks(plan) -> dict:
    """Longest planned session per sport: what the milestones measure against."""
    out = {}
    for s in plan:
        if s.sport in ("swim", "bike", "run"):
            out[s.sport] = max(out.get(s.sport, 0), s.amount)
    return out


def week_progress(plan, statuses, activities, wk) -> dict:
    start, end = week_dates(wk)
    out = {}
    sports = [sp for sp in ("swim", "bike", "run") if any(s.sport == sp for s in plan)]
    for sp in sports:
        planned = sum(s.amount for s in plan if s.week == wk and s.sport == sp)
        done = sum(activity_amount(a) for a in activities
                   if a["sport"] == sp and start.isoformat() <= a["date"] <= end.isoformat())
        out[sp] = (done, planned)
    return out


def plan_compliance(statuses, today) -> tuple[int, int]:
    past = [st for st in statuses.values() if st.session.day < today]
    done = sum(1 for st in past if st.state in ("done", "moved"))
    return done, len(past)


def days_to_race(today: date) -> int:
    return (race_day() - today).days
