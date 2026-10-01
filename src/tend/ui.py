"""Rendering. Three named styles only: accent, warn and dim.

Themes map the names to colors. The `plain` theme has no color and only
ASCII characters, for screen readers, logs and simple terminals. Rich already
respects the NO_COLOR environment variable.
"""

import sys
from datetime import date

from rich.console import Console, Group
from rich.markup import escape
from rich.padding import Padding
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from . import fmt, registry
from .model import Task
from .priority import Ranked

ACCENT, WARN, DIM = "accent", "warn", "dim"
ACCENT_B, WARN_B = "accent.bold", "warn.bold"

THEMES = {
    "dark": {"accent": "cyan", "warn": "yellow", "dim": "grey50"},
    "light": {"accent": "#00788a", "warn": "#a35a00", "dim": "#6a737d"},
    "plain": {"accent": "none", "warn": "none", "dim": "none"},
}


def _theme(name: str) -> Theme:
    colors = THEMES.get(name, THEMES["dark"])
    return Theme({
        "accent": colors["accent"], "warn": colors["warn"], "dim": colors["dim"],
        "accent.bold": f"bold {colors['accent']}".replace(" none", ""),
        "warn.bold": f"bold {colors['warn']}".replace(" none", ""),
    })


ASCII = str.maketrans({
    "→": ">", "⚑": "!", "✓": "*", "●": "*", "━": "=", "─": "-", "▆": "#", "▃": "_", "◆": "<", "↻": "~",
    "·": "-", "▸": ">", "⏸": "=", "↶": "<", "↷": ">", "✂": "%", "○": "o", "×": "x", "…": "...", "–": "-",
    "—": "-", "└": "`", "›": ">", "░": ".",
})


class _AsciiFile:
    """Wraps stdout and turns the few non-ASCII characters Tend uses into ASCII."""

    def __init__(self, inner):
        self.inner = inner

    def write(self, text: str) -> int:
        return self.inner.write(text.translate(ASCII))

    def __getattr__(self, name):
        return getattr(self.inner, name)


console = Console(highlight=False, theme=_theme("dark"))


def apply_theme(name: str):
    console.push_theme(_theme(name), inherit=False)
    if name == "plain":
        console.no_color = True
        console.file = _AsciiFile(sys.stdout)


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
    if t.repeat:
        parts.append((f"↻ {t.repeat.replace(',', ' ')}", DIM))
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
        parts.append(f"[{WARN}]⚑ {fmt.count(counts['at_risk'], 'deadline')} at risk[/]")
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


def label(key: str) -> str:
    if key == "q":
        return "quit"
    cmd = registry.by_key().get(key)
    return cmd.name if cmd else key


def footer(keys: list[str], cli: bool = True):
    """One line of keys. If it doesn't fit, keys are dropped from the end (help and quit stay)."""
    keys = list(keys)

    def build(ks):
        line = Text(" t ▸ " if cli else " ", style=DIM)
        for k in ks:
            line.append(k, ACCENT_B)
            line.append(f" {label(k)}  ", DIM)
        return line

    keep = [k for k in ("?", "q") if k in keys]
    while len(build(keys).plain.rstrip()) > console.width - 1 and len(keys) > len(keep) + 1:
        drop = next(i for i in range(len(keys) - 1, -1, -1) if keys[i] not in keep)
        keys.pop(drop)
    console.print(Rule(style=DIM))
    console.print(build(keys))


def queue(ranked: list[Ranked], today: date):
    """The queue as one table: one row for the task, one for the reason."""
    tbl = Table.grid(expand=True, padding=(0, 1))
    tbl.add_column(no_wrap=True, justify="right")
    tbl.add_column(ratio=1)
    tbl.add_column(justify="right", no_wrap=True)
    for i, r in enumerate(ranked, 1):
        at_risk = r.rule == 1
        mark = Text("⚑" if at_risk else str(i), WARN if at_risk else ACCENT if i == 1 else DIM)
        tbl.add_row(mark, Text(r.task.title, "bold" if i == 1 else ""), meta(r.task, today, at_risk))
        tbl.add_row("", Text(r.reason, WARN if at_risk else DIM), "")
    console.print(Padding(tbl, (0, 0, 0, 1)))


def help_screen(shown, version: str, config_path, data_path, extensions: bool):
    """All commands by group. `shown(cmd)` says whether a command is available."""
    console.print(Text.assemble((" Tend ", "bold"), (version, DIM),
                                ("  ·  t <key> or t <name> · t alone opens interactive mode · "
                                 "t help <command> for details", DIM)))
    for group in registry.GROUPS:
        cmds = [c for c in registry.listed() if c.group == group and shown(c)]
        if not cmds:
            continue
        tbl = Table(box=None, show_header=False, padding=(0, 2), title=None)
        tbl.add_column(style=ACCENT_B, width=1)
        tbl.add_column(style="bold", width=9)
        tbl.add_column(style=DIM)
        for c in cmds:
            tbl.add_row(c.key, c.name, c.help)
        console.print(f"\n [bold]{group}[/]")
        console.print(tbl)
    console.print("\n [bold]Adding details[/]")
    for line in (
        "t write ch.2 intro +thesis due:fri v:3 e:2h",
        "+goal   due:<date> hard deadline   aim:<date> soft target   after:<date> hide until",
        "v:1..3 value (nice to have · matters · really matters)   s:S|M|L size   e:45m estimate",
        "@high / @low energy   ·   every:mon every:2w every:month every:1st repeat   ·   none clears, as in due:none",
        "dates: today tom fri +3d +2w oct20 10-20 2026-10-20 1st eow eom",
        "--json on any command prints machine-readable output",
    ):
        console.print("   " + escape(line), style=DIM)
    if extensions:
        console.print(f"\n   [{DIM}]Plugins: any t-<name> program on your PATH runs as t <name>. "
                      f"t plugins lists them.[/]")
    console.print(f"\n   [{DIM}]config {escape(str(config_path))}\n   data   {escape(str(data_path))}[/]")


def command_help(cmd: registry.Command):
    usage = f"t {cmd.name}" + (f" {cmd.usage}" if cmd.usage else "")
    keys = f" [{DIM}]· key[/] [{ACCENT_B}]{cmd.key}[/]" if cmd.key else ""
    console.print(f" [bold]{escape(usage)}[/]{keys}")
    console.print(f"   {escape(cmd.help)}")
    if cmd.details:
        for line in cmd.details.strip().splitlines():
            console.print(f"   [{DIM}]{escape(line)}[/]")
    if cmd.feature:
        console.print(f"   [{DIM}]Part of the '{cmd.feature}' feature (t features).[/]")


def ask(prompt: str) -> str:
    """A line of input. The prompt may contain markup; escape user text in it."""
    try:
        return console.input(f"[{ACCENT}]{prompt}[/]").strip()
    except EOFError:
        return ""


def choose(prompt: str, options: dict[str, str]) -> str:
    """Show options, return the pressed key (only keys in options)."""
    from . import keys

    shown = "  ".join(f"[{ACCENT_B}]{escape(k)}[/] [{DIM}]{escape(v)}[/]" for k, v in options.items())
    console.print(f" {prompt}  {shown}")
    while True:
        k = keys.readkey()
        if k in options:
            return k
