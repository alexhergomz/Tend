"""The web UI's API: small functions over the same App and actions as the command line.

Each handler takes (app, body, params) and returns plain data. Messages that
commands would print ("✓ done · 3 done today") are collected and returned, so
the page can show them as notices.
"""

import io
from datetime import date, datetime, timedelta

from rich.text import Text

from tend import __version__, backup, config, features, fmt, parse, slips, transfer
from tend.app import App, UsageError
from tend.commands import actions
from tend.model import STATES, Task
from tend.priority import Ranked
from tend.store import UndoBlocked

ROUTES: dict[tuple[str, str], callable] = {}


def route(method: str, path: str):
    def wrap(fn):
        ROUTES[(method, path)] = fn
        return fn
    return wrap


class NotFound(Exception):
    pass


def plain(markup: str) -> str:
    return Text.from_markup(markup).plain.strip()


# ── shapes ──────────────────────────────────────────────────────────────
def chips(t: Task, today: date, warn_due: bool = False) -> list[dict]:
    """The small labels next to a task, already in words."""
    out = []
    if t.status == "open" and t.stage == "started":
        out.append({"text": "started", "tone": "accent"})
    elif t.status == "open" and t.stage == "waiting":
        out.append({"text": f"waiting until {fmt.day(t.start_after, today)}" if t.start_after else "waiting",
                    "tone": "warn"})
    if t.goal:
        out.append({"text": t.goal, "tone": "goal"})
    if t.estimate_min:
        out.append({"text": "~" + fmt.minutes(t.estimate_min), "tone": "muted"})
    elif t.size:
        out.append({"text": {"S": "small", "M": "medium", "L": "large"}[t.size], "tone": "muted"})
    if t.due:
        out.append({"text": f"due {fmt.day(t.due, today)}", "tone": "warn" if warn_due else "muted"})
    if t.aim:
        out.append({"text": f"aim {fmt.day(t.aim, today)}", "tone": "muted"})
    if t.energy:
        out.append({"text": f"{t.energy} energy", "tone": "muted"})
    if t.repeat:
        out.append({"text": f"↻ {t.repeat.replace(',', ', ')}", "tone": "muted"})
    if t.pushes >= 2:
        out.append({"text": f"pushed {t.pushes}×", "tone": "muted"})
    if not t.triaged and t.status == "open":
        out.append({"text": "inbox", "tone": "muted"})
    return out


def task(t: Task, today: date) -> dict:
    return {**t.to_json(), "state": t.state, "chips": chips(t, today)}


def ranked(r: Ranked, today: date, place: int) -> dict:
    return {**task(r.task, today), "chips": chips(r.task, today, r.rule == 1), "rule": r.rule,
            "reason": r.reason, "score": round(r.score, 2), "deadline": r.deadline, "place": place}


def fresh(app: App, task_id) -> Task:
    t = app.store.task(int(task_id))
    if not t or t.status != "open":
        raise UsageError(f"no open task #{task_id}")
    return t


# ── reading ─────────────────────────────────────────────────────────────
@route("GET", "/api/state")
def state(app: App, body, params) -> dict:
    """Everything the main screens need, in one call."""
    today = app.today
    queue = app.ranked()
    queued = {r.task.id for r in queue}
    goals_week = app.store.goal_minutes(app.week_start)
    tasks = app.store.tasks()
    return {
        "version": __version__,
        "today": today,
        "first_run": app.first_run(),
        "features": {name: app.on(name) for name in features.FEATURES},
        "status": app.status(queue),
        "energy_now": app.energy_now(),
        "queue": [ranked(r, today, i) for i, r in enumerate(queue, 1)],
        "waiting": [task(t, today) for t in tasks if t.stage == "waiting" and t.id not in queued]
        if app.on("states") else [],
        "inbox": [task(t, today) for t in tasks if not t.triaged],
        "slipped": [{**task(t, today), "why": slips.why(t, today), "hard": bool(t.due and t.due < today)}
                    for t in app.slipped()],
        "goals": [{"name": g.name, "weekly_min": g.weekly_min, "why": g.why,
                   "week_min": round(goals_week.get(g.name, 0), 1)} for g in app.store.goals()],
        "done_today": len(app.store.done_since(today)),
        "focused_today": round(app.store.focused_since(today), 1),
    }


