"""Databases made by every earlier release open in this one, with nothing lost.

The fixtures were made by running each release's own code (tests/fixtures/make_fixtures.py).
"""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from tend.store import VERSION, Store

FIXTURES = sorted((Path(__file__).parent / "fixtures").glob("tend-*.db"))


def rows(path) -> dict[int, dict]:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    out = {r["id"]: dict(r) for r in con.execute("SELECT * FROM tasks")}
    con.close()
    return out


def t(tmp_path, *args, stdin=None):
    env = {**os.environ, "TEND_DB": str(tmp_path / "tend.db"), "TEND_CONFIG": str(tmp_path / "c.toml"),
           "TEND_HOOKS": str(tmp_path / "hooks"), "COLUMNS": "100"}
    return subprocess.run([sys.executable, "-m", "tend", *args], env=env, capture_output=True, text=True, input=stdin)


def test_there_is_a_fixture_for_every_release():
    assert [f.stem for f in FIXTURES] == ["tend-0.1", "tend-0.3", "tend-0.5", "tend-0.6", "tend-0.7", "tend-0.8"]


@pytest.fixture(params=FIXTURES, ids=lambda p: p.stem)
def old_db(request, tmp_path):
    path = tmp_path / "tend.db"
    shutil.copy(request.param, path)
    return path


def test_migration_keeps_every_value(old_db):
    before = rows(old_db)
    Store(old_db)
    after = rows(old_db)
    assert sqlite3.connect(old_db).execute("PRAGMA user_version").fetchone()[0] == VERSION
    assert before.keys() == after.keys()
    for task_id, old in before.items():
        for column, value in old.items():
            assert after[task_id][column] == value, (task_id, column)


def test_history_is_rebuilt(old_db):
    Store(old_db)
    tasks = rows(old_db)
    reply = next(r for r in tasks.values() if r["title"] == "reply to professor")
    assert reply["pushes"] == 2 and reply["first_due"] < reply["due"]  # edited twice, later each time
    tax = next(r for r in tasks.values() if r["title"] == "tax form")
    assert tax["first_due"] == tax["due"] and tax["status"] == "done"
    experiments = next(r for r in tasks.values() if r["title"] == "run experiments")
    assert experiments["stage"] == "started"  # it had focus time (or was started)


def test_commands_work_on_old_data(old_db, tmp_path):
    queue = json.loads(t(tmp_path, "ls", "--json").stdout)
    assert {"outline", "draft first paragraph", "call the dentist"} <= {x["title"] for x in queue}
    assert t(tmp_path, "undo").returncode == 0  # undo through an event written by the old version
    assert t(tmp_path, "done", str(queue[0]["id"])).returncode == 0
    assert t(tmp_path, "stats", "--json").returncode == 0
    checks = json.loads(t(tmp_path, "doctor", "--json").stdout)
    assert not [c for c in checks if c["level"] == "error"]


def test_old_data_exports_and_imports_exactly(old_db, tmp_path):
    exported = t(tmp_path, "export").stdout
    other = tmp_path / "other"
    other.mkdir()
    assert t(other, "import", "-", stdin=exported).returncode == 0
    assert rows(old_db) == rows(other / "tend.db")
