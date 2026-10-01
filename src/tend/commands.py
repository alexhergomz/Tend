import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from rich.markup import escape
from rich.padding import Padding
from rich.text import Text

from . import backup, config, features, fmt, hooks, keys, parse, reminders, repeat, slips, transfer, ui, views
from . import focus as focus_timer
from .app import App, UsageError
from .store import UndoBlocked
from .model import STATES, Task
from .store import now_iso
from .ui import ACCENT, DIM, WARN, console


def _t(t: Task) -> str:
    return f"[bold]{escape(t.title)}[/]"


def _add_goal_hint(app: App, goal: str | None):
    if goal and app.store.ensure_goal(goal):
        app.say(f"   [{DIM}]new goal '{escape(goal)}' · give it a weekly target: t g add {escape(goal)} 3h[/]")


# ── doing ───────────────────────────────────────────────────────────────
def _energy_flag(app: App, args):
    for a in args:
        if a.lstrip("-") in ("low", "high"):
            app.energy_override = a.lstrip("-")


def cmd_next(app: App, args):
    _energy_flag(app, args)
    ranked = app.ranked()
    if app.json:
        return app.emit(ranked[0].to_json() if ranked else None)
    if app.tui:
        return
    if not ranked:
        app.say(f" [{DIM}]Nothing to do. Capture something with[/] t <text>")
        return app.bar("empty")
    app.store.set_meta("current", ranked[0].task.id)
    console.print(ui.card(ranked[0], app.today))
    app.bar("next")


def cmd_focus(app: App, args):
    mode, box_min, rest = app.cfg["focus"]["default_mode"], None, []
    it = iter(args)
    for a in it:
        word = a.lstrip("-")
        if word in ("pomo", "flow", "box"):
            mode = word
            if word == "box":
                nxt = next(it, None)
                if nxt:
                    try:
                        box_min = parse.parse_duration(nxt)
                    except parse.ParseError:
                        rest.append(nxt)
        else:
            rest.append(a)
    t = app.target(rest)
    if not t:
        return app.say(f" [{DIM}]Nothing to focus on.[/]")
    if not keys.interactive():
        raise UsageError("focus needs an interactive terminal")
    if app.on("states") and t.stage != "started":
        _set_stage(app, t, "started", quiet=True)
    start = datetime.now()
    app.hook("on_focus_start", t, mode=mode)
    result = focus_timer.run(t.title, ui.meta(t, app.today), mode, app.cfg, box_min)
    if result.minutes >= 0.5:
        app.store.add_session(t.id, start, datetime.now(), mode, round(result.minutes, 1))
    app.hook("on_focus_end", t, mode=mode, minutes=round(result.minutes, 1), outcome=result.outcome)
    app.say(f" [{ACCENT}]●[/] focused {fmt.minutes(result.minutes)} on {_t(t)}")
    if result.outcome == "done":
        _complete(app, t)
        app.bar("done")
    else:
        app.bar("next")


def _dates_for_repeat(app: App, t: Task):
    """A repeating task always has a date: without one, it gets the first date of its rule."""
    if t.repeat and app.on("repeat") and not t.due and not t.aim:
        t.aim = repeat.parse(t.repeat).first(app.today)


def _next_copy(app: App, t: Task) -> Task | None:
    """Inside an event: create the next copy of a repeating task. Returns it."""
    if not (t.repeat and app.on("repeat")):
        return None
    planned = t.due or t.aim or app.today
    nxt = repeat.parse(t.repeat).next_after(planned, max(planned, app.today))
    shift = nxt - planned
    copy = Task(id=None, title=t.title, goal=t.goal, value=t.value, size=t.size, estimate_min=t.estimate_min,
                energy=t.energy, repeat=t.repeat, series=t.series or t.id,
                due=t.due + shift if t.due else None, aim=(t.aim + shift if t.aim else None) if t.due or t.aim else nxt)
    app.store.insert(copy)
    return copy


def _say_next(app: App, copy: Task | None):
    if copy:
        app.say(f"   [{DIM}]↻ next one {fmt.day(copy.due or copy.aim, app.today)} · #{copy.id}[/]")


def _complete(app: App, t: Task):
    with app.store.event("done", f"done #{t.id} {t.title}"):
        t.status, t.done_at = "done", now_iso()
        app.store.update(t)
        copy = _next_copy(app, t)
        parent = app.store.task(t.parent) if t.parent else None
        while parent and parent.status == "open" and not app.store.children(parent.id):
            parent.status, parent.done_at = "done", now_iso()
            app.store.update(parent)
            app.say(f" [{ACCENT}]✓[/] all steps done · {_t(parent)}")
            _next_copy(app, parent)
            parent = app.store.task(parent.parent) if parent.parent else None
    app.store.set_meta("current", None)
    app.hook("on_done", app.store.task(t.id))
    app.hook("on_status", app.store.task(t.id), old=t.stage, new="done")
    n = len(app.store.done_since(app.today))
    app.say(f" [{ACCENT}]✓[/] {_t(t)}  [{DIM}]{n} done today[/]")
    _say_next(app, copy)


def cmd_done(app: App, args):
    t = app.target(args)
    if not t:
        return app.say(f" [{DIM}]Nothing open.[/]")
    _complete(app, t)
    if app.json:
        return app.emit(app.store.task(t.id).to_json())
    app.bar("done")


