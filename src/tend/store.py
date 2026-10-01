"""SQLite storage. The schema is the public data API: query it with any SQL tool.

Every task mutation happens inside an event, which records before/after
snapshots. That gives a full history (the `events` table) and a generic undo.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

from .model import SIZE_MINUTES, Goal, Task

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id           INTEGER PRIMARY KEY,
    title        TEXT NOT NULL,
    goal         TEXT,
    parent       INTEGER REFERENCES tasks(id),
    value        INTEGER CHECK (value BETWEEN 1 AND 3),
    size         TEXT CHECK (size IN ('S', 'M', 'L')),
    estimate_min INTEGER,
    due          TEXT,             -- hard deadline, ISO date
    aim          TEXT,             -- soft target, ISO date
    start_after  TEXT,
    status       TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done', 'dropped')),
    slips        INTEGER NOT NULL DEFAULT 0,
    skip_date    TEXT,
    created      TEXT NOT NULL,
    done_at      TEXT,
    energy       TEXT CHECK (energy IN ('high', 'low')),
    first_due    TEXT,             -- first hard deadline, kept when the date moves
    first_aim    TEXT,             -- first soft target, kept when the date moves
    pushes       INTEGER NOT NULL DEFAULT 0, -- times a date moved later
    stage        TEXT NOT NULL DEFAULT 'todo' CHECK (stage IN ('todo', 'started', 'waiting')),
    started_at   TEXT              -- first time work started
);
CREATE TABLE IF NOT EXISTS goals (
    name       TEXT PRIMARY KEY,
    weekly_min INTEGER NOT NULL DEFAULT 0,
    why        TEXT,
    created    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    id      INTEGER PRIMARY KEY,
    task_id INTEGER REFERENCES tasks(id),
    start   TEXT NOT NULL,
    end     TEXT NOT NULL,
    mode    TEXT NOT NULL,
    minutes REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id      INTEGER PRIMARY KEY,
    ts      TEXT NOT NULL,
    kind    TEXT NOT NULL,
    summary TEXT,
    changes TEXT NOT NULL,         -- JSON list of {table, id, before, after}
    undone  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""
VERSION = 3
NEW_COLUMNS = {
    # version 2
    "energy": "TEXT CHECK (energy IN ('high', 'low'))",
    "first_due": "TEXT",
    "first_aim": "TEXT",
    "pushes": "INTEGER NOT NULL DEFAULT 0",
    # version 3
    "stage": "TEXT NOT NULL DEFAULT 'todo' CHECK (stage IN ('todo', 'started', 'waiting'))",
    "started_at": "TEXT",
}
DEFAULTS = {"pushes": 0, "slips": 0, "stage": "todo"}

COLS = [
    "id", "title", "goal", "parent", "value", "size", "estimate_min", "due", "aim",
    "start_after", "status", "slips", "skip_date", "created", "done_at",
    "energy", "first_due", "first_aim", "pushes", "stage", "started_at",
]
NOT_UNDOABLE = ("rollover",)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str | Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self._changes: list | None = None
        self.on_event = None  # called as on_event(kind, summary, changes) after each commit
        self._migrate()

    def _migrate(self):
        have = {r["name"] for r in self.db.execute("PRAGMA table_info(tasks)")}
        added = [c for c in NEW_COLUMNS if c not in have]
        for c in added:
            self.db.execute(f"ALTER TABLE tasks ADD COLUMN {c} {NEW_COLUMNS[c]}")
        if "pushes" in added:
            self._backfill_dates()
        if "stage" in added:  # open tasks with focus time were started
            self.db.execute("""UPDATE tasks SET stage = 'started',
                started_at = (SELECT MIN(start) FROM sessions WHERE task_id = tasks.id)
                WHERE status = 'open' AND id IN (SELECT task_id FROM sessions)""")
        self.db.execute(f"PRAGMA user_version = {VERSION}")
        self.db.commit()

    def _backfill_dates(self):
        """Rebuild first_due, first_aim and pushes from the event history."""
        first: dict[int, dict] = {}
        pushes: dict[int, int] = {}
        for row in self.db.execute("SELECT changes FROM events WHERE undone = 0 ORDER BY id"):
            for ch in json.loads(row["changes"]):
                before, after = ch.get("before") or {}, ch.get("after") or {}
                for key in ("due", "aim"):
                    if after.get(key) and not first.get(ch["id"], {}).get(key):
                        first.setdefault(ch["id"], {})[key] = after[key]
                    if before.get(key) and after.get(key) and after[key] > before[key]:
                        pushes[ch["id"]] = pushes.get(ch["id"], 0) + 1
        for r in self.db.execute("SELECT id, due, aim FROM tasks").fetchall():
            f = first.get(r["id"], {})
            self.db.execute("UPDATE tasks SET first_due = ?, first_aim = ?, pushes = ? WHERE id = ?",
                            (f.get("due") or r["due"], f.get("aim") or r["aim"], pushes.get(r["id"], 0), r["id"]))

    # ── events ──────────────────────────────────────────────────────────
    @contextmanager
    def event(self, kind: str, summary: str = ""):
        ev = {"summary": summary}
        self._changes = []
        try:
            yield ev
            self.db.execute(
                "INSERT INTO events (ts, kind, summary, changes) VALUES (?, ?, ?, ?)",
                (now_iso(), kind, ev["summary"], json.dumps(self._changes)),
            )
            self.db.commit()
            if self.on_event:
                self.on_event(kind, ev["summary"], self._changes)
        except BaseException:
            self.db.rollback()
            raise
        finally:
            self._changes = None

    def _record(self, task_id: int, before: dict | None, after: dict | None):
        if self._changes is None:
            raise RuntimeError("task writes must happen inside Store.event()")
        self._changes.append({"table": "tasks", "id": task_id, "before": before, "after": after})

    def undo(self) -> str | None:
        placeholders = ",".join("?" * len(NOT_UNDOABLE))
        row = self.db.execute(
            f"SELECT * FROM events WHERE undone = 0 AND kind NOT IN ({placeholders}) ORDER BY id DESC LIMIT 1",
            NOT_UNDOABLE,
        ).fetchone()
        if not row:
            return None
        for ch in reversed(json.loads(row["changes"])):
            if ch["before"] is None:
                self.db.execute("DELETE FROM tasks WHERE id = ?", (ch["id"],))
            else:
                b = ch["before"]
                self.db.execute(
                    f"INSERT OR REPLACE INTO tasks ({','.join(COLS)}) VALUES ({','.join('?' * len(COLS))})",
                    [b.get(c, DEFAULTS.get(c)) for c in COLS],
                )
        self.db.execute("UPDATE events SET undone = 1 WHERE id = ?", (row["id"],))
        self.db.commit()
        return row["summary"]

    # ── tasks ───────────────────────────────────────────────────────────
    def tasks(self, status: str | None = "open") -> list[Task]:
        if status is None:
            rows = self.db.execute("SELECT * FROM tasks ORDER BY id")
        else:
            rows = self.db.execute("SELECT * FROM tasks WHERE status = ? ORDER BY id", (status,))
        return [Task.from_row(r) for r in rows]

    def task(self, task_id: int) -> Task | None:
        row = self.db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return Task.from_row(row) if row else None

    def children(self, task_id: int, status: str = "open") -> list[Task]:
        rows = self.db.execute("SELECT * FROM tasks WHERE parent = ? AND status = ? ORDER BY id", (task_id, status))
        return [Task.from_row(r) for r in rows]

    def blocked_ids(self) -> set[int]:
        """Tasks that were split: they wait for their open children."""
        rows = self.db.execute("SELECT DISTINCT parent FROM tasks WHERE parent IS NOT NULL AND status = 'open'")
        return {r[0] for r in rows}

    def insert(self, t: Task) -> int:
        if not t.created:
            t.created = now_iso()
        t.first_due = t.first_due or t.due
        t.first_aim = t.first_aim or t.aim
        row = t.to_row()
        cols = [c for c in COLS if c != "id"]
        cur = self.db.execute(
            f"INSERT INTO tasks ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", [row[c] for c in cols]
        )
        t.id = cur.lastrowid
        self._record(t.id, None, t.to_row())
        return t.id

    def update(self, t: Task):
        old = self.task(t.id)
        before = old.to_row()
        for key in ("due", "aim"):
            new, prev = getattr(t, key), getattr(old, key)
            if new and not getattr(t, f"first_{key}"):
                setattr(t, f"first_{key}", new)
            if new and prev and new > prev:
                t.pushes += 1
        row = t.to_row()
        cols = [c for c in COLS if c != "id"]
        self.db.execute(f"UPDATE tasks SET {','.join(c + ' = ?' for c in cols)} WHERE id = ?", [row[c] for c in cols] + [t.id])
        self._record(t.id, before, row)

    def done_since(self, since: date) -> list[Task]:
        rows = self.db.execute(
            "SELECT * FROM tasks WHERE status = 'done' AND done_at >= ? ORDER BY done_at", (since.isoformat(),)
        )
        return [Task.from_row(r) for r in rows]

    # ── goals ───────────────────────────────────────────────────────────
    def goals(self) -> list[Goal]:
        rows = self.db.execute("SELECT name, weekly_min, why FROM goals ORDER BY name")
        return [Goal(r["name"], r["weekly_min"], r["why"]) for r in rows]

    def ensure_goal(self, name: str) -> bool:
        cur = self.db.execute("INSERT OR IGNORE INTO goals (name, created) VALUES (?, ?)", (name, now_iso()))
        self.db.commit()
        return cur.rowcount == 1

    def set_goal(self, name: str, weekly_min: int, why: str | None):
        self.db.execute(
            """INSERT INTO goals (name, weekly_min, why, created) VALUES (?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET weekly_min = excluded.weekly_min,
                                               why = COALESCE(excluded.why, goals.why)""",
            (name, weekly_min, why, now_iso()),
        )
        self.db.commit()

    def delete_goal(self, name: str) -> bool:
        cur = self.db.execute("DELETE FROM goals WHERE name = ?", (name,))
        self.db.commit()
        return cur.rowcount == 1

    def goal_minutes(self, since: date) -> dict[str, float]:
        """Time spent per goal since a date. Tasks finished without a timer count their estimate."""
        out: dict[str, float] = {}
        for r in self.db.execute(
            """SELECT t.goal, SUM(s.minutes) FROM sessions s JOIN tasks t ON t.id = s.task_id
               WHERE s.start >= ? AND t.goal IS NOT NULL GROUP BY t.goal""",
            (since.isoformat(),),
        ):
            out[r[0]] = out.get(r[0], 0) + r[1]
        for r in self.db.execute(
            """SELECT goal, estimate_min, size FROM tasks
               WHERE status = 'done' AND done_at >= ? AND goal IS NOT NULL
                 AND id NOT IN (SELECT task_id FROM sessions WHERE task_id IS NOT NULL)
                 AND id NOT IN (SELECT parent FROM tasks WHERE parent IS NOT NULL)""",
            (since.isoformat(),),
        ):
            out[r[0]] = out.get(r[0], 0) + (r[1] or SIZE_MINUTES[r[2] or "M"])
        return out

    # ── sessions ────────────────────────────────────────────────────────
    def add_session(self, task_id: int, start: datetime, end: datetime, mode: str, minutes: float):
        self.db.execute(
            "INSERT INTO sessions (task_id, start, end, mode, minutes) VALUES (?, ?, ?, ?, ?)",
            (task_id, start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds"), mode, minutes),
        )
        self.db.commit()

    def logged_by_task(self) -> dict[int, float]:
        return {r[0]: r[1] for r in self.db.execute("SELECT task_id, SUM(minutes) FROM sessions GROUP BY task_id")}

    def focused_since(self, since: date) -> float:
        row = self.db.execute("SELECT COALESCE(SUM(minutes), 0) FROM sessions WHERE start >= ?", (since.isoformat(),))
        return row.fetchone()[0]

    # ── meta ────────────────────────────────────────────────────────────
    def get_meta(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value):
        self.db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, None if value is None else str(value)))
        self.db.commit()
