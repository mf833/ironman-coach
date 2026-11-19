import copy
from datetime import date, timedelta
from pathlib import Path

from ironman_coach import engine, plan as P
from ironman_coach.state import DEFAULT_CONFIG, DEFAULT_STATE

CFG = copy.deepcopy(DEFAULT_CONFIG)
PLANS = Path(__file__).resolve().parent.parent / "plans"
RACE = date(2027, 4, 24)  # a Saturday; 20-week plan starts Mon Dec 7, 2026


def full_plan():
    return P.load_plan(PLANS / "full-distance-triathlon-20wk.csv", RACE, "Test Race")


def state(**kw):
    s = copy.deepcopy(DEFAULT_STATE)
    s.update(kw)
    return s


_ids = iter(range(1, 10**6))


def act(day, sport, minutes=0, meters=0):
    return {"id": next(_ids), "name": sport, "type": sport, "sport": sport, "date": day.isoformat(),
            "minutes": minutes, "meters": meters, "avg_hr": None}


def run_engine(today, activities=(), day=None, st=None):
    st = st or state()
    plan = P.apply_overrides(full_plan(), st["overrides"])
    statuses, _ = engine.match(plan, list(activities), today, CFG)
    signals = engine.recovery_signals(day, st["notes"].get(today.isoformat()), CFG)
    return plan, statuses, engine.advise(plan, statuses, signals, today, st, CFG, list(activities))


def day(hrv=40, sleep=7.5, rhr=60, rhr7=60, status="BALANCED"):
    return {"hrv": {"last_night": hrv, "balanced_low": 35, "balanced_upper": 47, "low_upper": 32, "status": status},
            "sleep_h": sleep, "rhr": rhr, "rhr_7d": rhr7}


# ---- plan files -----------------------------------------------------------------
def test_full_plan_layout():
    plan = full_plan()
    assert P.plan_start() == date(2026, 12, 7) and P.num_weeks() == 20
    race = [s for s in plan if s.sport == "race"]
    assert len(race) == 1 and race[0].day == RACE
    assert max(s.amount for s in plan if s.sport == "bike") == 360
    assert len({s.id for s in plan}) == len(plan)
    assert not [s for s in plan if s.day == P.plan_start()]  # Monday rest


def test_every_example_plan_loads_and_swims_add_up():
    from ironman_coach.swimsets import breakdown
    from ironman_coach.workouts import structure
    for f in PLANS.glob("*.csv"):
        plan = P.load_plan(f, RACE, "x")
        assert plan
        for s in plan:
            if s.sport == "swim":
                assert breakdown(s.detail, s.amount)[1] == s.amount, (f.name, s.detail)
            if s.sport in ("bike", "run") and s.kind in ("intervals", "test"):
                assert structure(s.detail, s.amount), (f.name, s.detail)


def test_run_only_plan_has_no_swim_or_bike():
    plan = P.load_plan(PLANS / "marathon-16wk.csv", date(2027, 5, 2), "Marathon")
    assert {s.sport for s in plan} <= {"run", "strength", "race"}
    wp = engine.week_progress(plan, {}, [], 1)
    assert set(wp) == {"run"}


def test_bad_plan_row_is_reported(tmp_path):
    f = tmp_path / "p.csv"
    f.write_text("week,day,sport,amount,detail\n1,Tue,rowing,30,x\n")
    try:
        P.load_plan(f, RACE)
    except P.PlanError as e:
        assert "line 2" in str(e)
    else:
        raise AssertionError("expected PlanError")


# ---- matching ----------------------------------------------------------------
def test_done_partial_missed_and_moved():
    acts = [act(date(2026, 12, 9), "bike", 58), act(date(2026, 12, 8), "swim", meters=600),
            act(date(2026, 12, 13), "bike", 85)]
    _, st, _ = run_engine(date(2026, 12, 15), acts)
    by = {(s.session.day, s.session.sport): s.state for s in st.values()}
    assert by[(date(2026, 12, 9), "bike")] == "done"
    assert by[(date(2026, 12, 8), "swim")] == "partial"
    assert by[(date(2026, 12, 12), "bike")] == "moved"   # long ride done Sunday instead
    assert by[(date(2026, 12, 13), "run")] == "missed"


# ---- recovery ----------------------------------------------------------------
def test_all_normal_no_recovery_advice():
    _, _, adv = run_engine(date(2026, 12, 8), day=day())
    assert not [a for a in adv if a.rule == "recovery"]