def cmd_skip(app: App, args):
    t = app.target(args)
    if not t:
        return app.say(f" [{DIM}]Nothing to skip.[/]")
    with app.store.event("skip", f"skip #{t.id} {t.title}"):
        t.skip_date = app.today
        app.store.update(t)
    app.store.set_meta("current", None)
    app.hook("on_skip", t)
    app.say(f" [{DIM}]↷ skipped for today:[/] {escape(t.title)}")
    if not app.tui:
        cmd_next(app, [])


def _split(app: App, t: Task, steps: list[str]):
    with app.store.event("split", f"split #{t.id} {t.title}") as ev:
        ids, titles = [], []
        for step in steps:
            title, f = parse.parse_tokens([step], app.today)
            child = Task(
                id=None, title=title or step, parent=t.id, goal=f.get("goal", t.goal),
                value=f.get("value", t.value or 2), size=f.get("size", "S"),
                estimate_min=f.get("estimate_min"), due=f.get("due", t.due),
                aim=f.get("aim", t.aim if t.aim and t.aim >= app.today else None),
            )
            ids.append(app.store.insert(child))
            titles.append(child.title)
        if t.aim and t.aim < app.today:
            t.aim, t.slips = None, 0
            app.store.update(t)
        ev["summary"] += f" into #{', #'.join(map(str, ids))}"
    app.store.set_meta("current", ids[0])
    app.say(f" [{ACCENT}]✂[/] {_t(t)}")
    for i, title in zip(ids, titles):
        app.say(f"   [{DIM}]└ #{i}[/] {escape(title)}")


def cmd_split(app: App, args):
    ids = [a for a in args if a.lstrip("#").isdigit()]
    steps = [a for a in args if a not in ids]
    t = app.target(ids)
    if not t:
        return app.say(f" [{DIM}]Nothing to split.[/]")
    if not steps:
        console.print(f" Split {_t(t)} into steps. [{DIM}]Make the first one tiny. Empty line to finish.[/]")
        while step := ui.ask(f"   step {len(steps) + 1} › "):
            steps.append(step)
    if not steps:
        return
    _split(app, t, steps)
    app.bar("next")


# ── capturing & changing ────────────────────────────────────────────────
def cmd_add(app: App, args):
    if not args:
        text = ui.ask(" add › ")
        if not text:
            return
        args = [text]
    title, f = parse.parse_tokens(args, app.today)
    if not title:
        raise UsageError("a task needs a title")
    t = Task(id=None, title=title, **f)
    _dates_for_repeat(app, t)
    with app.store.event("add") as ev:
        app.store.insert(t)
        ev["summary"] = f"add #{t.id} {t.title}"
    app.hook("on_add", t)
    if app.json:
        return app.emit(t.to_json())
    where = "" if t.triaged else f" [{DIM}]→ inbox[/]"
    app.say(f" [{ACCENT}]+[/] {_t(t)} [{DIM}]#{t.id}[/]{where}")
    if t.repeat and app.on("repeat"):
        first = t.due or t.aim
        app.say(f"   [{DIM}]↻ {repeat.parse(t.repeat).describe()} · first one {fmt.day(first, app.today)}[/]")
    _add_goal_hint(app, t.goal)
    app.bar("added")


def cmd_edit(app: App, args):
    ids = [a for a in args[:1] if a.lstrip("#").isdigit()]
    tokens = args[len(ids):]
    t = app.target(ids)
    if not t:
        return app.say(f" [{DIM}]Nothing to edit.[/]")
    if not tokens:
        console.print(f" Editing {_t(t)} [{DIM}]· tokens like due:fri v:3 +goal, or a new title[/]")
        text = ui.ask(f"   #{t.id} › ")
        if not text:
            return
        tokens = [text]
    title, f = parse.parse_tokens(tokens, app.today)
    with app.store.event("edit", f"edit #{t.id} {t.title}"):
        if title:
            t.title = title
        for k, v in f.items():
            setattr(t, k, v)
        _dates_for_repeat(app, t)
        if "aim" in f or "due" in f:
            t.slips = 0
        app.store.update(t)
    if app.json:
        return app.emit(t.to_json())
    app.say(f" [{ACCENT}]✎[/] {_t(t)}")
    _add_goal_hint(app, f.get("goal"))
    app.bar("list")


# ── status ──────────────────────────────────────────────────────────────
def _set_stage(app: App, t: Task, stage: str, until=None, quiet: bool = False):
    old = t.stage
    with app.store.event("status", f"{stage} #{t.id} {t.title}"):
        t.stage = stage
        t.start_after = until if stage == "waiting" else (None if old == "waiting" else t.start_after)
        if stage == "started" and not t.started_at:
            t.started_at = now_iso()
        app.store.update(t)
        parent = app.store.task(t.parent) if t.parent else None
        if stage == "started" and parent and parent.stage == "todo":
            parent.stage, parent.started_at = "started", parent.started_at or now_iso()
            app.store.update(parent)
    app.hook("on_status", t, old=old, new=stage)
    if stage == "started" and not quiet:
        app.say(f" [{ACCENT}]▸[/] started {_t(t)}")
        limit = app.cfg["priority"]["max_started"]
        n = sum(1 for x in app.store.tasks() if x.stage == "started" and x.id not in app.store.blocked_ids())
        if n > limit:
            app.say(f" [{WARN}]{n} tasks are started.[/] [{DIM}]Finishing one before starting more usually goes faster.[/]")
    elif stage == "waiting":
        when = f" until {fmt.day(until, app.today)}" if until else ""
        back = f"back in the queue {fmt.day(until, app.today)}" if until else "t ls shows it"
        app.say(f" [{DIM}]⏸ waiting{when}:[/] {escape(t.title)} [{DIM}]· {back}[/]")
    elif stage == "todo" and not quiet:
        app.say(f" [{DIM}]○ back to todo:[/] {escape(t.title)}")


