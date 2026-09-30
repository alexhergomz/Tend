from datetime import date, timedelta

from tend.model import Task
from tend.priority import rank, slack_days, urgency

TODAY = date(2026, 9, 29)


def task(id, title, created="2026-09-01", **kw):
    return Task(id=id, title=title, created=created, **kw)


def test_worked_example_from_design():
    tasks = [
        task(1, "fix bike", created="2026-09-20", value=1, size="S"),
        task(2, "portfolio site", created="2026-09-10", value=3, size="M"),
        task(3, "reply to professor", value=2, size="S", due=TODAY + timedelta(days=5)),
        task(4, "thesis ch.2", goal="thesis", value=2, size="M"),
        task(5, "tax form", value=2, size="M", due=TODAY + timedelta(days=1)),
    ]
    ranked = rank(tasks, today=TODAY, goal_targets={"thesis": 180}, goal_minutes={"thesis": 60})
    assert [r.task.id for r in ranked] == [5, 4, 3, 2, 1]
    assert [r.rule for r in ranked] == [1, 2, 3, 3, 3]
    assert ranked[2].score == 4.0
    assert ranked[3].score == ranked[4].score == 2.0  # tie → older wins


def test_big_rock_only_until_goal_worked_today():
    tasks = [task(1, "email", value=3, size="S"), task(2, "thesis", goal="thesis", value=1, size="L")]
    kw = dict(today=TODAY, goal_targets={"thesis": 180}, goal_minutes={})
    assert rank(tasks, **kw)[0].task.id == 2
    assert rank(tasks, goal_worked_today=True, **kw)[0].task.id == 1


def test_big_rock_picks_goal_furthest_behind():
    tasks = [task(1, "a", goal="a", value=2, size="S"), task(2, "b", goal="b", value=2, size="S")]
    ranked = rank(tasks, today=TODAY, goal_targets={"a": 100, "b": 100}, goal_minutes={"a": 80, "b": 10})
    assert ranked[0].task.id == 2 and ranked[0].rule == 2


def test_no_big_rock_when_goal_met():
    tasks = [task(1, "a", goal="a", value=1, size="L"), task(2, "email", value=3, size="S")]
    ranked = rank(tasks, today=TODAY, goal_targets={"a": 60}, goal_minutes={"a": 90})
    assert ranked[0].task.id == 2


def test_slack_accounts_for_work_left():
    # big task due in 3 days with 12h of work at 4h/day has no slack left → at risk
    big = task(1, "big", value=2, size="L", estimate_min=12 * 60, due=TODAY + timedelta(days=3))
    small = task(2, "small", value=3, size="S", due=TODAY + timedelta(days=1))
    ranked = rank([small, big], today=TODAY)
    assert ranked[0].task.id == 1 and ranked[0].rule == 1
    assert slack_days(TODAY + timedelta(days=3), 12, TODAY, 4) == 0


def test_logged_time_reduces_work_left():
    t = task(1, "big", value=2, size="L", estimate_min=12 * 60, due=TODAY + timedelta(days=3))
    assert rank([t], today=TODAY, logged={1: 8 * 60})[0].rule == 3


def test_urgency_buckets():
    assert [urgency(s) for s in (None, 30, 7.5, 7, 2, 1.9, -3)] == [1, 1, 1, 2, 2, 3, 3]


def test_soft_target_raises_urgency_but_never_rule_1():
    t = task(1, "soft", value=2, size="S", aim=TODAY)
    r = rank([t], today=TODAY)[0]
    assert r.rule == 3 and r.urgency == 3


def test_skipped_go_last_and_blocked_or_future_hidden():
    tasks = [
        task(1, "skipped", value=3, size="S", skip_date=TODAY),
        task(2, "normal", value=1, size="L"),
        task(3, "parent", value=3, size="S"),
        task(4, "later", value=3, size="S", start_after=TODAY + timedelta(days=2)),
    ]
    ranked = rank(tasks, today=TODAY, blocked={3})
    assert [r.task.id for r in ranked] == [2, 1]
    assert ranked[1].reason.startswith("skipped today")


def test_untriaged_uses_defaults():
    r = rank([task(1, "inbox item")], today=TODAY)[0]
    assert r.score == (2 + 1) / 2 and "untriaged" in r.reason
