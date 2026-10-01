"""Changes to tasks that more than one command makes: finish, drop, split, change state."""

from rich.markup import escape

from .. import fmt, keys, parse, repeat, ui
from ..app import App
from ..model import Task
from ..store import now_iso
from ..ui import ACCENT, DIM, WARN
from ._shared import title


# ── repeating tasks ─────────────────────────────────────────────────────
def dates_for_repeat(app: App, t: Task):
    """A repeating task always has a date: without one, it gets the first date of its rule."""
    if t.repeat and app.on("repeat") and not t.due and not t.aim:
        t.aim = repeat.parse(t.repeat).first(app.today)


def next_copy(app: App, t: Task) -> Task | None:
    """Inside an event: create the next copy of a repeating task, with its dates moved along the rhythm."""
    if not (t.repeat and app.on("repeat")):
        return None
    planned = t.due or t.aim or app.today
    # count the rhythm from the first copy, so "every month" from the 31st comes back to the 31st after February
    first = app.store.task(t.series) if t.series else t
    anchor = (first.first_due or first.first_aim or first.due or first.aim) if first else None
    nxt = repeat.parse(t.repeat).next_after(anchor or planned, max(planned, app.today))
    shift = nxt - planned
    copy = Task(id=None, title=t.title, goal=t.goal, value=t.value, size=t.size, estimate_min=t.estimate_min,
                energy=t.energy, repeat=t.repeat, series=t.series or t.id,
                due=t.due + shift if t.due else None,
                aim=t.aim + shift if t.aim else (None if t.due else nxt))
    app.store.insert(copy)
    return copy


def say_next(app: App, copy: Task | None):
    if copy:
        app.say(f"   [{DIM}]↻ next one {fmt.day(copy.due or copy.aim, app.today)} · #{copy.id}[/]")


# ── finish and drop ─────────────────────────────────────────────────────
def complete(app: App, t: Task):
    """Mark done. A task whose steps are now all done is finished too."""
    with app.store.event("done", f"done #{t.id} {t.title}"):
        t.status, t.done_at = "done", now_iso()
        app.store.update(t)
        copy = next_copy(app, t)
        parent = app.store.task(t.parent) if t.parent else None
        while parent and parent.status == "open" and not app.store.children(parent.id):
            parent.status, parent.done_at = "done", now_iso()
            app.store.update(parent)
            app.say(f" [{ACCENT}]✓[/] all steps done · {title(parent)}")
            next_copy(app, parent)
            parent = app.store.task(parent.parent) if parent.parent else None
    app.store.set_meta("current", None)
    done = app.store.task(t.id)
    app.hook("on_done", done)
    app.hook("on_status", done, old=t.stage, new="done")
    n = len(app.store.done_since(app.today))
    app.say(f" [{ACCENT}]✓[/] {title(t)}  [{DIM}]{n} done today[/]")
    say_next(app, copy)


def drop(app: App, t: Task, once: bool = False):
    """Drop a task and its steps. With once=True, a repeating task gets its next copy (skip this one)."""
    with app.store.event("drop", f"{'skip once' if once else 'drop'} #{t.id} {t.title}"):
        stack = [t]
        while stack:
            cur = stack.pop()
            cur.status, cur.done_at = "dropped", now_iso()
            app.store.update(cur)
            stack.extend(app.store.children(cur.id))
        copy = next_copy(app, t) if once else None
    app.store.set_meta("current", None)
    app.hook("on_drop", t)
    app.hook("on_status", t, old=t.stage, new="dropped")
    if once:
        app.say(f" [{DIM}]skipped this time:[/] {escape(t.title)} [{DIM}]· u to undo[/]")
        say_next(app, copy)
    else:
        app.say(f" [{DIM}]let go:[/] {escape(t.title)} [{DIM}]· u to undo[/]")


def ask_once(app: App, t: Task, args: list[str]) -> bool:
    """For a repeating task: skip just this one (True) or stop the series (False)?"""
    if not (t.repeat and app.on("repeat")):
        return False
    if "--once" in args:
        return True
    if "--stop" in args or not keys.interactive():
        return False
    k = ui.choose(f"{escape(t.title)} repeats {repeat.parse(t.repeat).describe()}.",
                  {"o": "skip just this one", "s": "stop repeating"})
    return k == "o"


# ── split ───────────────────────────────────────────────────────────────
def split(app: App, t: Task, steps: list[str]):
    """Break a task into steps. The task waits until its steps are done."""
    with app.store.event("split", f"split #{t.id} {t.title}") as ev:
        children = []
        for step in steps:
            name, f = parse.parse_tokens([step], app.today)
            child = Task(
                id=None, title=name or step, parent=t.id, goal=f.get("goal", t.goal),
                value=f.get("value", t.value or 2), size=f.get("size", "S"),
                estimate_min=f.get("estimate_min"), due=f.get("due", t.due),
                aim=f.get("aim", t.aim if t.aim and t.aim >= app.today else None),
            )
            app.store.insert(child)
            children.append(child)
        if t.aim and t.aim < app.today:
            t.aim, t.slips = None, 0
            app.store.update(t)
        ev["summary"] += " into " + ", ".join(f"#{c.id}" for c in children)
    app.store.set_meta("current", children[0].id)
    app.say(f" [{ACCENT}]✂[/] {title(t)}")
    for c in children:
        app.say(f"   [{DIM}]└ #{c.id}[/] {escape(c.title)}")


def ask_steps() -> list[str]:
    steps = []
    while step := ui.ask(f"   step {len(steps) + 1} › "):
        steps.append(step)
    return steps


# ── states ──────────────────────────────────────────────────────────────
def set_stage(app: App, t: Task, stage: str, until=None, quiet: bool = False):
    """todo, started or waiting. Starting a step starts the task it was split from."""
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
        app.say(f" [{ACCENT}]▸[/] started {title(t)}")
        n = app.status()["started"]
        if n > app.cfg["priority"]["max_started"]:
            app.say(f" [{WARN}]{n} tasks are started.[/] "
                    f"[{DIM}]Finishing one before starting more usually goes faster.[/]")
    elif stage == "waiting":
        when = f" until {fmt.day(until, app.today)}" if until else ""
        back = f"back in the queue {fmt.day(until, app.today)}" if until else "t ls shows it"
        app.say(f" [{DIM}]⏸ waiting{when}:[/] {escape(t.title)} [{DIM}]· {back}[/]")
    elif stage == "todo" and not quiet:
        app.say(f" [{DIM}]○ back to todo:[/] {escape(t.title)}")
