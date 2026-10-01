"""Record demo sessions of the real `t` command as asciinema casts.

Usage: docs/demo/render.sh   (needs `t` installed, agg and ffmpeg)
"""

import fcntl
import json
import os
import pty
import random
import select
import sqlite3
import struct
import subprocess
import sys
import termios
import time
from datetime import date, datetime, timedelta
from pathlib import Path

COLS, ROWS = 84, 22
OUT = Path(sys.argv[1])
DB = OUT / "demo.db"
ENV = {
    **os.environ,
    "TEND_DB": str(DB),
    "TEND_CONFIG": str(OUT / "config.toml"),
    "TERM": "xterm-256color",
    "COLUMNS": str(COLS),
    "LINES": str(ROWS),
    "PATH": f"{Path(__file__).resolve().parents[2] / 'examples' / 'plugins'}{os.pathsep}{os.environ['PATH']}",
}
PROMPT = "\x1b[36m~\x1b[0m \x1b[1m$\x1b[0m "
random.seed(4)


def t(*args):
    subprocess.run(["t", *args], env=ENV, stdout=subprocess.DEVNULL, check=True)


def sql(query, *params):
    db = sqlite3.connect(DB)
    db.execute(query, params)
    db.commit()


def write_calendar():
    """A small calendar: lectures on Tue and Thu, a meeting tomorrow, a call on Friday."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    def dt(d, h, m=0):
        return f"{d:%Y%m%d}T{h:02d}{m:02d}00"
    tomorrow, friday = today + timedelta(days=1), monday + timedelta(days=4)
    events = [
        ("Lecture", dt(monday + timedelta(days=1), 10), dt(monday + timedelta(days=1), 11, 30), "RRULE:FREQ=WEEKLY;BYDAY=TU,TH"),
        ("Team meeting", dt(tomorrow, 14), dt(tomorrow, 15), None),
        ("Call with supervisor", dt(friday, 12), dt(friday, 12, 45), None),
    ]
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0"]
    for i, (title, start, end, rrule) in enumerate(events):
        lines += ["BEGIN:VEVENT", f"UID:demo-{i}", f"SUMMARY:{title}", f"DTSTART:{start}", f"DTEND:{end}"]
        lines += [rrule] if rrule else []
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    (OUT / "demo.ics").write_text("\r\n".join(lines))


def seed(config=""):
    DB.unlink(missing_ok=True)
    write_calendar()
    (OUT / "config.toml").write_text(f'[calendar]\nics = ["{OUT / "demo.ics"}"]\n' + config)
    for task in [
        "tax form due:tom e:2h v:2",
        "write ch.2 intro +thesis v:3 s:M",
        "run ablation experiments +thesis v:3 s:L due:+12d",
        "reply to professor due:+5d v:2 s:S",
        "portfolio site v:3 s:M",
        "fix bike v:1 s:S",
        "30 min walk +health v:2 s:S",
    ]:
        t(*task.split())
    t("g", "add", "thesis", "3h", "finish", "the", "MSc")
    t("g", "add", "health", "2h")
    start = datetime.now() - timedelta(days=1, hours=3)
    sql("INSERT INTO sessions (task_id, start, end, mode, minutes) VALUES (2, ?, ?, 'pomo', 50)",
        start.isoformat(timespec="seconds"), (start + timedelta(minutes=50)).isoformat(timespec="seconds"))
    # five finished tasks that took about 1.3x their estimate, so calibration has data
    for i, (size, actual) in enumerate([("S", 40), ("S", 35), ("M", 150), ("M", 170), ("S", 45)]):
        done_at = (datetime.now() - timedelta(days=3 + i)).isoformat(timespec="seconds")
        first_aim = (datetime.now() - timedelta(days=5 + i + i % 3)).date().isoformat()  # done 2-4 days late
        sql("INSERT INTO tasks (title, value, size, status, created, done_at, aim, first_aim, pushes) "
            "VALUES (?, 2, ?, 'done', ?, ?, ?, ?, ?)", f"old task {i}", size, done_at, done_at,
            done_at[:10], first_aim, i % 3)
        sql("INSERT INTO sessions (task_id, start, end, mode, minutes) VALUES "
            "((SELECT MAX(id) FROM tasks), ?, ?, 'pomo', ?)", done_at, done_at, actual)
    sql("INSERT OR REPLACE INTO meta (key, value) VALUES ('last_review', ?)", (date.today() - timedelta(days=8)).isoformat())


class Cast:
    def __init__(self, name, rows=ROWS):
        self.name, self.rows, self.now, self.events = name, rows, 0.0, []

    def out(self, text):
        self.events.append([round(self.now, 3), "o", text])

    def wait(self, seconds):
        self.now += seconds

    def prompt(self, command=None):
        if self.events:
            self.out("\r\n")
        self.out(PROMPT)
        if command is None:
            return
        self.wait(0.6)
        for ch in command:
            self.out(ch)
            self.wait(random.uniform(0.03, 0.09))
        self.wait(0.4)
        self.out("\r\n")

    def run(self, command, keys=(), after=1.8, speed=1.0):
        """Type `command`, run it in a pty, send keys as (delay, text) pairs."""
        self.prompt(command)
        pid, fd = pty.fork()
        if pid == 0:
            os.execvpe("sh", ["sh", "-c", command], ENV)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", self.rows, COLS, 0, 0))
        base, started = self.now, time.monotonic()
        queue = list(keys)
        next_at = started + (queue[0][0] if queue else 0)
        while True:
            timeout = max(0, next_at - time.monotonic()) if queue else 0.5
            ready, _, _ = select.select([fd], [], [], timeout)
            if ready:
                try:
                    data = os.read(fd, 65536)
                except OSError:
                    break
                if not data:
                    break
                self.now = base + (time.monotonic() - started) / speed
                self.out(data.decode(errors="ignore"))
            if queue and time.monotonic() >= next_at:
                os.write(fd, queue.pop(0)[1].encode())
                if queue:
                    next_at = time.monotonic() + queue[0][0]
        os.waitpid(pid, 0)
        self.now = base + (time.monotonic() - started) / speed
        self.wait(after)

    def save(self):
        self.prompt()
        self.wait(2)
        self.out("")
        header = {"version": 2, "width": COLS, "height": self.rows, "env": {"TERM": "xterm-256color"}}
        with open(OUT / f"{self.name}.cast", "w") as f:
            f.write(json.dumps(header) + "\n")
            for e in self.events:
                f.write(json.dumps(e) + "\n")


def typed(text, pause=0.12):
    return [(pause, ch) for ch in text]


# ── sessions ─────────────────────────────────────────────────────────────
def capture():
    seed()
    c = Cast("capture", rows=16)
    c.run("t call the dentist")
    c.run("t write ch.3 outline +thesis due:fri v:3 e:2h")
    c.run("t next", after=3)
    c.save()


def interactive():
    seed()
    c = Cast("interactive", rows=14)
    c.run("t", keys=[(3.0, "d"), (3.0, "s"), (2.5, "l"), (4.5, " "), (2.0, "q")], after=0.5)
    c.save()


def triage():
    seed()
    for task in ("call the dentist", "buy usb cables", "renew passport"):
        t(task)
    c = Cast("triage", rows=20)
    c.run("t triage", keys=[
        (2.0, "2"), (1.0, "s"), *typed("fri"), (0.6, "\r"), (1.0, "\r"),
        (1.5, "1"), (1.0, "s"), (1.2, "\r"), (1.0, "\r"),
        (1.5, "3"), (1.0, "m"), *typed("oct30"), (0.6, "\r"), (1.0, "\r"),
    ], after=3)
    c.save()


def focus():
    seed("[focus]\npomo_work = 1\npomo_break = 0.5\n")
    c = Cast("focus", rows=12)
    # timer shortened to 1 min + 30 s break, then played back 4x faster
    c.run("t focus 2", keys=[(96, "d")], after=3, speed=4)
    c.save()


def resolve():
    seed()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    sql("UPDATE tasks SET aim = ?, slips = 2 WHERE id = 6", yesterday)
    sql("UPDATE tasks SET due = ? WHERE id = 4", (date.today() - timedelta(days=2)).isoformat())
    c = Cast("resolve", rows=18)
    c.run("t resolve", keys=[(2.5, "r"), *typed("fri"), (0.8, "\r"), (2.5, "k")], after=3)
    c.save()


def planning():
    seed()
    c = Cast("plan", rows=24)
    c.run("t plan", after=2)
    c.save()
    c = Cast("gantt", rows=22)
    c.run("t gantt", after=2)
    c.save()


def review():
    seed()
    t("call the dentist")
    t("g", "add", "reading", "1h")
    c = Cast("review", rows=30)
    c.run("t review", keys=[(3.0, "y"), (1.5, "2"), (1.0, "s"), (1.0, "\r"), (1.2, "\r"),
                            *typed("read chapter 1 of Deep Work"), (0.8, "\r")], after=3)
    c.save()


def stats():
    seed()
    for when in ("tom", "+3d", "+6d"):  # fix bike keeps moving later
        t("e", "6", f"aim:{when}")
    c = Cast("stats", rows=20)
    c.run("t stats", after=2)
    c.save()
    c = Cast("plugins", rows=9)
    c.run("t pushed", after=2)
    c.save()


def states():
    seed()
    c = Cast("states", rows=30)
    c.run("t start 2", after=1.5)
    c.run("t wait 4 mon", after=1.5)
    c.run("t ls", after=4)
    c.save()


def queue():
    seed()
    t("call the dentist")
    c = Cast("queue", rows=25)
    c.run("t ls", after=2)
    c.save()


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    only = sys.argv[2:]
    for fn in (capture, interactive, triage, focus, resolve, planning, review, stats, states, queue):
        if not only or fn.__name__ in only:
            print("recording", fn.__name__, flush=True)
            fn()
