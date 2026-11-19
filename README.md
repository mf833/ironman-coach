# ironman-coach

Your training plan, your Garmin data, and a handful of simple, testable rules, in
your terminal or your browser. It tells you what to do today (with watts, heart
rate, swim sets and drills), checks what you actually did, and suggests changes
when your recovery or your week says so. **Nothing changes unless you say yes.**

Works for any plan: full or half IRONMAN, marathon, run-only, whatever you put in
the plan file. No AI required, no accounts, nothing in the cloud.

## What you get

- **`ironman`**: dashboard with today, recovery signals (HRV, sleep, resting HR,
  each shown on its own, no made-up readiness score), suggestions, your week,
  progress and milestones.
- **`ironman today`**: exactly what to do: the workout, zones in watts and bpm,
  swim set-by-set tables with rests, drills, fueling.
- **`ironman web`**: the same dashboard as a page in your browser. It stays running
  and syncs Garmin by itself. `ironman web --always` keeps it on whenever you're
  logged in (macOS), at http://localhost:8642.
- **`ironman send`**: swims and interval runs go to your Garmin workouts and watch;
  rides become Zwift workout files. Only when you ask: it never sends on its own.
- **Six rules** that adapt the plan (sick or pain, recovery signals, missed sessions,
  bad weeks, long-session jumps, busy days). See [RULES.md](RULES.md).

## Setup

You need a Mac or Linux computer with Python 3.12+ (the installer finds or
installs it).

```bash
git clone https://github.com/YOUR-NAME/ironman-coach.git
cd ironman-coach
./install.sh          # then open a new terminal tab
ironman setup         # race name, race date, pick a plan
ironman login         # Garmin email + password (+ 2FA code), once
ironman               # or: ironman web
```

Your Garmin login is stored only on your computer (`~/.garminconnect`), and all
your data lives in `data/`, which git ignores.

## Plans

Plans are CSV files in `plans/`, one row per session. Open them in Excel, Numbers
or Google Sheets.

| week | day | sport | amount | kind | phase | title | detail |
|---|---|---|---|---|---|---|---|
| 1 | Tue | swim | 1500 | intervals | Base | | WU 200 easy + 4x50 drills; main 9x100 on 20s rest; CD 200 easy |
| 1 | Wed | bike | 60 | intervals | Base | | At 15 min: 3x8 min Z3, 4 min easy between |
| 1 | Sun | run | 45 | long | Base | | Easy Z2 |

- **week**: 1 to N. The last week is race week. Your race date sets the calendar,
  so the same plan works for any race.
- **day**: Mon to Sun. **sport**: swim, bike, run, strength or race.
- **amount**: minutes, or yards for swims.
- **kind** (optional): easy, long, intervals, test, straight, brick, recovery.
  Long sessions, tests and straight swims are treated as key sessions.
- **detail**: the workout. Write zones like `Z2` or `Z3-Z4` and they turn into
  watts and heart rate. Write swims as `WU ...; main ...; CD ...` with sets like
  `6x100 on 20s rest` and they become set-by-set tables and Garmin workouts.

Included, original and free to use:

- `full-distance-triathlon-20wk.csv`: peaks around 15 h/week, 6-hour ride, 2:30 run
- `half-distance-triathlon-16wk.csv`: peaks around 10 h/week
- `marathon-16wk.csv`: run-only, 4-6 runs a week
- `template.csv`: start your own

Copying a plan from a book or website into a CSV for yourself is fine. Please
don't commit someone else's plan to a public repo.

## Daily commands

| Command | What it does |
|---|---|
| `ironman` | Dashboard |
| `ironman today` / `ironman today tomorrow` | What to do, in detail |
| `ironman web` | Dashboard in your browser |
| `ironman send` / `ironman send sat` | Workout to your watch, or ride to Zwift |
| `ironman apply 2` / `ironman dismiss 2` / `ironman undo` | Take, skip, or undo a suggestion |
| `ironman note tired` (or `sick`, `pain`, `clear`) | Tell it how you feel |
| `ironman busy wed 45` | Only 45 minutes on Wednesday |
| `ironman swap tue wed` / `ironman move sat sun` | Rearrange days |
| `ironman week next` / `ironman week 12` | Look ahead |
| `ironman set ftp 230` / `ironman set swim 1000 18:30` | Update your numbers after a test |
| `ironman --date 2027-03-20` | Preview any day |

## Honest limits

- Garmin sync uses the unofficial [`garminconnect`](https://github.com/cyberjunky/python-garminconnect)
  library. It works well, but Garmin has broken unofficial tools before. If sync
  fails, run `ironman login` again or update: `.venv/bin/pip install -U garminconnect`.
- The rules are coaching heuristics with documented thresholds, not medical advice
  or a substitute for a coach. Pain that changes how you move needs a professional.
- The example plans are generic. They don't know your history, injuries or schedule.

## Tests

```bash
.venv/bin/pytest -q
```

## License

MIT