def cmd_start(app: App, args):
    t = app.target(args)
    if not t:
        return app.say(f" [{DIM}]Nothing to start.[/]")
    if t.stage == "started":
        app.say(f" [{DIM}]Already started:[/] {escape(t.title)}")
    else:
        _set_stage(app, t, "started")
    if app.json:
        return app.emit(app.store.task(t.id).to_json())
    app.bar("next")


def cmd_wait(app: App, args):
    ids = [a for a in args[:1] if a.lstrip("#").isdigit()]
    rest = args[len(ids):]
    t = app.target(ids)
    if not t:
        return app.say(f" [{DIM}]Nothing to put on hold.[/]")
    text = " ".join(rest)
    if not rest and app.tui:
        text = ui.ask(f" {t.title} is waiting until? (a date, or enter for no date) › ")
    until = parse.parse_date(text, app.today) if text else None
    _set_stage(app, t, "waiting", until)
    if app.json:
        return app.emit(app.store.task(t.id).to_json())
    app.bar("next")


def cmd_status(app: App, args):
    states = [a for a in args if a in STATES]
    ids = [a for a in args if a.lstrip("#").isdigit()]
    if not states:
        raise UsageError("usage: t status [id] todo|started|waiting|done|dropped")
    t = app.target(ids)
    if not t:
        return app.say(f" [{DIM}]No open task.[/]")
    state = states[0]
    if state == "done":
        _complete(app, t)
    elif state == "dropped":
        _drop(app, t)
    elif state == t.stage:
        app.say(f" [{DIM}]Already {state}:[/] {escape(t.title)}")
    else:
        _set_stage(app, t, state)
    if app.json:
        return app.emit(app.store.task(t.id).to_json())
    app.bar("next")


def _drop(app: App, t: Task, once: bool = False):
    """Drop a task and its steps. With once=True, a repeating task gets its next copy (skip this one)."""
    with app.store.event("drop", f"{'skip once' if once else 'drop'} #{t.id} {t.title}"):
        stack = [t]
        while stack:
            cur = stack.pop()
            cur.status, cur.done_at = "dropped", now_iso()
            app.store.update(cur)
            stack.extend(app.store.children(cur.id))
        copy = _next_copy(app, t) if once else None
    app.store.set_meta("current", None)
    app.hook("on_drop", t)
    app.hook("on_status", t, old=t.stage, new="dropped")
    if once:
        app.say(f" [{DIM}]skipped this time:[/] {escape(t.title)} [{DIM}]· u to undo[/]")
        _say_next(app, copy)
    else:
        app.say(f" [{DIM}]let go:[/] {escape(t.title)} [{DIM}]· u to undo[/]")


def _ask_once(app: App, t: Task, args) -> bool:
    """For a repeating task: skip just this one (True) or stop the series (False)?"""
    if not (t.repeat and app.on("repeat")):
        return False
    if "--once" in args:
        return True
    if "--stop" in args or not keys.interactive():
        return False
    k = ui.choose(f"{t.title} repeats {repeat.parse(t.repeat).describe()}.",
                  {"o": "skip just this one", "s": "stop repeating"})
    return k == "o"


def cmd_drop(app: App, args):
    t = app.target([a for a in args if not a.startswith("--")])
    if not t:
        return app.say(f" [{DIM}]Nothing to drop.[/]")
    _drop(app, t, once=_ask_once(app, t, args))
    app.bar("next")


def cmd_undo(app: App, args):
    try:
        summary = app.store.undo()
    except UndoBlocked as e:
        raise UsageError(f"The last change was an import or a restore, which undo can't reverse. "
                         f"To go back: t restore (copy 1 is from just before it)") from None
    app.say(f" [{ACCENT}]↶[/] undid: {escape(summary)}" if summary else f" [{DIM}]Nothing to undo.[/]")
    app.bar("next")


# ── sorting ─────────────────────────────────────────────────────────────
def cmd_triage(app: App, args):
    inbox = [t for t in app.store.tasks() if not t.triaged]
    if not inbox:
        app.say(f" [{DIM}]Inbox is empty.[/]")
        return app.bar("next")
    goals = [g.name for g in app.store.goals()]
    for i, t in enumerate(inbox, 1):
        console.print(f"\n [{DIM}]{i}/{len(inbox)}[/]  {_t(t)}")
        v = ui.choose("matters?", {"1": "nice to have", "2": "matters", "3": "really", "k": "drop", "enter": "later", "q": "stop"})
        if v == "q":
            break
        if v == "enter":
            continue
        if v == "k":
            _drop(app, t)
            continue
        s = ui.choose("size?   ", {"s": "<1h", "m": "1-3h", "l": ">3h"})
        date_text = ui.ask(" date?    fri · oct20 · +3d  (prefix ~ for a soft target, enter for none) › ")
        due = aim = None
        while date_text:
            try:
                d = parse.parse_date(date_text.lstrip("~"), app.today)
                due, aim = (None, d) if date_text.startswith("~") else (d, None)
                break
            except parse.ParseError as e:
                date_text = ui.ask(f" [{WARN}]{e}[/] › ")
        goal = t.goal
        if goals and not goal:
            opts = {str(n): g for n, g in enumerate(goals[:9], 1)} | {"enter": "none"}
            g = ui.choose("goal?   ", opts)
            goal = opts[g] if g != "enter" else None
        with app.store.event("triage", f"triage #{t.id} {t.title}"):
            t.value, t.size, t.goal = int(v), s.upper(), goal
            t.due, t.aim = due or t.due, aim or t.aim
            app.store.update(t)
        if s == "l":
            console.print(f"   [{DIM}]big one · consider[/] t x {t.id} [{DIM}]to split it into steps[/]")
    app.say(f" [{ACCENT}]✓[/] triaged")
    app.bar("next")


