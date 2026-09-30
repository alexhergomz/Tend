from datetime import date, datetime, time, timedelta

from tend.ics import Event
from tend.model import Task
from tend.plan import free_slots, schedule

NOW = datetime(2026, 9, 29, 9, 0)  # Tuesday
TODAY = NOW.date()


def task(id, title, **kw):
    return Task(id=id, title=title, created="2026-09-01", **kw)


def test_free_slots_cut_around_events():
    events = [Event(datetime(2026, 9, 29, 10), datetime(2026, 9, 29, 11), "class")]
    slots = free_slots(TODAY, time(9), time(12), events, NOW)
    assert slots == [[datetime(2026, 9, 29, 9), datetime(2026, 9, 29, 10)],
                     [datetime(2026, 9, 29, 11), datetime(2026, 9, 29, 12)]]


def test_blocks_follow_the_three_rules_and_avoid_events():
    tasks = [
        task(1, "email", value=2, size="S"),
        task(2, "tax", value=2, size="S", estimate_min=60, due=TODAY + timedelta(days=1)),
        task(3, "thesis", goal="thesis", value=1, size="S"),
    ]
    events = [Event(datetime(2026, 9, 29, 10), datetime(2026, 9, 29, 10, 30), "call")]
    plan = schedule(tasks, events, now=NOW, days=1, break_minutes=0, goal_targets={"thesis": 60})
    assert [b.task.id for b in plan.blocks] == [2, 3, 1]
    assert [b.rule for b in plan.blocks] == [1, 2, 3]
    assert plan.blocks[0].start == NOW and plan.blocks[0].end == datetime(2026, 9, 29, 10)
    assert plan.blocks[1].start == datetime(2026, 9, 29, 10, 30)  # after the call


def test_daily_focus_budget_and_multi_day_split():
    big = task(1, "big", value=3, size="L", estimate_min=600)
    plan = schedule([big], [], now=NOW, days=5, hours_per_day=4, max_block=90, break_minutes=10)
    per_day = {d: sum(b.minutes for b in plan.on(d)) for d in plan.days}
    assert per_day[TODAY] == 240 and per_day[TODAY + timedelta(days=1)] == 240
    assert per_day[TODAY + timedelta(days=2)] == 120
    assert max(b.minutes for b in plan.blocks) <= 90


def test_late_detection():
    t = task(1, "report", value=3, size="L", estimate_min=12 * 60, due=TODAY + timedelta(days=1))
    plan = schedule([t], [], now=NOW, days=5, hours_per_day=4)
    assert len(plan.late) == 1 and plan.late[0].minutes_left == 4 * 60


def test_work_days_and_already_focused_time():
    t = task(1, "x", value=2, size="L", estimate_min=600)
    plan = schedule([t], [], now=NOW, days=3, work_days={0, 1, 3}, focused_today=180)  # Tue, skip Wed, Thu
    assert sum(b.minutes for b in plan.on(TODAY)) == 60
    assert not plan.on(TODAY + timedelta(days=1))
    assert plan.on(TODAY + timedelta(days=2))


def test_calibration_makes_tasks_longer():
    t = task(1, "x", value=2, size="S", estimate_min=60)
    plan = schedule([t], [], now=NOW, days=1, calibration=1.5, max_block=120)
    assert sum(b.minutes for b in plan.blocks) == 90
