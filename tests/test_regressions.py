"""Bugs found in the review before 1.0. Each test is the scenario that showed the bug."""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from tend.ics import parse as parse_ics
from tend.parse import ParseError, parse_date

TOMORROW = (date.today() + timedelta(days=1)).isoformat()


def t(tmp_path, *args, stdin=None):
    env = {**os.environ, "TEND_DB": str(tmp_path / "t.db"), "TEND_CONFIG": str(tmp_path / "c.toml"),
           "TEND_HOOKS": str(tmp_path / "hooks"), "COLUMNS": "100"}
    return subprocess.run([sys.executable, "-m", "tend", *args], env=env, capture_output=True,
                          encoding="utf-8", input=stdin)


def queue(tmp_path) -> list[dict]:
    return json.loads(t(tmp_path, "ls", "--json").stdout)


def row(tmp_path, task_id: int) -> dict:
    con = sqlite3.connect(tmp_path / "t.db")
    con.row_factory = sqlite3.Row
    return dict(con.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone())


# 1. a waiting date or after: date hid a deadline at risk
def test_a_hidden_task_comes_back_when_its_deadline_is_at_risk(tmp_path):
    t(tmp_path, "pay", "rent", "due:tom", "v:3", "s:S")
    t(tmp_path, "wait", "1", "+20d")
    t(tmp_path, "renew", "visa", "due:tom", "after:+10d", "v:3", "s:S")
    q = {x["id"]: x for x in queue(tmp_path)}
    assert q[1]["rule"] == 1 and "marked waiting" in q[1]["reason"]
    assert q[2]["rule"] == 1 and "was hidden until" in q[2]["reason"]
    assert "2 deadlines at risk" in t(tmp_path, "next").stdout


# 2. the deadline of a split task didn't reach its steps
def test_steps_get_the_deadline_of_the_task_they_came_from(tmp_path):
    t(tmp_path, "report", "v:2", "s:L")
    t(tmp_path, "split", "1", "outline", "write")
    t(tmp_path, "other", "v:3", "s:S")
    t(tmp_path, "edit", "1", "due:tom")
    q = queue(tmp_path)
    steps = [x for x in q if x["parent"] == 1]
    assert len(steps) == 2 and all(x["rule"] == 1 and x["deadline"] == TOMORROW for x in steps)
    assert "deadline of #1 report" in steps[0]["reason"]
    assert "2 deadlines at risk" in t(tmp_path, "next").stdout
    late = json.loads(t(tmp_path, "plan", "--json").stdout)["late"]
    assert all(x["due"] == TOMORROW for x in late)


# 3. turning a feature off and changing a task erased its fields
def test_features_that_are_off_never_erase_data(tmp_path):
    t(tmp_path, "water", "every:mon", "v:2", "s:S", "@low")
    t(tmp_path, "call", "landlord", "v:1", "s:L")
    t(tmp_path, "wait", "2", "+3d")
    t(tmp_path, "features", "off", "repeat", "energy", "states")
    t(tmp_path, "skip")
    t(tmp_path, "edit", "2", "v:2")
    t(tmp_path, "features", "on", "repeat", "energy", "states")
    assert (row(tmp_path, 1)["repeat"], row(tmp_path, 1)["energy"]) == ("mon", "low")
    assert row(tmp_path, 2)["stage"] == "waiting"


