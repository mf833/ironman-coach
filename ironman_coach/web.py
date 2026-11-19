"""`ironman web`: the dashboard as a local web page that stays up and syncs by itself.

Runs only on your computer (127.0.0.1). Nothing is sent anywhere except Garmin.
It syncs Garmin in the background but never sends a workout unless you press Send.
"""
from __future__ import annotations

import html
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from rich.text import Text

from . import cli, engine, plan as P, state as S
from .dashboard import DEFAULT_ZONES, HOW, SWIM_HOW
from .drills import DRILLS, drill_sets
from .swimsets import breakdown
from .zones import zone_rows, zones_in

PORT = 8642
TOKEN = secrets.token_urlsafe(16)
LOCK = threading.Lock()
SPORT_CLASS = {"swim": "swim", "bike": "bike", "run": "run", "strength": "str", "race": "race"}
STATE_ICON = {"done": "✓", "moved": "✓", "partial": "◐", "missed": "✕", "today": "●", "upcoming": ""}
LEVEL_CLASS = {0: "ok", 1: "warn", 2: "bad", None: "none"}

e = html.escape


def _plain(markup: str) -> str:
    return Text.from_markup(markup).plain


def _send_label(sessions) -> str:
    sports = {s.sport for s in sessions}
    if sports <= {"bike", "strength", "race"}:
        return "Send to Zwift"
    return "Send to watch / Zwift" if "bike" in sports else "Send to watch"


def _ctx(today: date) -> dict:
    with LOCK:
        return cli.build(today, sync=False)


# ---- pieces -----------------------------------------------------------------------
def _amount(sport, v):
    return f"{int(v):,} yd" if sport == "swim" else P.fmt_minutes(v)


def _bar(done, total, cls):
    pct = 0 if not total else min(100, round(100 * done / total))
    return f'<div class="bar"><div class="fill {cls}" style="width:{pct}%"></div></div>'


def _session_line(s, st, link=True):
    icon = STATE_ICON.get(st.state, "") if st else "★"
    state_cls = st.state if st else "race"
    amt = s.label() if s.amount else ""
    body = (f'<span class="dot {SPORT_CLASS.get(s.sport, "")}"></span><b>{e(s.title)}</b> '
            f'<span class="muted">{e(amt)}</span>'
            + (f' <span class="adj">adjusted</span>' if s.note else "")
            + f'<span class="st {state_cls}">{icon}</span>')
    return f'<a class="sess" href="/day/{s.day.isoformat()}">{body}</a>' if link else f'<div class="sess">{body}</div>'


ZONE_COLORS = ["#7aa7c7", "#4fa36b", "#e8b63b", "#e8743b", "#d9534f"]


def run_html(r: dict) -> str:
    u = r["units"]
    stats = [P.fmt_minutes(r["minutes"])] + ([f"{r['dist']} {u}"] if r.get("dist") else []) + \
            ([f"{r['pace']} /{u}"] if r.get("pace") else []) + ([f"{round(r['avg_hr'])} bpm"] if r.get("avg_hr") else []) + \
            ([f"{r['cadence']} spm"] if r.get("cadence") else [])
    zp = r.get("zone_pct")
    strip = ('<div class="zstrip">' + "".join(f'<div style="width:{p}%;background:{ZONE_COLORS[i]}" title="Z{i + 1} {p}%"></div>'
                                             for i, p in enumerate(zp) if p) + "</div>"
             '<div class="muted small">' + " · ".join(f"Z{i + 1} {p}%" for i, p in enumerate(zp) if p) + "</div>") \
        if zp else '<div class="muted small">No heart-rate zones for this run.</div>'
    laps = (f'<div class="muted small">Fastest {u} {r["fastest"][1]}: {r["fastest"][0]} · slowest {u} '
            f'{r["slowest"][1]}: {r["slowest"][0]}</div>') if r.get("fastest") else ""
    verdict = "".join(f'<div class="instead">→ {e(v)}</div>' for v in r["verdict"])
    planned = f' <span class="muted small">planned: {e(r["session_title"])}</span>' if r.get("session_title") else ""
    return (f'<div class="run"><div><b>{e(r["date"])}</b> {e(r["name"])}{planned}</div>'
            f'<div>{" · ".join(e(x) for x in stats)}</div>{strip}{laps}{verdict}</div>')


