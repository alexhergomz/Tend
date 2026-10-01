"""`t doctor`: checks the setup and says how to fix each problem.

It doesn't need a working config or database, and it changes nothing.
"""

import os
import platform
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta

from . import __version__, config, features, fmt, hooks, registry
from .store import VERSION


@dataclass
class Check:
    level: str  # ok / warn / error / info
    area: str
    text: str
    fix: str = ""

    def to_json(self) -> dict:
        return {"level": self.level, "area": self.area, "text": self.text, "fix": self.fix}


_home = fmt.home


def run() -> list[Check]:
    out = [Check("ok", "tend", f"Tend {__version__} · Python {platform.python_version()} · {sys.platform}")]
    cfg = _config(out)
    _data(out)
    _backups(out, cfg)
    if features.enabled(cfg, "planning"):
        _calendars(out, cfg)
    if features.enabled(cfg, "hooks"):
        _hooks(out)
    if features.enabled(cfg, "plugins"):
        _plugins(out)
    if features.enabled(cfg, "reminders"):
        _reminders(out)
    return out


def _config(out: list[Check]) -> dict:
    path = config.config_path()
    try:
        user = config.read_user()
    except config.ConfigError as e:
        out.append(Check("error", "config", str(e), "fix the line it names; deleting the file restores the defaults"))
        return config.merge({})
    cfg = config.merge(user)
    errors, warnings = config.check(cfg, user)
    for e in errors:
        out.append(Check("error", "config", e, f"edit {_home(path)}"))
    for w in warnings:
        out.append(Check("warn", "config", w, "check the spelling, or remove it"))
    if not errors and not warnings:
        out.append(Check("ok", "config", _home(path)))
    return cfg if not errors else config.merge({})


def _data(out: list[Check]):
    path = config.data_path()
    if not path.exists():
        out.append(Check("info", "data", f"no database yet at {_home(path)}; it is made when you add a task"))
        return
    try:
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            out.append(Check("error", "data", "the database is damaged", "t restore lists copies to go back to"))
            return
        open_tasks = db.execute("SELECT COUNT(*) FROM tasks WHERE status = 'open'").fetchone()[0]
        orphans = db.execute("SELECT COUNT(*) FROM tasks WHERE parent IS NOT NULL "
                             "AND parent NOT IN (SELECT id FROM tasks)").fetchone()[0]
        db.close()
    except sqlite3.Error as e:
        out.append(Check("error", "data", f"can't read {_home(path)}: {e}", "t restore lists copies to go back to"))
        return
    if version > VERSION:
        out.append(Check("error", "data", f"made by a newer Tend (schema {version}, this one knows {VERSION})",
                         "update Tend"))
        return
    note = "" if version == VERSION else f" · will be updated from schema {version} on the next run"
    out.append(Check("ok", "data", f"{_home(path)} · {open_tasks} open tasks{note}"))
    if orphans:
        out.append(Check("warn", "data", f"{orphans} steps point to a task that no longer exists",
                         "harmless; t drop <id> removes them"))


def _backups(out: list[Check], cfg: dict):
    from . import backup

    folder = backup.folder(cfg)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        writable = os.access(folder, os.W_OK)
    except OSError:
        writable = False
    if not writable:
        out.append(Check("error", "backups", f"can't write to {_home(folder)}", "set folder in [backup], or fix the "
                                                                                "folder's permissions"))
        return
    copies = backup.copies(cfg)
    if not copies:
        out.append(Check("info", "backups", "no copies yet; one is made on the first run of each day"))
        return
    age = datetime.now() - copies[0].made
    level = "warn" if age > timedelta(days=3) and config.data_path().exists() else "ok"
    newest = "today" if age < timedelta(days=1) else f"{age.days} days ago"
    out.append(Check(level, "backups", f"{fmt.count(len(copies), 'copy', 'copies')} in "
                                       f"{_home(folder)}, newest {newest}"))


def _calendars(out: list[Check], cfg: dict):
    from . import ics

    start = datetime.combine(datetime.now().date(), datetime.min.time())
    for source in cfg["calendar"]["ics"]:
        text, warning = ics.fetch(source, config.data_path().parent / "calendars")
        if text is None:
            out.append(Check("error", "calendar", f"{_home(source)}: {warning}", "check the path or address"))
            continue
        events = ics.parse(text, start, start + timedelta(days=cfg["schedule"]["horizon_days"]))
        level = "warn" if warning else "ok"
        out.append(Check(level, "calendar", f"{_home(source)}: {len(events)} events coming up" +
                         (f" · {warning}" if warning else "")))


def _hooks(out: list[Check]):
    folder = hooks.hooks_dir()
    if not folder.exists():
        return
    for p in sorted(folder.iterdir()):
        name = p.name[:-2] if p.is_dir() and p.name.endswith(".d") else p.name
        if name not in hooks.EVENTS:
            out.append(Check("warn", "hooks", f"{p.name} is not an event, so it never runs",
                             f"rename it to one of: {', '.join(hooks.EVENTS)}"))
            continue
        for script in ([p] if p.is_file() else sorted(p.iterdir())):
            if script.is_file() and not os.access(script, os.X_OK):
                out.append(Check("warn", "hooks", f"{_home(script)} is not executable", f"chmod +x {script}"))
            elif script.is_file():
                out.append(Check("ok", "hooks", f"{name}: {_home(script)}"))


def _plugins(out: list[Check]):
    for name, path in hooks.list_plugins():
        if registry.find(name):
            out.append(Check("warn", "plugins", f"t-{name} has the name of a built-in command, so it never runs",
                             f"rename {path}"))
        else:
            out.append(Check("ok", "plugins", f"t {name}: {_home(path)}"))


def _reminders(out: list[Check]):
    from . import reminders

    sender = shutil.which("notify-send") or (platform.system() == "Darwin" and shutil.which("osascript"))
    if not sender:
        out.append(Check("warn", "reminders", "no notify-send or osascript, so reminders can't be shown",
                         "install libnotify (notify-send); hooks still get every reminder"))
    timer = reminders.launchd_path() if platform.system() == "Darwin" else \
        reminders.systemd_dir() / "tend-notify.timer"
    if timer.exists():
        out.append(Check("ok", "reminders", f"timer installed: {_home(timer)}"))
    else:
        out.append(Check("info", "reminders", "no timer installed, so reminders only come when you run t notify",
                         "t notify --install"))
