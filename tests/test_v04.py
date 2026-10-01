"""Schema migration, push tracking, date corrections, energy, hooks and plugins."""

import json
import os
import sqlite3
import stat
import subprocess
import sys
import time
from datetime import date, datetime, timedelta

from tend.calibrate import corrections, from_lateness
from tend.energy import allowed, at, parse as parse_windows, split
from tend.model import Task
from tend.plan import schedule
from tend.priority import rank
from tend.store import VERSION, Store

TODAY = date(2026, 9, 29)


def test_migration_adds_columns_and_backfills_from_events(tmp_path):
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT NOT NULL, goal TEXT, parent INTEGER,
            value INTEGER, size TEXT, estimate_min INTEGER, due TEXT, aim TEXT, start_after TEXT,
            status TEXT NOT NULL DEFAULT 'open', slips INTEGER NOT NULL DEFAULT 0, skip_date TEXT,
            created TEXT NOT NULL, done_at TEXT);
        CREATE TABLE events (id INTEGER PRIMARY KEY, ts TEXT NOT NULL, kind TEXT NOT NULL,
            summary TEXT, changes TEXT NOT NULL, undone INTEGER NOT NULL DEFAULT 0);
        INSERT INTO tasks (id, title, aim, created) VALUES (1, 'bike', '2026-09-28', '2026-09-20');
    """)
    history = [
        [{"table": "tasks", "id": 1, "before": None, "after": {"aim": "2026-09-25"}}],
        [{"table": "tasks", "id": 1, "before": {"aim": "2026-09-25"}, "after": {"aim": "2026-09-26"}}],
        [{"table": "tasks", "id": 1, "before": {"aim": "2026-09-26"}, "after": {"aim": "2026-09-28"}}],
    ]
    for i, ch in enumerate(history):
        con.execute("INSERT INTO events (ts, kind, changes) VALUES (?, 'edit', ?)", (f"2026-09-2{i}", json.dumps(ch)))
    con.commit()
    con.close()

    t = Store(db).task(1)
    assert (t.first_aim, t.aim, t.pushes) == (date(2026, 9, 25), date(2026, 9, 28), 2)
    assert Store(db).db.execute("PRAGMA user_version").fetchone()[0] == VERSION


def test_update_tracks_first_date_and_pushes(tmp_path):
    s = Store(tmp_path / "t.db")
    with s.event("add"):
        t = Task(None, "x", due=date(2026, 10, 1))
        s.insert(t)
    for new in (date(2026, 10, 3), date(2026, 10, 2), date(2026, 10, 9)):
        with s.event("edit"):
            t.due = new
            s.update(t)
    t = s.task(t.id)
    assert (t.first_due, t.pushes) == (date(2026, 10, 1), 2)  # moving earlier is not a push
    s.undo()
    assert s.task(t.id).pushes == 1


def test_lateness_model():
    assert from_lateness([3, 3, 2]).days == 0  # too few tasks
    assert from_lateness([3, 1, 2, 0, 5]).days == 2
    assert from_lateness([-2, -1, -3, 0, -1]).days == 0  # early is fine, never shifts later
    assert from_lateness([30] * 6).days == 7  # clamped
    assert from_lateness([]).median_late is None


def test_corrections_from_store(tmp_path):
    s = Store(tmp_path / "t.db")
    with s.event("seed"):
        for i in range(5):
            s.insert(Task(None, f"t{i}", aim=date(2026, 9, 1), status="done", done_at="2026-09-04T10:00:00"))
    c = corrections(s)
    assert (c.soft.days, c.soft.samples, c.hard.samples) == (3, 5, 0)
    assert c.pushes.dated == 5 and c.pushes.pushed == 0


def test_date_shift_moves_rule_1_earlier():
    t = Task(1, "report", created="2026-09-01", value=2, size="S", due=TODAY + timedelta(days=3))
    assert rank([t], today=TODAY)[0].rule == 3
    r = rank([t], today=TODAY, hard_shift=2)[0]
    assert r.rule == 1 and "2 day margin" in r.reason


def test_energy_windows():
    w = parse_windows({"high": ["09:00-12:00"], "low": ["14:00-16:00"]})
    assert at(w, datetime(2026, 9, 29, 10)) == "high" and at(w, datetime(2026, 9, 29, 13)) is None
    pieces = split(datetime(2026, 9, 29, 11), datetime(2026, 9, 29, 15), w)
    assert [p[2] for p in pieces] == ["high", None, "low"]
    assert not allowed("high", "low", w) and allowed("high", "high", w) and allowed("low", "high", w)
    assert allowed("high", None, {"high": [], "low": []})  # no windows: anything goes


def test_energy_in_rank_and_plan():
    hard = Task(1, "proof", created="2026-09-01", value=3, size="S", energy="high")
    easy = Task(2, "email", created="2026-09-02", value=1, size="S", energy="low")
    assert [r.task.id for r in rank([hard, easy], today=TODAY, energy_now="low")] == [2, 1]
    assert [r.task.id for r in rank([hard, easy], today=TODAY, energy_now="high")] == [1, 2]

    w = parse_windows({"high": ["11:00-12:00"], "low": []})
    plan = schedule([hard, easy], [], now=datetime(2026, 9, 29, 9), days=1, energy_windows=w)
    by_task = {b.task.id: b for b in plan.blocks}
    assert by_task[1].start.hour == 11  # waits for the high window
    assert by_task[2].start.hour == 9


def _run_t(tmp_path, *args, **kw):
    env = {**os.environ, "TEND_DB": str(tmp_path / "t.db"), "TEND_CONFIG": str(tmp_path / "config.toml"),
           "TEND_HOOKS": str(tmp_path / "hooks"), **kw.pop("env", {})}
    return subprocess.run([sys.executable, "-m", "tend", *args], env=env, capture_output=True, text=True, **kw)


def test_hooks_receive_json(tmp_path):
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    out = tmp_path / "hook.json"
    script = hooks / "on_done"
    script.write_text(f"#!/bin/sh\ncat > {out}\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    _run_t(tmp_path, "write", "report")
    _run_t(tmp_path, "done", "1")
    for _ in range(50):
        if out.exists() and out.read_text():
            break
        time.sleep(0.05)
    data = json.loads(out.read_text())
    assert data["event"] == "on_done" and data["task"]["title"] == "write report"


def test_plugins_run_from_path(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    plugin = bin_dir / "t-hello"
    plugin.write_text('#!/bin/sh\necho "hello $1 $TEND_DB"\n')
    plugin.chmod(plugin.stat().st_mode | stat.S_IEXEC)
    r = _run_t(tmp_path, "hello", "world", env={"PATH": f"{bin_dir}:{os.environ['PATH']}"})
    assert r.stdout.strip() == f"hello world {tmp_path / 't.db'}"