def eff_html(eff: dict | None) -> str:
    if not eff:
        return ""
    u = eff["units"]
    if "change_pct" in eff:
        cls = "okmsg" if eff["change_pct"] > 0 else "adj"
        word = "faster" if eff["change_pct"] > 0 else "slower"
        return (f'<div class="{cls}">Easy pace at {eff["ref_hr"]} bpm: {eff["then"]} → {eff["now"]} /{u} '
                f'({abs(eff["change_pct"])}% {word} than 3-6 weeks ago)</div>')
    return (f'<div class="muted small">Easy pace at {eff["ref_hr"]} bpm: {eff.get("now") or eff.get("then")} /{u}. '
            "A trend shows up after a few weeks of easy runs.</div>")


def page(title: str, body: str) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title><style>{CSS}</style></head>
<body><main>{body}</main><div id="toast"></div>
<script>const TOKEN={json.dumps(TOKEN)};{JS}</script></body></html>"""


def dashboard_html(ctx: dict, week_override: int | None = None) -> str:
    today, plan, statuses, advice = ctx["today"], ctx["plan"], ctx["statuses"], ctx["advice"]
    n = P.num_weeks()
    cur = max(1, min(P.week_of(today), n))
    wk = week_override or cur
    days_left = engine.days_to_race(today)
    lbl = P.week_label(cur)
    when = ("Race day" if days_left == 0 else f"{days_left} days to go" if days_left > 0 else "Race done")
    where = (f"Plan starts {P.plan_start():%a %b %d}" if today < P.plan_start()
             else f"Week {cur} of {n}" + (f" · {lbl}" if lbl else ""))
    sync = ctx.get("synced_at") or "never"
    err = f'<div class="err">Garmin sync failed: {e(ctx["sync_error"])}. Run <code>ironman login</code>.</div>' \
        if ctx.get("sync_error") else ""

    head = f"""<header><div><h1>{e(P.race_name())}</h1>
