import os
from datetime import date
from pathlib import Path


def minutes(m: float) -> str:
    m = round(m)
    if m < 60:
        return f"{m}m"
    h, r = divmod(m, 60)
    return f"{h}h" if r == 0 else f"{h}h{r:02d}m"


def hours(h: float) -> str:
    return minutes(h * 60)


def day(d: date, today: date) -> str:
    delta = (d - today).days
    if delta == 0:
        return "today"
    if delta == 1:
        return "tomorrow"
    if delta == -1:
        return "yesterday"
    if 1 < delta < 7:
        return f"{d:%a}"
    if d.year != today.year:
        return f"{d:%b} {d.day} {d.year}"
    return f"{d:%b} {d.day}"


def clock(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def days(n: float) -> str:
    n = round(n, 1)
    n = int(n) if n == int(n) else n
    return f"{n} day" if n == 1 else f"{n} days"


def count(n: int, word: str, plural: str | None = None) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {plural or word + 's'}"


def home(path) -> str:
    """A path with your home folder written as ~."""
    p, root = str(path), str(Path.home())
    return "~" + p[len(root):] if p == root or p.startswith(root + os.sep) else p
