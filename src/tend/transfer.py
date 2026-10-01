"""Export and import: all data as JSON lines, one row per line.

The first line is a header. Every other line is {"table": ..., "row": {...}}.
Rows keep their ids, so an export loaded into an empty database is an exact copy.

Import into a database that already has tasks adds the tasks as new ones:
ids are renumbered, links between tasks are kept, goals are matched by name,
and a task with the same title and creation time as an existing one is
skipped, so importing the same file twice does not duplicate anything. The
change history (events) is only copied in a full replace.
"""

import json
from collections.abc import Iterable
from datetime import datetime
from typing import IO

from . import __version__
from .store import VERSION, Store

FORMAT = "tend-export"
FORMAT_VERSION = 1
TABLES = ("goals", "tasks", "sessions", "events", "meta")


class TransferError(ValueError):
    pass


def columns(store: Store, table: str) -> list[str]:
    return [r["name"] for r in store.db.execute(f"PRAGMA table_info({table})")]


def export(store: Store, out: IO[str]) -> dict[str, int]:
    header = {"format": FORMAT, "format_version": FORMAT_VERSION, "app_version": __version__,
              "schema": VERSION, "exported_at": datetime.now().isoformat(timespec="seconds")}
    out.write(json.dumps(header) + "\n")
    counts = {}
    for table in TABLES:
        rows = store.db.execute(f"SELECT * FROM {table}").fetchall()
        for r in rows:
            out.write(json.dumps({"table": table, "row": dict(r)}, ensure_ascii=False) + "\n")
        counts[table] = len(rows)
    return counts


def read(lines: Iterable[str]) -> tuple[dict, dict[str, list[dict]]]:
    it = (line for line in lines if line.strip())
    try:
        header = json.loads(next(it))
    except (StopIteration, json.JSONDecodeError):
        raise TransferError("this is not a Tend export (no header line)") from None
    if header.get("format") != FORMAT:
        raise TransferError("this is not a Tend export")
    if header.get("format_version", 0) > FORMAT_VERSION or header.get("schema", 0) > VERSION:
        raise TransferError(f"this file was made by a newer Tend ({header.get('app_version')}). Update Tend first.")
    data: dict[str, list[dict]] = {t: [] for t in TABLES}
    for n, line in enumerate(it, start=2):
        try:
            item = json.loads(line)
            data[item["table"]].append(item["row"])
        except (json.JSONDecodeError, KeyError, TypeError):
            raise TransferError(f"line {n} can't be read") from None
    return header, data


def _insert(store: Store, table: str, row: dict, cols: list[str], keep_id: bool = True) -> int:
    use = [c for c in cols if c in row and (keep_id or c != "id")]
    cur = store.db.execute(f"INSERT INTO {table} ({','.join(use)}) VALUES ({','.join('?' * len(use))})",
                           [row[c] for c in use])
    return cur.lastrowid


def replace_all(store: Store, header: dict, data: dict) -> dict[str, int]:
    """Make the database an exact copy of the export."""
    with store.db:
        for table in TABLES:
            store.db.execute(f"DELETE FROM {table}")
        for table in TABLES:
            cols = columns(store, table)
            for row in data[table]:
                _insert(store, table, row, cols)
    if header.get("schema", VERSION) < 2:  # older exports have no date history
        store._backfill_dates()
        store.db.commit()
    return {t: len(data[t]) for t in TABLES}


def add(store: Store, data: dict) -> dict[str, int]:
    """Add the export's tasks, goals and sessions to the current data."""
    counts = {"tasks": 0, "goals": 0, "sessions": 0, "skipped": 0}
    existing = {(r["title"], r["created"]): r["id"] for r in store.db.execute("SELECT id, title, created FROM tasks")}
    new_id: dict[int, int] = {}  # id in the file -> id here
    same: dict[int, int] = {}  # skipped duplicates -> the existing task
    with store.db:
        goal_cols = columns(store, "goals")
        have_goals = {r[0] for r in store.db.execute("SELECT name FROM goals")}
        for g in data["goals"]:
            if g["name"] not in have_goals:
                _insert(store, "goals", g, goal_cols)
                counts["goals"] += 1
        task_cols = columns(store, "tasks")
        for t in sorted(data["tasks"], key=lambda r: r["id"]):
            if (t["title"], t["created"]) in existing:
                same[t["id"]] = existing[(t["title"], t["created"])]
                counts["skipped"] += 1
                continue
            new_id[t["id"]] = _insert(store, "tasks", {**t, "parent": None}, task_cols, keep_id=False)
            counts["tasks"] += 1
        for t in data["tasks"]:  # links between tasks, now that every task has its new id
            parent = new_id.get(t.get("parent")) or same.get(t.get("parent"))
            if t["id"] in new_id and parent:
                store.db.execute("UPDATE tasks SET parent = ? WHERE id = ?", (parent, new_id[t["id"]]))
        session_cols = columns(store, "sessions")
        for s in data["sessions"]:
            if s.get("task_id") in new_id:
                _insert(store, "sessions", {**s, "task_id": new_id[s["task_id"]]}, session_cols, keep_id=False)
                counts["sessions"] += 1
    return counts