@route("GET", "/api/task")
def task_details(app: App, body, params) -> dict:
    t = app.store.task(int(params.get("id", 0)))
    if not t:
        raise NotFound("no such task")
    steps = [task(c, app.today) for c in app.store.children(t.id)]
    return {**task(t, app.today), "steps": steps,
            "focused_min": round(app.store.logged_by_task().get(t.id, 0), 1)}


@route("GET", "/api/parse")
def parse_preview(app: App, body, params) -> dict:
    """What the capture box will add, as you type."""
    text = params.get("text", "")
    try:
        name, fields = parse.parse_tokens([text], app.today)
    except parse.ParseError as e:
        return {"ok": False, "error": str(e)}
    preview = Task(id=0, title=name or "", **{k: v for k, v in fields.items() if v is not None})
    return {"ok": bool(name), "title": name, "chips": [c for c in chips(preview, app.today) if c["text"] != "inbox"]}


@route("GET", "/api/plan")
def plan(app: App, body, params) -> dict:
    days = max(1, min(int(params.get("days", 7)), 31))
    result, notes = app.build_plan(days)
    span = result.days[:days]
    return {
        "days": [{"date": d, "label": fmt.day(d, app.today), "weekday": f"{d:%a}",
                  "capacity": result.capacity.get(d, 0), "planned": sum(b.minutes for b in result.on(d))}
                 for d in span],
        "blocks": [{"task_id": b.task.id, "title": b.task.title, "start": b.start, "end": b.end, "rule": b.rule,
                    "minutes": b.minutes, "goal": b.task.goal, "energy": b.task.energy} for b in result.blocks
                   if b.start.date() in span],
        "events": [{"title": e.title, "start": e.start, "end": e.end} for e in result.events
                   if e.start.date() <= span[-1]],
        "late": [{"task_id": x.task.id, "title": x.task.title, "due": x.due, "due_label": fmt.day(x.due, app.today),
                  "finish": x.finish, "minutes_left": round(x.minutes_left), "past": x.due < app.today}
                 for x in result.late],
        "deadlines": {str(k): v for k, v in result.deadlines.items()},
        "unplanned_min": round(sum(m for _, m in result.unplanned)),
        "notes": notes,
        "corrections": app.corrections.to_json(),
        "day_start": app.cfg["schedule"]["day_start"], "day_end": app.cfg["schedule"]["day_end"],
    }


@route("GET", "/api/wins")
def wins(app: App, body, params) -> dict:
    week = params.get("week") == "1"
    since = app.week_start if week else app.today
    done = app.store.done_since(since)
    return {"week": week, "done": [{**task(t, app.today), "when": datetime.fromisoformat(t.done_at)} for t in done],
            "focused_min": round(app.store.focused_since(since), 1)}


@route("GET", "/api/stats")
def stats(app: App, body, params) -> dict:
    return app.corrections.to_json()


@route("GET", "/api/review")
def review(app: App, body, params) -> dict:
    since = app.today - timedelta(days=7)
    spent = app.store.goal_minutes(since)
    tasks = app.store.tasks()
    logged = app.store.logged_by_task()
    blocked = app.store.blocked_ids()
    cutoff = (app.today - timedelta(days=30)).isoformat()
    has_tasks = {t.goal for t in tasks if t.goal}
    return {
        "last": app.store.get_meta("last_review"),
        "done": len(app.store.done_since(since)),
        "focused_min": round(app.store.focused_since(since), 1),
        "goals": [{"name": g.name, "weekly_min": g.weekly_min, "spent": round(spent.get(g.name, 0), 1)}
                  for g in app.store.goals() if g.weekly_min],
        "inbox": sum(1 for t in tasks if not t.triaged),
        "slipped": len(app.slipped()),
        "waiting": [task(t, app.today) for t in tasks if t.stage == "waiting" and not t.start_after]
        if app.on("states") else [],
        "old": [task(t, app.today) for t in tasks if t.created[:10] < cutoff and not t.due and not t.aim
                and t.stage == "todo" and not logged.get(t.id) and t.id not in blocked],
        "empty_goals": [g.name for g in app.store.goals() if g.weekly_min and g.name not in has_tasks],
    }


