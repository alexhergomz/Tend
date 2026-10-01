"""Backups, restore, export and import."""

import io
import json
import os
import sqlite3
import subprocess
import sys
from datetime import date

import pytest

from tend import backup, transfer
from tend.model import Task
from tend.store import Store

CFG = lambda folder: {"backup": {"keep_days": 3, "folder": str(folder)}}


def seeded(path) -> Store:
    s = Store(path)
    with s.event("seed"):
        parent = Task(None, "thesis chapter", goal="thesis", created="2026-09-01T10:00:00")
        s.insert(parent)
        s.insert(Task(None, "outline", parent=parent.id, created="2026-09-01T10:01:00", due=date(2026, 10, 1)))
    s.set_goal("thesis", 180, "finish the MSc")
    s.add_session(2, __import__("datetime").datetime(2026, 9, 2, 9), __import__("datetime").datetime(2026, 9, 2, 9, 25),
                  "pomo", 25)
    return s


def test_daily_backup_once_a_day_and_pruned(tmp_path):
    s = seeded(tmp_path / "t.db")
    cfg = CFG(tmp_path / "b")
    assert backup.daily(s.db, cfg, date.today()) is not None
    assert backup.daily(s.db, cfg, date.today()) is None  # already made today
    for _ in range(5):
        backup.make(s.db, cfg, "daily")
    assert len([c for c in backup.copies(cfg) if c.kind == "daily"]) == 3


def test_empty_database_is_not_backed_up(tmp_path):
    s = Store(tmp_path / "t.db")
    assert backup.daily(s.db, CFG(tmp_path / "b"), date.today()) is None


def test_restore_brings_old_data_back_and_saves_current(tmp_path):
    s = seeded(tmp_path / "t.db")
    cfg = CFG(tmp_path / "b")
    copy = backup.make(s.db, cfg)
    with s.event("add"):
        s.insert(Task(None, "added later"))
    before = backup.restore(s.db, cfg, copy)
    assert [t.title for t in s.tasks()] == ["thesis chapter", "outline"]
    assert sqlite3.connect(before).execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 3


def test_restore_refuses_a_damaged_file(tmp_path):
    s = seeded(tmp_path / "t.db")
    bad = tmp_path / "b" / "manual-2026-09-01T100000.db"
    bad.parent.mkdir()
    bad.write_bytes(b"not a database")
    with pytest.raises(ValueError):
        backup.restore(s.db, CFG(tmp_path / "b"), bad)
    assert len(s.tasks()) == 2


def test_export_then_import_into_empty_is_an_exact_copy(tmp_path):
    src = seeded(tmp_path / "a.db")
    buf = io.StringIO()
    transfer.export(src, buf)
    dst = Store(tmp_path / "b.db")
    header, data = transfer.read(io.StringIO(buf.getvalue()))
    transfer.replace_all(dst, header, data)
    for table in ("tasks", "goals", "sessions", "events"):
        q = f"SELECT * FROM {table} ORDER BY 1"
        assert [tuple(r) for r in src.db.execute(q)] == [tuple(r) for r in dst.db.execute(q)]


def test_import_adds_renumbers_and_skips_duplicates(tmp_path):
    src = seeded(tmp_path / "a.db")
    buf = io.StringIO()
    transfer.export(src, buf)
    dst = Store(tmp_path / "b.db")
    with dst.event("add"):
        dst.insert(Task(None, "already here"))
    _, data = transfer.read(io.StringIO(buf.getvalue()))
    counts = transfer.add(dst, data)
    assert counts == {"tasks": 2, "goals": 1, "sessions": 1, "skipped": 0}
    chapter = next(t for t in dst.tasks() if t.title == "thesis chapter")
    outline = next(t for t in dst.tasks() if t.title == "outline")
    assert chapter.id == 2 and outline.parent == chapter.id  # renumbered, link kept
    assert dst.db.execute("SELECT task_id FROM sessions").fetchone()[0] == outline.id
    assert transfer.add(dst, data)["skipped"] == 2  # same file again: nothing new


def test_newer_or_foreign_files_are_refused():
    with pytest.raises(transfer.TransferError, match="newer"):
        transfer.read(['{"format": "tend-export", "format_version": 1, "schema": 99}'])
    with pytest.raises(transfer.TransferError, match="not a Tend export"):
        transfer.read(['{"hello": 1}'])


def _t(tmp_path, *args, stdin=None):
    env = {**os.environ, "TEND_DB": str(tmp_path / "t.db"), "TEND_CONFIG": str(tmp_path / "c.toml"),
           "TEND_HOOKS": str(tmp_path / "hooks"), "COLUMNS": "100"}
    return subprocess.run([sys.executable, "-m", "tend", *args], env=env, capture_output=True,
                          encoding="utf-8", input=stdin)


def test_cli_round_trip(tmp_path):
    _t(tmp_path, "write", "report", "due:fri")
    out = _t(tmp_path, "export").stdout
    assert json.loads(out.splitlines()[0])["format"] == "tend-export"
    assert "t ▸" not in out  # nothing but data on stdout
    other = tmp_path / "other"
    other.mkdir()
    r = _t(other, "import", "-", stdin=out)
    assert r.returncode == 0 and "loaded 1 task," in r.stdout
    r = _t(other, "import", "-", "--replace", stdin=out)
    assert r.returncode == 1 and "--yes" in r.stdout  # replacing real data needs a yes
    r = _t(other, "restore", "--json")
    assert any(c["kind"] == "daily" for c in json.loads(r.stdout))


def test_undo_stops_at_an_import(tmp_path):
    _t(tmp_path, "first", "task")
    _t(tmp_path, "edit", "1", "v:3")
    other = tmp_path / "o"
    other.mkdir()
    _t(other, "x1")  # a task so the import adds instead of replacing
    _t(other, "import", "-", stdin=_t(tmp_path, "export").stdout)
    r = _t(other, "undo")
    assert r.returncode == 1 and "t restore" in r.stdout
    assert "x1" in _t(other, "ls").stdout  # the earlier add was not undone
