"""Repeating tasks and reminders."""

import json
import os
import subprocess
import sys
from datetime import date, timedelta

import pytest

from tend.repeat import RuleError, parse

MON = date(2026, 9, 28)
WED = date(2026, 9, 30)


@pytest.mark.parametrize("rule,anchor,after,expected", [
    ("mon", MON, MON, date(2026, 10, 5)),          # done on the day
    ("mon", MON, WED, date(2026, 10, 5)),          # done late: next Monday, rhythm holds
    ("mon", MON, MON + timedelta(days=21), date(2026, 10, 26)),  # weeks late: still one copy
    ("mon,thu", MON, MON, date(2026, 10, 1)),
    ("weekday", MON, date(2026, 10, 2), date(2026, 10, 5)),      # Friday → Monday
    ("2w", MON, MON, date(2026, 10, 12)),
    ("2w", MON, date(2026, 10, 20), date(2026, 10, 26)),         # keeps the 2-week rhythm
    ("day", MON, WED, date(2026, 10, 1)),
    ("month", date(2026, 1, 31), date(2026, 1, 31), date(2026, 2, 28)),
    ("year", date(2024, 2, 29), date(2024, 2, 29), date(2025, 2, 28)),
    ("15th", MON, MON, date(2026, 10, 15)),
    ("31st", date(2026, 10, 31), date(2026, 10, 31), date(2026, 11, 30)),
    ("last", WED, WED, date(2026, 10, 31)),
])
def test_next_dates(rule, anchor, after, expected):
    assert parse(rule).next_after(anchor, after) == expected


def test_first_date_is_today_when_today_fits():
    assert parse("mon").first(MON) == MON
    assert parse("mon").first(WED) == date(2026, 10, 5)


@pytest.mark.parametrize("bad", ["fortnight", "0d", "32nd", "mo"])
def test_bad_rules(bad):
    with pytest.raises(RuleError):
        parse(bad)


def _t(tmp_path, *args, json_out=True):
    env = {**os.environ, "TEND_DB": str(tmp_path / "t.db"), "TEND_CONFIG": str(tmp_path / "c.toml"),
           "TEND_HOOKS": str(tmp_path / "hooks"), "COLUMNS": "100"}
    r = subprocess.run([sys.executable, "-m", "tend", *args] + (["--json"] if json_out else []),
                       env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout) if json_out and r.stdout.strip() else r.stdout


def test_done_creates_the_next_copy_and_undo_removes_it(tmp_path):
    today = date.today()
    t = _t(tmp_path, "water", "plants", "every:day")
    assert t["repeat"] == "day" and t["aim"] == today.isoformat()  # a date is added
    _t(tmp_path, "done", "1")
    tasks = _t(tmp_path, "ls")
    assert [(x["id"], x["aim"], x["series"]) for x in tasks] == [(2, (today + timedelta(days=1)).isoformat(), 1)]
    _t(tmp_path, "undo", json_out=False)
    assert [x["id"] for x in _t(tmp_path, "ls")] == [1]


def test_drop_once_skips_and_drop_stop_ends_the_series(tmp_path):
    _t(tmp_path, "stretch", "every:day")
    _t(tmp_path, "drop", "1", "--once", json_out=False)
    assert [x["id"] for x in _t(tmp_path, "ls")] == [2]
    _t(tmp_path, "drop", "2", "--stop", json_out=False)
    assert _t(tmp_path, "ls") == []


def test_due_date_repeats_as_a_due_date(tmp_path):
    friday = date.today() + timedelta(days=(4 - date.today().weekday()) % 7)
    _t(tmp_path, "rent", "due:fri", "every:fri")
    _t(tmp_path, "done", "1")
    nxt = _t(tmp_path, "ls")[0]
    assert nxt["due"] == (friday + timedelta(days=7)).isoformat() and nxt["aim"] is None


def test_repeat_feature_off_creates_no_copy(tmp_path):
    _t(tmp_path, "features", "off", "repeat", json_out=False)
    _t(tmp_path, "stretch", "every:day")
    _t(tmp_path, "done", "1")
    assert _t(tmp_path, "ls") == []


def test_notify_sends_each_reminder_once(tmp_path):
    (tmp_path / "c.toml").write_text('[schedule]\nday_start = "00:00"\nday_end = "23:59"\n')
    _t(tmp_path, "tax", "form", "due:tom", "e:3h")
    first = _t(tmp_path, "notify", "--dry-run")
    keys = {r["key"].split(":")[0] for r in first["reminders"]}
    assert keys == {"morning", "risk"}
    _t(tmp_path, "notify", json_out=False)  # sends and remembers
    assert _t(tmp_path, "notify", "--dry-run")["reminders"] == []


def test_notify_is_quiet_outside_the_working_day(tmp_path):
    (tmp_path / "c.toml").write_text('[schedule]\nday_start = "00:00"\nday_end = "00:01"\n')
    _t(tmp_path, "tax", "form", "due:tom")
    out = _t(tmp_path, "notify", json_out=False)
    assert "wait for later" in out


def test_systemd_units_point_at_t(monkeypatch):
    from tend import reminders
    monkeypatch.setenv("TEND_DB", "/data/tend.db")
    units = reminders.systemd_units(15)
    assert "OnCalendar=*:0/15" in units["tend-notify.timer"]
    service = units["tend-notify.service"]
    assert " notify" in service and 'Environment="TEND_DB=/data/tend.db"' in service
    assert "<integer>900</integer>" in reminders.launchd_plist(15)
