import json
from datetime import date, datetime, time, timedelta

from dataclasses import replace

import sys

from . import backup, calibrate, config, energy, features, hooks, ics, plan, priority, slips, ui
from .model import Task
from .store import Store

# Footer keys for each context. "t" (triage) and "r" (resolve) are added when relevant.
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


class UsageError(Exception):
    pass


class App:
    def __init__(self, json_out: bool = False, tui: bool = False):
        self.cfg = config.load()
        self.store = Store(config.data_path())
        self.json = json_out
        self.tui = tui
        self.flash: list[str] = []
        self.nested = False  # inside another command (review): no command bar
        self.energy_override: str | None = None  # t next --low / --high
        self.store.on_event = self._on_change
        try:
            backup.daily(self.store.db, self.cfg, date.today())
        except OSError as e:  # a failed backup must never stop you from using tend
            print(f"tend: daily backup failed: {e}", file=sys.stderr)
        self.reload()

    def reload(self):
        self.today = date.today()
        self.__dict__.pop("_corrections", None)
        slips.roll_over(self.store, self.today, self.cfg["slips"]["quiet_rollovers"])
        slips.wake_waiting(self.store, self.today)

    @property
    def week_start(self) -> date:
        return self.today - timedelta(days=self.today.weekday())

    def on(self, feature: str) -> bool:
        return features.enabled(self.cfg, feature)

    def _on_change(self, kind: str, summary: str, changes: list):
        if self.on("hooks"):
            hooks.fire("on_change", {"kind": kind, "summary": summary, "changes": changes})

    def hook(self, event: str, task: Task | None = None, **extra):
        if self.on("hooks"):
            hooks.fire(event, {"task": task.to_json() if task else None, **extra})

    def open_tasks(self) -> list[Task]:
        """Open tasks as the engines and screens should see them: features that are off leave no trace."""
        tasks = self.store.tasks()
        if not self.on("states"):
            tasks = [replace(t, stage="todo") for t in tasks]
        if not self.on("energy"):
            tasks = [replace(t, energy=None) for t in tasks]
        return tasks

    @property
    def corrections(self) -> calibrate.Corrections:
        if not hasattr(self, "_corrections"):
            self._corrections = calibrate.corrections(self.store, self.on("learning"))
        return self._corrections

    @property
    def calibration(self) -> calibrate.Calibration:
        return self.corrections.time

    @property
    def windows(self) -> energy.Windows:
        return energy.parse(self.cfg["energy"]) if self.on("energy") else {}

    def energy_now(self) -> str | None:
        return self.energy_override or energy.at(self.windows, datetime.now())

    def rank_inputs(self) -> dict:
        """Everything the three rules need, besides the tasks and the date."""
        targets = {g.name: g.weekly_min for g in self.store.goals()}
        today_min = self.store.goal_minutes(self.today)
        p = self.cfg["priority"]
        return dict(
            goal_targets=targets,
            goal_minutes=self.store.goal_minutes(self.week_start),
            goal_worked_today=any(today_min.get(g, 0) > 0 for g, t in targets.items() if t > 0),
            logged=self.store.logged_by_task(),
            blocked=self.store.blocked_ids(),
            at_risk_days=p["at_risk_slack_days"],
            calibration=self.corrections.time.factor,
            hard_shift=self.corrections.hard.days,
            soft_shift=self.corrections.soft.days,
        )

    def ranked(self) -> list[priority.Ranked]:
        return priority.rank(self.open_tasks(), today=self.today, energy_now=self.energy_now(),
                             hours_per_day=self.cfg["priority"]["hours_per_day"], **self.rank_inputs())

    def schedule_times(self) -> tuple[time, time]:
        sc = self.cfg["schedule"]
        return time.fromisoformat(sc["day_start"]), time.fromisoformat(sc["day_end"])

    def build_plan(self, days: int | None = None) -> tuple[plan.Plan, list[str]]:
        sc = self.cfg["schedule"]
        horizon = max(days or 0, sc["horizon_days"])
        start = datetime.combine(self.today, time())
        events, warnings = ics.load(self.cfg["calendar"]["ics"] if self.on("planning") else [], config.data_path().parent / "calendars",
                                    start, start + timedelta(days=horizon))
        day_start, day_end = self.schedule_times()
        names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        work_days = {names.index(d.lower()[:3]) for d in sc["work_days"] if d.lower()[:3] in names}
        result = plan.schedule(
            self.open_tasks(), events, now=datetime.now(), days=horizon,
            day_start=day_start, day_end=day_end, work_days=work_days,
            hours_per_day=self.cfg["priority"]["hours_per_day"],
            focused_today=self.store.focused_since(self.today),
            max_block=sc["max_block"], break_minutes=sc["break_minutes"],
            energy_windows=self.windows, **self.rank_inputs(),
        )
        return result, warnings

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
        open_tasks = self.store.tasks()
        return {
            "at_risk": sum(1 for r in ranked if r.rule == 1 and r.task.due >= self.today),
            "slipped": len(self.slipped()),
            "inbox": sum(1 for t in open_tasks if not t.triaged),
            "review": self.review_due(),
            "started": (started := sum(1 for t in open_tasks if t.stage == "started"
                                       and t.id not in self.store.blocked_ids())),
            "too_many_started": self.on("states") and started > self.cfg["priority"]["max_started"],
        }

    def footer_keys(self, ctx: str, counts: dict) -> list[str]:
        """Base keys for the context, with alerts after the first three so they survive trimming."""
        base = list(FOOTERS[ctx])
        alerts = [k for k, on in (("r", counts["slipped"]), ("t", counts["inbox"]), ("v", counts.get("review")))
                  if on and k not in base]
        keys = base[:3] + alerts + base[3:] + ["?"]
        return [k for k in keys if features.command_enabled(self.cfg, ui.LABELS.get(k, ""))]

    # ── output ──────────────────────────────────────────────────────────
    def say(self, msg: str):
        if self.tui:
            self.flash.append(msg)
        elif not self.json:
            ui.say(msg)

    def emit(self, obj):
        print(json.dumps(obj, indent=2, default=str))

    def bar(self, ctx: str):
        """Status line + command bar, printed under every CLI output."""
        if self.tui or self.json or self.nested or not self.cfg["ui"]["footer"]:
            return
        counts = self.status()
        ui.console.print()
        ui.status_line(counts)
        ui.footer(self.footer_keys(ctx, counts))

    # ── targets ─────────────────────────────────────────────────────────
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
        return ranked[0].task if ranked else None
