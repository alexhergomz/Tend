"""Correction factors: how your plans usually go, learned from finished tasks.

Every model is the same simple one: the median over your last RECENT finished
tasks, used only after MIN_SAMPLES tasks, and clamped to a safe range. The
median ignores a few extreme tasks.

time   actual focus time / estimate            → scales estimates
soft   days finished after the first soft date  → soft dates count as earlier
hard   days finished after the first deadline   → rule 1 warns earlier

Start to done (days from `t start` to done) is shown and stored, not used.
Push-backs (how often dates move later) are measured and shown, but there is
no simple model that uses them reliably. They stay in the data for plugins:
tasks.pushes, or `t stats --json`.
"""

from dataclasses import dataclass
from datetime import date, datetime
from statistics import median

from .model import SIZE_MINUTES
from .store import Store

MIN_SAMPLES = 5
RECENT = 20
LOW, HIGH = 0.5, 3.0  # time factor range
MAX_SHIFT = 7  # days


@dataclass
class Calibration:
    factor: float
    samples: int  # tasks used

    @property
    def active(self) -> bool:
        return self.samples >= MIN_SAMPLES


@dataclass
class Shift:
    days: int  # how many days earlier to treat the date; 0 = no change
    median_late: float | None  # median days after the first date (negative = early)
    samples: int

    @property
    def active(self) -> bool:
        return self.samples >= MIN_SAMPLES


@dataclass
class Pushes:
    dated: int  # recent finished or open tasks that ever had a date
    pushed: int  # of those, how many were pushed at least once
    average: float  # pushes per pushed task
    top: list[tuple[int, str, int]]  # (id, title, pushes) for open tasks, most pushed first


@dataclass
class Cycle:
    median_days: float | None  # median days from started to done
    samples: int


@dataclass
class Corrections:
    time: Calibration
    soft: Shift
    hard: Shift
    pushes: Pushes
    cycle: Cycle

    def to_json(self) -> dict:
        return {
            "time": {"factor": round(self.time.factor, 2), "samples": self.time.samples, "active": self.time.active},
            "soft": {"shift_days": self.soft.days, "median_late_days": self.soft.median_late,
                     "samples": self.soft.samples, "active": self.soft.active},
            "hard": {"shift_days": self.hard.days, "median_late_days": self.hard.median_late,
                     "samples": self.hard.samples, "active": self.hard.active},
            "start_to_done": {"median_days": self.cycle.median_days, "samples": self.cycle.samples},
            "pushes": {"dated": self.pushes.dated, "pushed": self.pushes.pushed,
                       "average": round(self.pushes.average, 2),
                       "top": [{"id": i, "title": t, "pushes": n} for i, t, n in self.pushes.top]},
        }


# ── models ──────────────────────────────────────────────────────────────
def from_ratios(ratios: list[float]) -> Calibration:
    ratios = ratios[:RECENT]
    if len(ratios) < MIN_SAMPLES:
        return Calibration(1.0, len(ratios))
    return Calibration(min(max(median(ratios), LOW), HIGH), len(ratios))


def from_lateness(days_late: list[int]) -> Shift:
    days_late = days_late[:RECENT]
    if not days_late:
        return Shift(0, None, 0)
    m = median(days_late)
    if len(days_late) < MIN_SAMPLES:
        return Shift(0, m, len(days_late))
    return Shift(min(max(round(m), 0), MAX_SHIFT), m, len(days_late))


# ── data ────────────────────────────────────────────────────────────────
def ratios(store: Store) -> list[float]:
    """actual / estimate for recent finished tasks with timed sessions, newest first."""
    rows = store.db.execute(
        """SELECT t.estimate_min, t.size, SUM(s.minutes) AS actual
           FROM tasks t JOIN sessions s ON s.task_id = t.id
           WHERE t.status = 'done' AND (t.estimate_min IS NOT NULL OR t.size IS NOT NULL)
             AND t.id NOT IN (SELECT parent FROM tasks WHERE parent IS NOT NULL)
           GROUP BY t.id ORDER BY t.done_at DESC LIMIT ?""",
        (RECENT,),
    )
    out = []
    for r in rows:
        estimate = r["estimate_min"] or SIZE_MINUTES[r["size"]]
        if r["actual"] > 0:
            out.append(r["actual"] / estimate)
    return out


def lateness(store: Store, column: str) -> list[int]:
    """Days between the first date and the day the task was done, newest first."""
    rows = store.db.execute(
        f"SELECT {column}, done_at FROM tasks WHERE status = 'done' AND {column} IS NOT NULL "
        f"ORDER BY done_at DESC LIMIT ?",
        (RECENT,),
    )
    return [(datetime.fromisoformat(r["done_at"]).date() - date.fromisoformat(r[column])).days for r in rows]


def pushes(store: Store) -> Pushes:
    rows = store.db.execute(
        """SELECT pushes FROM tasks WHERE status != 'dropped'
             AND (first_due IS NOT NULL OR first_aim IS NOT NULL)
           ORDER BY COALESCE(done_at, created) DESC LIMIT ?""",
        (RECENT,),
    ).fetchall()
    pushed = [r["pushes"] for r in rows if r["pushes"] > 0]
    top = store.db.execute(
        "SELECT id, title, pushes FROM tasks WHERE status = 'open' AND pushes > 0 ORDER BY pushes DESC, id LIMIT 5"
    ).fetchall()
    return Pushes(len(rows), len(pushed), sum(pushed) / len(pushed) if pushed else 0.0,
                  [(r["id"], r["title"], r["pushes"]) for r in top])


def cycle(store: Store) -> Cycle:
    """Days from the first start to done. Shown only: the data is for plugins."""
    rows = store.db.execute(
        "SELECT started_at, done_at FROM tasks WHERE status = 'done' AND started_at IS NOT NULL "
        "ORDER BY done_at DESC LIMIT ?", (RECENT,)).fetchall()
    days = [(datetime.fromisoformat(r["done_at"]) - datetime.fromisoformat(r["started_at"])).total_seconds() / 86400
            for r in rows]
    return Cycle(round(median(days), 1) if days else None, len(days))


def load(store: Store, enabled: bool = True) -> Calibration:
    if not enabled:
        return Calibration(1.0, 0)
    return from_ratios(ratios(store))


def corrections(store: Store, enabled: bool = True) -> Corrections:
    if not enabled:
        return Corrections(Calibration(1.0, 0), Shift(0, None, 0), Shift(0, None, 0), pushes(store), cycle(store))
    return Corrections(
        time=from_ratios(ratios(store)),
        soft=from_lateness(lateness(store, "first_aim")),
        hard=from_lateness(lateness(store, "first_due")),
        pushes=pushes(store),
        cycle=cycle(store),
    )
