"""Task states: todo, started, waiting, done, dropped."""

import json
import os
import subprocess
import sys
from datetime import date, timedelta

from tend.model import Task
from tend.priority import rank
from tend.slips import wake_waiting
from tend.store import Store

TODAY = date(2026, 9, 30)


def task(id, title, **kw):
    return Task(id=id, title=title, created="2026-09-01", value=2, size="S", **kw)


def test_started_wins_ties_and_waiting_leaves_the_queue():
    tasks = [task(1, "old"), task(2, "started", stage="started"), task(3, "on hold", stage="waiting"),
             task(4, "on hold until tomorrow", stage="waiting", start_after=TODAY + timedelta(days=1))]
    assert [r.task.id for r in rank(tasks, today=TODAY)] == [2, 1]
    # on the date, a dated waiting task is back in the queue
    assert 4 in [r.task.id for r in rank(tasks, today=TODAY + timedelta(days=1))]


def test_waiting_with_a_date_comes_back_as_todo(tmp_path):
    s = Store(tmp_path / "t.db")
    with s.event("seed"):
        a = Task(None, "reply", stage="waiting", start_after=TODAY)
        b = Task(None, "later", stage="waiting", start_after=TODAY + timedelta(days=3))
        c = Task(None, "no date", stage="waiting")
        for t in (a, b, c):
            s.insert(t)
    wake_waiting(s, TODAY)
    assert [(t.stage, t.start_after) for t in s.tasks()] == [
        ("todo", None), ("waiting", TODAY + timedelta(days=3)), ("waiting", None)]


def test_state_property():
    assert task(1, "x").state == "todo"
    assert task(1, "x", stage="started", status="done").state == "done"


def _t(tmp_path, *args):
    env = {**os.environ, "TEND_DB": str(tmp_path / "t.db"), "TEND_CONFIG": str(tmp_path / "c.toml"),
           "TEND_HOOKS": str(tmp_path / "hooks")}
    r = subprocess.run([sys.executable, "-m", "tend", *args, "--json"], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout) if r.stdout.strip() else None


def test_cli_status_flow(tmp_path):
    _t(tmp_path, "write", "report")
    t = _t(tmp_path, "start", "1")
    assert t["stage"] == "started" and t["started_at"]
    t = _t(tmp_path, "wait", "1", "+2d")
    assert t["stage"] == "waiting" and t["start_after"] == (date.today() + timedelta(days=2)).isoformat()
    assert _t(tmp_path, "ls") == []  # waiting tasks leave the queue
    t = _t(tmp_path, "status", "1", "todo")
    assert t["stage"] == "todo" and t["start_after"] is None
    t = _t(tmp_path, "status", "1", "done")
    assert t["status"] == "done"


def test_starting_a_step_starts_its_parent(tmp_path):
    _t(tmp_path, "thesis", "chapter")
    subprocess.run([sys.executable, "-m", "tend", "split", "1", "outline", "draft"],
                   env={**os.environ, "TEND_DB": str(tmp_path / "t.db"), "TEND_CONFIG": str(tmp_path / "c.toml")},
                   capture_output=True)
    _t(tmp_path, "start", "2")
    assert Store(tmp_path / "t.db").task(1).stage == "started"


def test_migration_marks_tasks_with_focus_time_as_started(tmp_path):
    import sqlite3
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT NOT NULL, goal TEXT, parent INTEGER,
            value INTEGER, size TEXT, estimate_min INTEGER, due TEXT, aim TEXT, start_after TEXT,
            status TEXT NOT NULL DEFAULT 'open', slips INTEGER NOT NULL DEFAULT 0, skip_date TEXT,
            created TEXT NOT NULL, done_at TEXT, energy TEXT, first_due TEXT, first_aim TEXT,
            pushes INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE sessions (id INTEGER PRIMARY KEY, task_id INTEGER, start TEXT NOT NULL,
            end TEXT NOT NULL, mode TEXT NOT NULL, minutes REAL NOT NULL);
        INSERT INTO tasks (id, title, created) VALUES (1, 'worked on', '2026-09-01'), (2, 'not yet', '2026-09-01');
        INSERT INTO sessions (task_id, start, end, mode, minutes) VALUES (1, '2026-09-20T10:00:00', '2026-09-20T10:25:00', 'pomo', 25);
    """)
    con.commit()
    con.close()
    s = Store(db)
    assert (s.task(1).stage, s.task(1).started_at) == ("started", "2026-09-20T10:00:00")
    assert s.task(2).stage == "todo"


def test_footer_trims_from_the_end_but_keeps_help(monkeypatch):
    from tend import ui
    monkeypatch.setattr(ui.console, "width", 40)  # property setter on rich Console
    with ui.console.capture() as cap:
        ui.footer(["f", "d", "r", "b", "s", "x", "h", "a", "?"])
    line = cap.get().splitlines()[-1]
    assert "f focus" in line and "r resolve" in line and "? help" in line and "a add" not in line


def test_waiting_task_returns_when_its_deadline_is_at_risk():
    t = task(1, "reply", stage="waiting", due=TODAY + timedelta(days=1))
    r = rank([t], today=TODAY)
    assert r[0].rule == 1 and "marked waiting" in r[0].reason
    calm = task(2, "reply", stage="waiting", due=TODAY + timedelta(days=9))
    assert rank([calm], today=TODAY) == []
