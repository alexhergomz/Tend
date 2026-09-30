from datetime import datetime

from rich.markup import escape

from . import config, fmt, keys, parse, slips, ui
from . import focus as focus_timer
from .app import App, UsageError
from .model import Task
from .store import now_iso
from .ui import ACCENT, DIM, WARN, console


def _t(t: Task) -> str:
    return f"[bold]{escape(t.title)}[/]"


def _add_goal_hint(app: App, goal: str | None):
    if goal and app.store.ensure_goal(goal):
        app.say(f"   [{DIM}]new goal '{escape(goal)}' · give it a weekly target: t g add {escape(goal)} 3h[/]")


# ── doing ───────────────────────────────────────────────────────────────
def cmd_next(app: App, args):
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
    start = datetime.now()
    result = focus_timer.run(t.title, ui.meta(t, app.today), mode, app.cfg, box_min)
    if result.minutes >= 0.5:
        app.store.add_session(t.id, start, datetime.now(), mode, round(result.minutes, 1))
    app.say(f" [{ACCENT}]●[/] focused {fmt.minutes(result.minutes)} on {_t(t)}")
    if result.outcome == "done":
        _complete(app, t)
        app.bar("done")
    else:
        app.bar("next")


def _complete(app: App, t: Task):
    with app.store.event("done", f"done #{t.id} {t.title}"):
        t.status, t.done_at = "done", now_iso()
        app.store.update(t)
        parent = app.store.task(t.parent) if t.parent else None
        while parent and parent.status == "open" and not app.store.children(parent.id):
            parent.status, parent.done_at = "done", now_iso()
            app.store.update(parent)
            app.say(f" [{ACCENT}]✓[/] all steps done · {_t(parent)}")
            parent = app.store.task(parent.parent) if parent.parent else None
    app.store.set_meta("current", None)
    n = len(app.store.done_since(app.today))
    app.say(f" [{ACCENT}]✓[/] {_t(t)}  [{DIM}]{n} done today[/]")


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
    with app.store.event("add") as ev:
        app.store.insert(t)
        ev["summary"] = f"add #{t.id} {t.title}"
    if app.json:
        return app.emit(t.to_json())
    where = "" if t.triaged else f" [{DIM}]→ inbox[/]"
    app.say(f" [{ACCENT}]+[/] {_t(t)} [{DIM}]#{t.id}[/]{where}")
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
        if "aim" in f or "due" in f:
            t.slips = 0
        app.store.update(t)
    if app.json:
        return app.emit(t.to_json())
    app.say(f" [{ACCENT}]✎[/] {_t(t)}")
    _add_goal_hint(app, f.get("goal"))
    app.bar("list")


def _drop(app: App, t: Task):
    with app.store.event("drop", f"drop #{t.id} {t.title}"):
        stack = [t]
        while stack:
            cur = stack.pop()
            cur.status, cur.done_at = "dropped", now_iso()
            app.store.update(cur)
            stack.extend(app.store.children(cur.id))
    app.store.set_meta("current", None)
    app.say(f" [{DIM}]let go:[/] {escape(t.title)} [{DIM}]· u to undo[/]")


def cmd_drop(app: App, args):
    t = app.target(args)
    if not t:
        return app.say(f" [{DIM}]Nothing to drop.[/]")
    _drop(app, t)
    app.bar("next")


def cmd_undo(app: App, args):
    summary = app.store.undo()
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
    console.print(f" [{DIM}]Slipped tasks need one decision each. Dropping is a valid choice.[/]")
    for t in todo:
        hard = bool(t.due and t.due < app.today)
        console.print(f"\n {_t(t)}  [{WARN}]{slips.why(t, app.today)}[/]")
        k = ui.choose("", {"n": "do it today", "r": "reschedule", "x": "split", "k": "drop", "q": "later"})
        if k == "q":
            break
        if k == "k":
            _drop(app, t)
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
    ranked = app.ranked()
    if app.json:
        return app.emit([r.to_json() for r in ranked])
    if not ranked:
        app.say(f" [{DIM}]Nothing open.[/]")
        return app.bar("empty")
    ui.queue(ranked, app.today)
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


def cmd_help(app: App, args):
    ui.help_screen(config.config_path(), config.data_path())


COMMANDS = {
    "next": cmd_next, "focus": cmd_focus, "done": cmd_done, "skip": cmd_skip, "split": cmd_split,
    "add": cmd_add, "triage": cmd_triage, "ls": cmd_ls, "edit": cmd_edit, "drop": cmd_drop,
    "resolve": cmd_resolve, "goals": cmd_goals, "wins": cmd_wins, "undo": cmd_undo, "help": cmd_help,
}
ALIASES = {k: name for k, name, _ in ui.COMMANDS} | {"list": "ls", "goal": "goals", "log": "wins"}


def lookup(word: str):
    return COMMANDS.get(ALIASES.get(word, word))
