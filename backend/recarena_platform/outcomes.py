"""Committed service outcomes, separate from HTTP responses."""
from dataclasses import dataclass


@dataclass
class Outcome:
    value: dict | None = None
    error: str | None = None
    status: int = 200


def rejected(code, status=409):
    return Outcome(error=code, status=status)
