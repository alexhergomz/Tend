"""Small helpers used by many commands."""

from rich.markup import escape

from .. import keys, ui
from ..app import App, UsageError
from ..model import Task
from ..ui import DIM


def title(t: Task) -> str:
    """A task title in bold, safe to put in markup."""
    return f"[bold]{escape(t.title)}[/]"


def fresh(app: App, t: Task) -> Task | None:
    """The task as it is now, or None if it was closed meanwhile (a loop may have dropped it)."""
    now = app.store.task(t.id)
    return now if now and now.status == "open" else None


def ids_in(args: list[str]) -> list[str]:
    return [a for a in args if a.lstrip("#").isdigit()]


def confirm(app: App, question: str, args: list[str]) -> bool:
    """Yes or no. `--yes` answers in advance; without a terminal, it is required."""
    if "--yes" in args or "-y" in args:
        return True
    if not keys.interactive():
        raise UsageError(f"{question} Add --yes to confirm.")
    return ui.choose(question, {"y": "yes", "n": "no"}) == "y"


def energy_flag(app: App, args: list[str]):
    for a in args:
        if a.lstrip("-") in ("low", "high"):
            app.energy_override = a.lstrip("-")


def goal_hint(app: App, goal: str | None):
    if goal and app.store.ensure_goal(goal):
        app.say(f"   [{DIM}]new goal '{escape(goal)}' · give it a weekly target: t g add {escape(goal)} 3h[/]")