def cmd_resolve(app: App, args):
    todo = app.slipped()
    if not todo:
        app.say(f" [{DIM}]Nothing has slipped.[/]")
        return app.bar("next")
    console.print(f" [bold]{len(todo)} task{'s' * (len(todo) > 1)} missed {'their' if len(todo) > 1 else 'its'} date.[/] "
                  f"[{DIM}]Pick one option for each:[/]")
    for key, name, what in (
        ("n", "do it today", "the date moves to today"),
        ("r", "reschedule", "you type a new date"),
        ("x", "split", "break it into smaller steps"),
        ("k", "drop", "remove it (u brings it back)"),
        ("q", "later", "stop here, the rest stay in the slipped count"),
    ):
        console.print(f"   [bold {ACCENT}]{key}[/]  {name:<12}[{DIM}]{what}[/]")
    for t in todo:
        hard = bool(t.due and t.due < app.today)
        console.print(f"\n {_t(t)}  [{WARN}]{slips.why(t, app.today)}[/]")
        repeating = bool(t.repeat and app.on("repeat"))
        k = ui.choose("", {"n": "today", "r": "reschedule", "x": "split",
                           "k": "skip this one" if repeating else "drop", "q": "later"})
        if k == "q":
            break
        if k == "k":
            _drop(app, t, once=repeating)
        elif k == "x":
            steps = []
            while step := ui.ask(f"   step {len(steps) + 1} › "):
                steps.append(step)
            if steps:
                if hard:
                    with app.store.event("resolve", f"reset deadline #{t.id} {t.title}"):
                        t.due = app.today
                        app.store.update(t)
                _split(app, t, steps)
        else:
            when = app.today
            if k == "r":
                while True:
                    text = ui.ask("   new date (required) › ")
                    try:
                        when = parse.parse_date(text, app.today)
                        break
                    except parse.ParseError as e:
                        console.print(f"   [{WARN}]{e}[/]")
            with app.store.event("resolve", f"reschedule #{t.id} {t.title}"):
                if hard:
                    t.due = when
                else:
                    t.aim = when
                t.slips = 0
                app.store.update(t)
            app.say(f" [{ACCENT}]→[/] {_t(t)} [{DIM}]{'due' if hard else 'aim'} {fmt.day(when, app.today)}[/]")
    app.bar("next")


# ── looking ─────────────────────────────────────────────────────────────
def cmd_ls(app: App, args):
    _energy_flag(app, args)
    ranked = app.ranked()
    if app.json:
        return app.emit([r.to_json() for r in ranked])
    if not ranked:
        app.say(f" [{DIM}]Nothing open.[/]")
        return app.bar("empty")
    ui.queue(ranked, app.today)
    waiting = [t for t in app.store.tasks() if t.stage == "waiting" and t.id not in {r.task.id for r in ranked}]
    if waiting and app.on("states"):
        console.print(f"\n [bold]Waiting[/] [{DIM}]· not in the queue · t start <id> brings one back[/]")
        for t in waiting:
            console.print(Text("   ") + Text(t.title) + Text("  ") + ui.meta(t, app.today))
    app.bar("list")


def cmd_goals(app: App, args):
    if args and args[0] in ("add", "set"):
        if len(args) < 3:
            raise UsageError("usage: t g add <name> <weekly time> [why...]")
        name = args[1].lstrip("+").lower()
        app.store.set_goal(name, parse.parse_duration(args[2]), " ".join(args[3:]) or None)
        app.say(f" [{ACCENT}]◆[/] {escape(name)} [{DIM}]· {fmt.minutes(parse.parse_duration(args[2]))} a week[/]")
    elif args and args[0] == "rm":
        if len(args) < 2:
            raise UsageError("usage: t g rm <name>")
        ok = app.store.delete_goal(args[1].lstrip("+").lower())
        app.say(f" [{DIM}]removed goal {escape(args[1])}[/]" if ok else f" [{WARN}]no goal {escape(args[1])}[/]")
    goals = app.store.goals()
    spent = app.store.goal_minutes(app.week_start)
    if app.json:
        return app.emit([{"name": g.name, "weekly_min": g.weekly_min, "why": g.why,
                          "this_week_min": round(spent.get(g.name, 0), 1)} for g in goals])
    if not goals:
        app.say(f" [{DIM}]No goals yet. A goal with a weekly target gets one 'big rock' task a day:[/] t g add thesis 3h")
        return app.bar("goals")
    width = max(len(g.name) for g in goals)
    console.print(f" [{DIM}]This week[/]")
    for g in goals:
        m = spent.get(g.name, 0)
        line = f" {escape(g.name):<{width}}  "
        if g.weekly_min:
            filled = min(int(m / g.weekly_min * 20), 20)
            done = " ✓" if m >= g.weekly_min else ""
            line += f"[{ACCENT}]{'━' * filled}[/][{DIM}]{'━' * (20 - filled)}[/]  {fmt.minutes(m)} [{DIM}]/ {fmt.minutes(g.weekly_min)}[/][{ACCENT}]{done}[/]"
        else:
            line += f"[{DIM}]{fmt.minutes(m)} · no weekly target[/]"
        if g.why:
            line += f"   [{DIM}]{escape(g.why)}[/]"
        console.print(line)
    app.bar("goals")


