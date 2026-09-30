import json
from datetime import date, timedelta

from . import config, priority, slips, ui
from .model import Task
from .store import Store

# Footer keys for each context. "t" (triage) and "r" (resolve) are added when relevant.
FOOTERS = {
    "next": ["f", "d", "s", "x", "a"],
    "added": ["n", "a", "u"],
    "done": ["n", "w", "u"],
    "list": ["n", "a", "e", "k"],
    "empty": ["a", "g", "w"],
    "goals": ["n", "g"],
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
        self.reload()

    def reload(self):
        self.today = date.today()
        slips.roll_over(self.store, self.today, self.cfg["slips"]["quiet_rollovers"])

    @property
    def week_start(self) -> date:
        return self.today - timedelta(days=self.today.weekday())

    def ranked(self) -> list[priority.Ranked]:
        goals = self.store.goals()
        targets = {g.name: g.weekly_min for g in goals}
        today_min = self.store.goal_minutes(self.today)
        p = self.cfg["priority"]
        return priority.rank(
            self.store.tasks(),
            today=self.today,
            goal_targets=targets,
            goal_minutes=self.store.goal_minutes(self.week_start),
            goal_worked_today=any(today_min.get(g, 0) > 0 for g, t in targets.items() if t > 0),
            logged=self.store.logged_by_task(),
            blocked=self.store.blocked_ids(),
            hours_per_day=p["hours_per_day"],
            at_risk_days=p["at_risk_slack_days"],
        )

    def slipped(self) -> list[Task]:
        return slips.needs_decision(self.store.tasks(), self.today, self.cfg["slips"]["quiet_rollovers"])

    def status(self, ranked=None) -> dict:
        ranked = self.ranked() if ranked is None else ranked
        open_tasks = self.store.tasks()
        return {
            "at_risk": sum(1 for r in ranked if r.rule == 1 and r.task.due >= self.today),
            "slipped": len(self.slipped()),
            "inbox": sum(1 for t in open_tasks if not t.triaged),
        }

    def footer_keys(self, ctx: str, counts: dict) -> list[str]:
        keys = list(FOOTERS[ctx])
        if counts["slipped"] and "r" not in keys:
            keys.append("r")
        if counts["inbox"] and "t" not in keys:
            keys.append("t")
        return keys + ["?"]

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
        if self.tui or self.json or not self.cfg["ui"]["footer"]:
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
