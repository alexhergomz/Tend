"""Capturing: adding tasks, sorting the inbox, changing details."""

from rich.markup import escape

from .. import fmt, parse, repeat, ui
from ..app import App, UsageError
from ..model import Task
from ..registry import command
from ..ui import ACCENT, DIM, WARN, console
from . import actions
from ._shared import fresh, goal_hint, ids_in, title


@command("add", key="a", group="Capturing", help="capture a task (or just: t <text>)", usage="<text> [details]",
         details="Anything that isn't a command is added as a task. Details: see `t help` under 'Adding details'.")
def cmd_add(app: App, args):
    if not args:
        text = ui.ask(" add › ")
        if not text:
            return
        args = [text]
    name, f = parse.parse_tokens(args, app.today)
    if not name:
        raise UsageError("a task needs a title")
    t = Task(id=None, title=name, **f)
    actions.dates_for_repeat(app, t)
    with app.store.event("add") as ev:
        app.store.insert(t)
        ev["summary"] = f"add #{t.id} {t.title}"
    app.store.set_meta("welcomed", "1")
    app.hook("on_add", t)
    if app.json:
        return app.emit(t.to_json())
    where = "" if t.triaged else f" [{DIM}]→ inbox[/]"
    app.say(f" [{ACCENT}]+[/] {title(t)} [{DIM}]#{t.id}[/]{where}")
    if t.repeat and app.on("repeat"):
        app.say(f"   [{DIM}]↻ {repeat.parse(t.repeat).describe()} · first one {fmt.day(t.due or t.aim, app.today)}[/]")
    goal_hint(app, t.goal)
    app.bar("added")


@command("triage", key="t", group="Capturing", help="sort the inbox, 3 quick questions each", screen=True,
         details="For each new task: how much it matters, how big it is, and a date if it has one.")
def cmd_triage(app: App, args):
    inbox = [t for t in app.store.tasks() if not t.triaged]
    if not inbox:
        app.say(f" [{DIM}]Inbox is empty.[/]")
        return app.bar("next")
    goals = [g.name for g in app.store.goals()]
    for i, t in enumerate(inbox, 1):
        if not (t := fresh(app, t)):
            continue
        console.print(f"\n [{DIM}]{i}/{len(inbox)}[/]  {title(t)}")
        v = ui.choose("matters?", {"1": "nice to have", "2": "matters", "3": "really", "k": "drop",
                                   "enter": "later", "q": "stop"})
        if v == "q":
            break
        if v == "enter":
            continue
        if v == "k":
            actions.drop(app, t)
            continue
        s = ui.choose("size?   ", {"s": "<1h", "m": "1-3h", "l": ">3h"})
        due = aim = None
        text = ui.ask(" date?    fri · oct20 · +3d  (prefix ~ for a soft target, enter for none) › ")
        while text:
            try:
                d = parse.parse_date(text.lstrip("~"), app.today)
                due, aim = (None, d) if text.startswith("~") else (d, None)
                break
            except parse.ParseError as e:
                text = ui.ask(f" [{WARN}]{escape(str(e))}[/] › ")
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


@command("edit", key="e", group="Capturing", help="change a task", usage="[id] <details or new title>",
         takes_id=True, details="Example: t e 12 due:fri v:3. A word that isn't a detail becomes the new title.")
def cmd_edit(app: App, args):
    ids = ids_in(args[:1])
    tokens = args[len(ids):]
    t = app.target(ids)
    if not t:
        return app.say(f" [{DIM}]Nothing to edit.[/]")
    if not tokens:
        console.print(f" Editing {title(t)} [{DIM}]· details like due:fri v:3 +goal, or a new title[/]")
        text = ui.ask(f"   #{t.id} › ")
        if not text:
            return
        tokens = [text]
    name, f = parse.parse_tokens(tokens, app.today)
    with app.store.event("edit", f"edit #{t.id} {t.title}"):
        if name:
            t.title = name
        for k, v in f.items():
            setattr(t, k, v)
        actions.dates_for_repeat(app, t)
        if "aim" in f or "due" in f:
            t.slips = 0
        app.store.update(t)
    if app.json:
        return app.emit(t.to_json())
    app.say(f" [{ACCENT}]✎[/] {title(t)}")
    goal_hint(app, f.get("goal"))
    app.bar("list")