def cmd_wins(app: App, args):
    week = any(a.lstrip("-") == "week" for a in args)
    since = app.week_start if week else app.today
    done = app.store.done_since(since)
    focused = app.store.focused_since(since)
    if app.json:
        return app.emit({"since": since, "done": [t.to_json() for t in done], "focused_min": round(focused, 1)})
    label = "This week" if week else "Today"
    console.print(f" [bold]{label}[/] [{DIM}]·[/] {len(done)} done [{DIM}]·[/] {fmt.minutes(focused)} focused")
    for t in done:
        when = datetime.fromisoformat(t.done_at)
        stamp = f"{when:%a}" if week else f"{when:%H:%M}"
        goal = f" [{DIM}]{escape(t.goal)}[/]" if t.goal else ""
        console.print(f"   [{ACCENT}]✓[/] [{DIM}]{stamp}[/]  {escape(t.title)}{goal}")
    if not done and not focused:
        console.print(f"   [{DIM}]Nothing yet, and that's fine. One small step counts.[/]")
    app.bar("done")


# ── planning ────────────────────────────────────────────────────────────
def _days_arg(args, default: int) -> int:
    for i, a in enumerate(args):
        if a.lstrip("-") == "days" and i + 1 < len(args) and args[i + 1].isdigit():
            return max(1, min(int(args[i + 1]), 31))
        if a.lstrip("-") in ("week", "w"):
            return 7
    return default


def cmd_plan(app: App, args):
    plan, notes = app.build_plan()
    if "--ics" in args:
        return print(views.to_ics(plan), end="")
    if app.json:
        return app.emit({
            "blocks": [{"task_id": b.task.id, "title": b.task.title, "start": b.start, "end": b.end, "rule": b.rule}
                       for b in plan.blocks],
            "events": [{"title": e.title, "start": e.start, "end": e.end} for e in plan.events],
            "late": [{"task_id": l.task.id, "title": l.task.title, "due": l.task.due, "finish": l.finish,
                      "minutes_left": round(l.minutes_left)} for l in plan.late],
            "corrections": app.corrections.to_json(),
        })
    for n in notes:
        console.print(f" [{WARN}]{escape(n)}[/]")
    day = next((d for d in plan.days if plan.on(d)), app.today)
    if day != app.today:
        console.print(f" [{DIM}]Nothing more planned today.[/]")
    views.day_plan(plan, day, app.today)
    console.print()
    views.warnings(plan, app.today)
    views.summary(plan, 7, app.corrections)
    app.bar("plan")


def cmd_gantt(app: App, args):
    days = _days_arg(args, 7)
    plan, notes = app.build_plan(days)
    if app.json:
        return cmd_plan(app, args)
    for n in notes:
        console.print(f" [{WARN}]{escape(n)}[/]")
    day_start, day_end = app.schedule_times()
    views.gantt(plan, days, app.today, app.cfg["priority"]["hours_per_day"], day_start, day_end)
    console.print()
    views.warnings(plan, app.today)
    views.summary(plan, days, app.corrections)
    app.bar("plan")


def cmd_review(app: App, args):
    since = app.today - timedelta(days=7)
    last = app.store.get_meta("last_review")
    ago = f"last one {(app.today - datetime.fromisoformat(last).date()).days} days ago" if last else "first one"
    console.print(f" [bold]Weekly review[/] [{DIM}]· {ago} · q stops at any question[/]")
    app.nested = True
    try:
        _review(app, since)
    finally:
        app.nested = False
    app.bar("next")


