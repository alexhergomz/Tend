"""Backups: copies of the database, made with SQLite's backup API so a copy is
always consistent, even while tend is writing.

daily   made on the first run of each day, the last `keep_days` are kept
manual  made by `t backup`, the last 10 are kept
before  made before a restore or an import, the last 5 are kept
"""

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from . import config

KEEP = {"manual": 10, "before": 5}


@dataclass
class Copy:
    path: Path
    kind: str  # daily / manual / before
    made: datetime

    @property
    def size_kb(self) -> int:
        return round(self.path.stat().st_size / 1024)

    def open_tasks(self) -> int | None:
        try:
            db = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
            n = db.execute("SELECT COUNT(*) FROM tasks WHERE status = 'open'").fetchone()[0]
            db.close()
            return n
        except sqlite3.Error:
            return None


def folder(cfg: dict) -> Path:
    custom = cfg["backup"]["folder"]
    return Path(custom).expanduser() if custom else config.data_path().parent / "backups"


def copies(cfg: dict) -> list[Copy]:
    """All backups, newest first."""
    out = []
    for p in folder(cfg).glob("*.db"):
        kind, _, stamp = p.stem.partition("-")
        try:
            made = datetime.strptime(stamp.split("_")[0], "%Y-%m-%dT%H%M%S")
        except ValueError:
            continue
        out.append(Copy(p, kind, made))
    return sorted(out, key=lambda c: (c.made, c.path.name), reverse=True)


def make(db: sqlite3.Connection, cfg: dict, kind: str = "manual") -> Path:
    target = folder(cfg)
    target.mkdir(parents=True, exist_ok=True)
    stamp = f"{kind}-{datetime.now():%Y-%m-%dT%H%M%S}"
    path, n = target / f"{stamp}.db", 1
    while path.exists():  # two copies in the same second
        path, n = target / f"{stamp}_{n}.db", n + 1
    dst = sqlite3.connect(path)
    with dst:
        db.backup(dst)
    dst.close()
    prune(cfg, kind)
    return path


def prune(cfg: dict, kind: str):
    keep = cfg["backup"]["keep_days"] if kind == "daily" else KEEP.get(kind, 5)
    for old in [c for c in copies(cfg) if c.kind == kind][keep:]:
        old.path.unlink(missing_ok=True)


def daily(db: sqlite3.Connection, cfg: dict, today: date) -> Path | None:
    """Make today's copy if there isn't one yet. Skips an empty database."""
    if any(c.kind == "daily" and c.made.date() == today for c in copies(cfg)):
        return None
    if not db.execute("SELECT 1 FROM tasks LIMIT 1").fetchone():
        return None
    return make(db, cfg, "daily")


def check(path: Path) -> bool:
    try:
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        ok = db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        ok = ok and db.execute("SELECT 1 FROM sqlite_master WHERE name = 'tasks'").fetchone() is not None
        db.close()
        return ok
    except sqlite3.Error:
        return False


def restore(db: sqlite3.Connection, cfg: dict, path: Path) -> Path:
    """Replace the current data with a copy. Saves the current data first and returns that copy."""
    if not check(path):
        raise ValueError(f"{path.name} is damaged or not a tend database")
    before = make(db, cfg, "before")
    src = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    src.backup(db)
    src.close()
    return before
