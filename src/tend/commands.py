from datetime import datetime, timedelta

from rich.markup import escape

from . import config, fmt, keys, parse, slips, ui, views
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
        k = ui.choose("", {"n": "today", "r": "reschedule", "x": "split", "k": "drop", "q": "later"})
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
            "calibration": app.calibration.factor,
        })
    for n in notes:
        console.print(f" [{WARN}]{escape(n)}[/]")
    day = next((d for d in plan.days if plan.on(d)), app.today)
    if day != app.today:
        console.print(f" [{DIM}]Nothing more planned today.[/]")
    views.day_plan(plan, day, app.today)
    console.print()
    views.warnings(plan, app.today)
    views.summary(plan, 7, app.calibration)
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
    views.summary(plan, days, app.calibration)
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

    step(2, "Estimates")
    cal = app.calibration
    if cal.active:
        word = "longer" if cal.factor > 1 else "less time"
        console.print(f"   Tasks took [bold]×{cal.factor:.1f}[/] your estimate [{DIM}](median of the last {cal.samples} "
                      f"timed tasks). Deadlines and plans already use this.[/]" if abs(cal.factor - 1) >= 0.05 else
                      f"   Your estimates are accurate [{DIM}](last {cal.samples} timed tasks).[/]")
        if abs(cal.factor - 1) >= 0.05:
            console.print(f"   [{DIM}]In short: things take {word} than you expect.[/]")
    else:
        console.print(f"   [{DIM}]Not enough data yet: {cal.samples} of 5 finished tasks have focus time. "
                      f"Use t focus and this step will start to learn.[/]")

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

    step(5, "Old tasks")
    logged = app.store.logged_by_task()
    cutoff = (app.today - timedelta(days=30)).isoformat()
    old = [t for t in app.store.tasks() if t.created[:10] < cutoff and not t.due and not t.aim
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

    step(6, "Goals")
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
    console.print(f"\n [{ACCENT}]✓[/] Review done. [{DIM}]Next one in {app.cfg['review']['every_days']} days.[/]")


def cmd_help(app: App, args):
    ui.help_screen(config.config_path(), config.data_path())


COMMANDS = {
    "next": cmd_next, "focus": cmd_focus, "done": cmd_done, "skip": cmd_skip, "split": cmd_split,
    "add": cmd_add, "triage": cmd_triage, "ls": cmd_ls, "edit": cmd_edit, "drop": cmd_drop,
    "resolve": cmd_resolve, "plan": cmd_plan, "gantt": cmd_gantt, "review": cmd_review,
    "goals": cmd_goals, "wins": cmd_wins, "undo": cmd_undo, "help": cmd_help,
}
ALIASES = {k: name for k, name, _ in ui.COMMANDS} | {"list": "ls", "goal": "goals", "log": "wins"}


def lookup(word: str):
    return COMMANDS.get(ALIASES.get(word, word))
