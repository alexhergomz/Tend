from datetime import date

import pytest

from tend.parse import ParseError, parse_date, parse_duration, parse_tokens

TODAY = date(2026, 9, 29)  # a Tuesday


@pytest.mark.parametrize("text,expected", [
    ("today", TODAY), ("tom", date(2026, 9, 30)), ("fri", date(2026, 10, 2)),
    ("tue", TODAY), ("monday", date(2026, 10, 5)), ("+3d", date(2026, 10, 2)),
    ("2w", date(2026, 10, 13)), ("oct20", date(2026, 10, 20)), ("20oct", date(2026, 10, 20)),
    ("10-20", date(2026, 10, 20)), ("2027-01-05", date(2027, 1, 5)), ("jan5", date(2027, 1, 5)),
    ("eow", date(2026, 10, 4)), ("eom", date(2026, 9, 30)), ("1st", date(2026, 10, 1)), ("29th", TODAY),
])
def test_dates(text, expected):
    assert parse_date(text, TODAY) == expected


def test_bad_date():
    with pytest.raises(ParseError):
        parse_date("someday", TODAY)


@pytest.mark.parametrize("text,minutes", [("45m", 45), ("45", 45), ("2h", 120), ("1h30m", 90), ("1.5h", 90)])
def test_durations(text, minutes):
    assert parse_duration(text) == minutes


def test_tokens():
    title, f = parse_tokens(["write ch.2 intro", "+Thesis", "due:fri", "v:3", "e:2h"], TODAY)
    assert title == "write ch.2 intro"
    assert f == {"goal": "thesis", "due": date(2026, 10, 2), "value": 3, "estimate_min": 120, "size": "M"}


def test_shell_unsafe_aliases_and_clearing():
    title, f = parse_tokens(["call mom !2 ~20m aim:none s:L"], TODAY)
    assert title == "call mom" and f == {"value": 2, "estimate_min": 20, "aim": None, "size": "L"}
