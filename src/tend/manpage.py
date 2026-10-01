"""The man page, made from the command registry so it never disagrees with `t help`.

Write it with:  python -m tend.manpage > docs/t.1
Read it with:   man ./docs/t.1
"""

from datetime import date

from . import __version__, registry
from .features import FEATURES
from .hooks import EVENTS


def _roff(text: str) -> str:
    text = text.replace("\\", "\\e").replace("-", "\\-")
    return "\n".join(("\\&" + line) if line.startswith((".", "'")) else line for line in text.splitlines())


def render(today: date | None = None) -> str:
    out = [f'.TH T 1 "{(today or date(2026, 10, 1)).isoformat()}" "Tend {__version__}" "Tend manual"',
           ".SH NAME", "t, tend \\- a calm task manager that tells you what to do next, and why",
           ".SH SYNOPSIS", ".B t", ".br", ".B t", ".I command", "[\\fIarguments\\fR] [\\fB\\-\\-json\\fR]", ".br",
           ".B t", ".I any text to capture as a task",
           ".SH DESCRIPTION",
           _roff("Tend shows one task at a time and says why it picked it. Three rules decide, in order: "
                 "a hard deadline at risk comes first; then one task a day from the goal furthest behind its "
                 "weekly target; then everything else by (value + urgency) / size."),
           ".PP", _roff("Run t alone for interactive mode, where every command is one key. Anything that is not "
                        "a command is added as a task. Every command prints JSON with --json.")]
    for group in registry.GROUPS:
        cmds = [c for c in registry.listed() if c.group == group]
        if not cmds:
            continue
        out.append(f".SH {group.upper()}")
        for c in cmds:
            usage = f" {c.usage}" if c.usage else ""
            key = f" (key {c.key})" if c.key else ""
            out += [".TP", f"\\fBt {c.name}\\fR{_roff(usage)}{_roff(key)}", _roff(c.help[0].upper() + c.help[1:] + ".")]
            if c.details:
                out += [".br", _roff(" ".join(c.details.split()))]
            if c.feature:
                out += [".br", _roff(f"Part of the '{c.feature}' feature.")]
    out += [".SH ADDING DETAILS", _roff("Words become the title; these set fields, anywhere in the line:"),
            ".TP", "\\fB+goal\\fR", "Goal.",
            ".TP", "\\fBdue:\\fIdate\\fR, \\fBaim:\\fIdate\\fR, \\fBafter:\\fIdate\\fR",
            _roff("Hard deadline, soft target, hidden until. Dates: today, tom, mon to sun, +3d, +2w, oct20, "
                  "10-20, 2026-10-20, 1st, eow, eom. none clears."),
            ".TP", "\\fBv:\\fR1..3, \\fBs:\\fRS|M|L, \\fBe:\\fItime\\fR",
            _roff("Value (nice to have, matters, really matters), size, estimate (45m, 2h)."),
            ".TP", "\\fB@high\\fR, \\fB@low\\fR", _roff("Energy the task needs."),
            ".TP", "\\fBevery:\\fIrule\\fR",
            _roff("Repeat: day, weekday, mon,thu, 3d, 2w, month, year, 1st, 15th, last. Only one copy exists at a "
                  "time.")]
    out += [".SH FEATURES", _roff("Everything after version 0.1 can be turned off with t features off NAME:")]
    for name, (since, what) in FEATURES.items():
        out += [".TP", f"\\fB{name}\\fR", _roff(f"{what} (since {since}).")]
    out += [".SH FILES",
            ".TP", "\\fI~/.config/tend/config.toml\\fR", _roff("Settings, each with a comment."),
            ".TP", "\\fI~/.local/share/tend/tend.db\\fR", _roff("Your data: one SQLite file."),
            ".TP", "\\fI~/.local/share/tend/backups/\\fR", _roff("A copy of the data for each of the last 7 days."),
            ".TP", "\\fI~/.config/tend/hooks/\\fR", _roff("Hooks: " + ", ".join(EVENTS) + "."),
            ".SH ENVIRONMENT",
            ".TP", "\\fBTEND_DB\\fR, \\fBTEND_CONFIG\\fR, \\fBTEND_HOOKS\\fR",
            _roff("Use another database, config file or hooks folder."),
            ".TP", "\\fBNO_COLOR\\fR", _roff("No colors. The plain theme also uses only ASCII."),
            ".SH EXIT STATUS", _roff("0 on success, 1 for a usage error or a problem t doctor found, "
                                     "2 for a config file that can't be used."),
            ".SH SEE ALSO", _roff("https://github.com/alexhergomz/Tend")]
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    print(render(), end="")
