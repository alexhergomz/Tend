"""Deciding: slipped tasks, and the weekly review."""

from datetime import date, timedelta

from rich.markup import escape

from .. import fmt, parse, slips, ui
from ..app import App
from ..model import Task
from ..registry import command
from ..ui import ACCENT, ACCENT_B, DIM, WARN, console
from . import actions
from ._shared import title
from .capture import cmd_triage
from .looking import corrections_table

CHOICES = (
    ("n", "do it today", "the date moves to today"),
    ("r", "reschedule", "you type a new date"),
    ("x", "split", "break it into smaller steps"),
    ("k", "drop", "remove it (u brings it back)"),
    ("q", "later", "stop here, the rest stay in the slipped count"),
)


def ask_date(prompt: str, today):
    while True:
        try:
            return parse.parse_date(ui.ask(prompt), today)
        except parse.ParseError as e:
            console.print(f"   [{WARN}]{escape(str(e))}[/]")


@command("resolve", key="r", group="Deciding", help="decide what to do with slipped tasks", screen=True,
         details="A task slips when its date passes. Each one needs one decision: today, a new date, split or drop.")
def cmd_resolve(app: App, args):
    todo = app.slipped()
    if not todo:
        app.say(f" [{DIM}]Nothing has slipped.[/]")
        return app.bar("next")
    console.print(f" [bold]{fmt.count(len(todo), 'task')} missed {'their' if len(todo) > 1 else 'its'} date.[/] "
                  f"[{DIM}]Pick one option for each:[/]")
    for key, name, what in CHOICES:
        console.print(f"   [{ACCENT_B}]{key}[/]  {name:<12}[{DIM}]{what}[/]")
    for t in todo:
        hard = bool(t.due and t.due < app.today)
        console.print(f"\n {title(t)}  [{WARN}]{slips.why(t, app.today)}[/]")
        repeating = bool(t.repeat and app.on("repeat"))
        k = ui.choose("", {"n": "today", "r": "reschedule", "x": "split",
                           "k": "skip this one" if repeating else "drop", "q": "later"})
        if k == "q":
            break
        if k == "k":
            actions.drop(app, t, once=repeating)
        elif k == "x":
            steps = actions.ask_steps()
            if steps:
                if hard:
                    with app.store.event("resolve", f"reset deadline #{t.id} {t.title}"):
                        t.due = app.today
                        app.store.update(t)
                actions.split(app, t, steps)
        else:
            when = ask_date("   new date (required) › ", app.today) if k == "r" else app.today
            with app.store.event("resolve", f"reschedule #{t.id} {t.title}"):
                if hard:
                    t.due = when
                else:
                    t.aim = when
                t.slips = 0
                app.store.update(t)
            app.say(f" [{ACCENT}]→[/] {title(t)} [{DIM}]{'due' if hard else 'aim'} {fmt.day(when, app.today)}[/]")
    app.bar("next")


@command("review", key="v", group="Deciding", help="weekly review, about 5 minutes", feature="review", screen=True,
         details="Seven steps: last week, your patterns, inbox, slipped, waiting, old tasks, goals. q stops anywhere.")
def cmd_review(app: App, args):
    last = app.store.get_meta("last_review")
    ago = f"last one {(app.today - date.fromisoformat(last)).days} days ago" if last else "first one"
    console.print(f" [bold]Weekly review[/] [{DIM}]· {ago} · q stops at any question[/]")
    app.nested = True
    try:
        if _review(app, app.today - timedelta(days=7)):
            app.store.set_meta("last_review", app.today.isoformat())
            app.hook("on_review")
            console.print(f"\n [{ACCENT}]✓[/] Review done. "
                          f"[{DIM}]Next one in {app.cfg['review']['every_days']} days.[/]")
    finally:
        app.nested = False
    app.bar("next")


def _step(n: int, name: str):
    console.print(f"\n [{ACCENT_B}]{n}[/] [bold]{name}[/]")


