"""The recommender: three rules, applied in order. Pure functions, no I/O.

Rule 1 (slack, from the Critical Path Method): a hard deadline whose slack is at
    most `at_risk_days` comes first. slack = days until due - work left.
Rule 2 (Big Rocks / Eat the Frog): until you've worked on a goal today, the
    next task comes from the goal furthest behind its weekly target.
Rule 3 (WSJF): everything else by (value + urgency) / size, ties to the oldest.

Tasks skipped today go to the end.
"""

from dataclasses import dataclass
from datetime import date

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


def work_left_hours(task: Task, logged_min: float = 0.0) -> float:
    estimate = task.estimate_min or SIZE_MINUTES[task.size or DEFAULT_SIZE]
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
) -> list[Ranked]:
    goal_targets = goal_targets or {}
    goal_minutes = goal_minutes or {}
    logged = logged or {}

    scored: list[Ranked] = []
    for t in tasks:
        if t.status != "open" or t.id in blocked or (t.start_after and t.start_after > today):
            continue
        work = work_left_hours(t, logged.get(t.id, 0))
        due_slack = slack_days(t.due, work, today, hours_per_day) if t.due else None
        aim_slack = slack_days(t.aim, work, today, hours_per_day) if t.aim else None
        slacks = [s for s in (due_slack, aim_slack) if s is not None]
        u = urgency(min(slacks) if slacks else None)
        v, size = t.value or DEFAULT_VALUE, t.size or DEFAULT_SIZE
        score = (v + u) / SIZES[size]
        if due_slack is not None and due_slack <= at_risk_days:
            if t.due < today:
                reason = f"past due · ~{fmt.hours(work)} of work left"
            else:
                reason = f"at risk · ~{fmt.hours(work)} of work, {max(due_slack, 0):.1f} days of slack"
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
    return first + big_rock + rest + skipped