<div class="sub">{when} · {where}</div></div>
<div class="right"><div class="muted small">Garmin synced {e(sync)}</div>
<button onclick="act('/api/sync')">Sync now</button></div></header>{err}"""

    todays = [s for s in plan if s.day == today]
    t_html = "".join(_session_line(s, statuses.get(s.id)) for s in todays) or \
        '<div class="rest">Rest day. Sleep, eat, walk.</div>'
    sendable = any(s.sport in ("swim", "run", "bike") for s in todays)
    t_actions = (f'<div class="actions"><a class="btn" href="/day/{today.isoformat()}">What to do</a>'
                 f'<button class="ghost" onclick="act(\'/api/send/{today.isoformat()}\')">{_send_label(todays)}</button>'
                 "</div>") if sendable else ""
    sig = "".join(f'<div class="sig"><span class="lvl {LEVEL_CLASS[g.level]}"></span><b>{e(g.name)}</b>'
                  f'<span>{e(g.value)}</span><span class="muted">{e(g.why)}</span></div>' for g in ctx["signals"])
    notes = ('<div class="notes">'
             + "".join(f'<button class="ghost" onclick="act(\'/api/note\',{{what:\'{w}\'}})">{w.title()}</button>'
                       for w in ("tired", "sick", "pain", "clear")) + "</div>")

    if advice:
        adv = ""
        for i, a in enumerate(advice, 1):
            btns = (f'<div class="actions"><button onclick="act(\'/api/apply/{i}\')">Apply</button>'
                    f'<button class="ghost" onclick="act(\'/api/dismiss/{i}\')">Dismiss</button></div>') if a.changes else ""
            adv += (f'<div class="adv {a.severity}"><div class="t">{e(a.title)}</div><div>{e(a.why)}</div>'
                    + (f'<div class="instead">If you change it: {e(a.instead)}</div>' if a.instead else "")
                    + btns + "</div>")
    else:
        adv = '<div class="okmsg">Nothing to change. Train as planned.</div>'
    adv += '<div class="small"><a href="#" onclick="act(\'/api/undo\');return false">Undo last change</a></div>'

    start, end = P.week_dates(wk)
    cols = ""
    for i in range(7):
        d = start + timedelta(days=i)
        items = "".join(_session_line(s, statuses.get(s.id)) for s in plan if s.day == d) or '<div class="muted">rest</div>'
        cols += f'<div class="day{" today" if d == today else ""}"><div class="dh">{d:%a} {d.day}</div>{items}</div>'
    nav = (f'<div class="wnav">'
           + (f'<a href="/?week={wk - 1}">‹</a>' if wk > 1 else "<span></span>")
           + f'<span>Week {wk}' + (f" · {e(P.week_label(wk))}" if P.week_label(wk) else "")
           + f' · {start:%b %d}–{end:%b %d}</span>'
           + (f'<a href="/?week={wk + 1}">›</a>' if wk < n else "<span></span>") + "</div>")

    wp = engine.week_progress(plan, statuses, ctx["activities"], wk)
    prog = "".join(f'<div class="prow"><span class="{sp}">{sp.title()}</span>{_bar(d, p_, sp)}'
                   f'<span class="muted">{_amount(sp, d)} / {_amount(sp, p_)}</span></div>' for sp, (d, p_) in wp.items())
    done, total = engine.plan_compliance(statuses, today)
    if total:
        prog += f'<div class="prow"><span>Plan so far</span>{_bar(done, total, "acc")}<span class="muted">{done}/{total} sessions</span></div>'
    f = ctx.get("fatigue")
    if f and f.get("ratio") is not None and f["history_days"] >= 28:
        cls = "okmsg" if f["ratio"] < 1.3 else "adj"
        prog += (f'<div class="prow"><span>Fatigue</span><span class="{cls}">{f["ratio"]}x fitness</span>'
                 f'<span class="muted">7-day {f["atl"]} vs 42-day {f["ctl"]}</span></div>')
    peaks, best = engine.plan_peaks(plan), ctx.get("bests", {})
    ms = "".join(f'<div class="prow"><span class="{sp}">Longest {nm}</span>{_bar(best.get(sp, 0), peaks[sp], sp)}'
                 f'<span class="muted">{_amount(sp, best.get(sp, 0))} of {_amount(sp, peaks[sp])}</span></div>'
                 for sp, nm in (("swim", "swim"), ("bike", "ride"), ("run", "run")) if sp in peaks)

    busy = (f'<form class="busy" onsubmit="busy(event)"><span>Busy day?</span>'
            f'<input type="date" name="day" value="{today.isoformat()}"><input type="number" name="minutes" '
            f'placeholder="minutes free" min="0"><button>Fit it</button></form>')

    runs = ctx.get("runs") or []
    last_run = (f'<section class="card"><h2>Last run <a class="small muted" href="/runs">all runs ›</a></h2>'
                f'{run_html(runs[0])}{eff_html(ctx.get("efficiency"))}</section>') if runs else ""
    body = f"""{head}
<section class="grid2"><div class="card"><h2>Today</h2>{t_html}{t_actions}</div>
<div class="card"><h2>Recovery signals</h2>{sig}{notes}</div></section>
<section class="card"><h2>Should anything change?</h2>{adv}{busy}</section>
{last_run}
<section class="card">{nav}<div class="week">{cols}</div>
<div class="legend">✓ done · ◐ partial · ✕ missed · ● today · adjusted = changed by you</div></section>
<section class="grid2"><div class="card"><h2>This week</h2>{prog}</div>
<div class="card"><h2>Milestones <span class="muted small">what you've actually done</span></h2>{ms}</div></section>"""
    return page(P.race_name(), body)


