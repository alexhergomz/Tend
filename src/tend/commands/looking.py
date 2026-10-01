"""Looking: the queue, plans, goals, wins and patterns."""

from datetime import datetime

from rich.markup import escape
from rich.padding import Padding
from rich.table import Table
from rich.text import Text

from .. import fmt, ui
from ..app import App
from ..registry import command
from ..ui import ACCENT, DIM, WARN, console
from ._shared import energy_flag

SHOWN = 20  # tasks in `t ls` before "… more"


@command("ls", key="l", group="Looking", help="the queue, in order, with the reason for each", screen=True,
         usage="[--all] [--low | --high]", aliases=("list",), flags=("--all", "--low", "--high"),
         details=f"Shows the first {SHOWN} tasks; --all shows every one. Waiting tasks are listed at the end.")
def cmd_ls(app: App, args):
    energy_flag(app, args)
    ranked = app.ranked()
    if app.json:
        return app.emit([r.to_json() for r in ranked])
    if not ranked:
        if app.first_run():
            from .doing import welcome
            return welcome()
        app.say(f" [{DIM}]Nothing open.[/]")
        return app.bar("empty")
    show_all = "--all" in args or "-a" in args
    ui.queue(ranked if show_all else ranked[:SHOWN], app.today)
    if not show_all and len(ranked) > SHOWN:
        console.print(f"   [{DIM}]… {len(ranked) - SHOWN} more · t ls --all shows them[/]")
    if app.on("states"):
        queued = {r.task.id for r in ranked}
        waiting = [t for t in app.store.tasks() if t.stage == "waiting" and t.id not in queued]
        if waiting:
            console.print(f"\n [bold]Waiting[/] [{DIM}]· not in the queue · t start <id> brings one back[/]")
            for t in waiting:
                console.print(Text("   ") + Text(t.title) + Text("  ") + ui.meta(t, app.today))
    app.bar("list")


def _days_arg(args, default: int) -> int:
    for i, a in enumerate(args):
        if a.lstrip("-") == "days" and i + 1 < len(args) and args[i + 1].isdigit():
            return max(1, min(int(args[i + 1]), 31))
        if a.lstrip("-") in ("week", "w"):
            return 7
    return default


def _plan_json(app: App, plan) -> dict:
    return {
        "blocks": [{"task_id": b.task.id, "title": b.task.title, "start": b.start, "end": b.end, "rule": b.rule}
                   for b in plan.blocks],
        "events": [{"title": e.title, "start": e.start, "end": e.end} for e in plan.events],
        "late": [{"task_id": x.task.id, "title": x.task.title, "due": x.due, "finish": x.finish,
                  "minutes_left": round(x.minutes_left)} for x in plan.late],
        "corrections": app.corrections.to_json(),
    }


@command("plan", key="p", group="Looking", help="today's schedule, built with the same rules", feature="planning",
         screen=True, usage="[--ics]", flags=("--ics",),
         details="Books focus blocks around your calendar. --ics prints the plan as a calendar file.")
def cmd_plan(app: App, args):
    from .. import views

    plan, notes = app.build_plan()
    if "--ics" in args:
        return print(views.to_ics(plan), end="")
    if app.json:
        return app.emit(_plan_json(app, plan))
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


@command("gantt", key="c", group="Looking", help="the next days as a chart", feature="planning", screen=True,
         usage="[--days 14]", flags=("--days",))
def cmd_gantt(app: App, args):
    from .. import views

    days = _days_arg(args, 7)
    plan, notes = app.build_plan(days)
    if app.json:
        return app.emit(_plan_json(app, plan))
    for n in notes:
        console.print(f" [{WARN}]{escape(n)}[/]")
    day_start, day_end = app.schedule_times()
    views.gantt(plan, days, app.today, app.cfg["priority"]["hours_per_day"], day_start, day_end)
    console.print()
    views.warnings(plan, app.today)
    views.summary(plan, days, app.corrections)
    app.bar("plan")


@command("goals", key="g", group="Looking", help="goals and weekly progress", screen=True,
         usage="[add <name> <weekly time> [why] | rm <name>]", aliases=("goal",), flags=("add", "rm"),
         details="A goal with a weekly target gets one 'big rock' task a day (rule 2). Example: t g add thesis 3h")
