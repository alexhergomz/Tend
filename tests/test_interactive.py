"""Interactive mode, the focus timer and the first-run guide, driven through a pseudo-terminal."""

import json
import os
import re
import subprocess
import sys
import time

import pytest

pty = pytest.importorskip("pty", reason="needs a POSIX terminal")  # Windows has no pty
select = pytest.importorskip("select")
ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")


def env(tmp_path, **extra):
    return {**os.environ, "TEND_DB": str(tmp_path / "t.db"), "TEND_CONFIG": str(tmp_path / "c.toml"),
            "TEND_HOOKS": str(tmp_path / "hooks"), "COLUMNS": "90", "LINES": "30", "TERM": "xterm", **extra}


def drive(tmp_path, args, keys, settle=1.5):
    """Run `t args` in a terminal, send (delay, key) pairs, return the screen text and exit code."""
    pid, fd = pty.fork()
    if pid == 0:
        os.execvpe(sys.executable, [sys.executable, "-m", "tend", *args], env(tmp_path))
    out = b""

    def pump(seconds):
        nonlocal out
        end = time.time() + seconds
        while time.time() < end:
            if select.select([fd], [], [], 0.05)[0]:
                try:
                    out += os.read(fd, 65536)
                except OSError:
                    return

    pump(settle)
    for delay, key in keys:
        try:
            os.write(fd, key.encode())
        except OSError:  # the program already ended; the screen says why
            break
        pump(delay)
    pump(0.5)
    _, status = os.waitpid(pid, 0)
    return ANSI.sub("", out.decode(errors="ignore")), os.waitstatus_to_exitcode(status)


def t(tmp_path, *args):
    r = subprocess.run([sys.executable, "-m", "tend", *args, "--json"], env=env(tmp_path),
                       capture_output=True, encoding="utf-8")
    return json.loads(r.stdout) if r.stdout.strip() else None


def test_first_run_shows_the_welcome(tmp_path):
    screen, code = drive(tmp_path, [], [(0.8, "q")])
    assert code == 0 and "Welcome to Tend" in screen and "t next" in screen


def test_interactive_mode_done_skip_list_help_quit(tmp_path):
    t(tmp_path, "first", "v:3", "s:S")
    t(tmp_path, "second", "v:1", "s:S")
    t(tmp_path, "third", "v:1", "s:L")
    screen, code = drive(tmp_path, [], [(0.8, "d"), (0.8, "s"), (0.8, "l"), (0.6, " "), (0.8, "?"),
                                        (0.6, " "), (0.6, "q")])
    assert code == 0
    assert "✓ first" in screen and "skipped for today: second" in screen
    assert "Doing" in screen and "Capturing" in screen  # the help screen
    assert "1 done today" in screen
    assert [x["title"] for x in t(tmp_path, "ls")] == ["third", "second"]


def test_focus_flow_logs_time_and_finishes(tmp_path):
    t(tmp_path, "write", "report")
    screen, code = drive(tmp_path, ["focus", "--flow"], [(2.0, "d")])
    assert code == 0 and "Focus" in screen and "write report" in screen
    assert t(tmp_path, "wins")["done"][0]["title"] == "write report"


def test_triage_in_a_terminal(tmp_path):
    t(tmp_path, "call", "dentist")
    screen, code = drive(tmp_path, ["triage"], [(0.6, "3"), (0.6, "s"), (0.6, "\r"), (0.8, "\r")])
    assert code == 0 and "triaged" in screen
    task = t(tmp_path, "ls")[0]
    assert (task["value"], task["size"]) == (3, "S")
