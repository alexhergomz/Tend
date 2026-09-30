"""Visible but kind: missed soft targets roll forward quietly a couple of times,
then ask for a decision. Missed hard deadlines always ask for a decision."""

from datetime import date

from . import fmt
from .model import Task
from .store import Store


def roll_over(store: Store, today: date, quiet: int):
    stale = [t for t in store.tasks() if t.aim and t.aim < today and t.slips < quiet]
    if not stale:
        return
    with store.event("rollover", f"rolled {len(stale)} soft target(s) to today"):
        for t in stale:
            t.aim = today
            t.slips += 1
            store.update(t)


def needs_decision(tasks: list[Task], today: date, quiet: int) -> list[Task]:
    return [t for t in tasks if t.status == "open" and (
        (t.due and t.due < today) or (t.aim and t.aim < today and t.slips >= quiet)
    )]


def why(t: Task, today: date) -> str:
    if t.due and t.due < today:
        return f"hard deadline was {fmt.day(t.due, today)}"
    return f"soft target slipped {t.slips + 1} times"