def test_one_signal_off_means_no_change():
    _, _, adv = run_engine(date(2026, 12, 8), day=day(sleep=5.8))
    rec = [a for a in adv if a.rule == "recovery"]
    assert rec and rec[0].severity == "info" and not rec[0].changes


def test_two_signals_turn_test_easy():
    wed = date(2027, 2, 3)  # week 9 FTP test
    _, _, adv = run_engine(wed, day=day(hrv=34, sleep=5.5, status="UNBALANCED"))
    rec = [a for a in adv if a.rule == "recovery"][0]
    assert rec.severity == "suggest" and list(rec.changes.values())[0]["kind"] == "easy"


def test_two_signals_shorten_long_session_25pct():
    sat = date(2027, 1, 9)  # week 5 long ride 135
    _, _, adv = run_engine(sat, day=day(sleep=4.5))
    rec = [a for a in adv if a.rule == "recovery"][0]
    assert list(rec.changes.values())[0]["amount"] == 100


def test_many_signals_means_rest_or_very_easy():
    _, _, adv = run_engine(date(2027, 1, 9), day=day(hrv=28, sleep=4.5, rhr=70, rhr7=60, status="LOW"))
    rec = [a for a in adv if a.rule == "recovery"][0]
    assert rec.severity == "important" and list(rec.changes.values())[0]["amount"] == 30


def test_sick_drops_today():
    tue = date(2026, 12, 8)
    _, _, adv = run_engine(tue, st=state(notes={tue.isoformat(): "sick"}))
    sick = [a for a in adv if a.rule == "sick"][0]
    assert sick.changes and all(c == {"dropped": True} for c in sick.changes.values())
    assert not [a for a in adv if a.rule == "recovery"]


def test_pain_swaps_runs_for_rides():
    tue = date(2026, 12, 15)
    _, _, adv = run_engine(tue, st=state(notes={tue.isoformat(): "pain"}))
    pain = [a for a in adv if a.rule == "pain"][0]
    assert pain.changes and all(c["sport"] == "bike" for c in pain.changes.values())


# ---- missed ------------------------------------------------------------------
def test_missed_easy_session_is_let_go():
    _, _, adv = run_engine(date(2026, 12, 10))
    m = [a for a in adv if a.rule == "missed"]
    assert m and m[0].severity == "info" and not m[0].changes


def test_missed_key_session_moves_only_to_free_slot():
    # Week 3 Thu straight swim (Dec 24) missed; Fri is next to Sat's long ride, so no slot.
    _, _, adv = run_engine(date(2026, 12, 25))
    key = [a for a in adv if a.id.startswith("missed:2026-12-24-swim")]
    assert key and not key[0].changes


# ---- gate --------------------------------------------------------------------
def test_gate_caps_big_jump():
    sat = date(2027, 2, 6)  # week 9 long ride 180
    adv = engine.rule_long_session_gate(full_plan(), [act(sat - timedelta(days=7), "bike", 120)],
                                        sat - timedelta(days=2), CFG)
    gate = [a for a in adv if "bike" in a.id]
    assert gate and list(gate[0].changes.values())[0]["amount"] == 150


def test_gate_quiet_when_history_supports_it():
    sat = date(2027, 2, 6)
    adv = engine.rule_long_session_gate(full_plan(), [act(sat - timedelta(days=7), "bike", 150)],
                                        sat - timedelta(days=2), CFG)
    assert not [a for a in adv if "bike" in a.id]


# ---- week compliance ---------------------------------------------------------
def test_bad_week_holds_long_sessions():
    # Monday of week 7 after doing nothing in week 6 (long ride 150, long run 65).
    _, _, adv = run_engine(date(2027, 1, 18))
    w = [a for a in adv if a.rule == "week"][0]
    assert w.severity == "suggest"
    # held at last week's length, and never above the gate (default baseline 60 min ride / 30 min run)
    assert sorted(c["amount"] for c in w.changes.values()) == [40, 75]
    assert not [a for a in adv if a.rule == "gate" and a.changes.keys() & w.changes.keys()]


# ---- busy --------------------------------------------------------------------
def test_busy_shortens():
    sun = date(2027, 1, 10)  # week 5 long run 60
    _, _, adv = run_engine(sun - timedelta(days=1), st=state(busy={sun.isoformat(): 40}))
    b = [a for a in adv if a.rule == "busy"][0]
    assert list(b.changes.values())[0]["amount"] == 40


