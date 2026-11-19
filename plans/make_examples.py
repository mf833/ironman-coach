"""Generates the example plans in this folder. Run: python plans/make_examples.py

These are original, conservative, finish-focused example plans: aerobic base,
3 weeks up / 1 week down, intensity added gradually, a 2-week taper. They are
starting points, not personalized coaching. Edit the CSVs freely.
"""
import csv
from pathlib import Path

HERE = Path(__file__).parent
FIELDS = ["week", "day", "sport", "amount", "kind", "phase", "title", "detail"]
CORE = "Core and hips, 2-3 rounds: plank, side plank, glute bridge, single-leg squat, calf raise"


def swim_a(yd, drills=8):
    main = yd - 400 - drills * 50
    return f"WU 200 easy + {drills}x50 drills; main {main // 100}x100 on 20s rest; CD 200 easy"


def swim_b(yd):
    main = yd - 600
    for d in (500, 400, 300, 200, 100):
        if main % d == 0 and 2 <= main // d <= 8:
            return f"WU 200 easy + 4x50 drills; main {main // d}x{d} on 30s rest; CD 200 easy"
    return f"WU 200 easy + 4x50 drills; main {main // 100}x100 on 20s rest; CD 200 easy"


def straight(yd):
    return f"WU 200 easy; {yd - 400} straight at easy, steady effort; CD 200 easy"


def test_swim():
    return "WU 300 easy; 1000 TEST: hard and even, time it; CD 200 easy"