def day_html(ctx: dict, day: date) -> str:
    cfg = S.load_config()
    cache = ctx.get("cache", {})
    hr = {k: {int(z): tuple(v) for z, v in zs.items()} for k, zs in (cache.get("hr_zones") or {}).items()}
    ftp = cfg.get("ftp") or cache.get("garmin_ftp")
    swim_t = cfg.get("swim_t_pace_sec")
    sessions = [s for s in ctx["plan"] if s.day == day]
    wd = min(max(P.week_of(day), 1), P.num_weeks())
    head = (f'<header><div><a href="/" class="muted">‹ Dashboard</a><h1>{day:%A, %B %d}</h1>'
            f'<div class="sub">Week {wd}' + (f" · {e(P.week_label(wd))}" if P.week_label(wd) else "") + "</div></div>"
            f'<div class="right"><a class="btn ghost" href="/day/{(day - timedelta(days=1)).isoformat()}">‹ Prev</a>'
            f'<a class="btn ghost" href="/day/{(day + timedelta(days=1)).isoformat()}">Next ›</a></div></header>')
    if not sessions:
        return page(f"{day:%a %b %d}", head + '<section class="card"><h2>Rest day</h2><p>No training. Sleep, eat well, '
                    'walk if you want. Rest is when the training turns into fitness.</p></section>')
    cards = ""
    for s in sessions:
        st = ctx["statuses"].get(s.id)
        how = SWIM_HOW.get(s.kind) if s.sport == "swim" else HOW.get(s.kind)
        c = (f'<section class="card"><h2><span class="dot {SPORT_CLASS.get(s.sport, "")}"></span>{e(s.title)}'
             f' <span class="muted">{e(s.label()) if s.amount else ""}</span>'
             + (' <span class="okmsg small">✓ done</span>' if st and st.state in ("done", "moved") else "") + "</h2>"
             f'<p class="detail">{e(s.detail)}</p>'
             + (f'<p class="adj">Adjusted: {e(s.note)}</p>' if s.note else "")
             + (f"<p><b>How:</b> {e(how)}</p>" if how else ""))
        if s.sport == "swim" and s.kind != "race":
            rows, tot = breakdown(s.detail, s.amount)
            c += '<h3>Set by set</h3><table><tr><th></th><th>Set</th><th>Yards</th><th>Rest after each</th><th>How</th></tr>'
            c += "".join(f'<tr><td><b>{e(r["part"])}</b></td><td>{e(r["set"])}</td><td>{r["yd"]:,}</td>'
                         f'<td>{e(r["rest"] or "-")}</td><td>{e(r["how"])}</td></tr>' for r in rows) + "</table>"
            c += (f'<p class="muted small">Total {tot:,} yd</p>' if tot == s.amount else
                  f'<p class="adj">These sets add up to {tot:,} yd; the plan lists {s.amount:,}.</p>')
            if "drill" in s.detail.lower():
                late = s.day.weekday() >= 3
                for ds in drill_sets(s.detail, s.week, late) or drill_sets("4x50 drills", s.week, late):
                    split = f"{ds['per']}x{ds['dist']} of each" if len(ds["drills"]) > 1 else f"all {ds['drills'][0]}"
                    c += f'<h3>Drills, {ds["part"]}: {ds["reps"]}x{ds["dist"]} = {split}</h3>'
                    c += '<p class="muted small">25 drill / 25 easy swim, 15-20s rest</p>'
                    for name in ds["drills"]:
                        d = DRILLS[name]
                        c += (f'<div class="drill"><b>{e(name)}</b><div>{e(d["how"])}'
                              + (f' <span class="muted">({e(d["gear"])})</span>' if d["gear"] else "")
                              + f'</div><div class="why">Why: {e(d["why"])}</div></div>')
        zs = zones_in(s.detail) or ([2, 3] if s.sport == "swim" else DEFAULT_ZONES.get(s.kind, []))
        if zs and s.sport in ("bike", "run", "swim"):
            cols = ["Zone"] + (["Power" + (f" (FTP {ftp} W)" if ftp else "")] if s.sport == "bike" else []) + \
                   (["Pace"] if s.sport == "swim" else []) + (["Heart rate"] if s.sport != "swim" else []) + ["Feels like"]
            c += "<h3>Zones</h3><table><tr>" + "".join(f"<th>{e(x)}</th>" for x in cols) + "</tr>"
            for z, target, bpm, feel in zone_rows(s.sport, zs, ftp, hr, swim_t):
                cells = [z] + ([target or "set FTP"] if s.sport == "bike" else []) + \
                        ([target or "after your swim test"] if s.sport == "swim" else []) + \
                        ([bpm or "no zones yet"] if s.sport != "swim" else []) + [feel]
                c += "<tr>" + "".join(f"<td>{e(x)}</td>" for x in cells) + "</tr>"
            c += "</table>"
        fuel = cfg.get("fuel_g_per_h", {})
        if s.sport in ("bike", "run") and s.amount >= 90:
            c += (f"<p><b>Fuel:</b> start eating by minute 30-45, aim for {e(fuel.get(s.sport, '30-60'))} g carbs/hour, "
                  "drink to thirst. Practice what you'll use on race day.</p>")
        cards += c + "</section>"
    if any(s.sport in ("swim", "run", "bike") for s in sessions):
        cards += (f'<div class="actions"><button onclick="act(\'/api/send/{day.isoformat()}\')">'
                  f"{_send_label(sessions)}</button></div>")
    return page(f"{day:%a %b %d}", head + cards)


