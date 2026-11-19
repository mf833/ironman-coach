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
- **`ironman runs`**: a report card for every run: time in each heart-rate zone vs
  the plan, heart-rate drift, pace, cadence, splits, and your easy-pace trend.
- **Fatigue tracking**: training load from your heart-rate zones, smoothed into
  fitness and fatigue, so it can tell when you're ramping too fast.
- **Ten rules** that adapt the plan, each with its reason. `ironman history` shows
  every change you accepted and why. All the math is below.
- **Any watch**: Garmin directly, or Coros, Polar, Suunto, Wahoo, Apple Watch and
  others through [intervals.icu](https://intervals.icu) (free).

## Quick start

Already comfortable in a terminal? This is everything:

```bash
git clone https://github.com/mf833/ironman-coach.git
cd ironman-coach
./install.sh          # then open a NEW terminal tab
ironman demo web      # look around with made-up data
ironman setup         # your race, date, plan, watch, miles or km
ironman login         # connect your watch, once
ironman web           # your dashboard at http://localhost:8642
```

New to the terminal? Follow the steps below.

## Step-by-step setup

### 1. Open Terminal

- **Mac**: press <kbd>Cmd</kbd> + <kbd>Space</kbd>, type `Terminal`, press Enter.
- **Linux**: open your terminal app.

Every gray box below is something you copy, paste into Terminal, and press Enter.

### 2. Download the app

```bash
cd ~
git clone https://github.com/mf833/ironman-coach.git
cd ironman-coach
```

If your Mac says `git` isn't installed, it offers to install the developer tools.
Click **Install**, wait, then run the lines again.

### 3. Install

```bash
./install.sh
```

It finds Python 3.12 or newer, or installs it (with uv, Homebrew or conda, whichever
you have), and adds an `ironman` command. It takes a minute or two.

**Then open a new Terminal tab** (<kbd>Cmd</kbd> + <kbd>T</kbd>). The `ironman` command
only exists in new tabs. If you already have something called `ironman`, install it
under another name: `IRONMAN_ALIAS=coach ./install.sh`, then use `coach` everywhere
below.

### 4. Try the demo (optional, 1 minute)

```bash
ironman demo web
```

Your browser opens a dashboard for a made-up runner 6 weeks into a marathon plan,
with improving easy pace, a missed run, easy runs that went too hard and a bad
night's sleep, so you can see every feature. Press <kbd>Ctrl</kbd> + <kbd>C</kbd> in
Terminal to stop it. The demo lives in `~/.ironman-demo` and never touches your
real data.

### 5. Set up your race and plan

```bash
ironman setup
```

It asks a few questions:

| Question | Example | Notes |
|---|---|---|
| Race name | `Lakeside 70.3` | shows at the top of the dashboard |
| Race date | `2027-06-05` | always YYYY-MM-DD |
| Plan | `2` | pick an included plan, or choose "my own CSV" (see [Your plan file](#your-plan-file)) |
| Your watch | `1` | 1 = Garmin, 2 = anything else (through intervals.icu) |
| Miles or km | `mi` | for paces and distances |
| Bike FTP | `220` | optional; press Enter to skip |

An included plan is copied to `plans/my-plan.csv`, so you can edit it freely.
Run `ironman setup` again anytime to change any of this.

### 6. Connect your watch

#### Garmin

```bash
ironman login
```

Type your Garmin Connect email and password. If you use two-step verification,
Garmin emails or texts you a code; type it when asked. That's it: the login is saved
on your computer (`~/.garminconnect`) and refreshes itself. You only do this again
if sync ever says it failed.

#### Coros, Polar, Suunto, Wahoo, Apple Watch and others

These connect through [intervals.icu](https://intervals.icu), a free training site
that already syncs with most watch brands.

1. Make a free account at [intervals.icu](https://intervals.icu).
2. In intervals.icu, go to **Settings > Connections** and connect your watch's app
   (Coros, Polar, Suunto, Wahoo, etc.). For Apple Watch, use an app like HealthFit
   to send workouts to intervals.icu.
3. Wait until your recent workouts show up in intervals.icu.
4. Go to **Settings > Developer Settings**. Copy your **athlete ID** (it looks like
   `i12345`) and click to create an **API key**.
5. Make sure `ironman setup` has your watch set to 2, then run:

```bash
ironman login
```

and paste the athlete ID and API key when asked. They're saved in `config.json`,
which stays on your computer and is never uploaded.

Everything works the same except `ironman send` (workouts to the watch), which is
Garmin-only for now.

### 7. Use it

```bash
ironman            # dashboard in Terminal
ironman today      # exactly what to do today
ironman web        # dashboard in your browser
```

To keep the browser dashboard running all the time (Mac), so you can just open
http://localhost:8642 whenever:

```bash
ironman web --always      # starts when you log in, restarts if it stops
ironman web --stop        # turn that off
```

It syncs your watch data on its own (whenever the last sync is over 3 hours old).
It never sends a workout to your watch unless you press Send or run `ironman send`.

### Updating to the newest version

```bash
cd ~/ironman-coach
git pull
./install.sh
```

Your plan, settings and data are never touched by updates.

### Troubleshooting

| Problem | Fix |
|---|---|
| `command not found: ironman` | open a new Terminal tab, or run `source ~/.zshrc` |
| "Sync failed" on the dashboard | run `ironman login` again |
| "Problem in your plan file" | run `ironman check` to see which line |
| Browser says it can't connect | `ironman web` isn't running; start it, or use `ironman web --always` |
| Mac asks if Terminal can access Documents | say yes; that's how rides get into your Zwift folder |
| Ride didn't show up in Zwift | restart Zwift; look under Workouts > Custom Workouts |
| Something else | run the tests: `.venv/bin/pytest -q`, and open an issue with what you see |

## Your plan file

A plan is a spreadsheet saved as CSV: one row per workout. Make it in Excel,
Google Sheets or Numbers, or start from `plans/template.csv`.

### The columns

| Column | Required? | What to put | Examples |
|---|---|---|---|
| `week` | yes | week number, 1 to N. The **last week is race week**. | `1`, `12` |
| `day` | yes | day of the week | `Mon`, `Tue`, ... `Sun` |
| `sport` | yes | one of: `swim`, `bike`, `run`, `strength`, `race` | `run` |
| `amount` | yes | **minutes**, or **yards** for swims. `0` for the race. | `45`, `90`, `2500` |
| `kind` | no | `easy`, `long`, `intervals`, `test`, `straight`, `brick`, `recovery`, `race` | `long` |
| `phase` | no | a label for the week, shown on the dashboard | `Base`, `Build`, `Taper` |
| `title` | no | a custom name; otherwise one is made from sport and kind | `Hill repeats` |
| `detail` | no, but recommended | the workout itself, in plain words (see below) | `At 15 min: 3x8 min Z3, 4 min easy between` |

Rules of thumb:

- Two workouts on one day = two rows with the same week and day (e.g. a swim and a run,
  or a ride and a brick run).
- Leave rest days out. Any day with no rows is a rest day.
- You don't need dates. Your race date (from `ironman setup`) places week N on race
  week and counts backward, so one plan works for any race.
- Put the race itself in the last week with `sport` = `race`. If you forget, it's
  added automatically on your race date.
- `long`, `test` and `straight` sessions count as key sessions: they're protected
  when things get moved around.

### Writing the detail so the app understands it

You can write anything, but these patterns unlock the extras (watts and heart rate,
swim tables, sending to your watch):

| Workout | Write it like this |
|---|---|
| Zones | `Z2`, `Z3-Z4`, `Z1 building to Z2` |
| Intervals | `At 15 min: 4x5 min Z4, 3 min easy between` |
| A single block | `At 20 min: 20 min Z3` |
| Hill repeats | `Z1-Z2; 6x2 min hill repeats once warm` |
| Run/walk | `Run/walk: 9 min Z2 running / 1 min walking` |
| Tests | `WU 20 min easy; 20 min FTP TEST; 10 min easy` |
| Swim | `WU 200 easy + 4x50 drills; main 8x100 on 20s rest; CD 200 easy` |
| Swim ladder | `main Ladder 25-50-75-100-75-50-25 on 20s` |
| Straight swim | `WU 200 easy; 2000 straight at easy, steady effort; CD 200 easy` |

For swims, split the workout into `WU`, `main` and `CD` with semicolons, and join sets
with `+` or `, then`. Make the sets add up to the `amount` (the checker tells you if
they don't). `4x50 drills` gets two drills picked for you automatically.

### A tiny example plan

| week | day | sport | amount | kind | phase | title | detail |
|---|---|---|---|---|---|---|---|
| 1 | Tue | run | 40 | easy | Base | | Easy, Z1-Z2 |
| 1 | Wed | swim | 1500 | intervals | Base | | WU 200 easy + 4x50 drills; main 9x100 on 20s rest; CD 200 easy |
| 1 | Thu | bike | 60 | intervals | Base | | At 15 min: 3x8 min Z3, 4 min easy between |
| 1 | Sat | bike | 120 | long | Base | | 15 min Z1, then steady Z2 |
| 1 | Sat | run | 15 | brick | Base | | Straight off the bike, easy Z2 |
| 1 | Sun | run | 60 | long | Base | | Easy Z2 |
| 2 | Sat | race | 0 | race | Race | | Race day |

As a raw CSV file, the first lines look like this:

```csv
week,day,sport,amount,kind,phase,title,detail
1,Tue,run,40,easy,Base,,"Easy, Z1-Z2"
1,Wed,swim,1500,intervals,Base,,WU 200 easy + 4x50 drills; main 9x100 on 20s rest; CD 200 easy
```

(Spreadsheet apps add the quotes around details with commas for you.)

### Saving it from a spreadsheet

- **Google Sheets**: File > Download > Comma-separated values (.csv)
- **Excel**: File > Save As > CSV UTF-8 (Comma delimited)
- **Numbers**: File > Export To > CSV

Save it as `plans/my-plan.csv` inside the `ironman-coach` folder (or anywhere, and
give that path in `ironman setup`). Then check it:

```bash
ironman check
```

It reports the number of weeks and sessions, weekly hours, and anything it can't
read, with the exact week and day.

### Included plans

All original and free to use:

- `full-distance-triathlon-20wk.csv`: peaks around 15 h/week, 6-hour ride, 2:30 run
- `half-distance-triathlon-16wk.csv`: peaks around 10 h/week
- `marathon-16wk.csv`: run-only, 4-6 runs a week
- `template.csv`: start your own

Copying a plan from a book or website into a CSV for yourself is fine. Please don't
commit someone else's plan to a public repo.

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
| `ironman runs` | Your recent runs: zones, drift, pace, trend |
| `ironman history` | Every change you applied, and why |
| `ironman set ftp 230` / `ironman set swim 1000 18:30` | Update your numbers after a test |
| `ironman --date 2027-03-20` | Preview any day |
| `ironman demo` | Try everything with made-up data |
| `ironman check` | Check your plan file for mistakes |
| `ironman setup` / `ironman login` | Change your race or plan / reconnect your watch |

## How it works: all the math

Everything here is plain arithmetic in the code, with tests in `tests/`. No AI makes
any decision. Every threshold lives in `config.json` under `thresholds`, so you can
change it. These are coaching heuristics with sensible defaults, not proven
physiology; where research backs an idea, that's noted, and where a number is a
judgment call, that's said too.

### 1. Did you do the session?

Each Garmin or intervals.icu activity is matched to the plan by date and sport.
For swims the unit is yards (meters × 1.0936); otherwise minutes.

$$\text{ratio} = \frac{\text{what you did}}{\text{what was planned}}$$

| ratio | status |
|---|---|
| $\ge 0.8$ | ✓ done |
| $0.3$ to $0.8$ | ◐ partial |
| $< 0.3$ (and the day has passed) | ✕ missed |

If you did that sport a day early or late, on a day with none of it planned, it
counts as **moved**, not missed.

### 2. Zones: from "Z2" to numbers

**Bike power**, as a percent of FTP (the standard Coggan zones):

| Zone | % of FTP | Feels like |
|---|---|---|
| Z1 | under 55% | RPE 1-2, could do it all day |
| Z2 | 56-75% | RPE 3-4, full sentences |
| Z3 | 76-90% | RPE 5-6, short sentences |
| Z4 | 91-105% | RPE 7-8, a few words |
| Z5 | 106-120% | RPE 9, no talking |

So with FTP 200 W, Z2 is $200 \times 0.56$ to $200 \times 0.75$ = 112-150 W.

**Heart rate** comes straight from the zones set on your watch account (Garmin or
intervals.icu), per sport. **Swim pace** comes from your 1,000-yard test:

$$T = \frac{\text{1,000-yd time in seconds}}{10} \text{ seconds per 100 yd}$$

with Z1 at $T + 15$ to $T + 25$ s, Z2 at $T + 8$ to $T + 15$, Z3 at $T + 3$ to $T + 8$,
Z4 at $T$ to $T + 3$, Z5 faster than $T$.

### 3. Recovery signals (shown one by one, never blended)

Each signal gets a level: 0 normal, 1 slightly off, 2 clearly off.

| Signal | 1 = slightly off | 2 = clearly off |
|---|---|---|
| HRV last night | below your normal range (or Garmin says UNBALANCED) | below your low threshold (or Garmin says LOW/POOR) |
| Sleep | under 6 h | under 5 h |
| Resting HR | $\ge 5$ bpm above your 7-day average | $\ge 8$ bpm above |
| `ironman note tired` | 1 | |

**Your HRV "normal range"**: Garmin calculates it for you. With intervals.icu, the
app calculates it from your previous 28 nights (needs at least 7):

$$\text{normal} = \bar{x} \pm s, \qquad \text{low threshold} = \bar{x} - 2s$$

where $\bar{x}$ is the average and $s$ the standard deviation of those nights.

The levels are added up into $L$, and only today's unfinished sessions change:

| $L$ | what happens |
|---|---|
| 0-1 | train as planned (one signal alone is usually noise) |
| 2-3 | intervals and tests become easy Z1-Z2 for the same time; long sessions are cut 25% |
| 4+ | rest, or 30 minutes very easy |

Why: studies of HRV-guided training (e.g. Vesterinen 2016, Javaloyes 2019) back
easing off when HRV drops below your own baseline. The exact cutoffs are judgment calls.

### 4. Fatigue and fitness

Every activity gets a **training load**, weighted by heart-rate zone (Edwards' TRIMP):

$$\text{load} = \sum_{i=1}^{5} i \times (\text{minutes in zone } i)$$

So 60 minutes all in Z2 is $2 \times 60 = 120$. Activities with no zone data (most
swims) count as Z2, or the zone of your average heart rate if there is one.

Each day's loads are smoothed into two running averages:

$$\text{fatigue}_t = \text{fatigue}_{t-1} + \frac{\text{load}_t - \text{fatigue}_{t-1}}{7}$$

$$\text{fitness}_t = \text{fitness}_{t-1} + \frac{\text{load}_t - \text{fitness}_{t-1}}{42}$$

Fatigue reacts within a week; fitness takes about six. Their ratio says how fast
you're ramping:

$$r = \frac{\text{fatigue}}{\text{fitness}}$$

| $r$ | what happens |
|---|---|
| under 1.3 | nothing, normal training |
| 1.3 to 1.5 | a heads-up: keep easy days easy |
| over 1.5 | suggests easing the next two days: intervals become easy, other sessions 30% shorter |

It only kicks in after 28 days of history and a fitness above 10, so a first week of
data can't trigger it. This is the idea behind TrainingPeaks' fitness/fatigue chart
and the "acute:chronic workload ratio." Research on exact injury cutoffs is mixed,
so treat it as a warning light, not a verdict.

### 5. Run report cards

**Time in zones**: seconds in each heart-rate zone, as percentages. For easy, long and
recovery runs planned in zones up to $Z_{top}$:

$$\text{above} = \sum_{i > top} \text{zone}_i\,\% \qquad \text{in target} = \sum_{i \in \text{planned}} \text{zone}_i\,\%$$

If $\text{above} \ge 25\%$, the card says the run was too hard.

**Heart-rate drift** (aerobic decoupling): split the run into two halves by time and
compare how far you go per heartbeat in each:

$$EF = \frac{\text{speed}}{\text{heart rate}}, \qquad \text{drift} = \frac{EF_1 - EF_2}{EF_1} \times 100\%$$

If your heart rate rises while your pace doesn't, $EF_2 < EF_1$ and drift is positive.
intervals.icu calculates this itself from second-by-second data; with Garmin the
app uses your mile or km splits. It's only shown for runs of 45+ minutes.

| drift | meaning |
|---|---|
| under 0% | you got faster at the same effort |
| 0-5% | aerobic engine held steady |
| 5-10% | moderate; normal for long or hot runs |
| over 10% | usually starting too fast, under-fueling, or heat |

The under-5% line is a widely used endurance-coaching guideline (popularized by Joe
Friel), not a lab standard.

**Easy-pace trend** (real fitness, not just finished workouts): for easy runs (at least
20 minutes, 60%+ in Z1-Z2),

$$EF = \frac{\text{distance per minute}}{\text{average heart rate}}$$

The average $EF$ of the last 14 days is compared with 15-42 days ago, and turned into a
pace at your typical easy heart rate $HR_{ref}$ (the median of those runs):

$$\text{pace at } HR_{ref} = \frac{1}{EF \times HR_{ref}} \qquad \text{change} = \frac{\overline{EF}_{now}}{\overline{EF}_{then}} - 1$$

Same heart rate, faster pace = fitter.

### 6. The rules: should anything change?

| # | Rule | Fires when | What it suggests |
|---|---|---|---|
| R1 | Sick | `note sick` today or yesterday | drop today's training |
| R1 | Pain | `note pain` today or yesterday | next 3 days of runs become easy rides |
| R2 | Recovery | $L \ge 2$ (section 3) | easier or shorter today |
| R3 | Missed | a session missed in the last 3 days | let it go; key sessions move only to a light day (≤ 60 min planned) this week that isn't next to another key session |
| R4 | Bad week | you did under 60% of last week's planned time | hold this week's long ride and run at last week's length |
| R5 | Long-session cap | a long session or straight swim in the next 7 days is over 125% of your longest in 4 weeks | cap it at 125% |
| R6 | Busy | `busy wed 45` and the day doesn't fit | shrink each session proportionally (min 20 min) |
| R7 | Easy too hard | 2 of your last 3 easy runs were 25%+ above zone | a heads-up to slow down |
| R8 | High drift | last long run drifted over 10% | pacing, fueling and heat tips |
| R9 | Base ready | last 2 long runs drifted under 5% | optionally extend the next long run 10% |
| R10 | Fatigue | $r > 1.5$ (section 4) | ease the next two days |

"Week compliance" for R4 is

$$\frac{\sum \min(\text{ratio}, 1.2) \times \text{planned minutes}}{\sum \text{planned minutes}}$$

so overdoing one session can't hide a missed one. Swims are converted to minutes at
2.4 min per 100 yd.

The long-session cap (R5) is

$$\text{cap} = 1.25 \times \max(\text{longest in the last 28 days},\ \text{your baseline})$$

rounded to 5 minutes or 100 yards. The baseline in `config.json` is what you can
comfortably do on day one, so a new user isn't capped at zero. Big single-session
jumps are a common injury pattern; the 25% itself is a conservative judgment call.

When two rules touch the same session, the stricter one wins, and you only see it once.

### 7. Why it changed

- Every suggestion shows **why** (the numbers that triggered it) and **exactly what
  changes**.
- Nothing changes until you `apply` it. `dismiss` hides it; `undo` reverses the last change.
- Changed sessions are marked "adjusted" with the reason, everywhere.
- `ironman history` lists every change you accepted, when, and why.

## Honest limits

- Garmin sync uses the unofficial [`garminconnect`](https://github.com/cyberjunky/python-garminconnect)
  library. It works well, but Garmin has broken unofficial tools before. If sync
  fails, run `ironman login` again or update: `.venv/bin/pip install -U garminconnect`.
- The rules are coaching heuristics with documented thresholds, not medical advice
  or a substitute for a coach. Pain that changes how you move needs a professional.
- The intervals.icu connection follows its public API. Field names were checked
  against its docs and community clients; report anything that looks off.
- Fatigue and fitness need a few weeks of synced history before they mean much.
- The example plans are generic. They don't know your history, injuries or schedule.

## Tests

```bash
.venv/bin/pytest -q
```

## License

MIT