def test_overrides_apply_and_drop():
    plan = full_plan()
    s = next(x for x in plan if x.sport == "bike")
    other = next(x for x in plan if x.sport == "swim")
    out = P.apply_overrides(plan, {s.id: {"amount": 10, "note": "x"}, other.id: {"dropped": True}})
    assert next(x for x in out if x.id == s.id).amount == 10
    assert other.id not in {x.id for x in out}


# ---- garmin, zones, drills, workouts ----------------------------------------------
def test_normalize_raw_garmin_shapes():
    from ironman_coach.garmin import normalize_activity, normalize_day
    a = normalize_activity({"activityId": 5, "activityName": "Zwift", "startTimeLocal": "2026-12-08 07:00:00",
                            "activityType": {"typeKey": "virtual_ride"}, "duration": 3600, "distance": 30000})
    assert a["sport"] == "bike" and a["minutes"] == 60 and a["date"] == "2026-12-08"
    assert normalize_activity({"activityType": {"typeKey": "walking"}}) is None
    d = normalize_day("2026-12-09",
                      {"hrvSummary": {"lastNightAvg": 34, "weeklyAvg": 33, "status": "UNBALANCED",
                                      "baseline": {"balancedLow": 35, "balancedUpper": 47, "lowUpper": 32}}},
                      {"restingHeartRate": 68, "lastSevenDaysAvgRestingHeartRate": 70},
                      {"dailySleepDTO": {"sleepTimeSeconds": 22800}})
    assert d["hrv"]["balanced_low"] == 35 and d["rhr"] == 68 and d["sleep_h"] == 6.33


def test_zones_parse_and_numbers():
    from ironman_coach.zones import zones_in, zone_rows, normalize_hr_zones, normalize_ftp
    assert zones_in("Z1 building to Z2") == [1, 2]
    assert zones_in("2x10 min Z3-Z4") == [3, 4]
    hr = normalize_hr_zones([{"sport": "CYCLING", "zone1Floor": 106, "zone2Floor": 127, "zone3Floor": 148,
                              "zone4Floor": 169, "zone5Floor": 190, "maxHeartRateUsed": 211}])
    (row,) = zone_rows("bike", [2], 200, hr, None)
    assert row[1] == "112-150 W" and row[2] == "127-147 bpm"
    assert normalize_ftp({"functionalThresholdPower": 149}) == 149


def test_drills_two_per_session():
    from ironman_coach.drills import drill_sets, DRILLS
    full_plan()
    sets = drill_sets("WU 200 easy + 8x50 drills; main 7x100 on 20s rest; CD 200 easy", 1)
    assert len(sets) == 1 and len(sets[0]["drills"]) == 2 and sets[0]["per"] == 4
    assert all(n in DRILLS for n in sets[0]["drills"])


def test_workout_builders():
    from ironman_coach.workouts import structure, swim_workout, zwo, run_workout
    from ironman_coach.drills import drill_sets
    for s in full_plan():
        if s.sport == "swim":
            w = swim_workout(s, [d["drills"] for d in drill_sets(s.detail, s.week)])
            assert w["workoutSegments"][0]["workoutSteps"]
        if s.sport == "bike":
            assert "<workout_file>" in zwo(s)
        if s.sport == "run" and s.kind in ("intervals", "test"):
            run_workout(s, structure(s.detail, s.amount))
    assert structure("Easy, Z1-Z2, conversational", 45) is None


# ---- run insights, intervals.icu, fatigue ---------------------------------------------
REAL_ZONES = [{"zoneNumber": 1, "secsInZone": 554.9}, {"zoneNumber": 2, "secsInZone": 2027.7},
              {"zoneNumber": 3, "secsInZone": 118.0}, {"zoneNumber": 4, "secsInZone": 0}, {"zoneNumber": 5, "secsInZone": 0}]
REAL_LAPS = {"lapDTOs": [{"distance": 1609.34, "duration": 941.8, "averageHR": 158, "averageRunCadence": 128},
                         {"distance": 1609.34, "duration": 854.1, "averageHR": 157, "averageRunCadence": 147},
                         {"distance": 1592.4, "duration": 904.8, "averageHR": 160, "averageRunCadence": 148}]}


def test_zone_and_lap_normalizing():
    from ironman_coach.insights import normalize_zone_secs, normalize_laps
    assert [round(x) for x in normalize_zone_secs(REAL_ZONES)] == [555, 2028, 118, 0, 0]
    assert normalize_zone_secs([10, 20, 30, 40, 50, 60, 70]) == [10, 20, 30, 40, 180]  # 7 zones folded
    assert len(normalize_laps(REAL_LAPS)) == 3


