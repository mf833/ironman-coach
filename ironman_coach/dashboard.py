"""Terminal dashboard (rich)."""
from __future__ import annotations

from datetime import date, timedelta

from rich import box
from rich.columns import Columns
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import engine
from .plan import fmt_minutes, num_weeks, plan_start, race_name, week_dates, week_label, week_of

ACCENT = "#e8743b"
SPORT_COLOR = {"swim": "#4fa3d9", "bike": "#e8b63b", "run": "#d9534f", "strength": "#9b8fd9", "race": ACCENT}
ICON = {"done": "[green]✓[/]", "moved": "[green]✓[/]", "partial": "[yellow]◐[/]", "missed": "[red]✗[/]",
        "today": f"[{ACCENT}]●[/]", "upcoming": "[dim]·[/]"}
SEV = {"important": "[bold red]![/]", "suggest": f"[bold {ACCENT}]→[/]", "info": "[dim]i[/]"}
LEVEL = {0: "[green]●[/]", 1: "[yellow]●[/]", 2: "[red]●[/]", None: "[dim]○[/]"}


def bar(done: float, total: float, width: int = 22, color: str = ACCENT) -> Text:
    frac = 0 if not total else min(done / total, 1)
    n = int(round(frac * width))
    t = Text()
    t.append("█" * n, style=color)
    t.append("░" * (width - n), style="grey30")
    return t


def amount(sport: str, v: float) -> str:
    return f"{int(v):,} yd" if sport == "swim" else fmt_minutes(v)


def render(console: Console, ctx: dict) -> None:
    today: date = ctx["today"]
    plan, statuses, advice = ctx["plan"], ctx["statuses"], ctx["advice"]
    wk = max(1, min(week_of(today), num_weeks()))
    days_left = engine.days_to_race(today)

    head = Text()
    head.append(race_name().upper(), style=f"bold {ACCENT}")
    head.append("   RACE DAY" if days_left == 0 else f"   {days_left} days to go" if days_left > 0 else "   race done",
                style="bold")
    if today < plan_start():
        head.append(f"   ·   plan starts {plan_start():%a %b %d}", style="dim")
    else:
        lbl = week_label(wk)
        head.append(f"   ·   week {wk} of {num_weeks()}" + (f" ({lbl})" if lbl else ""), style="dim")
    synced = ctx.get("synced_at")
    head.append(f"\n{today:%A, %B %d}" + (f"   ·   Garmin synced {synced}" if synced else "   ·   Garmin not synced"),
                style="dim")
    if ctx.get("sync_error"):
        head.append(f"\nSync failed: {ctx['sync_error']}  (run `ironman login`)", style="yellow")
    console.print(Panel(head, box=box.ROUNDED, border_style=ACCENT))

    # Today
    todays = [s for s in plan if s.day == today]
    tbl = Table(box=None, show_header=False, padding=(0, 1), expand=True)
    tbl.add_column(width=2)
    tbl.add_column(ratio=1)
    if not todays:
        tbl.add_row("", "[bold]Rest day.[/] Sleep, eat, walk.")
    for s in todays:
        st = statuses.get(s.id)
        icon = ICON.get(st.state, "") if st else f"[{ACCENT}]★[/]"
        line = Text()
        line.append(f"{s.title}  ", style=f"bold {SPORT_COLOR.get(s.sport, 'white')}")
        if s.amount:
            line.append(s.label(), style="bold")
        if st and st.actual:
            line.append(f"   done {amount(s.sport, st.actual)}", style="green")
        line.append(f"\n{s.detail}", style="")
        if s.note:
            line.append(f"\nadjusted: {s.note}", style=f"italic {ACCENT}")
        tbl.add_row(icon, line)

    sig = Table(box=None, show_header=False, padding=(0, 1))
    for g in ctx["signals"]:
        sig.add_row(LEVEL[g.level], f"[bold]{g.name}[/]", g.value, f"[dim]{g.why}[/]")
    console.print(Columns([Panel(tbl, title="Today", title_align="left", border_style="grey50", width=72),
                           Panel(sig, title="Recovery signals", title_align="left", border_style="grey50")]))

    # Advice
    if advice:
        a_tbl = Table(box=None, show_header=False, padding=(0, 1), expand=True)
        a_tbl.add_column(width=3)
        a_tbl.add_column(ratio=1)
        for i, a in enumerate(advice, 1):
            body = Text.from_markup(f"{SEV[a.severity]} [bold]{a.title}[/]")
            body.append(f"\n{a.why}", style="")
            if a.instead:
                body.append(f"\nIf you change it: {a.instead}", style=ACCENT)
            if a.changes:
                body.append(f"\nironman apply {i}   ·   ironman dismiss {i}", style="dim")
            a_tbl.add_row(f"[bold]{i}[/]", body)
        console.print(Panel(a_tbl, title="Should anything change?", title_align="left", border_style=ACCENT))
    else:
        console.print(Panel("[green]Nothing to change. Train as planned.[/]", title="Should anything change?",
                            title_align="left", border_style="grey50"))

    console.print(week_table(plan, statuses, wk, today))

    # Progress
    wp = engine.week_progress(plan, statuses, ctx["activities"], wk)
    prog = Table(box=None, show_header=False, padding=(0, 1))
    for sp, (d, p) in wp.items():
        prog.add_row(f"[{SPORT_COLOR[sp]}]{sp.title()}[/]", bar(d, p, color=SPORT_COLOR[sp]),
                     f"{amount(sp, d)} / {amount(sp, p)}")
    done, total = engine.plan_compliance(statuses, today)
    if total:
        prog.add_row("[bold]Plan so far[/]", bar(done, total), f"{done}/{total} sessions")

    best = ctx.get("bests", {})
    ms = Table(box=None, show_header=False, padding=(0, 1))
    peaks = engine.plan_peaks(plan)
    for sp, label in (("swim", "Longest swim"), ("bike", "Longest ride"), ("run", "Longest run")):
        if sp not in peaks:
            continue
        b = best.get(sp, 0)
        tgt = peaks[sp]
        tgt_label = "plan peak"
        ms.add_row(f"[{SPORT_COLOR[sp]}]{label}[/]", bar(b, tgt, width=16, color=SPORT_COLOR[sp]),
                   f"{amount(sp, b)} [dim]of {amount(sp, tgt)} {tgt_label}[/]")
    console.print(Columns([Panel(prog, title="This week", title_align="left", border_style="grey50"),
                           Panel(ms, title="Milestones (what you've actually done)", title_align="left",
                                 border_style="grey50")]))
    console.print(commands())


