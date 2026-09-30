"""Estimate calibration: how long tasks really take compared to their estimate.

Uses finished tasks that have timed focus sessions. The factor is the median of
actual / estimated time over the most recent tasks, so a few outliers don't
move it much. Below MIN_SAMPLES tasks there is not enough data and the factor is 1.
"""

from dataclasses import dataclass
from statistics import median

from .model import SIZE_MINUTES
from .store import Store

MIN_SAMPLES = 5
RECENT = 20
LOW, HIGH = 0.5, 3.0


@dataclass
class Calibration:
    factor: float
    samples: int  # tasks used

    @property
    def active(self) -> bool:
        return self.samples >= MIN_SAMPLES


def from_ratios(ratios: list[float]) -> Calibration:
    ratios = ratios[:RECENT]
    if len(ratios) < MIN_SAMPLES:
        return Calibration(1.0, len(ratios))
    return Calibration(min(max(median(ratios), LOW), HIGH), len(ratios))


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


def load(store: Store, enabled: bool = True) -> Calibration:
    if not enabled:
        return Calibration(1.0, 0)
    return from_ratios(ratios(store))
