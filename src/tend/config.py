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
        "calibrate": True,  # scale estimates by how long tasks really take
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
    "slips": {
        "quiet_rollovers": 2,  # soft targets roll forward silently this many times
    },
    "ui": {
        "footer": True,  # command bar under every output
    },
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
calibrate = true          # learn from focus sessions how long tasks really take

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

[slips]
quiet_rollovers = 2       # a missed soft target rolls forward quietly this many times

[ui]
footer = true             # show the command bar under every output
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
