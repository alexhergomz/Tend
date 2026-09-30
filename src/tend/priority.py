"""The recommender: three rules, applied in order. Pure functions, no I/O.

Rule 1 (slack, from the Critical Path Method): a hard deadline whose slack is at
    most `at_risk_days` comes first. slack = days until due - work left.
Rule 2 (Big Rocks / Eat the Frog): until you've worked on a goal today, the
    next task comes from the goal furthest behind its weekly target.
Rule 3 (WSJF): everything else by (value + urgency) / size, ties to the oldest.

Tasks skipped today go to the end. During a high or low energy window, tasks
tagged with the other energy level go after the rest (deadlines at risk still
come first).

Two date corrections from your history can apply (see calibrate.py): hard
deadlines and soft targets count as `hard_shift` / `soft_shift` days earlier.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from . import fmt
from .model import SIZE_MINUTES, SIZES, Task

DEFAULT_VALUE = 2
DEFAULT_SIZE = "M"


@dataclass
class Ranked:
    task: Task
    rule: int
    score: float
    urgency: int
    slack: float | None  # days, from the hard deadline
    reason: str

    def to_json(self) -> dict:
        return {
            **self.task.to_json(),
            "rule": self.rule,
            "score": round(self.score, 2),
            "urgency": self.urgency,
            "slack_days": None if self.slack is None else round(self.slack, 2),
            "reason": self.reason,
        }


def work_left_hours(task: Task, logged_min: float = 0.0, calibration: float = 1.0) -> float:
    estimate = (task.estimate_min or SIZE_MINUTES[task.size or DEFAULT_SIZE]) * calibration
    return max(estimate - logged_min, 15) / 60


def slack_days(deadline: date, work_hours: float, today: date, hours_per_day: float) -> float:
    return (deadline - today).days - work_hours / hours_per_day


def urgency(slack: float | None) -> int:
    """1: over a week of slack (or no date) · 2: 2-7 days · 3: under 2 days."""
    if slack is None or slack > 7:
        return 1
    return 2 if slack >= 2 else 3


def rank(
    tasks: list[Task],
    *,
    today: date,
    goal_targets: dict[str, int] | None = None,  # goal -> weekly target, minutes
    goal_minutes: dict[str, float] | None = None,  # goal -> minutes this week
    goal_worked_today: bool = False,
    logged: dict[int, float] | None = None,  # task id -> minutes already logged
    blocked: set[int] = frozenset(),
    hours_per_day: float = 4,
    at_risk_days: float = 1,
    calibration: float = 1.0,  # learned ratio of actual time to estimated time
    hard_shift: int = 0,  # days: treat deadlines as this much earlier
    soft_shift: int = 0,  # days: treat soft targets as this much earlier
    energy_now: str | None = None,  # "high" / "low" window, or None
) -> list[Ranked]:
    goal_targets = goal_targets or {}
    goal_minutes = goal_minutes or {}
    logged = logged or {}

    scored: list[Ranked] = []
    for t in tasks:
        if t.status != "open" or t.id in blocked or (t.start_after and t.start_after > today):
            continue
        work = work_left_hours(t, logged.get(t.id, 0), calibration)
        due = t.due - timedelta(days=hard_shift) if t.due else None
        aim = t.aim - timedelta(days=soft_shift) if t.aim else None
        due_slack = slack_days(due, work, today, hours_per_day) if due else None
        aim_slack = slack_days(aim, work, today, hours_per_day) if aim else None
        slacks = [s for s in (due_slack, aim_slack) if s is not None]
        u = urgency(min(slacks) if slacks else None)
        v, size = t.value or DEFAULT_VALUE, t.size or DEFAULT_SIZE
        score = (v + u) / SIZES[size]
        if due_slack is not None and due_slack <= at_risk_days:
            if t.due < today:
                reason = f"past due · ~{fmt.hours(work)} of work left"
            else:
                reason = f"at risk · ~{fmt.hours(work)} of work, {max(due_slack, 0):.1f} days of slack"
                if hard_shift:
                    reason += f" (with a {hard_shift} day margin)"
            rule = 1
        else:
            reason = f"(value {v} + urgency {u}) / size {SIZES[size]} = {score:.1f}"
            if not t.triaged:
                reason += " · untriaged, using defaults"
            rule = 3
        scored.append(Ranked(t, rule, score, u, due_slack, reason))

    skipped = [r for r in scored if r.task.skip_date == today]
    active = [r for r in scored if r.task.skip_date != today]

    first = sorted((r for r in active if r.rule == 1), key=lambda r: (r.slack, r.task.id))
    rest = sorted((r for r in active if r.rule == 3), key=lambda r: (-r.score, r.task.created, r.task.id))
    other = {"high": "low", "low": "high"}.get(energy_now)
    later = [r for r in rest if other and r.task.energy == other]
    rest = [r for r in rest if r not in later]
    for r in later:
        r.reason = f"saved for {other}-energy time · " + r.reason

    big_rock = []
    if not goal_worked_today:
        behind = [(goal_minutes.get(g, 0) / target, g) for g, target in goal_targets.items()
                  if target > 0 and goal_minutes.get(g, 0) < target]
        for _, goal in sorted(behind):
            pick = next((r for r in rest if r.task.goal == goal), None)
            if pick:
                rest.remove(pick)
                pick.rule = 2
                deficit = goal_targets[goal] - goal_minutes.get(goal, 0)
                pick.reason = f"big rock · {goal} is {fmt.minutes(deficit)} behind this week"
                big_rock = [pick]
                break

    for r in skipped:
        r.reason = "skipped today · " + r.reason
    return first + big_rock + rest + later + skipped
