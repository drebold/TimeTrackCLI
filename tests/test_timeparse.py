from datetime import datetime

import pytest

from time_tracker_app.timeparse import TimeParseError, parse_time_input


def test_parses_hh_mm_using_now_date():
    now = datetime(2026, 8, 13, 12, 0, 0)
    result = parse_time_input("09:30", now)
    assert result == datetime(2026, 8, 13, 9, 30, 0)


def test_parses_full_datetime():
    now = datetime(2026, 8, 13, 12, 0, 0)
    result = parse_time_input("2026-08-10 14:15", now)
    assert result == datetime(2026, 8, 10, 14, 15, 0)


def test_raises_on_unparseable_input():
    now = datetime(2026, 8, 13, 12, 0, 0)
    with pytest.raises(TimeParseError):
        parse_time_input("not a time", now)
