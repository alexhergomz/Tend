from datetime import datetime

from tend.ics import parse

START, END = datetime(2026, 9, 28), datetime(2026, 10, 12)

CAL = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:a
SUMMARY:Lecture
DTSTART;TZID=Europe/Madrid:20260901T100000
DTEND;TZID=Europe/Madrid:20260901T113000
RRULE:FREQ=WEEKLY;BYDAY=TU,TH;UNTIL=20261231T000000Z
EXDATE;TZID=Europe/Madrid:20261001T100000
END:VEVENT
BEGIN:VEVENT
UID:a
RECURRENCE-ID;TZID=Europe/Madrid:20261006T100000
SUMMARY:Lecture (moved)
DTSTART;TZID=Europe/Madrid:20261006T150000
DTEND;TZID=Europe/Madrid:20261006T163000
END:VEVENT
BEGIN:VEVENT
UID:b
SUMMARY:Holiday
DTSTART;VALUE=DATE:20260930
DTEND;VALUE=DATE:20261001
END:VEVENT
BEGIN:VEVENT
UID:c
SUMMARY:Dentist\\, Dr. Ruiz
DTSTART:20261002T160000
DURATION:PT45M
END:VEVENT
BEGIN:VEVENT
UID:d
SUMMARY:Cancelled
STATUS:CANCELLED
DTSTART:20261002T090000
DTEND:20261002T100000
END:VEVENT
END:VCALENDAR
"""


def local(y, mo, d, h, mi, tz="Europe/Madrid"):
    from zoneinfo import ZoneInfo
    return datetime(y, mo, d, h, mi, tzinfo=ZoneInfo(tz)).astimezone().replace(tzinfo=None)


def test_recurring_with_exdate_and_override():
    events = parse(CAL, START, END)
    lectures = [e.start for e in events if e.title == "Lecture"]
    # Tue 29, (Thu Oct 1 excluded), Tue Oct 6 moved, Thu Oct 8
    assert lectures == [local(2026, 9, 29, 10, 0), local(2026, 10, 8, 10, 0)]
    moved = [e for e in events if e.title == "Lecture (moved)"]
    assert moved[0].start == local(2026, 10, 6, 15, 0)


def test_all_day_and_cancelled_are_skipped_floating_and_duration_work():
    events = parse(CAL, START, END)
    titles = [e.title for e in events]
    assert "Holiday" not in titles and "Cancelled" not in titles
    dentist = next(e for e in events if e.title.startswith("Dentist"))
    assert dentist.title == "Dentist, Dr. Ruiz"
    assert (dentist.start, dentist.end) == (datetime(2026, 10, 2, 16), datetime(2026, 10, 2, 16, 45))


def test_folded_lines():
    text = ("BEGIN:VEVENT\r\nSUMMARY:Long\r\n  title\r\n"
            "DTSTART:20260929T090000\r\nDTEND:20260929T100000\r\nEND:VEVENT\r\n")
    assert parse(text, START, END)[0].title == "Long title"
