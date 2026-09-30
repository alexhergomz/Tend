"""Rendering for t plan and t gantt."""

from datetime import date, datetime, timedelta

from rich.markup import escape
from rich.text import Text

from . import fmt
from .plan import Plan
from .ui import ACCENT, DIM, WARN, console

RULE_LABEL = {1: "deadline", 2: "big rock", 3: ""}


def _day_title(day: date, today: date) -> str:
    if day == today:
        return f"Today · {day:%a} {day:%b} {day.day}"
    if day == today + timedelta(days=1):
        return f"Tomorrow · {day:%a} {day:%b} {day.day}"
    return f"{day:%A} · {day:%b} {day.day}"


def day_plan(plan: Plan, day: date, today: date):
    blocks = plan.on(day)
    events = [e for e in plan.events if e.start.date() == day]
    focus = sum(b.minutes for b in blocks)
    header = f" [bold]{_day_title(day, today)}[/] [{DIM}]· {fmt.minutes(focus)} of focus planned"
    if events:
        header += f" · {len(events)} calendar event{'s' * (len(events) > 1)}"
    console.print(header + "[/]")
    rows = [(b.start, b.end, b) for b in blocks] + [(e.start, e.end, e) for e in events]
    for start, end, item in sorted(rows, key=lambda r: r[0]):
        when = f"   [{DIM}]{start:%H:%M}–{end:%H:%M}[/]  "
        if hasattr(item, "task"):
            color = WARN if item.rule == 1 else ACCENT
            label = RULE_LABEL[item.rule]
            meta = f"#{item.task.id}" + (f" · {escape(item.task.goal)}" if item.task.goal else "")
            console.print(f"{when}[{color}]━[/] {escape(item.task.title)}  [{DIM}]{meta}"
                          f"{' · ' + label if label else ''}[/]")
        else:
            console.print(f"{when}[{DIM}]· {escape(item.title)}[/]")
    if not rows:
        console.print(f"   [{DIM}]Nothing planned.[/]")


def warnings(plan: Plan, today: date):
    for late in plan.late:
        t = late.task
        if t.due < today:
            msg = f"is past due ({fmt.day(t.due, today)}). t r to decide what to do."
        elif late.finish is None:
            msg = f"doesn't fit before {fmt.day(t.due, today)}: {fmt.minutes(late.minutes_left)} of work has no time slot"
        else:
            msg = f"won't be done by {fmt.day(t.due, today)}: {fmt.minutes(late.minutes_left)} of work lands after it"
        console.print(f" [{WARN}]⚑ {escape(t.title)} {msg}[/]")


def summary(plan: Plan, days: int, calibration):
    span = plan.days[:days]
    planned = sum(b.minutes for b in plan.blocks if b.start.date() in span)
    room = sum(plan.capacity.get(d, 0) for d in span)
    console.print(f" [{DIM}]Next {days} days: {fmt.minutes(planned)} of work planned, room for {fmt.minutes(room)}.[/]")
    left = sum(m for _, m in plan.unplanned)
    if left > 0.5:
        console.print(f" [{DIM}]{fmt.minutes(left)} of open work doesn't fit in the next {len(plan.days)} days.[/]")
    if calibration.active and abs(calibration.factor - 1) >= 0.05:
        console.print(f" [{DIM}]Estimates are scaled ×{calibration.factor:.1f}, learned from {calibration.samples} tasks.[/]")


def gantt(plan: Plan, days: int, today: date, hours_per_day: float, day_start, day_end, max_rows: int = 15):
    span = plan.days[:days]
    title_w = 22
    cell = max(3, min(6, (console.width - title_w - 18) // days))
    late_ids = {l.task.id for l in plan.late}

    def cells(values: list[Text]) -> Text:
        out = Text()
        for v in values:
            v.truncate(cell - 1)
            v.pad_right(cell - len(v.plain))
            out.append_text(v)
        return out

    head1 = Text(" " + " " * title_w)
    head2 = Text(" " + " " * title_w)
    for d in span:
        style = f"bold {ACCENT}" if d == today else DIM
        head1.append(f"{d:%a}"[: cell - 1].ljust(cell), style)
        head2.append(str(d.day).ljust(cell), style)
    console.print(head1)
    console.print(head2)

    window = (datetime.combine(today, day_end) - datetime.combine(today, day_start)).total_seconds() / 3600
    if plan.events:
        busy = []
        for d in span:
            h = sum((min(e.end, datetime.combine(d, day_end)) - max(e.start, datetime.combine(d, day_start))).total_seconds() / 3600
                    for e in plan.events if e.start.date() == d and e.end > datetime.combine(d, day_start)
                    and e.start < datetime.combine(d, day_end))
            n = round(h / window * (cell - 1)) if h > 0 else 0
            busy.append(Text("▃" * max(n, 1 if h > 0 else 0), DIM))
        console.print(Text(" " + "calendar".ljust(title_w), DIM) + cells(busy))

    order: list = []
    for b in plan.blocks:
        if b.start.date() in span and b.task.id not in [t.id for t in order]:
            order.append(b.task)
    for t in order[:max_rows]:
        color = WARN if t.id in late_ids else ACCENT
        row = []
        for d in span:
            m = sum(b.minutes for b in plan.blocks if b.task.id == t.id and b.start.date() == d)
            n = max(1, round(m / (hours_per_day * 60) * (cell - 1))) if m > 0 else 0
            v = Text("▆" * n, color)
            if t.due == d:
                v.append("◆", WARN)
            row.append(v)
        name = t.title if len(t.title) <= title_w - 1 else t.title[: title_w - 2] + "…"
        meta = f"#{t.id}"
        if t.due and t.due > span[-1]:
            meta += f" · due {fmt.day(t.due, today)}"
        console.print(Text(" ") + Text(name.ljust(title_w), "bold" if t.id in late_ids else "") + cells(row) + Text(meta, DIM))
    if len(order) > max_rows:
        console.print(f" [{DIM}]+ {len(order) - max_rows} more[/]")
    if not order:
        console.print(f" [{DIM}]Nothing planned.[/]")

    totals = [Text(f"{sum(b.minutes for b in plan.on(d)) / 60:.1f}".rstrip("0").rstrip("."), DIM) for d in span]
    console.print(Text(" " + "focus hours".ljust(title_w), DIM) + cells(totals))
    legend = Text.assemble(" ", ("▆", ACCENT), (" planned focus   ", DIM), ("◆", WARN), (" deadline", DIM))
    if plan.late:
        legend.append_text(Text.assemble("   ", ("▆", WARN), (" late task", DIM)))
    if plan.events:
        legend.append_text(Text.assemble("   ", ("▃", DIM), (" calendar", DIM)))
    console.print(legend)


def to_ics(plan: Plan) -> str:
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//tend//plan//EN"]
    for i, b in enumerate(plan.blocks):
        title = b.task.title.replace(",", "\\,").replace(";", "\\;")
        lines += ["BEGIN:VEVENT", f"UID:tend-{b.task.id}-{b.start:%Y%m%dT%H%M}-{i}@tend", f"DTSTAMP:{stamp}",
                  f"DTSTART:{b.start:%Y%m%dT%H%M%S}", f"DTEND:{b.end:%Y%m%dT%H%M%S}", f"SUMMARY:{title}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