# ── changing tasks ──────────────────────────────────────────────────────
@route("POST", "/api/tasks")
def add(app: App, body, params) -> dict:
    name, f = parse.parse_tokens([body.get("text", "")], app.today)
    if not name:
        raise UsageError("a task needs a title")
    t = Task(id=None, title=name, **f)
    actions.dates_for_repeat(app, t)
    with app.store.event("add", f"add {name}") as ev:
        app.store.insert(t)
        ev["summary"] = f"add #{t.id} {t.title}"
    app.store.set_meta("welcomed", "1")
    if t.goal:
        app.store.ensure_goal(t.goal)
    app.hook("on_add", t)
    app.say(f"Added {t.title}" + ("" if t.triaged else " to the inbox"))
    return {"id": t.id}


@route("POST", "/api/edit")
def edit(app: App, body, params) -> dict:
    t = fresh(app, body["id"])
    name, f = parse.parse_tokens([body.get("text", "")], app.today)
    with app.store.event("edit", f"edit #{t.id} {t.title}"):
        if name:
            t.title = name
        for k, v in f.items():
            setattr(t, k, v)
        actions.dates_for_repeat(app, t)
        if "aim" in f or "due" in f:
            t.slips = 0
        app.store.update(t)
    if f.get("goal"):
        app.store.ensure_goal(f["goal"])
    app.say(f"Changed {t.title}")
    return {"id": t.id}


@route("POST", "/api/act")
def act(app: App, body, params) -> dict:
    """One action on one task: done, skip, start, todo, wait, drop."""
    t = fresh(app, body["id"])
    action = body.get("action")
    if action == "done":
        actions.complete(app, t)
    elif action == "skip":
        with app.store.event("skip", f"skip #{t.id} {t.title}"):
            t.skip_date = app.today
            app.store.update(t)
        app.hook("on_skip", t)
        app.say(f"Skipped {t.title} for today")
    elif action in ("start", "todo"):
        if not app.on("states"):
            raise UsageError("task states are turned off")
        actions.set_stage(app, t, "started" if action == "start" else "todo")
    elif action == "wait":
        if not app.on("states"):
            raise UsageError("task states are turned off")
        until = parse.parse_date(body["until"], app.today) if body.get("until") else None
        actions.set_stage(app, t, "waiting", until)
    elif action == "drop":
        actions.drop(app, t, once=bool(body.get("once")) and bool(t.repeat) and app.on("repeat"))
    else:
        raise UsageError(f"unknown action {action!r}")
    app.store.set_meta("current", None)
    return {"id": t.id}


@route("POST", "/api/split")
def split(app: App, body, params) -> dict:
    t = fresh(app, body["id"])
    steps = [s.strip() for s in body.get("steps", []) if s.strip()]
    if not steps:
        raise UsageError("add at least one step")
    actions.split(app, t, steps)
    return {"id": t.id}


@route("POST", "/api/triage")
def triage(app: App, body, params) -> dict:
    t = fresh(app, body["id"])
    value, size = int(body["value"]), str(body["size"]).upper()
    if value not in (1, 2, 3) or size not in ("S", "M", "L"):
        raise UsageError("value is 1 to 3, size is S, M or L")
    when = parse.parse_date(body["date"], app.today) if body.get("date") else None
    with app.store.event("triage", f"triage #{t.id} {t.title}"):
        t.value, t.size = value, size
        if body.get("goal") is not None:
            t.goal = body["goal"] or None
        if when and body.get("soft"):
            t.aim = when
        elif when:
            t.due = when
        app.store.update(t)
    app.say(f"Sorted {t.title}")
    return {"id": t.id}