def commands() -> Table:
    t = Table(box=None, show_header=False, padding=(0, 2))
    cmds = [
        ("ironman today", "what to do today"), ("ironman send", "workout to watch / Zwift"),
        ("ironman week next", "next week"), ("ironman apply 1", "take suggestion 1"),
        ("ironman dismiss 1", "skip suggestion 1"), ("ironman undo", "undo last change"),
        ("ironman note tired", "or sick / pain / clear"), ("ironman busy wed 45", "only 45 min Wed"),
        ("ironman swap tue wed", "swap two days"), ("ironman move sat sun", "move a day"),
        ("ironman web", "dashboard in your browser"), ("ironman -h", "all commands"),
    ]
    for _ in range(3):
        t.add_column()
    rows = [cmds[i:i + 3] for i in range(0, len(cmds), 3)]
    for r in rows:
        t.add_row(*[Text.assemble((c, f"bold {ACCENT}"), ("  " + d, "dim")) for c, d in r])
    return Panel(t, title="Commands", title_align="left", border_style="grey30")

def legend() -> Text:
    t = Text(" ")
    for color, name in ((SPORT_COLOR["swim"], "swim"), (SPORT_COLOR["bike"], "bike"), (SPORT_COLOR["run"], "run")):
        t.append("■ ", style=color)
        t.append(f"{name}  ", style="dim")
    t.append("│  ", style="grey30")
    t.append_text(Text.from_markup("[green]✓[/] [dim]done[/]  [yellow]◐[/] [dim]partial[/]  [red]✗[/] [dim]missed[/]  "
                                   f"[{ACCENT}]●[/] [dim]today[/]  [dim]· upcoming  * adjusted[/]  "))
    t.append("│  ", style="grey30")
    t.append_text(Text.from_markup("[dim]signals:[/] [green]●[/] [dim]normal[/] [yellow]●[/] [dim]a bit off[/] "
                                   "[red]●[/] [dim]clearly off[/] [dim]○ no data[/]  "))
    t.append("│  ", style="grey30")
    t.append_text(Text.from_markup(f"[bold red]![/] [dim]important[/] [bold {ACCENT}]→[/] [dim]suggestion[/] "
                                   "[dim]i info[/]"))
    return t


