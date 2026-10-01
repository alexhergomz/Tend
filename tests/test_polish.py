"""0.9: doctor, completion, themes, help, version, config errors, speed."""

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import date, timedelta

import pytest

from tend import __version__


def run(tmp_path, *args, extra_env=None, stdin=None):
    env = {**os.environ, "TEND_DB": str(tmp_path / "t.db"), "TEND_CONFIG": str(tmp_path / "c.toml"),
           "TEND_HOOKS": str(tmp_path / "hooks"), "COLUMNS": "100", **(extra_env or {})}
    return subprocess.run([sys.executable, "-m", "tend", *args], env=env, capture_output=True, text=True, input=stdin)


# ── doctor ──────────────────────────────────────────────────────────────
def test_doctor_on_a_healthy_setup(tmp_path):
    run(tmp_path, "write", "report")
    r = run(tmp_path, "doctor", "--json")
    checks = json.loads(r.stdout)
    assert r.returncode == 0
    assert {c["area"] for c in checks} >= {"tend", "config", "data", "backups"}
    assert not [c for c in checks if c["level"] == "error"]


def test_doctor_finds_problems_and_still_runs_with_a_broken_config(tmp_path):
    (tmp_path / "c.toml").write_text('[ui]\ncolour = 1\n[schedule]\nday_start = "9am"\n')
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    (hooks / "on_finish").write_text("#!/bin/sh\n")
    (hooks / "on_done").write_text("#!/bin/sh\n")  # not executable
    r = run(tmp_path, "doctor", "--json")
    checks = json.loads(r.stdout)
    texts = " ".join(c["text"] for c in checks)
    assert r.returncode == 1
    assert "day_start" in texts and "unknown setting colour" in texts
    assert "on_finish is not an event" in texts and "can't be run" in texts


def test_broken_config_gives_a_clear_message(tmp_path):
    (tmp_path / "c.toml").write_text("[ui\nfooter = true\n")
    r = run(tmp_path, "next")
    assert r.returncode == 2 and "config file has a problem" in r.stdout and "t doctor" in r.stdout


# ── completion ──────────────────────────────────────────────────────────
def test_completion_candidates(tmp_path):
    run(tmp_path, "buy", "milk", "+home")
    complete = lambda *a: run(tmp_path, "_complete", *a).stdout.splitlines()
    assert [line.split("\t")[0] for line in complete("do")] == ["done", "doctor"]
    assert [line.split("\t")[0] for line in complete("done", "")] == ["1"]
    assert complete("add", "x", "+h")[0].startswith("+home")
    assert [line.split("\t")[0] for line in complete("x", "due:to")] == ["due:today", "due:tom"]
    assert [line.split("\t")[0] for line in complete("features", "off", "st")] == ["states"]
    assert not (tmp_path / "backups").exists()  # completion changes nothing


@pytest.mark.skipif(not shutil.which("bash"), reason="needs bash")
def test_bash_completion_script(tmp_path):
    run(tmp_path, "buy", "milk")
    script = run(tmp_path, "completion", "bash").stdout
    env = {**os.environ, "TEND_DB": str(tmp_path / "t.db"), "TEND_CONFIG": str(tmp_path / "c.toml"),
           "PATH": f"{os.path.dirname(shutil.which('t') or sys.executable)}:{os.environ['PATH']}"}
    if not shutil.which("t", path=env["PATH"]):
        pytest.skip("t is not installed on PATH")
    test = script + '\nCOMP_LINE="t add x due:to"; COMP_POINT=${#COMP_LINE}; _tend_complete; echo "${COMPREPLY[*]}"\n'
    out = subprocess.run(["bash", "-c", test], env=env, capture_output=True, text=True).stdout.strip()
    assert out == "today tom"


def test_completion_scripts_exist_for_three_shells(tmp_path):
    for shell in ("bash", "zsh", "fish"):
        assert "_complete" in run(tmp_path, "completion", shell).stdout
    assert run(tmp_path, "completion", "tcsh").returncode == 1


