"""Local storage. Everything personal lives in data/ (git-ignored)."""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(os.environ.get("IRONMAN_HOME", Path(__file__).resolve().parent.parent))
DATA = ROOT / "data"
CACHE = DATA / "garmin_cache.json"
STATE = DATA / "state.json"
CONFIG = ROOT / "config.json"

DEFAULT_STATE = {
    "overrides": {},   # session_id -> {amount, detail, note, day, dropped, ...}
    "dismissed": [],   # advice ids the user said no to
    "notes": {},       # "YYYY-MM-DD" -> "sick" | "pain" | "tired"
    "busy": {},        # "YYYY-MM-DD" -> minutes available
    "applied_log": [], # history of accepted changes
}

DEFAULT_CONFIG = {
    # Your race and plan. `ironman setup` fills these in.
    "race": {"name": "My race", "date": None},
    "plan": "plans/my-plan.csv",
    # What you can comfortably do today. Used as the starting reference for the
    # long-session gate until your Garmin history shows more.
    "baseline": {"bike_min": 60, "run_min": 30, "swim_yd": 1000},
    "thresholds": {
        "sleep_low_h": 6.0,
        "sleep_very_low_h": 5.0,
        "rhr_elevated_bpm": 5,
        "rhr_high_bpm": 8,
        "gate_ratio": 1.25,
        "done_ratio": 0.8,
        "partial_ratio": 0.3,
        "week_low_compliance": 0.6,
        "week_high_compliance": 1.2,
    },
    "sync_every_hours": 3,
    # Your numbers. null = use what Garmin has. Set with `ironman set ftp 200`.
    "ftp": None,
    # Pace per 100 yd from the 1,000-yd swim test (week 5). Set with `ironman set swim 1000 21:30`.
    "swim_t_pace_sec": None,
    # Carbs per hour you're working toward on long sessions.
    "fuel_g_per_h": {"bike": "60-90", "run": "30-60"},
}


def _load(path: Path, default: dict) -> dict:
    if not path.exists():
        return json.loads(json.dumps(default))
    data = json.loads(path.read_text())
    merged = json.loads(json.dumps(default))
    for k, v in data.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k].update(v)
        else:
            merged[k] = v
    return merged


def load_state() -> dict:
    return _load(STATE, DEFAULT_STATE)


def save_state(state: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2, sort_keys=True))


def load_config() -> dict:
    return _load(CONFIG, DEFAULT_CONFIG)


def load_cache() -> dict | None:
    if not CACHE.exists():
        return None
    return json.loads(CACHE.read_text())


def save_cache(cache: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, indent=2))