def test_decoupling_math():
    from ironman_coach.insights import decoupling_from_laps
    steady = [{"m": 1600, "s": 600, "hr": 150}] * 6
    assert decoupling_from_laps(steady) == 0.0
    drift = [{"m": 1600, "s": 600, "hr": 150}] * 3 + [{"m": 1600, "s": 600, "hr": 165}] * 3
    assert decoupling_from_laps(drift) == 9.1  # (1/150 - 1/165) / (1/150)
    assert decoupling_from_laps(steady[:2]) is None  # under 30 minutes


def test_easy_run_too_hard_verdict():
    from ironman_coach.insights import run_insight
    s = next(x for x in full_plan() if x.sport == "run" and x.kind == "easy")
    a = {"id": 1, "name": "Run", "date": s.day.isoformat(), "minutes": 40, "meters": 6000, "avg_hr": 165}
    r = run_insight(a, {"zone_secs": [0, 1200, 1200, 0, 0], "laps": []}, s)
    assert r["above_pct"] == 50 and "too hard" in r["verdict"][0]
    r2 = run_insight(a, {"zone_secs": [600, 1800, 0, 0, 0], "laps": []}, s)
    assert "Nicely controlled" in r2["verdict"][0]


def test_easy_efficiency_trend():
    from ironman_coach.insights import easy_efficiency
    today = date(2027, 2, 1)
    mk = lambda d, dist, hr: {"date": d, "dist": dist, "minutes": 40, "avg_hr": hr, "zone_pct": [20, 70, 10, 0, 0],
                              "units": "mi"}
    runs = [mk("2027-01-28", 4.0, 150), mk("2027-01-25", 4.0, 150), mk("2026-12-28", 3.6, 150)]
    eff = easy_efficiency(runs, today)
    assert eff["change_pct"] == 11.1 and eff["now"] == "10:00"


def test_intervals_normalizing():
    from ironman_coach import intervals as IC
    a = IC.normalize_activity({"id": "i1", "type": "VirtualRide", "start_date_local": "2026-12-08T07:00:00",
                               "moving_time": 3600, "distance": 30000, "average_heartrate": 135})
    assert a["sport"] == "bike" and a["minutes"] == 60 and a["date"] == "2026-12-08"
    assert IC.normalize_activity({"type": "Yoga"}) is None
    det = IC.activity_detail({"icu_hr_zone_times": [100, 200, 0, 0, 0, 0, 10], "decoupling": 3.2})
    assert det["zone_secs"] == [100, 200, 0, 0, 10] and det["decoupling"] == 3.2
    rows = [{"id": f"2026-11-{d:02d}", "hrv": 40 + (d % 3), "restingHR": 55, "sleepSecs": 27000} for d in range(1, 20)]
    days = IC.normalize_wellness(rows, date(2026, 11, 19))
    d = days["2026-11-19"]
    assert d["hrv"]["balanced_low"] < d["hrv"]["last_night"] + 5 and d["rhr_7d"] == 55 and d["sleep_h"] == 7.5
    zones, ftp = IC.zones_from_settings({"sportSettings": [
        {"types": ["Run"], "hr_zones": [138, 154, 160, 171, 176, 181, 190]},
        {"types": ["Ride", "VirtualRide"], "hr_zones": [130, 145, 155, 165, 175, 185, 195], "ftp": 210}]})
    assert zones["running"]["1"] == [0, 138] and zones["running"]["2"] == [139, 154] and ftp == 210


def test_load_and_fatigue():
    from ironman_coach.load import session_load, fatigue_series
    a = {"id": 1, "sport": "run", "date": "2027-01-01", "minutes": 60, "avg_hr": None}
    assert session_load(a, {"zone_secs": [0, 3600, 0, 0, 0]}, {}) == 120.0   # 60 min x Z2
    assert session_load(a, None, {}) == 120.0                               # no zones: assume Z2
    today = date(2027, 2, 15)
    steady = [{"id": i, "sport": "run", "date": (today - timedelta(days=i)).isoformat(), "minutes": 60,
               "avg_hr": None} for i in range(0, 80)]
    f = fatigue_series(steady, {}, {}, today)
    assert 0.95 <= f["ratio"] <= 1.3  # steady training: fatigue roughly equals fitness
    spike = steady + [{"id": 1000 + i, "sport": "bike", "date": (today - timedelta(days=i)).isoformat(),
                       "minutes": 120, "avg_hr": None} for i in range(0, 7)]
    f2 = fatigue_series(spike, {}, {}, today)
    assert f2["ratio"] > 1.5


