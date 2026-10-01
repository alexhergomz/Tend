"""Quick-add syntax: plain words form the title, tokens set fields.

    +goal  due:fri  aim:fri  after:mon  v:1..3  e:45m  s:S|M|L  @high @low  every:mon

`!2` and `~45m` also work, but zsh expands them unless they're inside quotes.
"""

import calendar
import re
from datetime import date, timedelta

from . import repeat

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
CLEAR = ("", "none", "-")


class ParseError(ValueError):
    pass


def parse_date(text: str, today: date) -> date:
    s = text.lower().strip()
    if s in ("today", "tod", "now"):
        return today
    if s in ("tomorrow", "tom", "tmr"):
        return today + timedelta(days=1)
    if s == "eow":
        return today + timedelta(days=6 - today.weekday())
    if s == "eom":
        return today.replace(day=calendar.monthrange(today.year, today.month)[1])
    if len(s) >= 3:
        for i, name in enumerate(WEEKDAYS):
            if name.startswith(s):
                return today + timedelta(days=(i - today.weekday()) % 7)
    if m := re.fullmatch(r"(\d{1,2})(st|nd|rd|th)", s):  # the next 1st, 15th, ...
        try:
            return repeat.parse(s).first(today)
        except repeat.RuleError as e:
            raise ParseError(str(e)) from None
    if m := re.fullmatch(r"\+?(\d+)([dw])", s):
        n = int(m[1]) * (7 if m[2] == "w" else 1)
        return today + timedelta(days=n)
    try:
        return date.fromisoformat(s)
    except ValueError:
        pass
    month = day = None
    if m := re.fullmatch(r"(\d{1,2})[-/](\d{1,2})", s):
        month, day = int(m[1]), int(m[2])
    elif m := re.fullmatch(r"([a-z]{3})[a-z]*\s*(\d{1,2})", s):
        month, day = _month(m[1]), int(m[2])
    elif m := re.fullmatch(r"(\d{1,2})\s*([a-z]{3})[a-z]*", s):
        month, day = _month(m[2]), int(m[1])
    if month and day:
        try:
            d = date(today.year, month, day)
        except ValueError:
            raise ParseError(f"not a real date: {text}") from None
        year = today.year + (d < today)
        while True:  # Feb 29 waits for the next leap year
            try:
                return d.replace(year=year)
            except ValueError:
                year += 1
    raise ParseError(f"can't read date '{text}' (try fri, oct20, +3d, 2026-10-20)")


def _month(abbr: str) -> int | None:
    return MONTHS.index(abbr) + 1 if abbr in MONTHS else None


MAX_MINUTES = 1000 * 60  # 1,000 hours: anything longer is a typo


def parse_duration(text: str) -> int:
    s = text.lower().strip()
    minutes = None
    if m := re.fullmatch(r"(\d+(?:\.\d+)?)h(?:(\d+)m?)?", s):
        minutes = round(float(m[1]) * 60) + int(m[2] or 0)
    elif m := re.fullmatch(r"(\d+)m?", s):
        minutes = int(m[1])
    if minutes is None:
        raise ParseError(f"can't read duration '{text}' (try 45m, 2h, 1h30m)")
    if minutes > MAX_MINUTES:
        raise ParseError(f"'{text}' is longer than 1,000 hours. Split the task into steps instead.")
    return minutes


def size_for(minutes: int) -> str:
    return "S" if minutes <= 60 else "M" if minutes <= 180 else "L"


def parse_tokens(args: list[str], today: date) -> tuple[str, dict]:
    """Returns (title, fields). A field set to None means 'clear it'."""
    words, f = [], {}
    for w in " ".join(args).split():
        if m := re.fullmatch(r"\+([\w-]+)", w):
            f["goal"] = m[1].lower()
        elif m := re.fullmatch(r"(due|aim|after):(.*)", w, re.I):
            key = {"due": "due", "aim": "aim", "after": "start_after"}[m[1].lower()]
            f[key] = None if m[2].lower() in CLEAR else parse_date(m[2], today)
        elif m := re.fullmatch(r"every:(\S+)", w, re.I):
            if m[1].lower() in CLEAR:
                f["repeat"] = None
            else:
                try:
                    f["repeat"] = repeat.parse(m[1]).text
                except repeat.RuleError as e:
                    raise ParseError(str(e)) from None
        elif m := re.fullmatch(r"@(high|low|any)", w, re.I):
            f["energy"] = None if m[1].lower() == "any" else m[1].lower()
        elif m := re.fullmatch(r"(?:!|v:)([123])", w):
            f["value"] = int(m[1])
        elif m := re.fullmatch(r"(?:s|size):([sml])", w, re.I):
            f["size"] = m[1].upper()
        elif m := re.fullmatch(r"(?:~|e:|est:)(\S+)", w, re.I):
            f["estimate_min"] = parse_duration(m[1])
        else:
            words.append(w)
    if f.get("estimate_min") and "size" not in f:
        f["size"] = size_for(f["estimate_min"])
    return " ".join(words), f
