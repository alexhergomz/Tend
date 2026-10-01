"""The state of one run of Tend: config, data, today's date, and output helpers."""

import json
import sys
from dataclasses import replace
from datetime import date, datetime, time, timedelta

from . import backup, calibrate, config, energy, features, hooks, priority, slips, ui
from .model import Task
from .store import Store

# Keys in the command bar for each screen. Alerts (resolve, triage, review) are added when they apply.
FOOTERS = {
    "next": ["f", "d", "b", "s", "x", "h", "a"],
    "added": ["n", "a", "u"],
    "done": ["n", "w", "u"],
    "list": ["n", "p", "a", "e"],
    "empty": ["a", "g", "w"],
    "goals": ["n", "g"],
    "plan": ["n", "c", "f"],
    "stats": ["n", "p"],
}
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class UsageError(Exception):
    """A mistake in how a command was used. Shown as one friendly line."""


class App:
    def __init__(self, json_out: bool = False, tui: bool = False):
        self.cfg = config.load()
        ui.apply_theme(self.cfg["ui"]["theme"])
        self.store = Store(config.data_path())
        self.json = json_out
        self.tui = tui
        self.flash: list[str] = []  # messages for the next interactive screen
        self.nested = False  # inside another command (review): no command bar
        self.energy_override: str | None = None  # t next --low / --high
        self._ranked: tuple | None = None
        self.store.on_event = self._on_change
        try:
            backup.daily(self.store.db, self.cfg, date.today())
        except OSError as e:  # a failed backup must never stop you from using Tend
            print(f"Tend: daily backup failed: {e}", file=sys.stderr)
        self.reload()

    def reload(self):
        """Start of a run, or of a new screen: apply what the date changes."""
        self.today = date.today()
        self.__dict__.pop("_corrections", None)
        slips.roll_over(self.store, self.today, self.cfg["slips"]["quiet_rollovers"])
        woken = slips.wake_waiting(self.store, self.today)
        if woken:  # kept for the day, so a reminder goes out whichever run woke them
            seen = json.loads(self.store.get_meta("woken") or "{}")
            ids = (seen.get("ids", []) if seen.get("day") == self.today.isoformat() else []) + [t.id for t in woken]
            self.store.set_meta("woken", json.dumps({"day": self.today.isoformat(), "ids": ids}))

    def woken_today(self) -> list[Task]:
        """Waiting tasks that came back on their date today."""
        seen = json.loads(self.store.get_meta("woken") or "{}")
        if seen.get("day") != self.today.isoformat():
            return []
        return [t for i in seen.get("ids", []) if (t := self.store.task(i)) and t.status == "open"]

    @property
    def week_start(self) -> date:
        return self.today - timedelta(days=self.today.weekday())

    # ── features and hooks ──────────────────────────────────────────────
    def on(self, feature: str) -> bool:
        return features.enabled(self.cfg, feature)

    def _on_change(self, kind: str, summary: str, changes: list):
        if self.on("hooks"):
            hooks.fire("on_change", {"kind": kind, "summary": summary, "changes": changes})

    def hook(self, event: str, task: Task | None = None, **extra):
        if self.on("hooks"):
            hooks.fire(event, {"task": task.to_json() if task else None, **extra})

    # ── what the engines see ────────────────────────────────────────────
    def open_tasks(self) -> list[Task]:
        """Open tasks as the engines and screens should see them: features that are off leave no trace."""
        tasks = self.store.tasks()
        off = {f: None for f, name in (("energy", "energy"), ("repeat", "repeat")) if not self.on(name)}
        if not self.on("states"):
            off["stage"] = "todo"
        return [replace(t, **off) for t in tasks] if off else tasks

    @property
    def corrections(self) -> calibrate.Corrections:
        if "_corrections" not in self.__dict__:
            self._corrections = calibrate.corrections(self.store, self.on("learning"))
        return self._corrections

    @property
    def windows(self) -> energy.Windows:
        return energy.parse(self.cfg["energy"]) if self.on("energy") else {}

    def energy_now(self) -> str | None:
        return self.energy_override or energy.at(self.windows, datetime.now())

    def rank_inputs(self) -> dict:
        """Everything the three rules need, besides the tasks and the date."""
        targets = {g.name: g.weekly_min for g in self.store.goals()}
        today_min = self.store.goal_minutes(self.today)
        c = self.corrections
        return dict(
            goal_targets=targets,
            goal_minutes=self.store.goal_minutes(self.week_start),
            goal_worked_today=any(today_min.get(g, 0) > 0 for g, t in targets.items() if t > 0),
            logged=self.store.logged_by_task(),
            blocked=self.store.blocked_ids(),
            at_risk_days=self.cfg["priority"]["at_risk_slack_days"],
            calibration=c.time.factor,
            hard_shift=c.hard.days,
            soft_shift=c.soft.days,
        )

    def ranked(self) -> list[priority.Ranked]:
        """The queue. Built once per change of the data."""
        key = (self.store.generation, self.today, self.energy_now())
        if not self._ranked or self._ranked[0] != key:
            result = priority.rank(self.open_tasks(), today=self.today, energy_now=key[2],
                                   hours_per_day=self.cfg["priority"]["hours_per_day"], **self.rank_inputs())
            self._ranked = (key, result)
        return list(self._ranked[1])

    def schedule_times(self) -> tuple[time, time]:
        sc = self.cfg["schedule"]
        return time.fromisoformat(sc["day_start"]), time.fromisoformat(sc["day_end"])

    def build_plan(self, days: int | None = None):
        from . import ics, plan  # only needed here

        sc = self.cfg["schedule"]
        horizon = max(days or 0, sc["horizon_days"])
        start = datetime.combine(self.today, time())
        sources = self.cfg["calendar"]["ics"] if self.on("planning") else []
        events, warnings = ics.load(sources, config.data_path().parent / "calendars",
                                    start, start + timedelta(days=horizon))
        day_start, day_end = self.schedule_times()
        result = plan.schedule(
            self.open_tasks(), events, now=datetime.now(), days=horizon,
            day_start=day_start, day_end=day_end,
            work_days={DAYS.index(d.lower()[:3]) for d in sc["work_days"] if d.lower()[:3] in DAYS},
            hours_per_day=self.cfg["priority"]["hours_per_day"],
            focused_today=self.store.focused_since(self.today),
            max_block=sc["max_block"], break_minutes=sc["break_minutes"],
            energy_windows=self.windows, **self.rank_inputs(),
        )
        return result, warnings

    # ── status ──────────────────────────────────────────────────────────
    def review_due(self) -> bool:
        if not self.on("review"):
            return False
        last = self.store.get_meta("last_review")
        if last is None:
            self.store.set_meta("last_review", self.today.isoformat())
            return False
        return (self.today - date.fromisoformat(last)).days >= self.cfg["review"]["every_days"]

    def slipped(self) -> list[Task]:
        return slips.needs_decision(self.store.tasks(), self.today, self.cfg["slips"]["quiet_rollovers"])

    def status(self, ranked=None) -> dict:
        ranked = self.ranked() if ranked is None else ranked
        tasks = self.store.tasks()
        blocked = self.store.blocked_ids()
        started = sum(1 for t in tasks if t.stage == "started" and t.id not in blocked)
        return {
            "at_risk": sum(1 for r in ranked if r.rule == 1 and r.deadline >= self.today),
            "slipped": len(self.slipped()),
            "inbox": sum(1 for t in tasks if not t.triaged),
            "review": self.review_due(),
            "started": started,
            "too_many_started": self.on("states") and started > self.cfg["priority"]["max_started"],
        }

    def footer_keys(self, screen: str, counts: dict) -> list[str]:
        """Keys for a screen, with alerts after the first three so they survive trimming."""
        base = list(FOOTERS[screen])
        alerts = [k for k, on in (("r", counts["slipped"]), ("t", counts["inbox"]), ("v", counts.get("review")))
                  if on and k not in base]
        keys = base[:3] + alerts + base[3:] + ["?"]
        return [k for k in keys if features.command_enabled(self.cfg, ui.label(k))]

    def first_run(self) -> bool:
        """No task was ever added: show the welcome instead of an empty screen."""
        return self.store.get_meta("welcomed") is None and not self.store.db.execute(
            "SELECT 1 FROM tasks LIMIT 1").fetchone()

    # ── output ──────────────────────────────────────────────────────────
    def say(self, msg: str):
        if self.tui:
            self.flash.append(msg)
        elif not self.json:
            ui.say(msg)

    def emit(self, obj):
        print(json.dumps(obj, indent=2, default=str))

    def bar(self, screen: str):
        """Status line and command bar, printed under every command's output."""
        if self.tui or self.json or self.nested or not self.cfg["ui"]["footer"]:
            return
        counts = self.status()
        ui.console.print()
        ui.status_line(counts)
        ui.footer(self.footer_keys(screen, counts))

    # ── which task ──────────────────────────────────────────────────────
    def target(self, args: list[str]) -> Task | None:
        """Explicit id, else the task last shown by `next`, else the top of the queue."""
        ids = [a.lstrip("#") for a in args if a.lstrip("#").isdigit()]
        if args and not ids:
            raise UsageError(f"expected a task id, got '{args[0]}' · to capture it as a task: t add ...")
        if ids:
            t = self.store.task(int(ids[0]))
            if not t or t.status != "open":
                raise UsageError(f"no open task #{ids[0]}")
            return t
        current = self.store.get_meta("current")
        if current and (t := self.store.task(int(current))) and t.status == "open" \
                and t.id not in self.store.blocked_ids():
            return t
        ranked = self.ranked()
        # the queue may show a view of the task (features that are off are blanked out); commands get the real one
        return self.store.task(ranked[0].task.id) if ranked else None