@route("POST", "/api/resolve")
def resolve(app: App, body, params) -> dict:
    t = fresh(app, body["id"])
    choice = body.get("choice")
    hard = bool(t.due and t.due < app.today)
    if choice == "drop":
        actions.drop(app, t, once=bool(t.repeat) and app.on("repeat"))
        return {"id": t.id}
    if choice not in ("today", "reschedule"):
        raise UsageError(f"unknown choice {choice!r}")
    when = app.today if choice == "today" else parse.parse_date(body.get("date", ""), app.today)
    with app.store.event("resolve", f"reschedule #{t.id} {t.title}"):
        if hard:
            t.due = when
        else:
            t.aim = when
        t.slips = 0
        app.store.update(t)
    app.say(f"{t.title}: {'due' if hard else 'aim'} {fmt.day(when, app.today)}")
    return {"id": t.id}


@route("POST", "/api/focus/start")
def focus_start(app: App, body, params) -> dict:
    t = fresh(app, body["id"])
    if app.on("states") and t.stage != "started":
        actions.set_stage(app, t, "started", quiet=True)
    app.hook("on_focus_start", t, mode=body.get("mode", "pomo"))
    return {"id": t.id, "settings": app.cfg["focus"]}


@route("POST", "/api/focus/end")
def focus_end(app: App, body, params) -> dict:
    t = fresh(app, body["id"])
    minutes = max(0.0, min(float(body.get("minutes", 0)), 24 * 60))
    mode = body.get("mode", "pomo")
    if minutes >= 0.5:
        end = datetime.now()
        app.store.add_session(t.id, end - timedelta(minutes=minutes), end, mode, round(minutes, 1))
    outcome = "done" if body.get("done") else "stop"
    app.hook("on_focus_end", t, mode=mode, minutes=round(minutes, 1), outcome=outcome)
    app.say(f"Focused {fmt.minutes(minutes)} on {t.title}" if minutes >= 0.5 else "Stopped the timer")
    if outcome == "done":
        actions.complete(app, app.store.task(t.id))
    return {"id": t.id}


@route("POST", "/api/undo")
def undo(app: App, body, params) -> dict:
    try:
        summary = app.store.undo()
    except UndoBlocked:
        raise UsageError("The last change was an import or a restore. Go back with a backup copy instead.") from None
    app.say(f"Undid: {summary}" if summary else "Nothing to undo")
    return {"undone": summary}


@route("POST", "/api/review/done")
def review_done(app: App, body, params) -> dict:
    app.store.set_meta("last_review", app.today.isoformat())
    app.hook("on_review")
    app.say("Review done. See you next week.")
    return {}


# ── goals ───────────────────────────────────────────────────────────────
@route("POST", "/api/goals")
def goal_set(app: App, body, params) -> dict:
    name = str(body.get("name", "")).strip().lstrip("+").lower().replace(" ", "-")
    if not name:
        raise UsageError("a goal needs a name")
    minutes = parse.parse_duration(str(body.get("weekly", "0")) or "0")
    app.store.set_goal(name, minutes, body.get("why") or None)
    app.say(f"Goal {name}: {fmt.minutes(minutes)} a week" if minutes else f"Goal {name} saved")
    return {"name": name}


@route("POST", "/api/goals/remove")
def goal_remove(app: App, body, params) -> dict:
    app.store.delete_goal(str(body.get("name", "")))
    app.say(f"Removed goal {body.get('name')}")
    return {}