def triathlon(name, weeks, phases, recovery, long_ride, long_run, swim_a_yd, swim_b_yd,
              straight_weeks, test_weeks, ftp_week, brick_from, peak_week):
    rows = []
    add = lambda w, d, sp, amt, kind, title, detail: rows.append(
        dict(week=w, day=d, sport=sp, amount=amt, kind=kind, phase=phases(w), title=title, detail=detail))
    for w in range(1, weeks):
        rec = w in recovery
        build = w >= brick_from and not rec
        taper = w > peak_week
        # Tue: swim A + easy run
        if w in test_weeks:
            add(w, "Tue", "swim", 1500, "test", "", test_swim())
        else:
            add(w, "Tue", "swim", swim_a_yd[w - 1], "intervals", "", swim_a(swim_a_yd[w - 1]))
        add(w, "Tue", "run", 30 if rec or taper else min(30 + 5 * (w // 4), 45), "easy", "", "Easy, Z1-Z2, conversational")
        # Wed: bike
        if w == ftp_week:
            add(w, "Wed", "bike", 55, "test", "", "WU 20 min easy with 3x1 min hard; 20 min FTP TEST; 10 min easy")
        elif rec or w < brick_from - 4:
            add(w, "Wed", "bike", 60, "easy", "", "Z2, with 5x1 min high cadence (100+ rpm) in the middle, 2 min easy between")
        elif taper:
            add(w, "Wed", "bike", 60, "intervals", "", "At 15 min: 3x5 min Z3, 3 min easy between")
        elif w < brick_from:
            add(w, "Wed", "bike", 60, "intervals", "", "At 15 min: 3x6 min Z3, 3 min easy between")
        else:
            reps = 3 if w < peak_week - 3 else 4
            add(w, "Wed", "bike", 75, "intervals", "", f"At 15 min: {reps}x10 min Z3, 5 min easy between")
        # Thu: swim B + run
        if w in straight_weeks:
            add(w, "Thu", "swim", swim_b_yd[w - 1], "straight", "", straight(swim_b_yd[w - 1]))
        else:
            add(w, "Thu", "swim", swim_b_yd[w - 1], "intervals", "", swim_b(swim_b_yd[w - 1]))
        if build and not taper:
            add(w, "Thu", "run", 50, "intervals", "", "At 15 min: 3x6 min Z3, 3 min easy between")
        else:
            add(w, "Thu", "run", 35 if rec else 40, "easy", "", "Easy, Z1-Z2")
        # Fri: strength
        if not taper:
            add(w, "Fri", "strength", 20 if rec else 25, "easy", "Strength", CORE)
        # Sat: long ride (+ brick)
        add(w, "Sat", "bike", long_ride[w - 1], "long", "", "15 min Z1, then steady Z2. Practice fueling.")
        if build and not taper:
            add(w, "Sat", "run", 15 if w < peak_week - 3 else 20, "brick", "", "Straight off the bike, easy Z2")
        # Sun: long run
        add(w, "Sun", "run", long_run[w - 1], "long", "", "Easy Z2. Run/walk is fine (e.g. 9 min run / 1 min walk).")
    w = weeks  # race week
    add(w, "Tue", "swim", 1200, "easy", "", "WU 200 easy + 4x50 drills; main 6x100 on 20s rest; CD 200 easy")
    add(w, "Wed", "bike", 45, "intervals", "", "At 15 min: 3x2 min Z3, 3 min easy between")
    add(w, "Thu", "run", 20, "easy", "", "Easy, a few relaxed strides at the end")
    add(w, "Fri", "swim", 600, "easy", "Shakeout swim", "600 easy; open water on the course if allowed")
    add(w, "Sat", "race", 0, "race", "", "Race day. Start easy, fuel early, trust the training.")
    return rows


def write(path, rows):
    with open(path, "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=FIELDS)
        wr.writeheader()
        wr.writerows(rows)
    print(f"wrote {path.name}: {len(rows)} sessions")


def full():
    ph = lambda w: "Base" if w <= 8 else "Build" if w <= 15 else "Peak" if w <= 17 else "Taper" if w <= 19 else "Race"
    return triathlon(
        "full", 20, ph, recovery={4, 8, 12, 16},
        long_ride=[90, 105, 120, 85, 135, 150, 165, 110, 180, 210, 240, 165, 270, 300, 330, 240, 360, 240, 150],
        long_run=[45, 50, 55, 40, 60, 65, 75, 50, 80, 90, 100, 70, 110, 120, 135, 90, 150, 100, 70],
        swim_a_yd=[1500, 1600, 1700, 1300, 1800, 1900, 2000, 1500, 2200, 2400, 2500, 1800, 2600, 2800, 3000, 2200, 3000, 2400, 1800],
        swim_b_yd=[1600, 1800, 2000, 1400, 2200, 2400, 2600, 1800, 2800, 3000, 3200, 2400, 3400, 3600, 3800, 2600, 4200, 3000, 2000],
        straight_weeks={3, 7, 11, 15, 17}, test_weeks={1, 9}, ftp_week=9, brick_from=9, peak_week=17)


def half():
    ph = lambda w: "Base" if w <= 6 else "Build" if w <= 12 else "Peak" if w <= 13 else "Taper" if w <= 15 else "Race"
    return triathlon(
        "half", 16, ph, recovery={4, 8, 12},
        long_ride=[60, 75, 90, 60, 100, 110, 120, 80, 135, 150, 165, 110, 180, 120, 75],
        long_run=[40, 45, 50, 35, 55, 60, 65, 45, 70, 80, 90, 60, 100, 70, 50],
        swim_a_yd=[1200, 1300, 1400, 1100, 1500, 1600, 1700, 1300, 1800, 1900, 2000, 1500, 2100, 1700, 1300],
        swim_b_yd=[1400, 1600, 1800, 1400, 2000, 2200, 2400, 1800, 2400, 2600, 2600, 2000, 2400, 2000, 1600],
        straight_weeks={3, 7, 11, 13}, test_weeks={1, 7}, ftp_week=7, brick_from=7, peak_week=13)


def marathon():
    rows = []
    ph = lambda w: "Base" if w <= 5 else "Build" if w <= 11 else "Peak" if w <= 13 else "Taper" if w <= 15 else "Race"
    long_run = [60, 70, 80, 60, 90, 100, 110, 80, 120, 135, 150, 105, 165, 120, 80]
    recovery = {4, 8, 12}
    add = lambda w, d, amt, kind, detail, title="": rows.append(
        dict(week=w, day=d, sport="run", amount=amt, kind=kind, phase=ph(w), title=title, detail=detail))
    for w in range(1, 16):
        rec, taper = w in recovery, w >= 14
        add(w, "Tue", 40 if not rec else 30, "easy", "Easy, Z1-Z2")
        if w == 1 or w == 9:
            add(w, "Wed", 55, "test", "WU 10 min easy; 30 min LTHR TEST; 10 min easy")
        elif rec:
            add(w, "Wed", 40, "easy", "Easy, Z2, with 6x20s relaxed strides at the end")
        elif w <= 5:
            add(w, "Wed", 50, "intervals", "At 15 min: 15 min Z3")
        elif taper:
            add(w, "Wed", 45, "intervals", "At 15 min: 4x3 min Z4, 2 min easy between")
        elif w % 2:
            add(w, "Wed", 60, "intervals", "At 15 min: 6x3 min Z4, 2 min easy between")
        else:
            add(w, "Wed", 60, "intervals", "At 15 min: 25 min Z3")
        add(w, "Thu", 40 if not rec else 30, "easy", "Easy, Z1-Z2")
        if not taper:
            rows.append(dict(week=w, day="Fri", sport="strength", amount=25, kind="easy", phase=ph(w),
                             title="Strength", detail=CORE))
        add(w, "Sat", 30 if rec or taper else 45, "easy", "Easy, Z1-Z2")
        add(w, "Sun", long_run[w - 1], "long", "Easy Z2. Last 15 min at goal-race effort from week 9 on.")
    add(16, "Tue", 30, "easy", "Easy with 4x20s strides")
    add(16, "Thu", 20, "easy", "Easy, a few relaxed strides")
    rows.append(dict(week=16, day="Sun", sport="race", amount=0, kind="race", phase="Race", title="",
                     detail="Race day. Start slower than you want to."))
    return rows


if __name__ == "__main__":
    write(HERE / "full-distance-triathlon-20wk.csv", full())
    write(HERE / "half-distance-triathlon-16wk.csv", half())
    write(HERE / "marathon-16wk.csv", marathon())
    with open(HERE / "template.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=FIELDS)
        wr.writeheader()
        wr.writerow(dict(week=1, day="Tue", sport="swim", amount=1500, kind="intervals", phase="Base", title="",
                         detail="WU 200 easy + 4x50 drills; main 9x100 on 20s rest; CD 200 easy"))
        wr.writerow(dict(week=1, day="Wed", sport="bike", amount=60, kind="intervals", phase="Base", title="",
                         detail="At 15 min: 3x8 min Z3, 4 min easy between"))
        wr.writerow(dict(week=1, day="Sun", sport="run", amount=45, kind="long", phase="Base", title="",
                         detail="Easy Z2"))
        wr.writerow(dict(week=2, day="Sat", sport="race", amount=0, kind="race", phase="Race", title="",
                         detail="Race day"))
    print("wrote template.csv")
