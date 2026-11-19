"""Swim drills for a plan's "8x50 drills" sets.

Six classic freestyle drills, ordered for the most common beginner problems:
lifting the head to breathe, a sinking lead arm, and form falling apart when
tired. Rotation and a long lead arm come first; catch work comes later.
"""
from __future__ import annotations

import re

DRILLS = {
    "6-Kick Switch": {
        "how": "Push off in a streamline. One stroke, rotate onto your side, and kick 6 times with one arm overhead "
               "and the other at your side. Keep head, hands, hips and heels in a line, take a quick breath, "
               "then take the next stroke and rotate to the other side for 6 kicks.",
        "why": "Rotation, so you breathe by rolling instead of lifting your head.",
        "gear": "fins optional, they keep your hips up",
    },
    "Catch-Up": {
        "how": "One stroke at a time: the recovering hand 'catches up' to the lead hand before the next stroke starts. "
               "Elbow high before entry, hand enters shoulder-width apart. Long, smooth strokes, small steady kick.",
        "why": "Keeps your lead arm out front while you breathe instead of letting it sink.",
        "gear": "kickboard out front optional",
    },
    "Finger Tip Drag": {
        "how": "Normal freestyle, but on each recovery lift the elbow high and drag your fingertips along the surface "
               "until the hand enters. Keep rotating.",
        "why": "High-elbow recovery and a cleaner hand entry, which sets up a stronger pull.",
        "gear": "",
    },
    "Single Arm": {
        "how": "Stroke with one arm, other arm extended in front. Rotate hips and shoulders, breathe to the stroking "
               "side. Full length one arm, then switch. Harder version: resting arm at your side.",
        "why": "Balance and rotation on each side; practice breathing without dropping the front arm.",
        "gear": "",
    },
    "3-Stroke Glide (6/3/6)": {
        "how": "Push off, one stroke onto your side, 6 kicks, then 3 long smooth strokes, rotate to the other side "
               "and 6 kicks. Repeat for the length.",
        "why": "Holds your rotation and length when you get tired, the exact point where your form breaks.",
        "gear": "",
    },
    "Fist": {
        "how": "Freestyle with closed fists and high elbows, steady kick. Open your hands for the last 25 and feel "
               "the difference.",
        "why": "Forces you to catch and pull with your forearm, not just your hand.",
        "gear": "tennis balls instead of fists optional",
    },
}

# Two drills per session, never more. Early-week and late-week swims get different
# pairs. Pairs get harder as the plan goes on (first third, middle, last third).
PAIRS = [
    (0.0, 0.34, [["6-Kick Switch", "Catch-Up"], ["Catch-Up", "Finger Tip Drag"]]),
    (0.34, 0.67, [["6-Kick Switch", "3-Stroke Glide (6/3/6)"], ["Catch-Up", "Single Arm"]]),
    (0.67, 1.01, [["3-Stroke Glide (6/3/6)", "Fist"], ["Catch-Up", "Single Arm"]]),
]
COOLDOWN = ["Catch-Up"]  # one easy drill to finish


def drill_sets(detail: str, week: int, late_week: bool = False) -> list[dict]:
    """For each 'NxM drills' in a swim description, say which drills and how many of each."""
    from .plan import num_weeks
    frac = (week - 1) / max(1, num_weeks())
    pair = next(p for lo, hi, p in PAIRS if lo <= frac < hi)[1 if late_week else 0]
    out = []
    for seg in detail.split(";"):
        m = re.search(r"(\d+)x(\d+) drills", seg)
        if not m:
            continue
        n, dist = int(m.group(1)), int(m.group(2))
        part = "cool-down" if seg.strip().startswith("CD") else "warm-up"
        names = COOLDOWN if part == "cool-down" else pair[:n]
        out.append({"part": part, "reps": n, "dist": dist, "per": max(1, n // len(names)), "drills": names})
    return out