def week_table(plan, statuses, wk: int, today: date) -> Panel:
    start, end = week_dates(wk)
    t = Table(box=box.SIMPLE_HEAD, expand=True, padding=(0, 1))
    for i in range(7):
        d = start + timedelta(days=i)
        style = f"bold {ACCENT}" if d == today else "bold"
        t.add_column(f"{d:%a} {d.day}", style="", header_style=style, ratio=1)
    cells = []
    for i in range(7):
        d = start + timedelta(days=i)
        lines = []
        for s in [s for s in plan if s.day == d]:
            st = statuses.get(s.id)
            icon = ICON.get(st.state, "") if st else f"[{ACCENT}]★[/]"
            mark = "*" if s.note else ""
            lines.append(f"{icon} [{SPORT_COLOR.get(s.sport, 'white')}]{s.sport.title() if s.sport != 'race' else 'RACE'}[/] "
                         f"{s.label() if s.amount else ''}{mark}")
        cells.append("\n".join(lines) or "[dim]rest[/]")
    t.add_row(*cells)
    label = week_label(wk)
    return Panel(t, title=f"Week {wk}" + (f" · {label}" if label else "") + f" · {start:%b %d}–{end:%b %d}", title_align="left",
                 border_style="grey50", subtitle="[dim]✓ done  ◐ partial  ✗ missed  * adjusted[/]",
                 subtitle_align="right")


# ---- `ironman today`: exactly what to do ------------------------------------------
from .zones import fmt_pace, zone_rows, zones_in

DEFAULT_ZONES = {"easy": [1, 2], "recovery": [1, 2], "long": [1, 2], "brick": [2], "straight": [2, 3],
                 "intervals": [], "test": []}

HOW = {
    "long": "Start very easy for the first 15 min, then settle into Z2. If you drift above Z2 on hills, ease off. "
            "This is about time on your feet/saddle, not speed.",
    "intervals": "Warm up at least 10-15 min easy before the first effort. Hit the target zone, not more. "
                 "Easy between efforts is truly easy. Cool down 5-10 min.",
    "easy": "Keep it conversational the whole time. If you can't talk in full sentences, slow down.",
    "recovery": "Easier than you think. This should feel like nothing.",
    "brick": "Change shoes fast and start running right off the bike. Legs will feel heavy for 5-10 min; that's the point.",
    "straight": "Swim the whole distance without stopping, at a pace you could hold forever. Breathe early and often. "
                "If you have to stop, rest at the wall for 15-20 sec and keep going; it still counts.",
    "test": "Warm up as written, then go as hard as you can hold evenly for the whole test. Don't start too fast. "
            "Afterwards run `ironman set` with the result so your zones update.",
}


SWIM_HOW = {
    "intervals": "Drills first, slowly. Swim the main set at a steady pace you could repeat on every rep, and take "
                 "the listed rest. Carry the drill feel into it: roll to breathe, keep the lead arm long.",
    "easy": "Relaxed and continuous where you can. Rest at the wall whenever form starts to slip.",
    "straight": HOW["straight"],
    "test": HOW["test"],
}