def cmd_goals(app: App, args):
    from .. import parse
    from ..app import UsageError

    if args and args[0] in ("add", "set"):
        if len(args) < 3:
            raise UsageError("usage: t g add <name> <weekly time> [why...]")
        name, minutes = args[1].lstrip("+").lower(), parse.parse_duration(args[2])
        app.store.set_goal(name, minutes, " ".join(args[3:]) or None)
        app.say(f" [{ACCENT}]◆[/] {escape(name)} [{DIM}]· {fmt.minutes(minutes)} a week[/]")
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
        app.say(f" [{DIM}]No goals yet. A goal with a weekly target gets one 'big rock' task a day:[/] "
                f"t g add thesis 3h")
        return app.bar("goals")
    width = max(len(g.name) for g in goals)
    console.print(f" [{DIM}]This week[/]")
    for g in goals:
        m = spent.get(g.name, 0)
        line = f" {escape(g.name):<{width}}  "
        if g.weekly_min:
            filled = min(int(m / g.weekly_min * 20), 20)
            reached = " ✓" if m >= g.weekly_min else ""
            line += (f"[{ACCENT}]{'━' * filled}[/][{DIM}]{'━' * (20 - filled)}[/]  {fmt.minutes(m)} "
                     f"[{DIM}]/ {fmt.minutes(g.weekly_min)}[/][{ACCENT}]{reached}[/]")
        else:
            line += f"[{DIM}]{fmt.minutes(m)} · no weekly target[/]"
        if g.why:
            line += f"   [{DIM}]{escape(g.why)}[/]"
        console.print(line)
    app.bar("goals")


@command("wins", key="w", group="Looking", help="what you got done today", usage="[--week]", screen=True,
         aliases=("log",), flags=("--week",))
def cmd_wins(app: App, args):
    week = any(a.lstrip("-") == "week" for a in args)
    since = app.week_start if week else app.today
    done = app.store.done_since(since)
    focused = app.store.focused_since(since)
    if app.json:
        return app.emit({"since": since, "done": [t.to_json() for t in done], "focused_min": round(focused, 1)})
    console.print(f" [bold]{'This week' if week else 'Today'}[/] [{DIM}]·[/] {len(done)} done [{DIM}]·[/] "
                  f"{fmt.minutes(focused)} focused")
    for t in done:
        when = datetime.fromisoformat(t.done_at)
        stamp = f"{when:%a}" if week else f"{when:%H:%M}"
        goal = f" [{DIM}]{escape(t.goal)}[/]" if t.goal else ""
        console.print(f"   [{ACCENT}]✓[/] [{DIM}]{stamp}[/]  {escape(t.title)}{goal}")
    if not done and not focused:
        console.print(f"   [{DIM}]Nothing yet, and that's fine. One small step counts.[/]")
    app.bar("done")


def corrections_table(app: App, indent: int = 1):
    """What Tend learned from your history: one row per factor."""
    c = app.corrections
    rows = []
    if c.time.active:
        what = f"tasks take [bold]×{c.time.factor:.1f}[/] your estimate"
        use = "estimates are scaled" if abs(c.time.factor - 1) >= 0.05 else "no change needed"
    else:
        what, use = f"[{DIM}]not enough data[/]", "needs 5 finished tasks with focus time"
    rows.append(("Time", what, c.time.samples, use))
    for name, shift, kind in (("Soft dates", c.soft, "soft targets"), ("Deadlines", c.hard, "deadlines")):
        if shift.median_late is None or not shift.active:
            what, use = f"[{DIM}]not enough data[/]", "needs 5 finished tasks with this kind of date"
        else:
            late = shift.median_late
            what = (f"done [bold]{fmt.days(late)}[/] after the first date (median)" if late > 0 else
                    f"done {fmt.days(-late)} before the first date" if late < 0 else "done on the first date")
            use = f"{kind} count as {fmt.days(shift.days)} earlier" if shift.days else "no change needed"
        rows.append((name, what, shift.samples, use))
    if c.cycle.samples:
        rows.append(("Start to done", f"median {fmt.days(c.cycle.median_days)} from start to done",
                     c.cycle.samples, "data only, for plugins"))
    p = c.pushes
    what = (f"{p.pushed} of {p.dated} dated tasks pushed back" + (f", {p.average:.1f}× each" if p.pushed else "")
            if p.dated else f"[{DIM}]no dated tasks yet[/]")
    rows.append(("Push-backs", what, p.dated, "data only, for plugins"))
    tbl = Table.grid(padding=(0, 2))
    tbl.add_column(style="bold", no_wrap=True)
    tbl.add_column()
    for name, what, n, use in rows:
        tbl.add_row(name, f"{what}\n[{DIM}]{fmt.count(n, 'task')} · {use}[/]")
    if p.top:
        most = ", ".join(f"{escape(t)} ({n}×)" for _, t, n in p.top[:3])
        tbl.add_row("", f"[{DIM}]most pushed now: {most}[/]")
    console.print(Padding(tbl, (0, 0, 0, indent)))


@command("stats", key="i", group="Looking", help="how your plans usually go: time, dates, push-backs",
         feature="learning", screen=True,
         details="The median of your last 20 finished tasks. Corrections start after 5 tasks of a kind.")
def cmd_stats(app: App, args):
    if app.json:
        return app.emit(app.corrections.to_json())
    console.print(f" [bold]How your plans usually go[/] [{DIM}]· median of your last 20 finished tasks[/]")
    corrections_table(app)
    app.bar("stats")
