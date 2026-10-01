"""Config lives in one commented TOML file. Missing keys fall back to DEFAULTS."""

import os
import tomllib
from datetime import time
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
        "theme": "dark",  # dark | light | plain
    },
    "backup": {
        "keep_days": 7,  # daily copies to keep
        "folder": "",  # empty: next to the database
    },
    "reminders": {
        "every_minutes": 15,  # how often the timer from t notify --install runs
        "quiet_outside_day": True,  # no reminders outside [schedule] day_start..day_end
    },
    "features": {name: True for name in ("review", "learning", "planning", "hooks", "plugins", "energy", "states",
                                         "repeat", "reminders")},
}

TEMPLATE = """\
# Tend configuration. Delete a line to go back to its default.

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
theme = "dark"            # dark | light | plain (no color, ASCII only)

[backup]
keep_days = 7             # a copy of your data is made every day; this many are kept
folder = ""               # where copies go; empty means next to the database

[reminders]
every_minutes = 15        # how often the timer from `t notify --install` runs
quiet_outside_day = true  # no reminders outside [schedule] day_start..day_end

[features]                # optional parts of tend; false removes a part completely
review = true             # weekly review and its reminder
learning = true           # corrections learned from your history, and t stats
planning = true           # t plan, t gantt and calendar import
hooks = true              # scripts that run after events
plugins = true            # t-<name> programs run as t <name>
energy = true             # energy windows and @high / @low tasks
states = true             # started and waiting states
repeat = true             # repeating tasks (every:mon)
reminders = true          # desktop reminders from a timer (t notify)
"""


def _xdg(var: str, fallback: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / fallback)


def config_path() -> Path:
    return Path(os.environ.get("TEND_CONFIG") or _xdg("XDG_CONFIG_HOME", ".config") / "tend" / "config.toml")


def data_path() -> Path:
    return Path(os.environ.get("TEND_DB") or _xdg("XDG_DATA_HOME", ".local/share") / "tend" / "tend.db")


class ConfigError(Exception):
    """The config file can't be used. The message says where and why."""


def read_user() -> dict:
    """The user's config file as written, without defaults. Creates it on first run."""
    path = config_path()
    if not path.exists():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(TEMPLATE)
        except OSError:
            return {}
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from None
    except OSError as e:
        raise ConfigError(f"can't read {path}: {e.strerror}") from None


def merge(user: dict) -> dict:
    return {section: {**values, **user.get(section, {})} for section, values in DEFAULTS.items()}


def load() -> dict:
    cfg = merge(read_user())
    errors, _ = check(cfg, {})
    if errors:
        raise ConfigError(f"{config_path()}: {errors[0]}")
    return cfg


# ── checks ──────────────────────────────────────────────────────────────
def _time(value) -> time | None:
    try:
        return time.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def check(cfg: dict, user: dict) -> tuple[list[str], list[str]]:
    """(errors, warnings). Errors stop Tend; warnings are for `t doctor`."""
    errors, warnings = [], []

    for section, values in user.items():
        if section not in DEFAULTS:
            warnings.append(f"unknown section [{section}]")
            continue
        if isinstance(values, dict):
            for key in values:
                if key not in DEFAULTS[section]:
                    warnings.append(f"unknown setting {key} in [{section}]")

    for section, values in DEFAULTS.items():
        for key, default in values.items():
            value = cfg[section][key]
            if isinstance(default, bool):
                ok, want = isinstance(value, bool), "true or false"
            elif isinstance(default, (int, float)):
                ok, want = isinstance(value, (int, float)) and not isinstance(value, bool), "a number"
            else:
                ok, want = isinstance(value, type(default)), "a list" if isinstance(default, list) else "text in quotes"
            if not ok:
                errors.append(f"{key} in [{section}] should be {want}, not {value!r}")
    if errors:
        return errors, warnings

    def need(cond, msg):
        if not cond:
            errors.append(msg)

    f, p, sc = cfg["focus"], cfg["priority"], cfg["schedule"]
    need(f["default_mode"] in ("pomo", "flow", "box"), "default_mode in [focus] should be pomo, flow or box")
    for k in ("pomo_work", "pomo_break", "box_minutes"):
        need(f[k] > 0, f"{k} in [focus] should be more than 0")
    need(0 < f["flow_break_ratio"] <= 1, "flow_break_ratio in [focus] should be between 0 and 1")
    need(0 < p["hours_per_day"] <= 24, "hours_per_day in [priority] should be between 0 and 24")
    need(p["at_risk_slack_days"] >= 0, "at_risk_slack_days in [priority] can't be negative")
    need(p["max_started"] >= 1, "max_started in [priority] should be 1 or more")
    start, end = _time(sc["day_start"]), _time(sc["day_end"])
    need(start is not None, f"day_start in [schedule] should be a time like 09:00, not {sc['day_start']!r}")
    need(end is not None, f"day_end in [schedule] should be a time like 18:00, not {sc['day_end']!r}")
    if start and end:
        need(start < end, "day_start in [schedule] should be before day_end")
    days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    bad = [d for d in sc["work_days"] if not isinstance(d, str) or d.lower()[:3] not in days]
    not_days = f" (not {bad})" if bad else ""
    need(not bad and sc["work_days"], f"work_days in [schedule] should be day names like mon, tue{not_days}")
    need(sc["max_block"] >= 15, "max_block in [schedule] should be 15 minutes or more")
    need(sc["break_minutes"] >= 0, "break_minutes in [schedule] can't be negative")
    need(1 <= sc["horizon_days"] <= 90, "horizon_days in [schedule] should be between 1 and 90")
    need(all(isinstance(x, str) for x in cfg["calendar"]["ics"]), "ics in [calendar] should be a list of paths or URLs")
    need(cfg["review"]["every_days"] >= 1, "every_days in [review] should be 1 or more")
    for level in ("high", "low"):
        for span in cfg["energy"][level]:
            a, _, b = str(span).partition("-")
            ta, tb = _time(a.strip()), _time(b.strip())
            need(ta is not None and tb is not None and ta < tb,
                 f"{span!r} in {level} [energy] should look like \"09:00-12:00\"")
    need(cfg["slips"]["quiet_rollovers"] >= 0, "quiet_rollovers in [slips] can't be negative")
    need(cfg["ui"]["theme"] in ("dark", "light", "plain"), "theme in [ui] should be dark, light or plain")
    need(cfg["backup"]["keep_days"] >= 1, "keep_days in [backup] should be 1 or more")
    need(1 <= cfg["reminders"]["every_minutes"] <= 60, "every_minutes in [reminders] should be between 1 and 60")
    return errors, warnings