# ── themes, help, version ───────────────────────────────────────────────
def test_plain_theme_is_ascii_only(tmp_path):
    (tmp_path / "c.toml").write_text('[ui]\ntheme = "plain"\n')
    run(tmp_path, "tax", "form", "due:tom", "every:month", "v:2", "s:S")
    for cmd in ("next", "ls", "help", "wins", "goals", "features"):
        out = run(tmp_path, cmd, extra_env={"FORCE_COLOR": "1"}).stdout
        assert out.isascii(), (cmd, [c for c in out if not c.isascii()])
        assert "\x1b[3" not in out and "\x1b[9" not in out  # no color codes (bold is fine)


def test_light_theme_and_no_color(tmp_path):
    (tmp_path / "c.toml").write_text('[ui]\ntheme = "light"\n')
    run(tmp_path, "something")
    assert run(tmp_path, "next", extra_env={"FORCE_COLOR": "1"}).returncode == 0
    out = run(tmp_path, "next", extra_env={"FORCE_COLOR": "1", "NO_COLOR": "1"}).stdout
    assert "\x1b[36m" not in out and "\x1b[38" not in out


def test_version_and_command_help(tmp_path):
    assert run(tmp_path, "--version").stdout.strip() == f"Tend {__version__}"
    r = run(tmp_path, "help", "drop")
    assert "t drop [id] [--once | --stop]" in r.stdout and "repeating" in r.stdout
    assert run(tmp_path, "drop", "--help").stdout == r.stdout
    assert run(tmp_path, "help", "nope").returncode == 1


def test_help_is_grouped_and_hides_disabled_features(tmp_path):
    run(tmp_path, "features", "off", "planning")
    out = run(tmp_path, "help").stdout
    for group in ("Doing", "Capturing", "Deciding", "Looking", "Your data", "Setup"):
        assert group in out
    assert " gantt " not in out and "_complete" not in out


def test_ls_shows_twenty_then_all(tmp_path):
    for i in range(25):
        run(tmp_path, f"task{i}")
    count = lambda out: len(re.findall(r"^\s*\d+ task\d+", out, re.M))
    short = run(tmp_path, "ls").stdout
    assert count(short) == 20 and "5 more" in short
    full = run(tmp_path, "ls", "--all").stdout
    assert count(full) == 25 and "more" not in full


# ── speed ───────────────────────────────────────────────────────────────
def test_fast_with_5000_tasks(tmp_path):
    """The roadmap promise: a command answers quickly with 5,000 tasks (1,000 open)."""
    run(tmp_path, "seed")
    db = sqlite3.connect(tmp_path / "t.db")
    today = date.today()
    rows = [(f"task {i}", "done" if i < 4000 else "open", 2, "M",
             (today + timedelta(days=i % 40)).isoformat() if i % 3 == 0 else None,
             f"{today - timedelta(days=i % 300)}T10:00:00", f"{today}T10:00:00" if i < 4000 else None)
            for i in range(5000)]
    db.executemany("INSERT INTO tasks (title, status, value, size, due, created, done_at) VALUES (?,?,?,?,?,?,?)", rows)
    db.commit()
    run(tmp_path, "next")  # first run of the day makes a backup; don't time that
    timings = []
    for _ in range(3):
        start = time.perf_counter()
        assert run(tmp_path, "next").returncode == 0
        timings.append(time.perf_counter() - start)
    # 0.15 s on a laptop; the limit leaves room for slow test machines
    assert min(timings) < 0.6, timings


def test_every_style_name_resolves_in_every_theme():
    """Rich silently drops a style it can't read, so check them all."""
    import pathlib

    from rich.console import Console

    from tend import ui

    for name in ui.THEMES:
        console = Console(theme=ui._theme(name))
        for style in ("accent", "warn", "dim", "accent.bold", "warn.bold", "dim.bold"):
            console.get_style(style)  # raises if unknown
    for path in pathlib.Path(ui.__file__).parent.rglob("*.py"):
        if path.name == "ui.py":  # where the themes are built from colors
            continue
        text = path.read_text()
        assert 'f"bold {' not in text and "f'bold {" not in text, f"{path}: combine styles with a theme name"

