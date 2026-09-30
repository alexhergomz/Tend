"""Energy windows: times of day for hard (high) and easy (low) work.

A task tagged @high is only scheduled inside a high window, and `t next` puts it
after other tasks during a low window. A task tagged @low is put after other
tasks during a high window, so peak time goes to hard work. Untagged tasks fit
anywhere. A deadline at risk ignores all of this.
"""

from datetime import datetime, time

Windows = dict[str, list[tuple[time, time]]]


def parse(cfg: dict) -> Windows:
    out: Windows = {}
    for level in ("high", "low"):
        spans = []
        for text in cfg.get(level, []):
            start, _, end = text.partition("-")
            spans.append((time.fromisoformat(start.strip()), time.fromisoformat(end.strip())))
        out[level] = spans
    return out


def at(windows: Windows, moment: datetime) -> str | None:
    t = moment.time()
    for level, spans in windows.items():
        if any(s <= t < e for s, e in spans):
            return level
    return None


def split(start: datetime, end: datetime, windows: Windows) -> list[list]:
    """Cut [start, end) at window edges. Returns [start, end, level] pieces."""
    cuts = {start, end}
    for spans in windows.values():
        for s, e in spans:
            for edge in (s, e):
                moment = datetime.combine(start.date(), edge)
                if start < moment < end:
                    cuts.add(moment)
    points = sorted(cuts)
    return [[a, b, at(windows, a)] for a, b in zip(points, points[1:])]


def allowed(task_energy: str | None, level: str | None, windows: Windows) -> bool:
    """High tasks need a high window, if you defined any."""
    return not (task_energy == "high" and windows.get("high") and level != "high")