def setup_html(msg: str) -> str:
    return page("Set up", f'<section class="card"><h2>Almost there</h2><p>{e(msg)}</p>'
                "<p>In your terminal run <code>ironman setup</code>, then reload this page.</p></section>")


# ---- server -----------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        today = date.today()
        try:
            if u.path == "/":
                q = parse_qs(u.query)
                wk = int(q["week"][0]) if "week" in q else None
                return self._send(200, dashboard_html(_ctx(today), wk))
            if u.path == "/runs":
                ctx = _ctx(today)
                runs = ctx.get("runs") or []
                body = ('<header><div><a href="/" class="muted">‹ Dashboard</a><h1>Your runs</h1>'
                        '<div class="sub">Last 6 weeks</div></div></header>'
                        f'<section class="card">{eff_html(ctx.get("efficiency")) or "<p>No easy-run trend yet.</p>"}</section>'
                        + "".join(f'<section class="card">{run_html(r)}</section>' for r in runs)
                        + ("" if runs else '<section class="card"><p>No runs yet.</p></section>'))
                return self._send(200, page("Runs", body))
            if u.path.startswith("/day/"):
                return self._send(200, day_html(_ctx(today), date.fromisoformat(u.path[5:15])))
            return self._send(404, page("Not found", "<p>Not found. <a href='/'>Dashboard</a></p>"))
        except cli.NotSetUp as ex:
            return self._send(200, setup_html(str(ex)))
        except Exception as ex:
            return self._send(500, page("Error", f"<pre>{e(type(ex).__name__)}: {e(str(ex))}</pre>"))

    def do_POST(self):
        if self.headers.get("X-Token") != TOKEN:
            return self._send(403, json.dumps({"messages": ["Reload the page and try again."]}), "application/json")
        n = int(self.headers.get("Content-Length") or 0)
        data = json.loads(self.rfile.read(n) or b"{}")
        msgs: list[str] = []
        say = lambda m: msgs.append(_plain(str(m)))
        path = urlparse(self.path).path
        today = date.today()
        try:
            with LOCK:
                if path == "/api/sync":
                    _, err = cli.maybe_sync(S.load_config(), force=True, quiet=True)
                    say(f"Sync failed: {err}" if err else "Synced with Garmin.")
                elif path.startswith("/api/apply/") or path.startswith("/api/dismiss/"):
                    cli.build(today, sync=False)  # refresh numbering
                    cli.cmd_apply(int(path.rsplit("/", 1)[1]), dismiss="dismiss" in path, say=say)
                elif path == "/api/undo":
                    cli.cmd_undo(say=say)
                elif path.startswith("/api/send/"):
                    ctx = cli.build(today, sync=False)
                    cli.cmd_send(ctx, date.fromisoformat(path.rsplit("/", 1)[1]), say=say)
                elif path == "/api/note":
                    st = S.load_state()
                    if data.get("what") == "clear":
                        st["notes"].pop(today.isoformat(), None)
                        say("Cleared today's note.")
                    else:
                        st["notes"][today.isoformat()] = data.get("what")
                        say(f"Noted: {data.get('what')}.")
                    S.save_state(st)
                elif path == "/api/busy":
                    st = S.load_state()
                    st["busy"][data["day"]] = int(data["minutes"])
                    S.save_state(st)
                    say(f"Got it: {data['minutes']} min on {data['day']}.")
                else:
                    return self._send(404, json.dumps({"messages": ["Unknown action"]}), "application/json")
        except Exception as ex:
            say(f"{type(ex).__name__}: {ex}")
        self._send(200, json.dumps({"messages": msgs}), "application/json")


def _background_sync(stop: threading.Event):
    while not stop.is_set():
        try:
            with LOCK:
                cli.maybe_sync(S.load_config(), force=False, quiet=True)  # only syncs when stale
        except Exception:
            pass
        stop.wait(30 * 60)


