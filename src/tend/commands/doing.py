"""Doing: the one next task, and what you do with it."""

from datetime import datetime

from rich.markup import escape

from .. import fmt, keys, parse, ui
from ..app import App, UsageError
from ..model import STATES
from ..registry import command
from ..store import UndoBlocked
from ..ui import ACCENT, DIM, console
from . import actions
from ._shared import energy_flag, ids_in, title

WELCOME = [
    ("t call the dentist", "capture anything. No fields needed, details can come later."),
    ("t next", "Tend picks the one thing to do now, and says why."),
    ("t focus", "start a timer on it. Or press d when it's done."),
]


def welcome():
    console.print(f" [bold]Welcome to Tend.[/] [{DIM}]Three steps to start:[/]\n")
    for i, (cmd, what) in enumerate(WELCOME, 1):
        console.print(f"   [{ACCENT}]{i}[/]  [bold]{cmd:<22}[/][{DIM}]{what}[/]")
    console.print(f"\n [{DIM}]t help lists every command. Tend has more (plans, goals, reminders), "
                  f"but none of it is needed to start.[/]")


@command("next", key="n", group="Doing", help="the one thing to do now", usage="[--low | --high]",
         details="--low or --high says how much energy you have right now (see energy windows).",
         flags=("--low", "--high"))
def cmd_next(app: App, args):
    energy_flag(app, args)
    ranked = app.ranked()
    if app.json:
        return app.emit(ranked[0].to_json() if ranked else None)
    if app.tui:
        return
    if not ranked:
        if app.first_run():
            welcome()
            return
        app.say(f" [{DIM}]Nothing to do. Capture something with[/] t <text>")
        return app.bar("empty")
    app.store.set_meta("current", ranked[0].task.id)
    console.print(ui.card(ranked[0], app.today))
    app.bar("next")


@command("focus", key="f", group="Doing", help="a focus timer on it", usage="[id] [--pomo | --flow | --box 45]",
         takes_id=True, flags=("--pomo", "--flow", "--box"),
         details="""pomo: 25 minutes of work, then a 5 minute break.
flow: counts up with no forced stop; press b for a break sized to the time you worked.
box: a hard stop after the given minutes.
Keys while it runs: p pause, d done, q stop.""")
def cmd_focus(app: App, args):
    mode, box_min, rest = app.cfg["focus"]["default_mode"], None, []
    it = iter(args)
    for a in it:
        word = a.lstrip("-")
        if word in ("pomo", "flow", "box"):
            mode = word
            if word == "box" and (nxt := next(it, None)):
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
    from .. import focus as timer  # the timer is only loaded when it runs

    if app.on("states") and t.stage != "started":
        actions.set_stage(app, t, "started", quiet=True)
    start = datetime.now()
    app.hook("on_focus_start", t, mode=mode)
    result = timer.run(t.title, ui.meta(t, app.today), mode, app.cfg, box_min)
    if result.minutes >= 0.5:
        app.store.add_session(t.id, start, datetime.now(), mode, round(result.minutes, 1))
    app.hook("on_focus_end", t, mode=mode, minutes=round(result.minutes, 1), outcome=result.outcome)
    app.say(f" [{ACCENT}]●[/] focused {fmt.minutes(result.minutes)} on {title(t)}")
    if result.outcome == "done":
        actions.complete(app, app.store.task(t.id))
        app.bar("done")
    else:
        app.bar("next")


@command("start", key="b", group="Doing", help="mark it started (focus does this too)", usage="[id]",
         feature="states", takes_id=True)
def cmd_start(app: App, args):
    t = app.target(args)
    if not t:
        return app.say(f" [{DIM}]Nothing to start.[/]")
    if t.stage == "started":
        app.say(f" [{DIM}]Already started:[/] {escape(t.title)}")
    else:
        actions.set_stage(app, t, "started")
    if app.json:
        return app.emit(app.store.task(t.id).to_json())
    app.bar("next")


@command("done", key="d", group="Doing", help="mark it done", usage="[id]", takes_id=True)
def cmd_done(app: App, args):
    t = app.target(args)
    if not t:
        return app.say(f" [{DIM}]Nothing open.[/]")
    actions.complete(app, t)
    if app.json:
        return app.emit(app.store.task(t.id).to_json())
    app.bar("done")


@command("skip", key="s", group="Doing", help="skip it for today, no questions asked", usage="[id]", takes_id=True)
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


@command("split", key="x", group="Doing", help="break it into smaller steps", usage='[id] ["step" ...]',
         takes_id=True, details="Without steps, Tend asks for them one by one. Make the first one tiny.")
def cmd_split(app: App, args):
    ids = ids_in(args)
    steps = [a for a in args if a not in ids]
    t = app.target(ids)
    if not t:
        return app.say(f" [{DIM}]Nothing to split.[/]")
    if not steps:
        console.print(f" Split {title(t)} into steps. [{DIM}]Make the first one tiny. Empty line to finish.[/]")
        steps = actions.ask_steps()
    if steps:
        actions.split(app, t, steps)
        app.bar("next")


@command("wait", key="h", group="Doing", help="on hold, waiting for someone", usage="[id] [date]",
         feature="states", takes_id=True,
         details="The task leaves the queue. With a date, it comes back that day by itself.")
def cmd_wait(app: App, args):
    ids = ids_in(args[:1])
    rest = args[len(ids):]
    t = app.target(ids)
    if not t:
        return app.say(f" [{DIM}]Nothing to put on hold.[/]")
    text = " ".join(rest)
    if not rest and app.tui:
        text = ui.ask(f" {escape(t.title)} is waiting until? (a date, or enter for no date) › ")
    until = parse.parse_date(text, app.today) if text else None
    actions.set_stage(app, t, "waiting", until)
    if app.json:
        return app.emit(app.store.task(t.id).to_json())
    app.bar("next")


@command("drop", key="k", group="Doing", help="let a task go", usage="[id] [--once | --stop]", takes_id=True,
         flags=("--once", "--stop"),
         details="For a repeating task, --once skips just this one and --stop ends the series.")
def cmd_drop(app: App, args):
    t = app.target([a for a in args if not a.startswith("--")])
    if not t:
        return app.say(f" [{DIM}]Nothing to drop.[/]")
    actions.drop(app, t, once=actions.ask_once(app, t, args))
    app.bar("next")


@command("status", group="Doing", help="set any state", usage="[id] todo|started|waiting|done|dropped",
         feature="states", takes_id=True, flags=STATES)
def cmd_status(app: App, args):
    states = [a for a in args if a in STATES]
    if not states:
        raise UsageError("usage: t status [id] todo|started|waiting|done|dropped")
    t = app.target(ids_in(args))
    if not t:
        return app.say(f" [{DIM}]No open task.[/]")
    state = states[0]
    if state == "done":
        actions.complete(app, t)
    elif state == "dropped":
        actions.drop(app, t)
    elif state == t.stage:
        app.say(f" [{DIM}]Already {state}:[/] {escape(t.title)}")
    else:
        actions.set_stage(app, t, state)
    if app.json:
        return app.emit(app.store.task(t.id).to_json())
    app.bar("next")


@command("undo", key="u", group="Doing", help="undo the last change")
def cmd_undo(app: App, args):
    try:
        summary = app.store.undo()
    except UndoBlocked:
        raise UsageError("The last change was an import or a restore, which undo can't reverse. "
                         "To go back: t restore (copy 1 is from just before it)") from None
    app.say(f" [{ACCENT}]↶[/] undid: {escape(summary)}" if summary else f" [{DIM}]Nothing to undo.[/]")
    app.bar("next")
