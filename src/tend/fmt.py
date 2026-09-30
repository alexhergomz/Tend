from datetime import date


def minutes(m: float) -> str:
    m = int(round(m))
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