def serve(port: int = PORT, open_browser: bool = True):
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    stop = threading.Event()
    threading.Thread(target=_background_sync, args=(stop,), daemon=True).start()
    url = f"http://localhost:{port}"
    print(f"Dashboard running at {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        srv.server_close()


# ---- always on (macOS) ------------------------------------------------------------
LABEL = "com.ironman-coach.web"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def install_always(port: int = PORT):
    S.DATA.mkdir(parents=True, exist_ok=True)
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    PLIST.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{LABEL}</string>
  <key>ProgramArguments</key><array>
    <string>{sys.executable}</string><string>-m</string><string>ironman_coach.cli</string>
    <string>web</string><string>--no-browser</string><string>--port</string><string>{port}</string>
  </array>
  <key>WorkingDirectory</key><string>{S.ROOT}</string>
  <key>EnvironmentVariables</key><dict><key>IRONMAN_HOME</key><string>{S.ROOT}</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>{S.DATA / "web.log"}</string>
  <key>StandardErrorPath</key><string>{S.DATA / "web.log"}</string>
</dict></plist>
""")
    subprocess.run(["launchctl", "unload", str(PLIST)], capture_output=True)
    subprocess.run(["launchctl", "load", "-w", str(PLIST)], check=False)
    print(f"Always on: http://localhost:{port} now starts when you log in and restarts if it stops.")
    print("Turn it off with: ironman web --stop")
    time.sleep(1)
    webbrowser.open(f"http://localhost:{port}")


def uninstall_always():
    if PLIST.exists():
        subprocess.run(["launchctl", "unload", "-w", str(PLIST)], capture_output=True)
        os.remove(PLIST)
        print("Always-on dashboard turned off.")
    else:
        print("It wasn't set to always on.")


CSS = """
:root{--bg:#f7f6f3;--card:#fff;--ink:#1d1d1b;--mut:#8a8984;--line:#e6e4de;--acc:#e8743b;
--swim:#3d8fd1;--bike:#d9a21b;--run:#d9534f;--str:#8a7fd0;--ok:#3a9a5b;--warn:#d9a21b;--bad:#d9534f}
@media(prefers-color-scheme:dark){:root{--bg:#18181a;--card:#222225;--ink:#ecebe7;--mut:#8f8e8a;--line:#333337}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.55 -apple-system,BlinkMacSystemFont,"Inter","Segoe UI",sans-serif}
main{max-width:1000px;margin:0 auto;padding:28px 18px 60px}
header{display:flex;justify-content:space-between;align-items:flex-end;gap:12px;margin-bottom:18px;flex-wrap:wrap}
h1{margin:0;font-size:26px;letter-spacing:-.02em;font-weight:650}h2{margin:0 0 12px;font-size:15px;font-weight:600}
h3{font-size:13px;margin:18px 0 6px;font-weight:600}
.sub{color:var(--acc);font-weight:550}.muted{color:var(--mut)}.small{font-size:12.5px}
.right{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px;margin-bottom:14px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}.grid2 .card{margin-bottom:0}.grid2{margin-bottom:14px}
@media(max-width:720px){.grid2{grid-template-columns:1fr}.week{grid-template-columns:1fr!important}.day{min-height:0}}
button,.btn{background:var(--acc);color:#fff;border:0;border-radius:9px;padding:7px 13px;font:inherit;font-size:13.5px;
font-weight:550;cursor:pointer;text-decoration:none;display:inline-block}
button.ghost,.btn.ghost{background:transparent;color:var(--ink);border:1px solid var(--line)}
button:hover,.btn:hover{filter:brightness(1.06)}
.actions{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}.notes{display:flex;gap:6px;margin-top:12px;flex-wrap:wrap}
.notes button{padding:4px 10px;font-size:12.5px}
a{color:inherit}.sess{display:flex;align-items:center;gap:7px;padding:5px 0;text-decoration:none}
.sess b{font-weight:550}.dot{width:9px;height:9px;border-radius:50%;display:inline-block;flex:none}h2 .dot{margin-right:8px}
.dot.swim,.fill.swim{background:var(--swim)}.dot.bike,.fill.bike{background:var(--bike)}.dot.run,.fill.run{background:var(--run)}
.dot.str{background:var(--str)}.dot.race,.fill.acc{background:var(--acc)}
span.swim{color:var(--swim)}span.bike{color:var(--bike)}span.run{color:var(--run)}
.st{margin-left:auto;font-weight:700}.st.done,.st.moved{color:var(--ok)}.st.partial{color:var(--warn)}
.st.missed{color:var(--bad)}.st.today{color:var(--acc)}
.adj{color:var(--acc);font-size:12px;font-style:italic}
.sig{display:grid;grid-template-columns:14px 90px 1fr;gap:4px 8px;align-items:baseline;padding:3px 0}
.sig .muted{grid-column:3;font-size:12.5px;margin-top:-4px}
.lvl{width:9px;height:9px;border-radius:50%;display:inline-block;border:1.5px solid var(--mut)}
.lvl.ok{background:var(--ok);border-color:var(--ok)}.lvl.warn{background:var(--warn);border-color:var(--warn)}
.lvl.bad{background:var(--bad);border-color:var(--bad)}
.adv{border-left:3px solid var(--line);padding:4px 0 4px 12px;margin-bottom:14px}
.adv.suggest{border-color:var(--acc)}.adv.important{border-color:var(--bad)}.adv .t{font-weight:600}
.instead{color:var(--acc);margin-top:3px}.okmsg{color:var(--ok)}.rest{color:var(--mut);padding:6px 0}
.busy{display:flex;gap:8px;align-items:center;margin-top:12px;flex-wrap:wrap;font-size:13px}
input{font:inherit;font-size:13px;padding:6px 8px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink)}
.wnav{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;font-weight:600}
.wnav a{text-decoration:none;font-size:20px;padding:0 8px}
.week{display:grid;grid-template-columns:repeat(7,1fr);gap:6px}
.day{border:1px solid var(--line);border-radius:10px;padding:8px;min-height:84px;font-size:13px}
.day.today{border-color:var(--acc)}.dh{font-weight:600;font-size:12px;margin-bottom:4px;color:var(--mut)}
.day.today .dh{color:var(--acc)}.day .sess{padding:2px 0;flex-wrap:wrap}.day .sess b{font-size:12.5px}
.legend{color:var(--mut);font-size:12px;text-align:right;margin-top:10px}
.prow{display:grid;grid-template-columns:110px 1fr auto;gap:10px;align-items:center;padding:4px 0;font-size:13.5px}
.bar{height:8px;background:var(--line);border-radius:5px;overflow:hidden}.fill{height:100%;border-radius:5px}
table{width:100%;border-collapse:collapse;font-size:13.5px}th{text-align:left;color:var(--mut);font-weight:550}
th,td{padding:5px 8px 5px 0;border-bottom:1px solid var(--line)}
.detail{background:var(--bg);border-radius:8px;padding:9px 11px;font-family:ui-monospace,Menlo,monospace;font-size:13px}
.drill{padding:7px 0;border-bottom:1px solid var(--line)}.drill .why{color:var(--acc);font-size:13px}
.zstrip{display:flex;height:10px;border-radius:5px;overflow:hidden;margin:8px 0 3px}
.run>div{margin-bottom:3px}.err{background:#d9534f22;color:var(--bad);padding:10px 14px;border-radius:10px;margin-bottom:14px}
#toast{position:fixed;bottom:18px;left:50%;transform:translateX(-50%);background:var(--ink);color:var(--bg);
padding:10px 16px;border-radius:10px;font-size:13.5px;max-width:90%;opacity:0;transition:opacity .25s;pointer-events:none}
#toast.show{opacity:1}code{background:var(--bg);padding:1px 5px;border-radius:5px}
"""

JS = """
function toast(m){const t=document.getElementById('toast');t.textContent=m;t.classList.add('show');
clearTimeout(window._tt);window._tt=setTimeout(()=>t.classList.remove('show'),4500)}
async function act(url,data){try{const r=await fetch(url,{method:'POST',headers:{'X-Token':TOKEN,
'Content-Type':'application/json'},body:JSON.stringify(data||{})});const j=await r.json();
toast((j.messages||[]).join(' ')||'Done.');setTimeout(()=>location.reload(),1400)}catch(e){toast('Could not reach the app.')}}
function busy(ev){ev.preventDefault();const f=ev.target;if(!f.minutes.value){toast('Enter how many minutes you have.');return}
act('/api/busy',{day:f.day.value,minutes:f.minutes.value})}
setInterval(()=>{if(!document.activeElement||document.activeElement.tagName!=='INPUT')location.reload()},5*60*1000);
"""
