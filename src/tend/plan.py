"""Schedule solver. Pure functions, no I/O.

The plan uses the same three rules as `t next`. For every free slot, it asks
"what would `next` say at this point?", books a block for that task, and
repeats. Each day gets at most `hours_per_day` of focus, so the rest of the
working window stays free as a buffer. Nothing is stored: the plan is rebuilt
from the current state every time you run it.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from . import priority
from .ics import Event
from .model import Task


@dataclass
class Block:
    start: datetime
    end: datetime
    task: Task
    rule: int

    @property
    def minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60


@dataclass
class Late:
    task: Task
    finish: date | None  # None: doesn't fit in the horizon at all
    minutes_left: float  # work not scheduled before the deadline


@dataclass
class Plan:
    days: list[date]
    blocks: list[Block] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    capacity: dict[date, float] = field(default_factory=dict)  # focus minutes available
    late: list[Late] = field(default_factory=list)
    unplanned: list[tuple[Task, float]] = field(default_factory=list)  # open work beyond the horizon

    def on(self, day: date) -> list[Block]:
        return [b for b in self.blocks if b.start.date() == day]


def free_slots(day: date, day_start: time, day_end: time, events: list[Event], not_before: datetime) -> list[list[datetime]]:
    start = max(datetime.combine(day, day_start), not_before)
    end = datetime.combine(day, day_end)
    slots = [[start, end]] if start < end else []
    for e in events:
        nxt = []
        for s, t in slots:
            if e.end <= s or e.start >= t:
                nxt.append([s, t])
                continue
            if e.start > s:
                nxt.append([s, e.start])
            if e.end < t:
                nxt.append([e.end, t])
        slots = nxt
    return slots


def schedule(
    tasks: list[Task],
    events: list[Event],
    *,
    now: datetime,
    days: int = 14,
    day_start: time = time(9),
    day_end: time = time(18),
    work_days: set[int] = frozenset(range(7)),  # 0 = Monday
    hours_per_day: float = 4,
    focused_today: float = 0,  # minutes already focused today
    max_block: int = 90,
    min_block: int = 15,
    break_minutes: int = 10,
    goal_targets: dict[str, int] | None = None,
    goal_minutes: dict[str, float] | None = None,  # this week so far
    goal_worked_today: bool = False,
    logged: dict[int, float] | None = None,
    blocked: set[int] = frozenset(),
    at_risk_days: float = 1,
    calibration: float = 1.0,
) -> Plan:
    goal_targets = goal_targets or {}
    week_goal = dict(goal_minutes or {})
    logged = dict(logged or {})
    open_tasks = [t for t in tasks if t.status == "open" and t.id not in blocked]
    remaining = {t.id: priority.work_left_hours(t, logged.get(t.id, 0), calibration) * 60 for t in open_tasks}
    finished_on: dict[int, date] = {}
    today = now.date()
    plan = Plan(days=[today + timedelta(days=i) for i in range(days)])

    # start at the next 5 minute mark
    now = now.replace(second=0, microsecond=0) + timedelta(minutes=(-now.minute) % 5 or 0)
    for day in plan.days:
        if day.weekday() == 0 and day != today:
            week_goal = {}
        if day.weekday() not in work_days:
            continue
        slots = free_slots(day, day_start, day_end, events, now)
        budget = hours_per_day * 60 - (focused_today if day == today else 0)
        plan.capacity[day] = max(0, min(budget, sum((t - s).total_seconds() / 60 for s, t in slots)))
        worked_goal = goal_worked_today if day == today else False

        while slots and budget >= min_block:
            pending = [t for t in open_tasks if remaining[t.id] > 0.5]
            if not pending:
                break
            ranked = priority.rank(
                pending, today=day, goal_targets=goal_targets, goal_minutes=week_goal,
                goal_worked_today=worked_goal, logged=logged, blocked=blocked,
                hours_per_day=hours_per_day, at_risk_days=at_risk_days, calibration=calibration,
            )
            if not ranked:
                break
            pick = ranked[0]
            s, t = slots[0]
            room = (t - s).total_seconds() / 60
            length = min(remaining[pick.task.id], max_block, budget, room)
            if length < min(min_block, remaining[pick.task.id]):
                slots.pop(0)
                continue
            end = s + timedelta(minutes=length)
            plan.blocks.append(Block(s, end, pick.task, pick.rule))
            tid = pick.task.id
            remaining[tid] -= length
            logged[tid] = logged.get(tid, 0) + length
            budget -= length
            if pick.task.goal:
                week_goal[pick.task.goal] = week_goal.get(pick.task.goal, 0) + length
                if goal_targets.get(pick.task.goal, 0) > 0:
                    worked_goal = True
            if remaining[tid] <= 0.5:
                finished_on[tid] = day
            slots[0][0] = end + timedelta(minutes=break_minutes)
            if slots[0][0] >= slots[0][1] - timedelta(minutes=min_block):
                slots.pop(0)

    plan.events = [e for e in events if plan.days[0] <= e.start.date() <= plan.days[-1]]
    for t in open_tasks:
        if remaining[t.id] > 0.5:
            plan.unplanned.append((t, remaining[t.id]))
        if t.due:
            finish = finished_on.get(t.id)
            if finish is None or finish > t.due:
                before = sum(b.minutes for b in plan.blocks if b.task.id == t.id and b.start.date() <= t.due)
                total = sum(b.minutes for b in plan.blocks if b.task.id == t.id) + max(remaining[t.id], 0)
                plan.late.append(Late(t, finish, total - before))
    return plan