def _offer(app: App, n: int, name: str, count: int, fn, what: str) -> bool:
    _step(n, name)
    if not count:
        console.print(f"   [{DIM}]Nothing to do.[/]")
        return True
    k = ui.choose(f"  {count} {what}. Do it now?", {"y": "yes", "n": "skip", "q": "stop"})
    if k == "y":
        fn(app, [])
    return k != "q"


def _review(app: App, since) -> bool:
    """The seven steps. Returns False if stopped early."""
    _step(1, "Last 7 days")
    console.print(f"   {len(app.store.done_since(since))} done [{DIM}]·[/] "
                  f"{fmt.minutes(app.store.focused_since(since))} focused")
    spent = app.store.goal_minutes(since)
    for g in app.store.goals():
        if g.weekly_min:
            m = spent.get(g.name, 0)
            mark = f"[{ACCENT}]✓[/]" if m >= g.weekly_min else f"[{DIM}]·[/]"
            console.print(f"   {mark} {escape(g.name)} [{DIM}]{fmt.minutes(m)} of {fmt.minutes(g.weekly_min)}[/]")

    _step(2, "How your plans usually go")
    if app.on("learning"):
        corrections_table(app, indent=3)
    else:
        console.print(f"   [{DIM}]The learning feature is off.[/]")

    inbox = sum(1 for t in app.store.tasks() if not t.triaged)
    if not _offer(app, 3, "Inbox", inbox, cmd_triage, f"{'task' if inbox == 1 else 'tasks'} to triage"):
        return False
    slipped = len(app.slipped())
    if not _offer(app, 4, "Slipped tasks", slipped, cmd_resolve, f"{'task' if slipped == 1 else 'tasks'} to resolve"):
        return False

    _step(5, "Waiting")
    waiting = [t for t in app.store.tasks() if t.stage == "waiting" and not t.start_after] if app.on("states") else []
    if not waiting:
        console.print(f"   [{DIM}]No task is waiting without a date.[/]")
    for t in waiting:
        console.print(f"   {title(t)} [{DIM}]waiting, no date[/]")
        k = ui.choose("  ", {"enter": "still waiting", "b": "back to the queue", "d": "done", "k": "drop", "q": "stop"})
        if k == "q":
            return False
        if k == "b":
            actions.set_stage(app, t, "todo")
        elif k == "d":
            actions.complete(app, t)
        elif k == "k":
            actions.drop(app, t)

    _step(6, "Old tasks")
    logged = app.store.logged_by_task()
    blocked = app.store.blocked_ids()
    cutoff = (app.today - timedelta(days=30)).isoformat()
    old = [t for t in app.store.tasks() if t.created[:10] < cutoff and not t.due and not t.aim
           and t.stage == "todo" and not logged.get(t.id) and t.id not in blocked]
    if not old:
        console.print(f"   [{DIM}]Nothing older than 30 days without a date.[/]")
    for t in old:
        console.print(f"   {title(t)} [{DIM}]added {t.created[:10]}[/]")
        k = ui.choose("  ", {"enter": "keep", "a": "set a date", "k": "drop", "q": "stop"})
        if k == "q":
            return False
        if k == "k":
            actions.drop(app, t)
        elif k == "a":
            when = ask_date("   soft target › ", app.today)
            with app.store.event("review", f"aim #{t.id} {t.title}"):
                t.aim = when
                app.store.update(t)

    _step(7, "Goals")
    has_tasks = {t.goal for t in app.store.tasks() if t.goal}
    empty = [g for g in app.store.goals() if g.weekly_min and g.name not in has_tasks]
    if not empty:
        console.print(f"   [{DIM}]Every goal with a target has at least one open task.[/]")
    for g in empty:
        console.print(f"   {escape(g.name)} [{DIM}]has no open tasks, so rule 2 can't move it forward.[/]")
        name = ui.ask(f"   next small step for {escape(g.name)} (enter to skip) › ")
        if name:
            t = Task(id=None, title=name, goal=g.name, value=3, size="S")
            with app.store.event("add", f"add {name}"):
                app.store.insert(t)
            console.print(f"   [{ACCENT}]+[/] {title(t)} [{DIM}]#{t.id}[/]")
    return True
