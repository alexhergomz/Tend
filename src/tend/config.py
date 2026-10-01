"""Config lives in one commented TOML file. Missing keys fall back to DEFAULTS."""

import os
import tomllib
from pathlib import Path

DEFAULTS = {
    "focus": {
        "default_mode": "pomo",  # pomo | flow | box
        "pomo_work": 25,  # minutes
        "pomo_break": 5,
        "box_minutes": 45,
        "flow_break_ratio": 0.2,  # flow: break earned = 20% of time worked
    },
    "priority": {
        "hours_per_day": 4,  # realistic focused hours per day, used for slack
        "at_risk_slack_days": 1,  # rule 1 threshold
        "calibrate": True,  # learn time and date corrections from finished tasks
        "max_started": 3,  # warn when more tasks than this are started at once
    },
    "schedule": {
        "day_start": "09:00",
        "day_end": "18:00",
        "work_days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
        "max_block": 90,  # minutes
        "break_minutes": 10,
        "horizon_days": 14,
    },
    "calendar": {
        "ics": [],  # .ics files or URLs with busy times
    },
    "review": {
        "every_days": 7,
    },
    "energy": {
        "high": [],  # e.g. ["09:00-12:00"]
        "low": [],  # e.g. ["14:00-16:00"]
    },
    "slips": {
        "quiet_rollovers": 2,  # soft targets roll forward silently this many times
    },
    "ui": {
        "footer": True,  # command bar under every output
    },
    "backup": {
        "keep_days": 7,  # daily copies to keep
        "folder": "",  # empty: next to the database
    },
    "features": {name: True for name in ("review", "learning", "planning", "hooks", "plugins", "energy", "states")},
}

TEMPLATE = """\
# tend configuration. Delete a line to go back to its default.

[focus]
default_mode = "pomo"     # pomo | flow | box
pomo_work = 25            # minutes
pomo_break = 5
box_minutes = 45
flow_break_ratio = 0.2    # flow mode: break earned = 20% of time worked

[priority]
hours_per_day = 4         # realistic focused hours per day (used to compute slack)
at_risk_slack_days = 1    # rule 1: a deadline with this much slack or less comes first
calibrate = true          # learn time and date corrections from finished tasks
max_started = 3           # warn when more tasks than this are started at once

[schedule]
day_start = "09:00"       # t plan only books time inside this window
day_end = "18:00"
work_days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
max_block = 90            # longest focus block, minutes
break_minutes = 10        # gap between blocks
horizon_days = 14         # how far ahead t plan looks for deadline problems

[calendar]
ics = []                  # busy times, e.g. ["~/cal/uni.ics", "https://.../basic.ics"]

[review]
every_days = 7            # show "review due" after this many days

[energy]
high = []                 # hard work hours, e.g. ["09:00-12:00"]; tasks tagged @high go here
low = []                  # easy work hours, e.g. ["14:00-16:00"]; tasks tagged @low fit here

[slips]
quiet_rollovers = 2       # a missed soft target rolls forward quietly this many times

[ui]
footer = true             # show the command bar under every output

[backup]
keep_days = 7             # a copy of your data is made every day; this many are kept
folder = ""               # where copies go; empty means next to the database

[features]                # optional parts of tend; false removes a part completely
review = true             # weekly review and its reminder
learning = true           # corrections learned from your history, and t stats
planning = true           # t plan, t gantt and calendar import
hooks = true              # scripts that run after events
plugins = true            # t-<name> programs run as t <name>
energy = true             # energy windows and @high / @low tasks
states = true             # started and waiting states
"""


def _xdg(var: str, fallback: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / fallback)


def config_path() -> Path:
    return Path(os.environ.get("TEND_CONFIG") or _xdg("XDG_CONFIG_HOME", ".config") / "tend" / "config.toml")


def data_path() -> Path:
    return Path(os.environ.get("TEND_DB") or _xdg("XDG_DATA_HOME", ".local/share") / "tend" / "tend.db")


def load() -> dict:
    path = config_path()
    if not path.exists():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(TEMPLATE)
        except OSError:
            pass
    user = {}
    if path.exists():
        with path.open("rb") as f:
            user = tomllib.load(f)
    return {section: {**values, **user.get(section, {})} for section, values in DEFAULTS.items()}