# 4. resolve wrote a stale task back after its parent was dropped
def test_resolve_does_not_reopen_a_dropped_step(tmp_path, monkeypatch):
    t(tmp_path, "report", "due:2026-01-05", "v:2", "s:L")
    t(tmp_path, "split", "1", "outline due:2026-01-05")
    monkeypatch.setenv("TEND_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("TEND_CONFIG", str(tmp_path / "c.toml"))
    from tend import ui
    from tend.app import App
    from tend.commands.deciding import cmd_resolve

    answers = iter(["k", "n"])
    monkeypatch.setattr(ui, "choose", lambda *a, **k: next(answers))
    app = App()
    app.store.db.execute("UPDATE tasks SET due = '2026-01-05' WHERE id IN (1, 2)")  # both slipped
    app.store.db.commit()
    app.store.changed()
    cmd_resolve(app, [])
    assert row(tmp_path, 1)["status"] == "dropped" and row(tmp_path, 2)["status"] == "dropped"


# 5. restoring an old copy deleted it first; 10. a pre-1.0 copy crashed after restoring
def test_restore_the_oldest_copy_and_an_old_format_copy(tmp_path):
    t(tmp_path, "something")
    backups = tmp_path / "backups"
    backups.mkdir(exist_ok=True)
    for i in range(5):
        shutil.copy(tmp_path / "t.db", backups / f"before-2026-09-0{i + 1}T100000.db")
    shutil.copy(Path(__file__).parent / "fixtures" / "tend-0.1.db", backups / "before-2026-08-01T100000.db")
    copies = json.loads(t(tmp_path, "restore", "--json").stdout)
    oldest = copies[-1]
    assert oldest["path"].endswith("before-2026-08-01T100000.db")  # pruned first, before the fix
    r = t(tmp_path, "restore", str(oldest["n"]), "--yes")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "call the dentist" in {x["title"] for x in queue(tmp_path)}  # the 0.1 copy, migrated


# 6. undo through an old snapshot lost migrated history
def test_undo_keeps_history_added_by_a_migration(tmp_path):
    shutil.copy(Path(__file__).parent / "fixtures" / "tend-0.1.db", tmp_path / "t.db")
    t(tmp_path, "ls")
    before = row(tmp_path, 4)
    assert before["pushes"] == 2
    t(tmp_path, "undo")  # the skip
    t(tmp_path, "undo")  # the second date change of task 4
    after = row(tmp_path, 4)
    assert after["first_due"] == before["first_due"] and after["pushes"] == 2


# 7. undoing an added task left its focus sessions behind for a new task with the same id
def test_undo_removes_the_focus_time_of_an_undone_task(tmp_path):
    t(tmp_path, "big", "task")
    t(tmp_path, "split", "1", "step a")
    con = sqlite3.connect(tmp_path / "t.db")
    con.execute("INSERT INTO sessions (task_id, start, end, mode, minutes) VALUES (2, '2026-09-01T10:00:00', "
                "'2026-09-01T11:30:00', 'flow', 90)")
    con.commit()
    t(tmp_path, "undo")
    t(tmp_path, "unrelated", "new", "task")
    assert sqlite3.connect(tmp_path / "t.db").execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


# 8. import kept the old series number
def test_import_remaps_series(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    t(src, "water", "every:day", "v:2", "s:S")
    t(src, "done", "1")
    dst = tmp_path / "dst"
    dst.mkdir()
    for title in ("x1", "x2", "x3"):
        t(dst, title)
    t(dst, "import", "-", stdin=t(src, "export").stdout)
    rows = {r[0]: r for r in sqlite3.connect(dst / "t.db").execute("SELECT id, title, series FROM tasks")}
    water = [r for r in rows.values() if r[1] == "water"]
    first = min(r[0] for r in water)
    assert {r[2] for r in water if r[0] != first} == {first}


# 9. monthly repeats drifted to the 28th after February
def test_month_end_repeats_keep_their_day(tmp_path):
    t(tmp_path, "rent", "due:2027-01-31", "every:month", "v:3", "s:S")
    t(tmp_path, "done", "1")
    t(tmp_path, "done", "2")
    assert row(tmp_path, 2)["due"] == "2027-02-28" and row(tmp_path, 3)["due"] == "2027-03-31"


# 11. tracebacks on unusual input
@pytest.mark.parametrize("args", [["foo", "due:0th"], ["foo", "due:32nd"], ["foo", "e:99999999999999999999h"],
                                  ["export", "/nonexistent/folder/x.jsonl"]])
def test_bad_input_gives_a_message_not_a_traceback(tmp_path, args):
    r = t(tmp_path, *args)
    assert r.returncode == 1 and "Traceback" not in r.stderr and r.stdout.strip()


def test_one_broken_calendar_event_is_skipped():
    start, end = datetime(2026, 9, 28), datetime(2026, 10, 12)
    text = ("BEGIN:VEVENT\nDTSTART:2026100\nEND:VEVENT\n"
            "BEGIN:VEVENT\nDTSTART;TZID=Europe/Madrid:20260929T100000\nDTEND:20260929T110000\nEND:VEVENT\n"
            "BEGIN:VEVENT\nSUMMARY:Fine\nDTSTART:20260930T100000\nDTEND:20260930T110000\nEND:VEVENT\n")
    assert "Fine" in [e.title for e in parse_ics(text, start, end)]


def test_floating_repeat_until_includes_its_last_day():
    text = ("BEGIN:VEVENT\nSUMMARY:Daily\nDTSTART:20261005T090000\nDTEND:20261005T100000\n"
            "RRULE:FREQ=DAILY;UNTIL=20261007\nEND:VEVENT\n")
    days = [e.start.day for e in parse_ics(text, datetime(2026, 10, 1), datetime(2026, 10, 31))]
    assert days == [5, 6, 7]


def test_feb29_is_the_next_one_that_exists():
    assert parse_date("feb29", date(2028, 3, 1)) == date(2032, 2, 29)
    with pytest.raises(ParseError):
        parse_date("31st", date(2026, 9, 1)) and parse_date("feb30", date(2026, 1, 1))


def test_back_from_waiting_reminder_survives_another_run(tmp_path):
    (tmp_path / "c.toml").write_text('[schedule]\nday_start = "00:00"\nday_end = "23:59"\n', encoding="utf-8")
    t(tmp_path, "reply", "from", "bank")
    t(tmp_path, "wait", "1", "+1d")
    con = sqlite3.connect(tmp_path / "t.db")
    con.execute("UPDATE tasks SET start_after = ? WHERE id = 1", (date.today().isoformat(),))
    con.commit()
    t(tmp_path, "ls")  # this run wakes the task
    pending = json.loads(t(tmp_path, "notify", "--json").stdout)["reminders"]
    assert any(r["key"].startswith("back:1:") for r in pending)
