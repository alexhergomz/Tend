"""Repeating tasks: the rule after `every:`, and the date of the next copy.

    every:day  every:weekday  every:mon  every:mon,thu  every:3d  every:2w
    every:week  every:month  every:2m  every:year  every:1st  every:15th  every:last

Only one copy of a repeating task exists at a time. When it is done, the next
copy gets the first date in the rhythm that is after both the planned date and
today. So doing Monday's task on Wednesday gives next Monday (the rhythm
holds), and a task finished weeks late still creates only one new copy.
"""

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class RuleError(ValueError):
    pass


@dataclass(frozen=True)
class Rule:
    text: str
    weekdays: frozenset[int] = frozenset()  # 0 = Monday
    days: int = 0  # every N days
    months: int = 0  # every N months, same day of the month
    month_day: int = 0  # 1..31, or -1 for the last day

    def next_after(self, anchor: date, after: date) -> date:
        """The first date in the rhythm that starts at `anchor` and is later than `after`."""
        if self.weekdays:
            d = after + timedelta(days=1)
            while d.weekday() not in self.weekdays:
                d += timedelta(days=1)
            return d
        if self.days:
            if anchor > after:
                return anchor
            steps = (after - anchor).days // self.days + 1
            return anchor + timedelta(days=steps * self.days)
        if self.months:
            k = 0
            while True:
                d = _add_months(anchor, k * self.months)
                if d > after:
                    return d
                k += 1
        # a day of the month
        d = after + timedelta(days=1)
        while True:
            last = calendar.monthrange(d.year, d.month)[1]
            target = last if self.month_day == -1 else min(self.month_day, last)
            if d.day <= target:
                return d.replace(day=target)
            d = (d.replace(day=1) + timedelta(days=32)).replace(day=1)

    def first(self, today: date) -> date:
        """The first date for a new repeating task: today, if today is in the rhythm."""
        return self.next_after(today, today - timedelta(days=1))

    def describe(self) -> str:
        return "every " + self.text.replace(",", ", ")


def _add_months(d: date, n: int) -> date:
    month = d.month - 1 + n
    year, month = d.year + month // 12, month % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def parse(text: str) -> Rule:
    s = text.lower().strip()
    if s in ("day", "daily"):
        return Rule(s, days=1)
    if s == "week":
        return Rule(s, days=7)
    if s == "weekday":
        return Rule(s, weekdays=frozenset(range(5)))
    if s in ("month", "monthly"):
        return Rule(s, months=1)
    if s in ("year", "yearly"):
        return Rule(s, months=12)
    if m := re.fullmatch(r"(\d+)([dwmy])", s):
        n = int(m[1])
        if n < 1:
            raise RuleError("the number must be 1 or more")
        unit = m[2]
        return Rule(s, days=n * (7 if unit == "w" else 1)) if unit in "dw" else \
            Rule(s, months=n * (12 if unit == "y" else 1))
    if s == "last":
        return Rule(s, month_day=-1)
    if m := re.fullmatch(r"(\d{1,2})(st|nd|rd|th)?", s):
        n = int(m[1])
        if not 1 <= n <= 31:
            raise RuleError("a day of the month is 1 to 31")
        return Rule(s, month_day=n)
    parts = s.split(",")
    found = set()
    for p in parts:
        match = [i for i, name in enumerate(DAYS) if len(p) >= 3 and calendar.day_name[i].lower().startswith(p)]
        if not match:
            raise RuleError(f"can't read 'every:{text}' (try every:mon, every:2w, every:month, every:1st)")
        found.add(match[0])
    return Rule(",".join(DAYS[i] for i in sorted(found)), weekdays=frozenset(found))