def _review(app: App, since):

    def step(n, title):
        console.print(f"\n [bold {ACCENT}]{n}[/] [bold]{title}[/]")

    step(1, "Last 7 days")
    done = app.store.done_since(since)
    console.print(f"   {len(done)} done [{DIM}]·[/] {fmt.minutes(app.store.focused_since(since))} focused")
    spent = app.store.goal_minutes(since)
    for g in app.store.goals():
        if g.weekly_min:
            m = spent.get(g.name, 0)
            mark = f"[{ACCENT}]✓[/]" if m >= g.weekly_min else f"[{DIM}]·[/]"
            console.print(f"   {mark} {escape(g.name)} [{DIM}]{fmt.minutes(m)} of {fmt.minutes(g.weekly_min)}[/]")

    step(2, "How your plans usually go")
    if app.on("learning"):
        _corrections(app, indent="   ")
    else:
        console.print(f"   [{DIM}]The learning feature is off.[/]")

    def offer(n, title, count, fn, what):
        step(n, title)
        if not count:
            console.print(f"   [{DIM}]Nothing to do.[/]")
            return True
        k = ui.choose(f"  {count} {what}. Do it now?", {"y": "yes", "n": "skip", "q": "stop"})
        if k == "y":
            fn(app, [])
        return k != "q"

    inbox = sum(1 for t in app.store.tasks() if not t.triaged)
    if not offer(3, "Inbox", inbox, cmd_triage, f"task{'s' * (inbox != 1)} to triage"):
        return
    slipped = len(app.slipped())
    if not offer(4, "Slipped tasks", slipped, cmd_resolve, f"task{'s' * (slipped != 1)} to resolve"):
        return

    step(5, "Waiting")
    waiting = [t for t in app.store.tasks() if t.stage == "waiting" and not t.start_after and app.on("states")]
    if not waiting:
        console.print(f"   [{DIM}]No task is waiting without a date.[/]")
    for t in waiting:
        console.print(f"   {_t(t)} [{DIM}]waiting, no date[/]")
        k = ui.choose("  ", {"enter": "still waiting", "b": "back to the queue", "d": "done", "k": "drop", "q": "stop"})
        if k == "q":
            return
        if k == "b":
            _set_stage(app, t, "todo")
        elif k == "d":
            _complete(app, t)
        elif k == "k":
            _drop(app, t)

    step(6, "Old tasks")
    logged = app.store.logged_by_task()
    cutoff = (app.today - timedelta(days=30)).isoformat()
    old = [t for t in app.store.tasks() if t.created[:10] < cutoff and not t.due and not t.aim and t.stage == "todo"
           and not logged.get(t.id) and t.id not in app.store.blocked_ids()]
    if not old:
        console.print(f"   [{DIM}]Nothing older than 30 days without a date.[/]")
    for t in old:
        console.print(f"   {_t(t)} [{DIM}]added {t.created[:10]}[/]")
        k = ui.choose("  ", {"enter": "keep", "a": "set a date", "k": "drop", "q": "stop"})
        if k == "q":
            return
        if k == "k":
            _drop(app, t)
        elif k == "a":
            while True:
                try:
                    when = parse.parse_date(ui.ask("   soft target › "), app.today)
                    break
                except parse.ParseError as e:
                    console.print(f"   [{WARN}]{e}[/]")
            with app.store.event("review", f"aim #{t.id} {t.title}"):
                t.aim = when
                app.store.update(t)

    step(7, "Goals")
    open_by_goal: dict[str, int] = {}
    for t in app.store.tasks():
        if t.goal:
            open_by_goal[t.goal] = open_by_goal.get(t.goal, 0) + 1
    empty = [g for g in app.store.goals() if g.weekly_min and not open_by_goal.get(g.name)]
    if not empty:
        console.print(f"   [{DIM}]Every goal with a target has at least one open task.[/]")
    for g in empty:
        console.print(f"   {escape(g.name)} [{DIM}]has no open tasks, so rule 2 can't move it forward.[/]")
        title = ui.ask(f"   next small step for {g.name} (enter to skip) › ")
        if title:
            t = Task(id=None, title=title, goal=g.name, value=3, size="S")
            with app.store.event("add", f"add {title}"):
                app.store.insert(t)
            console.print(f"   [{ACCENT}]+[/] {_t(t)} [{DIM}]#{t.id}[/]")

    app.store.set_meta("last_review", app.today.isoformat())
    app.hook("on_review")
    console.print(f"\n [{ACCENT}]✓[/] Review done. [{DIM}]Next one in {app.cfg['review']['every_days']} days.[/]")


def _corrections(app: App, indent: str = " "):
    c = app.corrections
    rows = []
    if c.time.active:
        what = f"tasks take [bold]×{c.time.factor:.1f}[/] your estimate"
        use = "estimates are scaled" if abs(c.time.factor - 1) >= 0.05 else "no change needed"
    else:
        what, use = f"[{DIM}]not enough data[/]", "needs 5 finished tasks with focus time"
    rows.append(("Time", what, c.time.samples, use))
    for label, shift, date_word in (("Soft dates", c.soft, "soft targets"), ("Deadlines", c.hard, "deadlines")):
        if shift.median_late is None or not shift.active:
            what, use = f"[{DIM}]not enough data[/]", "needs 5 finished tasks with this kind of date"
        else:
            late = shift.median_late
            what = (f"done [bold]{fmt.days(late)}[/] after the first date (median)" if late > 0 else
                    f"done {fmt.days(-late)} before the first date" if late < 0 else "done on the first date")
            use = f"{date_word} count as {fmt.days(shift.days)} earlier" if shift.days else "no change needed"
        rows.append((label, what, shift.samples, use))
    if c.cycle.samples:
        rows.append(("Start to done", f"median {fmt.days(c.cycle.median_days)} from start to done",
                     c.cycle.samples, "data only, for plugins"))
    p = c.pushes
    if p.dated:
        what = f"{p.pushed} of {p.dated} dated tasks pushed back" + (f", {p.average:.1f}× each" if p.pushed else "")
    else:
        what = f"[{DIM}]no dated tasks yet[/]"
    rows.append(("Push-backs", what, p.dated, "data only, for plugins"))
    from rich.table import Table
    tbl = Table.grid(padding=(0, 2))
    tbl.add_column(style="bold", no_wrap=True)
    tbl.add_column()
    for label, what, n, use in rows:
        tbl.add_row(label, f"{what}\n[{DIM}]{n} tasks · {use}[/]")
    if p.top:
        most = ", ".join(f"{escape(title)} ({n}×)" for _, title, n in p.top[:3])
        tbl.add_row("", f"[{DIM}]most pushed now: {most}[/]")
    console.print(Padding(tbl, (0, 0, 0, len(indent))))


def cmd_stats(app: App, args):
    if app.json:
        return app.emit(app.corrections.to_json())
    console.print(f" [bold]How your plans usually go[/] [{DIM}]· median of your last 20 finished tasks[/]")
    _corrections(app)
    app.bar("stats")