def day_card(console: Console, ctx: dict, day: date, cfg: dict) -> None:
    sessions = [s for s in ctx["plan"] if s.day == day]
    cache = ctx.get("cache", {})
    hr = {k: {int(z): tuple(v) for z, v in zs.items()} for k, zs in (cache.get("hr_zones") or {}).items()}
    ftp = cfg.get("ftp") or cache.get("garmin_ftp")
    ftp_src = "your setting" if cfg.get("ftp") else "Garmin" if cache.get("garmin_ftp") else None
    swim_t = cfg.get("swim_t_pace_sec")

    wd = min(max(week_of(day), 1), num_weeks())
    title = f"{day:%A, %B %d}  ·  week {wd}" + (f" ({week_label(wd)})" if week_label(wd) else "")
    if not sessions:
        console.print(Panel("[bold]Rest day.[/] No training. Sleep, eat well, walk if you want.\n"
                            "[dim]Rest is when the training actually turns into fitness.[/]",
                            title=title, title_align="left", border_style=ACCENT))
        return
    for s in sessions:
        st = ctx["statuses"].get(s.id)
        body = Text()
        body.append(f"{s.title}", style=f"bold {SPORT_COLOR.get(s.sport, 'white')}")
        if s.amount:
            body.append(f"  ·  {s.label()}", style="bold")
        if st and st.state in ("done", "moved"):
            body.append("   ✓ done", style="green")
        body.append(f"\n\n{s.detail}\n")
        if s.note:
            body.append(f"\nAdjusted: {s.note}\n", style=f"italic {ACCENT}")
        how = SWIM_HOW.get(s.kind) if s.sport == "swim" else HOW.get(s.kind)
        if how:
            body.append(f"\nHow: {how}\n", style="")

        zs = zones_in(s.detail) or ([2, 3] if s.sport == "swim" else DEFAULT_ZONES.get(s.kind, []))
        parts = [body]
        if s.sport == "swim" and s.kind != "race":
            parts.append(swim_table(s))
        if s.sport == "swim" and "drill" in s.detail.lower():
            parts.append(drill_block(s))
        if zs and s.sport in ("bike", "run", "swim"):
            t = Table(box=box.SIMPLE, padding=(0, 1), show_edge=False)
            t.add_column("Zone", style="bold")
            if s.sport == "bike":
                t.add_column(f"Power (FTP {ftp} W)" if ftp else "Power")
            if s.sport == "swim":
                t.add_column("Pace")
            if s.sport != "swim":
                t.add_column("Heart rate")
            t.add_column("Feels like")
            for z, target, bpm, feel in zone_rows(s.sport, zs, ftp, hr, swim_t):
                row = [z]
                if s.sport == "bike":
                    row.append(target or "[dim]set FTP[/]")
                if s.sport == "swim":
                    row.append(target or "[dim]after your swim test[/]")
                if s.sport != "swim":
                    row.append(bpm or "[dim]no zones yet[/]")
                row.append(feel)
                t.add_row(*row)
            parts.append(t)
            if s.sport == "bike" and ftp_src:
                parts.append(Text(f"FTP from {ftp_src}. Change it with `ironman set ftp N`.", style="dim"))
            if s.sport == "bike" and not ftp:
                parts.append(Text("No FTP yet: ride by heart rate and feel. `ironman set ftp N` adds watts.", style="dim"))

        fuel = cfg.get("fuel_g_per_h", {})
        if s.sport in ("bike", "run") and s.amount >= 90:
            parts.append(Text(f"\nFuel: start eating by minute 30-45, aim for {fuel.get(s.sport, '30-60')} g carbs/hour, "
                              f"and drink to thirst. Practice what you'll use on race day.", style=""))
        elif s.sport in ("bike", "run") and s.amount >= 60:
            parts.append(Text("\nFuel: bring water. A gel is optional if you feel flat.", style="dim"))
        console.print(Panel(Group(*parts), title=title, title_align="left", border_style=ACCENT))


def drill_block(s):
    from .drills import DRILLS, drill_sets
    late = s.day.weekday() >= 3
    sets = drill_sets(s.detail, s.week, late) or drill_sets("4x50 drills", s.week, late)
    parts, seen = [], set()
    for ds in sets:
        parts.append(Text(f"\nDrills, {ds['part']}: {ds['reps']}x{ds['dist']} = " + (f"{ds['per']}x{ds['dist']} of each " if len(ds["drills"]) > 1 else f"all {ds['drills'][0]} ") +
                          f"(25 drill / 25 easy swim, 15-20s rest)", style=f"bold {SPORT_COLOR['swim']}"))
        t = Table(box=None, show_header=False, padding=(0, 1), expand=True)
        t.add_column(style="bold", width=16)
        t.add_column(ratio=1)
        for name in ds["drills"]:
            d = DRILLS[name]
            if name in seen:
                t.add_row(name, Text("same as in the warm-up, nice and easy now", style="dim"))
                continue
            seen.add(name)
            cell = Text(d["how"])
            if d["gear"]:
                cell.append(f"  ({d['gear']})", style="dim")
            cell.append(f"\nWhy: {d['why']}", style=ACCENT)
            t.add_row(name, cell)
        parts.append(t)
    return Group(*parts)


def swim_table(s):
    from .swimsets import breakdown
    rows, tot = breakdown(s.detail, s.amount)
    t = Table(box=box.SIMPLE, padding=(0, 1), show_edge=False)
    for col in ("", "Set", "Yards", "Rest after each", "How"):
        t.add_column(col, style="bold" if col == "" else "")
    for r in rows:
        t.add_row(r["part"], r["set"], f"{r['yd']:,}", r["rest"] or "-", r["how"])
    out = [Text("\nThe swim, set by set", style=f"bold {SPORT_COLOR['swim']}"), t]
    if tot == s.amount:
        out.append(Text(f"Total {tot:,} yd", style="dim"))
    elif tot < s.amount:
        out.append(Text(f"These sets add up to {tot:,} yd; the plan lists {s.amount:,}. Add {s.amount - tot:,} easy "
                        f"to the cool-down if you want the full total.", style=ACCENT))
    else:
        out.append(Text(f"These sets add up to {tot:,} yd; the plan lists {s.amount:,}. Either is fine.", style=ACCENT))
    return Group(*out)
