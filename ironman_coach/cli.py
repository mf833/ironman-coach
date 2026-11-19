"""`ironman` command line."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from rich.console import Console

from . import engine, garmin, plan as P, state as S
from .dashboard import render, week_table

console = Console()
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def parse_day(s: str, today: date) -> date:
    s = s.lower()
    if s == "today":
        return today
    if s == "tomorrow":
        return today + timedelta(days=1)
    if s[:3] in WEEKDAYS:
        ahead = (WEEKDAYS.index(s[:3]) - today.weekday()) % 7
        return today + timedelta(days=ahead)
    return date.fromisoformat(s)


def maybe_sync(cfg, force=False, quiet=False) -> tuple[dict | None, str | None]:
    cache = S.load_cache()
    fresh = cache and datetime.now() - datetime.fromisoformat(cache["synced_at"]) < timedelta(hours=cfg["sync_every_hours"])
    if fresh and not force:
        return cache, None
    try:
        def _do():
            if cfg.get("source") == "intervals":
                from . import intervals
                return intervals.sync(cfg)
            return garmin.sync(previous=cache)
        if quiet:
            cache = _do()
        else:
            with console.status("Syncing your watch data…"):
                cache = _do()
        S.save_cache(cache)
        st = S.load_state()
        bests = st.setdefault("bests", {})
        for a in cache["activities"]:
            bests[a["sport"]] = max(bests.get(a["sport"], 0), round(engine.activity_amount(a)))
        S.save_state(st)
        return cache, None
    except Exception as e:  # keep the dashboard usable offline
        return cache, f"{type(e).__name__}: {str(e)[:120]}"


class NotSetUp(Exception):
    pass


def load_plan(cfg) -> list:
    race = cfg.get("race") or {}
    if not race.get("date"):
        raise NotSetUp("No race date yet.")
    path = S.ROOT / cfg["plan"] if not Path(cfg["plan"]).is_absolute() else Path(cfg["plan"])
    if not path.exists():
        raise NotSetUp(f"Plan file not found: {path}")
    return P.load_plan(path, date.fromisoformat(race["date"]), race.get("name") or "Race")


def build(today: date, sync=True, force=False, quiet=False) -> dict:
    cfg, st = S.load_config(), S.load_state()
    base_plan = load_plan(cfg)
    cache, err = maybe_sync(cfg, force, quiet) if sync else (S.load_cache(), None)
    st = S.load_state()
    cache = cache or {"activities": [], "days": {}}
    plan = P.apply_overrides(base_plan, st["overrides"])
    statuses, extras = engine.match(plan, cache["activities"], today, cfg)
    from . import insights as I
    runs = I.recent_insights(cache["activities"], cache.get("details") or {}, statuses, today, cfg.get("units", "mi"))
    signals = engine.recovery_signals(cache["days"].get(today.isoformat()), st["notes"].get(today.isoformat()), cfg)
    from .load import fatigue_series
    fatigue = fatigue_series(cache["activities"], cache.get("details") or {}, cache.get("hr_zones") or {}, today)
    advice = engine.advise(plan, statuses, signals, today, st, cfg, cache["activities"], runs, fatigue)
    st["last_advice"] = [{"id": a.id, "title": a.title, "why": a.why, "changes": a.changes} for a in advice]
    S.save_state(st)
    return {"today": today, "plan": plan, "statuses": statuses, "extras": extras, "signals": signals,
            "advice": advice, "activities": cache["activities"], "synced_at": cache.get("synced_at", "")[:16].replace("T", " "),
            "sync_error": err, "cache": cache, "runs": runs, "fatigue": fatigue, "efficiency": I.easy_efficiency(runs, today), "bests": _bests(st, cache["activities"])}


def _bests(st: dict, activities: list) -> dict:
    out = dict(st.get("bests", {}))
    for a in activities:
        out[a["sport"]] = max(out.get(a["sport"], 0), round(engine.activity_amount(a)))
    return out


def cmd_apply(n: int, dismiss=False, say=None):
    say = say or console.print
    st = S.load_state()
    items = st.get("last_advice", [])
    if not 1 <= n <= len(items):
        say("[red]No suggestion with that number. Run `ironman` first.[/]")
        return
    a = items[n - 1]
    if dismiss:
        st["dismissed"].append(a["id"])
        say(f"Dismissed: {a['title']}. The plan stays as it is.")
    elif not a["changes"]:
        say("That one's just information; nothing to apply.")
        return
    else:
        before = {sid: st["overrides"].get(sid) for sid in a["changes"]}
        for sid, ch in a["changes"].items():
            st["overrides"].setdefault(sid, {}).update(ch)
        st["dismissed"].append(a["id"])
        st["applied_log"].append({"at": datetime.now().isoformat(timespec="seconds"), "id": a["id"],
                                  "title": a["title"], "why": a.get("why", ""), "before": before})
        say(f"[green]Applied:[/] {a['title']}. Run `ironman undo` to take it back.")
    S.save_state(st)


def cmd_undo(say=None):
    say = say or console.print
    st = S.load_state()
    if not st["applied_log"]:
        say("Nothing to undo.")
        return
    last = st["applied_log"].pop()
    for sid, prev in last["before"].items():
        if prev is None:
            st["overrides"].pop(sid, None)
        else:
            st["overrides"][sid] = prev
    if last["id"] in st["dismissed"]:
        st["dismissed"].remove(last["id"])
    S.save_state(st)
    say(f"Undid: {last['title']}")


def push_to_watch(api, workout_id: int, name: str) -> bool:
    """Same as 'Send to device' in the Garmin app. Best effort."""
    try:
        dev = api.get_device_last_used() or {}
        device_id = dev.get("userDeviceId") or dev.get("deviceId")
        if not device_id:
            return False
        payload = [{"deviceId": device_id, "messageUrl": f"workout-service/workout/FIT/{workout_id}",
                    "messageType": "workouts", "messageName": name, "groupName": None, "priority": 1,
                    "fileType": "FIT", "metaDataId": workout_id}]
        api.client.post("connectapi", "/device-service/devicemessage/messages", json=payload, api=True)
        return True
    except Exception:
        return False


def cmd_send(ctx, day: date, say=None):
    say = say or console.print
    from . import workouts as W
    from .drills import drill_sets
    sessions = [s for s in ctx["plan"] if s.day == day and s.sport in ("swim", "run", "bike")]
    if not sessions:
        say(f"Nothing to send for {day:%a %b %d}: it's a rest day.")
        return
    st = S.load_state()
    sent = st.setdefault("sent", {})
    api = None
    garmin_ok = S.load_config().get("source", "garmin") == "garmin"
    for s in sessions:
        if s.sport == "bike":
            folder = W.zwift_folder()
            out_dir = folder or (S.ROOT / "zwift")
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / f"ironman-{s.day.isoformat()}.zwo"
            path.write_text(W.zwo(s))
            if folder:
                say(f"[green]Zwift:[/] {s.title} {s.label()} saved. In Zwift: Workouts > Custom Workouts (restart Zwift if it was open).")
            else:
                say(f"[yellow]Zwift:[/] couldn't find your Zwift workouts folder, so it's in {path}. "
                              "Copy it to Documents/Zwift/Workouts/<your number>/.")
            continue
        if not garmin_ok:
            say(f"{s.title}: sending to the watch works with Garmin only for now. Use `ironman today` for the details.")
            continue
        if s.sport == "run":
            plan = W.structure(s.detail, s.amount)
            if plan is None:
                say(f"Run: {s.label()} {s.detail}. It's just time, so nothing to send. Start a normal run.")
                continue
            body = W.run_workout(s, plan)
        else:
            late = s.day.weekday() >= 3
            names = [d["drills"] for d in drill_sets(s.detail, s.week, late)]
            body = W.swim_workout(s, names)
        try:
            api = api or garmin.connect()
            wid = sent.get(s.id)
            if not wid:
                res = api.upload_workout(body)
                wid = res.get("workoutId")
                sent[s.id] = wid
                S.save_state(st)
            ok = push_to_watch(api, wid, body["workoutName"])
            if ok:
                say(f"[green]Sent to your watch:[/] {body['workoutName']}. It shows up after your watch syncs "
                              "(open the Garmin Connect app). On the watch: Training > Workouts.")
            else:
                say(f"[green]Saved to Garmin workouts:[/] {body['workoutName']}. In the Garmin Connect app: "
                              "Training > Workouts > tap it > Send to device.")
        except Exception as e:
            say(f"[red]Couldn't reach Garmin:[/] {type(e).__name__}: {str(e)[:100]}. Try `ironman login`.")


def cmd_setup():
    import shutil as _sh
    cfg_path = S.CONFIG
    cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
    console.print("[bold]Let's set up your plan.[/] Press Enter to keep the value in [brackets].\n")
    race = cfg.get("race") or {}
    name = input(f"Race name [{race.get('name') or 'My race'}]: ").strip() or race.get("name") or "My race"
    while True:
        d = input(f"Race date, YYYY-MM-DD [{race.get('date') or ''}]: ").strip() or race.get("date") or ""
        try:
            date.fromisoformat(d)
            break
        except ValueError:
            console.print("[red]Use the format 2027-04-24.[/]")
    plans = sorted(p for p in (S.ROOT / "plans").glob("*.csv") if p.name not in ("template.csv", "my-plan.csv"))
    console.print("\nPlans:")
    for i, p in enumerate(plans, 1):
        console.print(f"  {i}. {p.stem}")
    console.print(f"  {len(plans) + 1}. my own CSV file (start from plans/template.csv)")
    choice = input(f"Pick 1-{len(plans) + 1}: ").strip()
    mine = S.ROOT / "plans" / "my-plan.csv"
    if choice.isdigit() and 1 <= int(choice) <= len(plans):
        if mine.exists() and input("Replace your existing plans/my-plan.csv? [y/N] ").lower() != "y":
            pass
        else:
            _sh.copyfile(plans[int(choice) - 1], mine)
        plan_path = "plans/my-plan.csv"
    else:
        plan_path = input("Path to your plan CSV: ").strip() or "plans/my-plan.csv"
    src = input("Your watch: 1. Garmin  2. Something else (Coros, Polar, Suunto, Wahoo, Apple) via intervals.icu "
                f"[{'2' if cfg.get('source') == 'intervals' else '1'}]: ").strip()
    cfg["source"] = "intervals" if src == "2" or (not src and cfg.get("source") == "intervals") else "garmin"
    units = input(f"Miles or km? [{cfg.get('units', 'mi')}]: ").strip().lower()
    cfg["units"] = "km" if units.startswith("k") else "mi" if units.startswith("m") else cfg.get("units", "mi")
    ftp = input(f"Bike FTP in watts, if you know it [{cfg.get('ftp') or 'skip'}]: ").strip()
    cfg.update(race={"name": name, "date": d}, plan=plan_path)
    if ftp.isdigit():
        cfg["ftp"] = int(ftp)
    cfg_path.write_text(json.dumps(cfg, indent=2))
    try:
        load_plan(S.load_config())
        console.print(f"\n[green]Done.[/] Week 1 starts {P.plan_start():%a %b %d}; race day is {P.race_day():%a %b %d}.")
    except (NotSetUp, P.PlanError) as ex:
        console.print(f"[red]{ex}[/]")
        return
    who = "intervals.icu" if cfg["source"] == "intervals" else "Garmin"
    console.print(f"Next: [bold]ironman login[/] to connect {who}, then [bold]ironman[/] or [bold]ironman web[/].")


def cmd_login_intervals():
    cfg_path = S.CONFIG
    cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
    console.print("In intervals.icu: Settings > Developer Settings. Copy your athlete ID (like i12345) and API key.")
    aid = input("Athlete ID: ").strip()
    key = input("API key: ").strip()
    cfg["source"] = "intervals"
    cfg["intervals"] = {"athlete_id": aid, "api_key": key}
    cfg_path.write_text(json.dumps(cfg, indent=2))
    try:
        from . import intervals
        intervals.Client(aid, key).get(f"/athlete/{aid}")
        console.print("[green]Connected to intervals.icu.[/] Your key is saved in config.json, which never leaves your computer.")
    except Exception as ex:
        console.print(f"[red]Couldn't connect:[/] {ex}. Check the ID and key and run `ironman login` again.")


def cmd_set(what, values):
    cfg_path = S.CONFIG
    cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
    if what == "ftp":
        cfg["ftp"] = int(values[0])
        console.print(f"FTP set to {cfg['ftp']} W. Bike zones now use it.")
    else:
        yards, t = int(values[0]), values[1]
        m, sec = t.split(":")
        per100 = (int(m) * 60 + int(sec)) / yards * 100
        cfg["swim_t_pace_sec"] = round(per100, 1)
        console.print(f"Swim pace set: {int(per100 // 60)}:{int(per100 % 60):02d} per 100 yd. Swim zones now use it.")
    cfg_path.write_text(json.dumps(cfg, indent=2))


def cmd_explain(ctx):
    if not shutil.which("claude"):
        console.print("[yellow]Claude Code isn't on your PATH, so there's no AI explanation. The rules above still apply.[/]")
        return
    payload = {
        "today": ctx["today"].isoformat(),
        "today_sessions": [{"title": s.title, "amount": s.label(), "detail": s.detail, "note": s.note}
                           for s in ctx["plan"] if s.day == ctx["today"]],
        "signals": [vars(g) for g in ctx["signals"]],
        "advice": [{k: getattr(a, k) for k in ("rule", "title", "why", "instead")} for a in ctx["advice"]],
        "this_week": [{"day": st.session.day.isoformat(), "session": st.session.title, "planned": st.session.label(),
                       "state": st.state} for st in ctx["statuses"].values() if st.session.week == P.week_of(ctx["today"])],
        "days_to_race": engine.days_to_race(ctx["today"]),
    }
    prompt = ("You're my triathlon coach's assistant. My training plan and a rules engine made today's decisions; "
              "do not invent new workouts or override the rules. In under 120 words, plainly explain what today "
              "looks like, why any suggestion was made, and one thing to focus on. Data:\n" + json.dumps(payload))
    with console.status("Asking Claude…"):
        out = subprocess.run(["claude", "-p", prompt], capture_output=True, text=True, timeout=180)
    console.print(out.stdout.strip() or out.stderr.strip())


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ironman", description="Your training plan, Garmin, and simple rules, in the terminal or the browser.")
    ap.add_argument("--date", help="pretend today is YYYY-MM-DD (preview the plan)")
    ap.add_argument("--offline", action="store_true", help="don't sync Garmin")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("sync", help="force a Garmin sync")
    w = sub.add_parser("week", help="show a week: number, 'next', or 'last'")
    w.add_argument("which", nargs="?", default="this")
    for name in ("apply", "dismiss"):
        p = sub.add_parser(name, help=f"{name} a numbered suggestion")
        p.add_argument("n", type=int)
    sub.add_parser("undo", help="take back the last applied change")
    n = sub.add_parser("note", help="tell it how you feel: sick | pain | tired | clear")
    n.add_argument("what", choices=["sick", "pain", "tired", "clear"])
    n.add_argument("day", nargs="?", default="today")
    b = sub.add_parser("busy", help="only have N minutes on a day: ironman busy wed 45")
    b.add_argument("day")
    b.add_argument("minutes", help="minutes available, or 'clear'")
    m = sub.add_parser("move", help="move a day's training: ironman move sat sun")
    m.add_argument("src")
    m.add_argument("dst")
    sub.add_parser("explain", help="plain-English explanation from Claude (optional)")
    t = sub.add_parser("today", help="exactly what to do today: zones, watts, heart rate, how")
    t.add_argument("day", nargs="?", default="today", help="or: tomorrow, sat, 2026-12-05")
    sub.add_parser("history", help="every change you've applied, and why")
    sub.add_parser("runs", help="your recent runs: zones, drift, pace, and your easy-pace trend")
    sd = sub.add_parser("send", help="send the day's swim/run to your watch and ride to Zwift: ironman send today")
    sd.add_argument("day", nargs="?", default="today")
    sw = sub.add_parser("swap", help="swap two days' training: ironman swap tue wed")
    sw.add_argument("a")
    sw.add_argument("b")
    se = sub.add_parser("set", help="ironman set ftp 200  |  ironman set swim 1000 18:30")
    se.add_argument("what", choices=["ftp", "swim"])
    se.add_argument("values", nargs="+")
    sub.add_parser("login", help="connect your Garmin account (once)")
    sub.add_parser("setup", help="choose your race, date and plan")
    wb = sub.add_parser("web", help="open the dashboard in your browser (keeps running, syncs by itself)")
    wb.add_argument("--port", type=int, default=8642)
    wb.add_argument("--no-browser", action="store_true")
    wb.add_argument("--always", action="store_true", help="keep it running whenever you're logged in (macOS)")
    wb.add_argument("--stop", action="store_true", help="turn off --always")
    a = ap.parse_args(argv)

    today = date.fromisoformat(a.date) if a.date else date.today()
    sync = not a.offline and not a.date

    if a.cmd == "setup":
        return cmd_setup()
    if a.cmd == "web":
        from . import web
        if a.stop:
            return web.uninstall_always()
        if a.always:
            return web.install_always(a.port)
        return web.serve(a.port, open_browser=not a.no_browser)
    if a.cmd == "login":
        cfg = S.load_config()
        if cfg.get("source") == "intervals":
            return cmd_login_intervals()
        garmin.connect(interactive=True)
        console.print("[green]Logged in. Tokens saved to ~/.garminconnect.[/]")
        return
    if a.cmd in ("apply", "dismiss"):
        return cmd_apply(a.n, dismiss=a.cmd == "dismiss")
    if a.cmd == "undo":
        return cmd_undo()
    if a.cmd == "note":
        st = S.load_state()
        d = parse_day(a.day, today).isoformat()
        if a.what == "clear":
            st["notes"].pop(d, None)
        else:
            st["notes"][d] = a.what
        S.save_state(st)
        console.print(f"Noted for {d}: {a.what}.")
        return
    if a.cmd == "busy":
        st = S.load_state()
        d = parse_day(a.day, today).isoformat()
        if a.minutes == "clear":
            st["busy"].pop(d, None)
        else:
            st["busy"][d] = int(a.minutes)
        S.save_state(st)
        console.print(f"Got it: {a.minutes} min on {d}. Run `ironman` to see the suggestion.")
        return
    if a.cmd == "set":
        return cmd_set(a.what, a.values)
    if a.cmd == "swap":
        st = S.load_state()
        da, db = parse_day(a.a, today), parse_day(a.b, today)
        plan = P.apply_overrides(load_plan(S.load_config()), st["overrides"])
        before = {}
        for s_ in plan:
            if s_.day in (da, db):
                before[s_.id] = st["overrides"].get(s_.id)
                to = db if s_.day == da else da
                st["overrides"].setdefault(s_.id, {}).update({"day": to.isoformat(), "note": f"swapped from {s_.day:%a}"})
        st["applied_log"].append({"at": datetime.now().isoformat(timespec="seconds"), "id": f"swap:{da}:{db}",
                                  "title": f"Swap {da:%a %b %d} and {db:%a %b %d}", "before": before})
        S.save_state(st)
        console.print(f"Swapped {da:%a %b %d} and {db:%a %b %d}. `ironman undo` reverses it.")
        return
    if a.cmd == "move":
        st = S.load_state()
        src, dst = parse_day(a.src, today), parse_day(a.dst, today)
        plan = P.apply_overrides(load_plan(S.load_config()), st["overrides"])
        moved = [s for s in plan if s.day == src]
        before = {s.id: st["overrides"].get(s.id) for s in moved}
        for s in moved:
            st["overrides"].setdefault(s.id, {}).update({"day": dst.isoformat(), "note": f"moved from {src:%a %b %d}"})
        st["applied_log"].append({"at": datetime.now().isoformat(timespec="seconds"), "id": f"move:{src}",
                                  "title": f"Move {src:%a} to {dst:%a}", "before": before})
        S.save_state(st)
        console.print(f"Moved {len(moved)} session(s) from {src:%a %b %d} to {dst:%a %b %d}.")
        return

    try:
        ctx = build(today, sync=sync, force=a.cmd == "sync")
    except NotSetUp as ex:
        console.print(f"[yellow]{ex}[/] Run [bold]ironman setup[/] first.")
        return
    except P.PlanError as ex:
        console.print(f"[red]Problem in your plan file:[/] {ex}")
        return
    if a.cmd == "week":
        wk = P.week_of(today) + {"this": 0, "next": 1, "last": -1}.get(a.which, 0)
        if a.which.isdigit():
            wk = int(a.which)
        wk = max(1, min(wk, P.num_weeks()))
        console.print(week_table(ctx["plan"], ctx["statuses"], wk, today))
        for s in [s for s in ctx["plan"] if s.week == wk or P.week_of(s.day) == wk]:
            console.print(f"[bold]{s.day:%a %b %d}[/]  {s.title} {s.label() if s.amount else ''}  [dim]{s.detail}[/]"
                          + (f"  [italic]({s.note})[/]" if s.note else ""))
        return
    if a.cmd == "explain":
        return cmd_explain(ctx)
    if a.cmd == "history":
        log = S.load_state().get("applied_log", [])
        if not log:
            console.print("No changes applied yet. The plan is exactly as written.")
        for item in reversed(log):
            console.print(f"[bold]{item['at'][:16].replace('T', ' ')}[/]  {item['title']}")
            if item.get("why"):
                console.print(f"   Why: {item['why']}")
            for sid in item.get("before", {}):
                o = S.load_state()["overrides"].get(sid, {})
                if o.get("note"):
                    console.print(f"   [dim]{sid[:10]} {sid.split('-')[3]}: {o['note']}[/]")
        return
    if a.cmd == "runs":
        from .dashboard import run_card, efficiency_line
        if not ctx["runs"]:
            console.print("No runs in the last 6 weeks yet.")
            return
        if ctx.get("efficiency"):
            console.print(efficiency_line(ctx["efficiency"]))
        for r in ctx["runs"][:8]:
            console.print(run_card(r, title="Run"))
        return
    if a.cmd == "send":
        return cmd_send(ctx, parse_day(a.day, today))
    if a.cmd == "today":
        from .dashboard import day_card
        return day_card(console, ctx, parse_day(a.day, today), S.load_config())
    render(console, ctx)


if __name__ == "__main__":
    sys.exit(main())