def test_fatigue_rule_eases_next_two_days():
    plan = full_plan()
    statuses, _ = engine.match(plan, [], date(2027, 2, 2), CFG)
    adv = engine.rule_fatigue(plan, statuses, date(2027, 2, 2),
                              {"ratio": 1.7, "atl": 170, "ctl": 100, "history_days": 60}, CFG)
    assert adv and adv[0].severity == "suggest" and adv[0].changes
    assert not engine.rule_fatigue(plan, statuses, date(2027, 2, 2),
                                   {"ratio": 1.7, "atl": 17, "ctl": 10, "history_days": 10}, CFG)  # too little history


def test_demo_runs_end_to_end(tmp_path, monkeypatch):
    from ironman_coach import demo, insights as I
    from ironman_coach.load import fatigue_series
    monkeypatch.setattr(demo, "HOME", tmp_path / "demo")
    import json
    today = date(2026, 11, 19)
    home = demo.build(today)
    cfg = json.loads((home / "config.json").read_text())
    cache = json.loads((home / "data" / "garmin_cache.json").read_text())
    plan = P.load_plan(home / cfg["plan"], date.fromisoformat(cfg["race"]["date"]), "Demo")
    statuses, _ = engine.match(plan, cache["activities"], today, CFG)
    runs = I.recent_insights(cache["activities"], cache["details"], statuses, today)
    f = fatigue_series(cache["activities"], cache["details"], cache["hr_zones"], today)
    signals = engine.recovery_signals(cache["days"][today.isoformat()], None, CFG)
    adv = engine.advise(plan, statuses, signals, today, state(), CFG, cache["activities"], runs, f)
    rules = {a.rule for a in adv}
    assert {"recovery", "missed", "insight"} <= rules
    assert I.easy_efficiency(runs, today)["change_pct"] > 0


def test_no_go_longer_while_easing_off():
    plan = full_plan()
    today = date(2027, 1, 14)
    statuses, _ = engine.match(plan, [], today, CFG)
    longs = [{"session_kind": "long", "decoupling": 2.0, "minutes": 70, "date": "2027-01-10"},
             {"session_kind": "long", "decoupling": 3.0, "minutes": 65, "date": "2027-01-03"}]
    calm = engine.advise(plan, statuses, [], today, state(), CFG, [], longs, None)
    assert any(a.rule == "insight" and a.changes for a in calm)
    hot = engine.advise(plan, statuses, [], today, state(), CFG, [], longs,
                        {"ratio": 1.7, "atl": 170, "ctl": 100, "history_days": 60})
    assert not any(a.rule == "insight" and a.changes for a in hot)


# ---- regressions from bug hunt --------------------------------------------------------
def test_moved_session_counts_in_its_new_week():
    plan = full_plan()
    sun = next(s for s in plan if s.week == 2 and s.sport == "run" and s.kind == "long")
    moved = P.apply_overrides(plan, {sun.id: {"day": (sun.day + timedelta(days=1)).isoformat()}})
    s2 = next(s for s in moved if s.id == sun.id)
    assert s2.week == 3 == P.week_of(s2.day)


def test_hrv_without_baseline_is_not_called_normal():
    sig = engine.recovery_signals({"hrv": {"last_night": 40, "status": None}}, None, CFG)
    hrv = next(g for g in sig if g.name == "HRV")
    assert hrv.level is None and "baseline" in hrv.why


def test_no_drift_verdict_on_interval_runs():
    from ironman_coach.insights import run_insight
    s = next(x for x in full_plan() if x.sport == "run" and x.kind == "intervals")
    laps = [{"m": 1609, "s": 600, "hr": 150}] * 3 + [{"m": 1609, "s": 600, "hr": 175}] * 3
    r = run_insight({"id": 1, "name": "x", "date": s.day.isoformat(), "minutes": 60, "meters": 9600, "avg_hr": 160},
                    {"zone_secs": None, "laps": laps}, s)
    assert not any("drift" in v for v in r["verdict"])


def test_set_swim_accepts_hours(tmp_path, monkeypatch):
    from ironman_coach import cli, state as S
    monkeypatch.setattr(S, "CONFIG", tmp_path / "config.json")
    cli.cmd_set("swim", ["1000", "1:05:00"])
    import json
    assert json.loads((tmp_path / "config.json").read_text())["swim_t_pace_sec"] == 390.0
