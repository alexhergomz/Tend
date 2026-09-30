"""Hooks: executable files in ~/.config/tend/hooks/ that run after an event.

A hook is named after its event (for example `on_done`), or placed in a folder
named after it (`on_done.d/`). It gets the event as JSON on stdin and runs in
the background, so it can never slow tend down or change what tend does. Output
goes to hooks.log next to the database.

Events: on_add, on_done, on_drop, on_skip, on_focus_start, on_focus_end,
on_review, and on_change, which runs for every change with before/after rows.
"""

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

from . import __version__, config

EVENTS = ("on_add", "on_done", "on_drop", "on_skip", "on_focus_start", "on_focus_end", "on_review", "on_change")
_running: list[subprocess.Popen] = []


def hooks_dir() -> Path:
    return Path(os.environ.get("TEND_HOOKS") or config.config_path().parent / "hooks")


def plugin_env() -> dict:
    """Environment for hooks and plugins: where the data lives."""
    return {
        **os.environ,
        "TEND_DB": str(config.data_path()),
        "TEND_CONFIG": str(config.config_path()),
        "TEND_VERSION": __version__,
    }


def scripts(event: str) -> list[Path]:
    base = hooks_dir()
    found = [base / event] + sorted((base / f"{event}.d").glob("*"))
    return [p for p in found if p.is_file() and os.access(p, os.X_OK)]


def fire(event: str, payload: dict):
    targets = scripts(event)
    if not targets:
        return
    for p in _running[:]:
        if p.poll() is not None:
            _running.remove(p)
    data = json.dumps({"event": event, "time": datetime.now().isoformat(timespec="seconds"), **payload},
                      default=str).encode()
    log_path = config.data_path().parent / "hooks.log"
    with open(log_path, "ab") as log:
        for script in targets:
            try:
                proc = subprocess.Popen([str(script)], stdin=subprocess.PIPE, stdout=log, stderr=log,
                                        env=plugin_env(), start_new_session=True)
                proc.stdin.write(data)
                proc.stdin.close()
                _running.append(proc)
            except OSError as e:
                log.write(f"{datetime.now():%F %T} {script}: {e}\n".encode())


def find_plugin(name: str) -> str | None:
    import re
    import shutil
    if not re.fullmatch(r"[a-z][a-z0-9_-]*", name):
        return None
    return shutil.which(f"t-{name}")


def list_plugins() -> list[tuple[str, str]]:
    seen, out = set(), []
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        try:
            entries = sorted(Path(folder).glob("t-*"))
        except OSError:
            continue
        for p in entries:
            name = p.name[2:]
            if name not in seen and p.is_file() and os.access(p, os.X_OK):
                seen.add(name)
                out.append((name, str(p)))
    return out
