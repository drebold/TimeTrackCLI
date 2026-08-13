from datetime import datetime


class TimeParseError(ValueError):
    pass


def parse_time_input(value: str, now: datetime) -> datetime:
    value = value.strip()
    for fmt in ("%Y-%m-%d %H:%M", "%H:%M"):
        try:
            parsed = datetime.strptime(value, fmt)
        except ValueError:
            continue
        if fmt == "%H:%M":
            parsed = parsed.replace(year=now.year, month=now.month, day=now.day)
        return parsed
    raise TimeParseError(f"Could not parse time: {value!r}")
