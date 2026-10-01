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
    ("n", "next", "the one thing to do now  (--low · --high energy)"),
    ("f", "focus", "focus timer on it  (--pomo · --flow · --box 45)"),
    ("b", "start", "mark it started (focus does this too)"),
    ("d", "done", "mark it done"),
    ("s", "skip", "skip it for today, no questions asked"),
    ("x", "split", "break it into smaller steps"),
    ("a", "add", "capture a task  (or just: t <text>)"),
    ("t", "triage", "sort the inbox, 3 quick questions each"),
    ("l", "ls", "the whole queue, in order, with reasons"),
    ("e", "edit", "change a task:  t e 12 due:fri v:3"),
    ("h", "wait", "on hold, waiting for someone:  t wait 12 mon"),
    ("k", "drop", "let a task go"),
    ("r", "resolve", "decide what to do with slipped tasks"),
    ("p", "plan", "today's schedule, built with the same rules"),
    ("c", "gantt", "the next 7 days as a chart  (--days 14)"),
    ("v", "review", "weekly review, about 5 minutes"),
    ("g", "goals", "goals and weekly progress  (g add thesis 3h)"),
    ("w", "wins", "what you got done today  (--week)"),
    ("i", "stats", "how your plans usually go: time, dates, push-backs"),
    ("u", "undo", "undo the last change"),
    ("", "backup", "save a copy of your data now (one is made every day)"),
    ("", "restore", "list copies, or go back to one:  t restore 2"),
    ("", "export", "all data as JSON lines:  t export tasks.jsonl"),
    ("", "import", "load an export  (--replace for an exact copy)"),
    ("?", "help", "this list"),
]
LABELS = {k: name for k, name, _ in COMMANDS if k} | {"q": "quit"}


def say(msg: str):
    console.print(msg)


def meta(t: Task, today: date, warn_due: bool = False) -> Text:
    parts: list[tuple[str, str]] = [(f"#{t.id}", DIM)]
    if t.status == "open" and t.stage == "started":
        parts.append(("started", ACCENT))
    elif t.status == "open" and t.stage == "waiting":
        parts.append((f"waiting until {fmt.day(t.start_after, today)}" if t.start_after else "waiting", WARN))
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
    if t.energy:
        parts.append((f"@{t.energy}", DIM))
    if t.pushes >= 2:
        parts.append((f"pushed {t.pushes}×", DIM))
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
    if counts.get("too_many_started"):
        parts.append(f"[{WARN}]{counts['started']} started[/]")
    if counts.get("inbox"):
        parts.append(f"[{DIM}]{counts['inbox']} in inbox[/]")
    if counts.get("review"):
        parts.append(f"[{DIM}]weekly review due[/]")
    if parts:
        console.print(" " + f"[{DIM}] · [/]".join(parts))


def footer(keys: list[str], cli: bool = True):
    """One line of keys. If it doesn't fit, keys are dropped from the end (help and quit stay)."""
    keys = list(keys)

    def build(ks):
        line = Text(" t ▸ " if cli else " ", style=DIM)
        for k in ks:
            line.append(k, f"bold {ACCENT}")
            line.append(f" {LABELS.get(k, k)}  ", DIM)
        return line

    keep = [k for k in ("?", "q") if k in keys]
    while len(build(keys).plain.rstrip()) > console.width - 1 and len(keys) > len(keep) + 1:
        drop = next(i for i in range(len(keys) - 1, -1, -1) if keys[i] not in keep)
        keys.pop(drop)
    console.print(Rule(style=DIM))
    console.print(build(keys))


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


def help_screen(config_path, data_path, shown=lambda name: True, extensions: bool = True):
    tbl = Table(box=None, show_header=False, padding=(0, 2))
    tbl.add_column(style=f"bold {ACCENT}")
    tbl.add_column(style="bold")
    tbl.add_column(style=DIM)
    for k, name, what in COMMANDS:
        if shown(name):
            tbl.add_row(k, name, what)
    console.print(Text(" Commands", "bold"), Text("· t <key> or t <name> · t alone opens interactive mode", DIM))
    console.print(tbl)
    console.print()
    console.print(Text(" Quick-add syntax", "bold"))
    for line in (
        "t write ch.2 intro +thesis due:fri v:3 e:2h",
        "+goal   due:<date> hard deadline   aim:<date> soft target   after:<date> hide until",
        "v:1..3 value (nice to have · matters · really matters)   s:S|M|L size   e:45m estimate",
        "@high / @low energy: hard work goes in high-energy hours   ·   @any clears",
        "dates: today tom fri +3d +2w oct20 10-20 2026-10-20 eow eom   ·   due:none clears",
        "--json on any command prints machine-readable output",
    ):
        console.print("   " + escape(line), style=DIM)
    console.print()
    if extensions:
        console.print(Text(" Plugins and hooks", "bold"))
        console.print(f"   [{DIM}]any t-<name> program on your PATH runs as t <name> · t plugins lists them and your hooks[/]")
        console.print()
    console.print(f"   [{DIM}]t features turns optional parts on and off[/]")
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