def cmd_plugins(app: App, args):
    found = hooks.list_plugins()
    hook_files = [(e, p) for e in hooks.EVENTS for p in hooks.scripts(e)]
    if app.json:
        return app.emit({"plugins": [{"name": n, "path": p} for n, p in found],
                         "hooks": [{"event": e, "path": str(p)} for e, p in hook_files]})
    console.print(" [bold]Plugins[/] [{DIM}]· programs named t-<name> on your PATH[/]".replace("{DIM}", DIM))
    for name, path in found:
        console.print(f"   t {escape(name):<14}[{DIM}]{escape(path)}[/]")
    if not found:
        console.print(f"   [{DIM}]none[/]")
    console.print(f"\n [bold]Hooks[/] [{DIM}]· {escape(str(hooks.hooks_dir()))}[/]")
    for event, path in hook_files:
        console.print(f"   {event:<16}[{DIM}]{escape(str(path))}[/]")
    if not hook_files:
        console.print(f"   [{DIM}]none · events: {', '.join(hooks.EVENTS)}[/]")


def cmd_features(app: App, args):
    if len(args) >= 2 and args[0] in ("on", "off"):
        for name in args[1:]:
            if name not in features.FEATURES:
                raise UsageError(f"no feature '{name}'. Features: {', '.join(features.FEATURES)}")
            features.set_enabled(name, args[0] == "on")
        app.cfg = config.load()
        app.say(f" [{ACCENT}]✓[/] {' '.join(args[1:])} turned {args[0]}")
    elif args:
        raise UsageError("usage: t features [on|off <name>...]")
    if app.json:
        return app.emit({n: {"on": app.on(n), "since": v, "what": w, "commands": c}
                         for n, (v, w, c) in features.FEATURES.items()})
    console.print(f" [bold]Features[/] [{DIM}]· the core is always on · t features off <name> removes a part[/]")
    from rich.table import Table
    tbl = Table.grid(padding=(0, 2))
    for name, (since, what, cmds) in features.FEATURES.items():
        on = app.on(name)
        state = f"[{ACCENT}]on[/]" if on else f"[{DIM}]off[/]"
        tbl.add_row(f"  {state}", f"[bold]{name}[/]" if on else f"[{DIM}]{name}[/]", f"[{DIM}]{since}[/]",
                    what if on else f"[{DIM}]{what}[/]", f"[{DIM}]{', '.join('t ' + c for c in cmds)}[/]")
    console.print(tbl)
    app.bar("stats")


# ── reminders ───────────────────────────────────────────────────────────
def cmd_notify(app: App, args):
    every = app.cfg["reminders"]["every_minutes"]
    if "--install" in args:
        try:
            for line in reminders.install(every):
                app.say(f" [{ACCENT}]✓[/] {escape(line)}")
        except (RuntimeError, OSError, subprocess.CalledProcessError) as e:
            raise UsageError(str(e)) from None
        app.say(f" [{DIM}]Tend now checks every {every} minutes. t notify --test sends a test reminder.[/]")
        return
    if "--uninstall" in args:
        lines = reminders.uninstall()
        for line in lines or ["no timer was installed"]:
            app.say(f" [{DIM}]{escape(line)}[/]")
        return
    if "--test" in args:
        ok = reminders.send("Tend", "Reminders work.")
        return app.say(f" [{ACCENT}]✓[/] sent a test reminder" if ok else
                       f" [{WARN}]This system has no notify-send or osascript. Hooks still get reminders.[/]")
    now = datetime.now()
    todo = reminders.pending(app, now)
    quiet = app.cfg["reminders"]["quiet_outside_day"] and not reminders.in_working_day(app, now)
    dry = "--dry-run" in args
    if app.json:
        return app.emit({"quiet": quiet, "reminders": [r.to_json() for r in todo]})
    if quiet and not dry:
        return app.say(f" [{DIM}]Outside the working day: {len(todo)} reminder(s) wait for later.[/]")
    for r in todo:
        if not dry:
            reminders.send(r.title, r.body)
            app.hook("on_remind", app.store.task(r.task_id) if r.task_id else None,
                     title=r.title, body=r.body, key=r.key)
        app.say(f" [{ACCENT}]●[/] [bold]{escape(r.title)}[/] [{DIM}]{escape(r.body)}[/]")
    if not dry:
        reminders.mark_sent(app, todo, now)
    if not todo:
        app.say(f" [{DIM}]Nothing new to remind you of.[/]")


# ── your data ───────────────────────────────────────────────────────────
def cmd_backup(app: App, args):
    path = backup.make(app.store.db, app.cfg, "manual")
    if app.json:
        return app.emit({"path": str(path)})
    app.say(f" [{ACCENT}]✓[/] saved a copy [{DIM}]{escape(str(path))}[/]")
    app.say(f" [{DIM}]t restore lists every copy.[/]")


def _confirm(app: App, question: str, args) -> bool:
    if "--yes" in args or "-y" in args:
        return True
    if not keys.interactive():
        raise UsageError(f"{question} Add --yes to confirm.")
    return ui.choose(question, {"y": "yes", "n": "no"}) == "y"


