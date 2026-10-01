"""Reminders: `t notify` checks once and sends what is new. A timer runs it.

It sends each reminder once:
  morning    the first task of the day, once a day after day_start
  at risk    a hard deadline that just became at risk (rule 1)
  missed     a hard deadline that just passed
  back       a waiting task that came back on its date

Outside the working day (schedule day_start..day_end) nothing is sent, and
reminders wait for the next run inside it. tend never runs in the background
itself: `t notify --install` sets up a systemd user timer or a launchd agent.
"""

import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from . import fmt

SENT_KEY = "reminders_sent"
KEEP_DAYS = 30


@dataclass
class Reminder:
    key: str  # unique, so each reminder is sent once
    title: str
    body: str
    task_id: int | None = None

    def to_json(self) -> dict:
        return {"key": self.key, "title": self.title, "body": self.body, "task_id": self.task_id}


def collect(app, now: datetime) -> list[Reminder]:
    today = now.date()
    ranked = app.ranked()
    out = []
    day_start, _ = app.schedule_times()
    if ranked and now.time() >= day_start:
        top = ranked[0]
        out.append(Reminder(f"morning:{today}", "Today starts with", f"{top.task.title} · {top.reason}", top.task.id))
    for r in ranked:
        t = r.task
        if r.rule == 1 and t.due >= today:
            out.append(Reminder(f"risk:{t.id}:{t.due}", "Deadline at risk",
                                f"{t.title} · due {fmt.day(t.due, today)}, {r.reason.split(' · ', 1)[-1]}", t.id))
        elif r.rule == 1:
            out.append(Reminder(f"missed:{t.id}:{t.due}", "Missed deadline",
                                f"{t.title} · was due {fmt.day(t.due, today)}. t resolve to decide.", t.id))
    for t in getattr(app, "woken", []):
        out.append(Reminder(f"back:{t.id}:{today}", "Back from waiting", t.title, t.id))
    return out


def in_working_day(app, now: datetime) -> bool:
    start, end = app.schedule_times()
    return start <= now.time() < end


def pending(app, now: datetime) -> list[Reminder]:
    sent = json.loads(app.store.get_meta(SENT_KEY) or "{}")
    return [r for r in collect(app, now) if r.key not in sent]


def mark_sent(app, reminders: list[Reminder], now: datetime):
    sent = json.loads(app.store.get_meta(SENT_KEY) or "{}")
    cutoff = (now - timedelta(days=KEEP_DAYS)).isoformat()
    sent = {k: v for k, v in sent.items() if v >= cutoff}
    for r in reminders:
        sent[r.key] = now.isoformat(timespec="seconds")
    app.store.set_meta(SENT_KEY, json.dumps(sent))


def send(title: str, body: str) -> bool:
    """A desktop notification. Returns False if this system has no way to show one."""
    try:
        if shutil.which("notify-send"):
            subprocess.run(["notify-send", "-a", "Tend", title, body], timeout=10, check=False)
            return True
        if platform.system() == "Darwin":
            script = f"display notification {json.dumps(body)} with title {json.dumps(title)}"
            subprocess.run(["osascript", "-e", script], timeout=10, check=False)
            return True
    except (OSError, subprocess.TimeoutExpired):
        pass
    return False


# ── timer ───────────────────────────────────────────────────────────────
def _command() -> list[str]:
    t = shutil.which("t") or shutil.which("tend")
    return [t, "notify"] if t else [sys.executable, "-m", "tend", "notify"]


def _env() -> dict[str, str]:
    keep = ("TEND_DB", "TEND_CONFIG", "TEND_HOOKS", "PATH")
    return {k: os.environ[k] for k in keep if k in os.environ}


def systemd_units(every: int) -> dict[str, str]:
    env = "".join(f'Environment="{k}={v}"\n' for k, v in _env().items())
    service = ("[Unit]\nDescription=Tend reminders\n\n[Service]\nType=oneshot\n"
               f"ExecStart={' '.join(_command())}\n{env}")
    timer = (f"[Unit]\nDescription=Run Tend reminders every {every} minutes\n\n[Timer]\n"
             f"OnCalendar=*:0/{every}\nPersistent=true\n\n[Install]\nWantedBy=timers.target\n")
    return {"tend-notify.service": service, "tend-notify.timer": timer}


def launchd_plist(every: int) -> str:
    args = "".join(f"<string>{a}</string>" for a in _command())
    env = "".join(f"<key>{k}</key><string>{v}</string>" for k, v in _env().items())
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0"><dict>'
            f"<key>Label</key><string>{LAUNCHD_LABEL}</string>"
            f"<key>ProgramArguments</key><array>{args}</array>"
            f"<key>EnvironmentVariables</key><dict>{env}</dict>"
            f"<key>StartInterval</key><integer>{every * 60}</integer>"
            "<key>RunAtLoad</key><true/></dict></plist>\n")


LAUNCHD_LABEL = "com.github.tend.notify"


def systemd_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "systemd" / "user"


def launchd_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def install(every: int) -> list[str]:
    """Write and start the timer. Returns what was done, one line each."""
    done = []
    if platform.system() == "Darwin":
        path = launchd_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(launchd_plist(every))
        done.append(f"wrote {path}")
        subprocess.run(["launchctl", "unload", str(path)], capture_output=True)
        subprocess.run(["launchctl", "load", "-w", str(path)], check=True)
        done.append("started it with launchctl")
        return done
    if not shutil.which("systemctl"):
        raise RuntimeError("no systemd or launchd here. Run `t notify` from cron instead, "
                           f"for example: */{every} * * * * {' '.join(_command())}")
    folder = systemd_dir()
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in systemd_units(every).items():
        (folder / name).write_text(text)
        done.append(f"wrote {folder / name}")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", "tend-notify.timer"], check=True)
    done.append("started tend-notify.timer with systemctl --user")
    return done


def uninstall() -> list[str]:
    done = []
    if platform.system() == "Darwin":
        path = launchd_path()
        if path.exists():
            subprocess.run(["launchctl", "unload", "-w", str(path)], capture_output=True)
            path.unlink()
            done.append(f"removed {path}")
        return done
    if shutil.which("systemctl"):
        subprocess.run(["systemctl", "--user", "disable", "--now", "tend-notify.timer"], capture_output=True)
    for name in ("tend-notify.service", "tend-notify.timer"):
        p = systemd_dir() / name
        if p.exists():
            p.unlink()
            done.append(f"removed {p}")
    if done and shutil.which("systemctl"):
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    return done
