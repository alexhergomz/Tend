"""Rendering. Three colors only: accent, warn, dim."""

from datetime import date

from rich.console import Console, Group
from rich.markup import escape
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from . import fmt
from .model import Task
from .priority import Ranked

console = Console(highlight=False)
ACCENT, WARN, DIM = "cyan", "yellow", "grey50"

# key, command, what it does
COMMANDS = [
    ("n", "next", "the one thing to do now"),
    ("f", "focus", "focus timer on it  (--pomo · --flow · --box 45)"),
    ("d", "done", "mark it done"),
    ("s", "skip", "skip it for today, no questions asked"),
    ("x", "split", "break it into smaller steps"),
    ("a", "add", "capture a task  (or just: t <text>)"),
    ("t", "triage", "sort the inbox, 3 quick questions each"),
    ("l", "ls", "the whole queue, in order, with reasons"),
    ("e", "edit", "change a task:  t e 12 due:fri v:3"),
    ("k", "drop", "let a task go"),
    ("r", "resolve", "decide what to do with slipped tasks"),
    ("g", "goals", "goals and weekly progress  (g add thesis 3h)"),
    ("w", "wins", "what you got done today  (--week)"),
    ("u", "undo", "undo the last change"),
    ("?", "help", "this list"),
]
LABELS = {k: name for k, name, _ in COMMANDS} | {"q": "quit"}


def say(msg: str):
    console.print(msg)


def meta(t: Task, today: date, warn_due: bool = False) -> Text:
    parts: list[tuple[str, str]] = [(f"#{t.id}", DIM)]
    if t.goal:
        parts.append((t.goal, DIM))
    if t.estimate_min:
        parts.append(("~" + fmt.minutes(t.estimate_min), DIM))
    elif t.size:
        parts.append((t.size, DIM))
    if t.due:
        parts.append((f"due {fmt.day(t.due, today)}", WARN if warn_due else DIM))
    if t.aim:
        parts.append((f"aim {fmt.day(t.aim, today)}", DIM))
    if not t.triaged:
        parts.append(("inbox", DIM))
    out = Text()
    for i, (s, style) in enumerate(parts):
        if i:
            out.append(" · ", DIM)
        out.append(s, style)
    return out


def card(r: Ranked, today: date) -> Group:
    grid = Table.grid(expand=True, padding=(0, 1))
    grid.add_column(ratio=1)
    grid.add_column(justify="right", no_wrap=True)
    grid.add_row(Text.assemble((" → ", ACCENT), (r.task.title, "bold")), meta(r.task, today, r.rule == 1))
    return Group(grid, Text("   " + r.reason, style=WARN if r.rule == 1 else DIM))


def status_line(counts: dict):
    parts = []
    if counts.get("at_risk"):
        parts.append(f"[{WARN}]⚑ {counts['at_risk']} deadline{'s' * (counts['at_risk'] > 1)} at risk[/]")
    if counts.get("slipped"):
        parts.append(f"[{WARN}]{counts['slipped']} slipped[/]")
    if counts.get("inbox"):
        parts.append(f"[{DIM}]{counts['inbox']} in inbox[/]")
    if parts:
        console.print(" " + f"[{DIM}] · [/]".join(parts))


def footer(keys: list[str], cli: bool = True):
    console.print(Rule(style=DIM))
    line = Text(" t ▸ " if cli else " ", style=DIM)
    for k in keys:
        line.append(k, f"bold {ACCENT}")
        line.append(f" {LABELS.get(k, k)}  ", DIM)
    console.print(line)


def queue(ranked: list[Ranked], today: date):
    width = len(str(len(ranked)))
    for i, r in enumerate(ranked, 1):
        grid = Table.grid(expand=True, padding=(0, 1))
        grid.add_column(no_wrap=True)
        grid.add_column(ratio=1)
        grid.add_column(justify="right", no_wrap=True)
        mark = Text(" " + ("⚑" if r.rule == 1 else str(i)).rjust(width), WARN if r.rule == 1 else ACCENT if i == 1 else DIM)
        grid.add_row(mark, Text(r.task.title, "bold" if i == 1 else ""), meta(r.task, today, r.rule == 1))
        grid.add_row("", Text(r.reason, WARN if r.rule == 1 else DIM), "")
        console.print(grid)


def help_screen(config_path, data_path):
    tbl = Table(box=None, show_header=False, padding=(0, 2))
    tbl.add_column(style=f"bold {ACCENT}")
    tbl.add_column(style="bold")
    tbl.add_column(style=DIM)
    for k, name, what in COMMANDS:
        tbl.add_row(k, name, what)
    console.print(Text(" Commands", "bold"), Text("· t <key> or t <name> · t alone opens interactive mode", DIM))
    console.print(tbl)
    console.print()
    console.print(Text(" Quick-add syntax", "bold"))
    for line in (
        "t write ch.2 intro +thesis due:fri v:3 e:2h",
        "+goal   due:<date> hard deadline   aim:<date> soft target   after:<date> hide until",
        "v:1..3 value (nice to have · matters · really matters)   s:S|M|L size   e:45m estimate",
        "dates: today tom fri +3d +2w oct20 10-20 2026-10-20 eow eom   ·   due:none clears",
        "--json on any command prints machine-readable output",
    ):
        console.print("   " + escape(line), style=DIM)
    console.print()
    console.print(f"   [{DIM}]config {config_path}\n   data   {data_path}[/]")


def ask(prompt: str) -> str:
    try:
        return console.input(f"[{ACCENT}]{prompt}[/]").strip()
    except EOFError:
        return ""


def choose(prompt: str, options: dict[str, str]) -> str:
    """Show options, return the pressed key (only keys in options)."""
    from . import keys

    shown = "  ".join(f"[bold {ACCENT}]{escape(k)}[/] [{DIM}]{escape(v)}[/]" for k, v in options.items())
    console.print(f" {prompt}  {shown}")
    while True:
        k = keys.readkey()
        if k in options:
            return k
