"""Read busy times from iCalendar (.ics) files or URLs.

Supports the parts calendars use for normal events: DTSTART/DTEND/DURATION with
UTC, TZID or floating times, RRULE, EXDATE, RECURRENCE-ID overrides, and
cancelled or "free" (TRANSPARENT) events, which are skipped. All-day events are
skipped too: they usually mark a day, they don't block hours.
"""

import hashlib
import re
import time
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dateutil.rrule import rrulestr

CACHE_TTL = 15 * 60  # seconds


@dataclass
class Event:
    start: datetime  # local, naive
    end: datetime
    title: str


def _unfold(text: str) -> list[str]:
    return re.sub(r"\r?\n[ \t]", "", text).splitlines()


def _prop(line: str) -> tuple[str, dict, str]:
    head, _, value = line.partition(":")
    name, *params = head.split(";")
    return name.upper(), dict(p.split("=", 1) for p in params if "=" in p), value


def _parse_dt(params: dict, value: str) -> datetime | None:
    """Returns an aware datetime (or naive for floating time). None for all-day values."""
    if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", value):
        return None
    dt = datetime.strptime(value.rstrip("Z")[:15], "%Y%m%dT%H%M%S")
    if value.endswith("Z"):
        return dt.replace(tzinfo=UTC)
    if "TZID" in params:
        try:
            return dt.replace(tzinfo=ZoneInfo(params["TZID"].strip('"')))
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return dt


def _local(dt: datetime) -> datetime:
    return dt.astimezone().replace(tzinfo=None) if dt.tzinfo else dt


def _duration(value: str) -> timedelta:
    m = re.fullmatch(r"P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", value)
    if not m:
        return timedelta(hours=1)
    w, d, h, mi, s = (int(x or 0) for x in m.groups())
    return timedelta(weeks=w, days=d, hours=h, minutes=mi, seconds=s)


def parse(text: str, start: datetime, end: datetime) -> list[Event]:
    """Events that overlap [start, end), in local time."""
    vevents, cur = [], None
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            cur = []
        elif line == "END:VEVENT" and cur is not None:
            vevents.append(cur)
            cur = None
        elif cur is not None:
            cur.append(_prop(line))

    overridden: dict[str, set[datetime]] = {}
    for props in vevents:
        p = {name: (params, value) for name, params, value in props}
        if "RECURRENCE-ID" in p and "UID" in p:
            try:
                rid = _parse_dt(*p["RECURRENCE-ID"])
            except ValueError:
                continue
            if rid:
                overridden.setdefault(p["UID"][1], set()).add(_local(rid))

    out = []
    for props in vevents:
        try:
            out += _expand(props, overridden, start, end)
        except (ValueError, TypeError, OverflowError):  # one broken event must not break the plan
            continue
    return sorted(out, key=lambda e: e.start)


def _expand(props: list, overridden: dict[str, set[datetime]], start: datetime, end: datetime) -> list[Event]:
    """The occurrences of one event between start and end."""
    p = {name: (params, value) for name, params, value in props}
    if "DTSTART" not in p:
        return []
    if p.get("STATUS", ({}, ""))[1].upper() == "CANCELLED" or p.get("TRANSP", ({}, ""))[1].upper() == "TRANSPARENT":
        return []
    dtstart = _parse_dt(*p["DTSTART"])
    if dtstart is None:
        return []
    if "DTEND" in p and (dtend := _parse_dt(*p["DTEND"])):
        length = _local(dtend) - _local(dtstart)
    else:
        length = _duration(p["DURATION"][1]) if "DURATION" in p else timedelta(0)
    title = p.get("SUMMARY", ({}, "busy"))[1].replace("\\,", ",").replace("\\;", ";")

    if "RRULE" in p and "RECURRENCE-ID" not in p:
        rule = p["RRULE"][1]
        if dtstart.tzinfo is None:  # floating time: UNTIL must be floating too, and cover its whole day
            rule = re.sub(r"(UNTIL=\d{8}T\d{6})Z", r"\1", rule)
            rule = re.sub(r"UNTIL=(\d{8})(?![T\d])", r"UNTIL=\1T235959", rule)
        elif not re.search(r"UNTIL=\d{8}T\d{6}Z", rule):
            rule = re.sub(r"UNTIL=(\d{8})(?![T\d])", r"UNTIL=\1T235959Z", rule)
        rr = rrulestr(rule, dtstart=dtstart)
        lo, hi = start - length - timedelta(days=1), end + timedelta(days=1)
        if dtstart.tzinfo:
            lo, hi = lo.astimezone(), hi.astimezone()
        excluded = {_local(d) for name, params, value in props if name == "EXDATE"
                    for v in value.split(",") if (d := _parse_dt(params, v))}
        excluded |= overridden.get(p.get("UID", ({}, ""))[1], set())
        starts = [s for s in (_local(d) for d in rr.between(lo, hi, inc=True)) if s not in excluded]
    else:
        starts = [_local(dtstart)]
    return [Event(s, s + length, title) for s in starts if s < end and s + length > start and length > timedelta(0)]


def fetch(source: str, cache_dir: Path) -> tuple[str | None, str | None]:
    """Returns (text, warning). URLs are cached; a stale cache is used when offline."""
    if not source.startswith(("http://", "https://", "webcal://")):
        path = Path(source).expanduser()
        if not path.exists():
            return None, f"calendar file not found: {source}"
        return path.read_text(encoding="utf-8", errors="ignore"), None
    url = "https://" + source[len("webcal://"):] if source.startswith("webcal://") else source
    cache = cache_dir / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".ics")
    if cache.exists() and time.time() - cache.stat().st_mtime < CACHE_TTL:
        return cache.read_text(encoding="utf-8", errors="ignore"), None
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            text = r.read().decode(errors="ignore")
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache.write_text(text, encoding="utf-8")
        return text, None
    except OSError as e:
        if cache.exists():
            return cache.read_text(encoding="utf-8", errors="ignore"), "calendar offline, using the last copy"
        return None, f"can't load calendar ({e.__class__.__name__})"


def load(sources: list[str], cache_dir: Path, start: datetime, end: datetime) -> tuple[list[Event], list[str]]:
    events, warnings = [], []
    for src in sources:
        text, warning = fetch(src, cache_dir)
        if warning:
            warnings.append(warning)
        if text:
            events += parse(text, start, end)
    return sorted(events, key=lambda e: e.start), warnings
