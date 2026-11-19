# The rules

Every suggestion the dashboard makes comes from one of these rules in
`ironman_coach/engine.py`, and each rule has tests in `tests/test_rules.py`.
Nothing changes your plan until you run `ironman apply N`.

These are coaching heuristics, not proven science. Where research points one
way, that's noted; the exact thresholds are judgment calls you can change in
`config.json`.

## R1. Sick or in pain
- **Sick** (`ironman note sick`): today's training is dropped. Come back easy.
- **Pain** (`ironman note pain`): runs for the next 3 days become easy rides of the
  same length. Pain that changes how you move or doesn't go away needs a
  professional, not an app.

## R2. Recovery signals
Three signals from Garmin, shown separately. They're never blended into one
"readiness score," because a single number hides which thing is off.

| Signal | Slightly off (1) | Clearly off (2) |
|---|---|---|
| HRV last night | Garmin says UNBALANCED, or below your normal range | Garmin says LOW/POOR, or below your low threshold |
| Sleep | under 6 h | under 5 h |
| Resting HR | 5+ bpm above your 7-day average | 8+ bpm above |

`ironman note tired` adds 1.

- **Total 0-1:** train as planned. One signal alone is noise more often than not.
- **Total 2-3:** intervals become easy Z1-Z2 for the same time; long sessions are cut 25%.
- **Total 4+:** rest, or 30 min very easy.

Why: HRV-guided training studies (e.g. Vesterinen 2016, Javaloyes 2019) back the
idea of easing off when HRV drops below your own baseline, and look at trends
rather than single readings.

## R3. Missed sessions
- Don't make up missed work. Stacking it raises fatigue for little benefit.
- A missed **key** session (long ride/run, straight swim, test) moves to a later day
  this week only if that day is light and isn't next to another key session.
  Otherwise, skip it.

## R4. Week compliance
- If you did under 60% of last week's planned time, this week's long ride and long
  run are held at last week's length instead of progressing.
- Over 120%: a heads-up, no change.

## R5. Long-session gate
- A long session or straight swim in the next 7 days is capped at **125%** of the
  longest you've done in the last 4 weeks (or your starting baseline in
  `config.json`, whichever is bigger).
- Why: big single-session jumps are a common injury and burnout pattern. The 25% is
  a conservative judgment call, not a research-derived limit.

## R6. Busy days
- `ironman busy wed 45`: if a day's training doesn't fit, every session that day
  shrinks proportionally (minimum 20 min). Cut warm-up and cool-down first, and
  keep the main set.

## What counts as "done"
- Done: 80%+ of the planned time (or yards for swims).
- Partial: 30-80%.
- Same sport done a day early or late, on a day with none of that sport planned:
  counts as moved, not missed.
