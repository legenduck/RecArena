"""Millisecond timestamps shared by review preparation and pop configuration."""
from datetime import datetime, timezone

DAY_MS = 86_400_000
DEFAULT_TAU = '2022-07-13T02:46:01.348Z'


def milliseconds(value):
    if isinstance(value, bool):
        raise ValueError('Timestamp must be integer milliseconds or a timezone-aware ISO date')
    if isinstance(value, int):
        return value
    date = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
    if not isinstance(date, datetime) or date.tzinfo is None or date.utcoffset() is None or date.microsecond % 1000:
        raise ValueError('Timestamp requires a timezone and millisecond precision')
    delta = date.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return delta.days * DAY_MS + delta.seconds * 1000 + delta.microseconds // 1000


def normalize_tau(value):
    if not isinstance(value, str):
        raise ValueError('tau must be a timezone-aware ISO timestamp')
    milliseconds(value)
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