def cmd_restore(app: App, args):
    found = backup.copies(app.cfg)
    picks = [a for a in args if a.isdigit()]
    if not picks:
        if app.json:
            return app.emit([{"n": i, "path": str(c.path), "kind": c.kind, "made": c.made,
                              "open_tasks": c.open_tasks()} for i, c in enumerate(found, 1)])
        if not found:
            return app.say(f" [{DIM}]No copies yet. One is made every day you use Tend, or now with[/] t backup")
        console.print(f" [bold]Copies of your data[/] [{DIM}]· newest first · {escape(str(backup.folder(app.cfg)))}[/]")
        for i, c in enumerate(found, 1):
            n = c.open_tasks()
            tasks = f"{n} open tasks" if n is not None else "can't be read"
            console.print(f"  [bold {ACCENT}]{i:>2}[/]  {c.made:%a %b %d %H:%M}  [{DIM}]{c.kind:<7} {tasks} · {c.size_kb} KB[/]")
        console.print(f"\n [{DIM}]t restore <number> goes back to a copy. Your current data is saved first.[/]")
        return
    n = int(picks[0])
    if not 1 <= n <= len(found):
        raise UsageError(f"no copy {n}. t restore lists them.")
    chosen = found[n - 1]
    if not _confirm(app, f"Replace your current data with the copy from {chosen.made:%a %b %d %H:%M}?", args):
        return app.say(f" [{DIM}]Nothing changed.[/]")
    try:
        before = backup.restore(app.store.db, app.cfg, chosen.path)
    except ValueError as e:
        raise UsageError(str(e)) from None
    app.store.mark("restore", f"restored the copy from {chosen.made:%Y-%m-%d %H:%M}")
    if app.json:
        return app.emit({"restored": str(chosen.path), "saved_first": str(before)})
    app.say(f" [{ACCENT}]✓[/] restored the copy from {chosen.made:%a %b %d %H:%M}")
    app.say(f" [{DIM}]Your data from before is saved too. To go back: t restore 1[/]")
    app.bar("next")


def cmd_export(app: App, args):
    files = [a for a in args if not a.startswith("-")]
    if not files or files[0] == "-":
        transfer.export(app.store, sys.stdout)  # data only: nothing else on stdout
        return
    path = Path(files[0]).expanduser()
    with path.open("w", encoding="utf-8") as f:
        counts = transfer.export(app.store, f)
    if app.json:
        return app.emit({"path": str(path), **counts})
    app.say(f" [{ACCENT}]✓[/] exported {fmt.count(counts['tasks'], 'task')}, {fmt.count(counts['goals'], 'goal')}, "
            f"{fmt.count(counts['sessions'], 'focus session')} and {fmt.count(counts['events'], 'change')} "
            f"[{DIM}]→ {escape(str(path))}[/]")


def cmd_import(app: App, args):
    files = [a for a in args if not a.startswith("-") or a == "-"]
    if not files:
        raise UsageError("usage: t import <file> [--replace]   (- reads from stdin)")
    try:
        if files[0] == "-":
            header, data = transfer.read(sys.stdin)
        else:
            with Path(files[0]).expanduser().open(encoding="utf-8") as f:
                header, data = transfer.read(f)
    except OSError as e:
        raise UsageError(f"can't read {files[0]}: {e.strerror}") from None
    except transfer.TransferError as e:
        raise UsageError(str(e)) from None
    has_tasks = any(app.store.db.execute(f"SELECT 1 FROM {t} LIMIT 1").fetchone() for t in ("tasks", "goals", "sessions"))
    replace = "--replace" in args or not has_tasks  # an empty database becomes an exact copy
    if replace and has_tasks and not _confirm(app, "Replace ALL your current data with this file?", args):
        return app.say(f" [{DIM}]Nothing changed.[/]")
    saved = backup.make(app.store.db, app.cfg, "before") if has_tasks else None
    if replace:
        counts = transfer.replace_all(app.store, header, data)
        msg = (f"loaded {fmt.count(counts['tasks'], 'task')}, {fmt.count(counts['goals'], 'goal')} "
               f"and {fmt.count(counts['sessions'], 'focus session')}")
    else:
        counts = transfer.add(app.store, data)
        msg = (f"added {fmt.count(counts['tasks'], 'task')}, {fmt.count(counts['goals'], 'goal')} "
               f"and {fmt.count(counts['sessions'], 'focus session')}")
        if counts["skipped"]:
            msg += f" · {counts['skipped']} already here, skipped"
    app.store.mark("import", f"import from {files[0]}")
    if app.json:
        return app.emit({"mode": "replace" if replace else "add", **counts, "saved_first": str(saved) if saved else None})
    app.say(f" [{ACCENT}]✓[/] {msg}")
    if saved:
        app.say(f" [{DIM}]Your data from before is saved. To go back: t restore 1[/]")
    app.bar("next")


def cmd_help(app: App, args):
    ui.help_screen(config.config_path(), config.data_path(),
                   lambda name: features.command_enabled(app.cfg, name), app.on("plugins") or app.on("hooks"))


COMMANDS = {
    "next": cmd_next, "focus": cmd_focus, "done": cmd_done, "skip": cmd_skip, "split": cmd_split,
    "add": cmd_add, "triage": cmd_triage, "ls": cmd_ls, "edit": cmd_edit, "drop": cmd_drop,
    "start": cmd_start, "wait": cmd_wait, "status": cmd_status,
    "resolve": cmd_resolve, "plan": cmd_plan, "gantt": cmd_gantt, "review": cmd_review,
    "goals": cmd_goals, "wins": cmd_wins, "stats": cmd_stats, "plugins": cmd_plugins, "features": cmd_features,
    "backup": cmd_backup, "restore": cmd_restore, "export": cmd_export, "import": cmd_import,
    "notify": cmd_notify,
    "undo": cmd_undo, "help": cmd_help,
}
ALIASES = {k: name for k, name, _ in ui.COMMANDS if k} | {"list": "ls", "goal": "goals", "log": "wins"}


def lookup(word: str, app: App | None = None):
    """The command for a name or key. Commands of a feature that is off explain how to turn it on."""
    name = ALIASES.get(word, word)
    fn = COMMANDS.get(name)
    if fn and app and not features.command_enabled(app.cfg, name):
        feature = features.OWNER[name]

        def off(app, args):
            raise UsageError(f"t {name} is part of '{feature}', which is turned off. Turn it on: t features on {feature}")
        return off
    return fn
