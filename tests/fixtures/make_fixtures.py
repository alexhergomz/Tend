"""Make one database with each released version of Tend, using that version's own code.

Run from the repository root:  python tests/fixtures/make_fixtures.py
Each database gets the same kind of use: tasks with details, a goal, done,
split, edited dates, a focus session, and the features of that version.
"""

import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

RELEASES = {  # version: (commit, extra commands that version understands)
    "0.1": ("29a61a6", []),
    "0.3": ("dc1e69e", []),
    "0.5": ("e81f8bd", [["e", "3", "@high"]]),
    "0.6": ("a9f3e6c", [["e", "3", "@high"], ["start", "3"], ["wait", "4", "+5d"]]),
    "0.7": ("860c107", [["e", "3", "@high"], ["start", "3"], ["wait", "4", "+5d"]]),
    "0.8": ("e14a524", [["e", "3", "@high"], ["start", "3"], ["wait", "4", "+5d"],
                        ["water", "plants", "every:mon", "v:2", "s:S"]]),
}
COMMON = [
    ["tax", "form", "due:tom", "e:2h", "v:2"],
    ["write", "ch.2", "intro", "+thesis", "v:3", "s:M"],
    ["run", "experiments", "+thesis", "v:3", "s:L", "due:+12d"],
    ["reply", "to", "professor", "due:+5d", "v:2", "s:S"],
    ["call", "the", "dentist"],
    ["g", "add", "thesis", "3h", "finish", "the", "MSc"],
    ["done", "1"],
    ["split", "2", "outline", "draft first paragraph"],
    ["e", "4", "due:+8d"],
    ["e", "4", "due:+9d"],
    ["skip", "5"],
]


def make(version: str, commit: str, extra: list[list[str]]):
    with tempfile.TemporaryDirectory() as tmp:
        tree = Path(tmp) / "src"
        subprocess.run(["git", "-C", str(ROOT), "worktree", "add", "--detach", "-q", str(tree), commit], check=True)
        try:
            db = Path(tmp) / "tend.db"
            env = {**os.environ, "PYTHONPATH": str(tree / "src"), "TEND_DB": str(db),
                   "TEND_CONFIG": str(Path(tmp) / "c.toml"), "TEND_HOOKS": str(Path(tmp) / "hooks")}
            for args in COMMON + extra:
                subprocess.run([sys.executable, "-m", "tend", *args], env=env, check=True, capture_output=True)
            con = sqlite3.connect(db)
            con.execute("INSERT INTO sessions (task_id, start, end, mode, minutes) "
                        "VALUES (3, '2026-09-20T10:00:00', '2026-09-20T10:25:00', 'pomo', 25)")
            con.commit()
            con.close()
            shutil.copy(db, HERE / f"tend-{version}.db")
            print(f"tend-{version}.db  ({commit})")
        finally:
            subprocess.run(["git", "-C", str(ROOT), "worktree", "remove", "--force", str(tree)], check=True)


if __name__ == "__main__":
    for version, (commit, extra) in RELEASES.items():
        make(version, commit, extra)
