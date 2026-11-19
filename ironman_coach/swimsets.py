"""Break a swim description into a set-by-set table: reps, distance, rest."""
from __future__ import annotations

import re

PART = {"WU": "Warm-up", "main": "Main set", "CD": "Cool-down"}


def _rest(text: str) -> str:
    m = re.search(r"on (\d+)\s*s(?:ec)?", text)
    return f"{m.group(1)}s" if m else ""


def _item(text: str) -> dict | None:
    t = text.strip().rstrip(".")
    if not t:
        return None
    rest = _rest(t)
    m = re.match(r"[Ll]adder ([\d-]+)", t)
    if m:
        dists = [int(x) for x in m.group(1).split("-")]
        return {"set": "Ladder " + "-".join(map(str, dists)), "yd": sum(dists), "rest": rest or "20s",
                "how": "steady; rest after each"}
    m = re.match(r"(\d+)x(\d+)\s*(\w+)?", t)
    if m:
        n, d, word = int(m.group(1)), int(m.group(2)), (m.group(3) or "").lower()
        how = {"drills": "drills (see below)", "pull": "pull buoy", "build": "start easy, get faster each one",
               "easy": "easy"}.get(word, "steady")
        if "continuous" in t:
            how = "continuous, no stopping"
        return {"set": f"{n} x {d}", "yd": n * d, "rest": rest or ("15-20s" if word == "drills" else ""), "how": how}
    m = re.match(r"([\d,]+)\s*(\w+)?", t)
    if m:
        d = int(m.group(1).replace(",", ""))
        word = (m.group(2) or "").lower()
        how = {"easy": "easy", "pull": "pull buoy", "straight": "straight, no stopping"}.get(word, word or "easy")
        if "TEST" in t:
            how = "TEST: hard and even, time it"
        return {"set": f"{d}", "yd": d, "rest": "", "how": how}
    return None


def breakdown(detail: str, total: int) -> tuple[list[dict], int]:
    """Returns rows [{part, set, yd, rest, how}] and the yards they add up to."""
    rows = []
    segs = [s.strip() for s in detail.split(";") if s.strip()]
    for seg in segs:
        part = "Set"
        for key in ("WU", "main", "CD"):
            if seg.startswith(key + " "):
                part, seg = PART[key], seg[len(key) + 1:]
                break
        for piece in re.split(r"\s*\+\s*|,\s*then\s*|\bthen\b", seg):
            it = _item(piece)
            if it:
                rows.append({"part": part, **it})
                part = ""
    return rows, sum(r["yd"] for r in rows)