# ── settings and data ───────────────────────────────────────────────────
@route("POST", "/api/features")
def set_feature(app: App, body, params) -> dict:
    name = body.get("name")
    if name not in features.FEATURES:
        raise UsageError(f"no feature {name!r}")
    if name == "plugins" and not body.get("on"):
        raise UsageError("the web UI is a plugin: turn plugins off from the terminal, t features off plugins")
    features.set_enabled(name, bool(body.get("on")))
    app.cfg = config.load()
    app.say(f"{name} turned {'on' if body.get('on') else 'off'}")
    return {}


@route("GET", "/api/settings")
def settings(app: App, body, params) -> dict:
    from tend import doctor, reminders

    return {
        "features": [{"name": n, "since": since, "what": what, "on": app.on(n)}
                     for n, (since, what) in features.FEATURES.items()],
        "backups": [{"n": i, "kind": c.kind, "made": c.made, "open_tasks": c.open_tasks(), "size_kb": c.size_kb}
                    for i, c in enumerate(backup.copies(app.cfg), 1)],
        "doctor": [c.to_json() for c in doctor.run()],
        "reminders": {"on": app.on("reminders"), "timer": reminders.timer() if app.on("reminders") else None,
                      "pending": [r.to_json() for r in reminders.pending(app, datetime.now())]
                      if app.on("reminders") else []},
        "paths": {"config": fmt.home(config.config_path()), "data": fmt.home(config.data_path())},
        "states": list(STATES),
    }


@route("POST", "/api/backup")
def make_backup(app: App, body, params) -> dict:
    path = backup.make(app.store.db, app.cfg, "manual")
    app.say(f"Saved a copy: {path.name}")
    return {}


@route("POST", "/api/restore")
def restore(app: App, body, params) -> dict:
    found = backup.copies(app.cfg)
    n = int(body.get("n", 0))
    if not 1 <= n <= len(found):
        raise UsageError(f"no copy {n}")
    try:
        backup.restore(app.store.db, app.cfg, found[n - 1].path)
    except ValueError as e:
        raise UsageError(str(e)) from None
    app.store.migrate()
    app.store.changed()
    app.store.mark("restore", f"restored the copy from {found[n - 1].made:%Y-%m-%d %H:%M}")
    app.say(f"Restored the copy from {found[n - 1].made:%a %b %d %H:%M}. Your data from before is copy 1.")
    return {}


@route("GET", "/api/export")
def export(app: App, body, params) -> dict:
    out = io.StringIO()
    transfer.export(app.store, out)
    return {"filename": f"tend-{app.today}.jsonl", "content": out.getvalue()}


@route("POST", "/api/import")
def import_data(app: App, body, params) -> dict:
    try:
        header, data = transfer.read(io.StringIO(body.get("content", "")))
    except transfer.TransferError as e:
        raise UsageError(str(e)) from None
    has_data = any(app.store.db.execute(f"SELECT 1 FROM {t} LIMIT 1").fetchone()
                   for t in ("tasks", "goals", "sessions"))
    replace = bool(body.get("replace")) or not has_data
    if has_data:
        backup.make(app.store.db, app.cfg, "before")
    counts = transfer.replace_all(app.store, header, data) if replace else transfer.add(app.store, data)
    app.store.changed()
    app.store.mark("import", "import from the web UI")
    app.say(f"{'Loaded' if replace else 'Added'} {fmt.count(counts['tasks'], 'task')}"
            + (f", {counts['skipped']} already here" if counts.get("skipped") else ""))
    return counts


@route("POST", "/api/reminders")
def reminder_action(app: App, body, params) -> dict:
    from tend import reminders

    if not app.on("reminders"):
        raise UsageError("reminders are turned off")
    what = body.get("action")
    if what == "test":
        ok = reminders.send("Tend", "Reminders work.")
        app.say("Sent a test reminder" if ok else "This system can't show notifications. Hooks still get them.")
    elif what == "install":
        for line in reminders.install(app.cfg["reminders"]["every_minutes"]):
            app.say(line)
    elif what == "uninstall":
        for line in reminders.uninstall() or ["No timer was installed"]:
            app.say(line)
    else:
        raise UsageError(f"unknown action {what!r}")
    return {}
