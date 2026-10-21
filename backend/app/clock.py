"""Controllable UTC clock used by services and tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FrozenClock:
    """Test/demo clock that advances only when asked."""

    def __init__(self, value: datetime | None = None) -> None:
        self._value = _ensure_utc(value or datetime.now(UTC))

    def now(self) -> datetime:
        return self._value

    def advance(self, *, seconds: float = 0, minutes: float = 0, hours: float = 0) -> datetime:
        self._value += timedelta(seconds=seconds, minutes=minutes, hours=hours)
        return self._value

    def set(self, value: datetime) -> None:
        self._value = _ensure_utc(value)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def utc(value: datetime | None) -> datetime | None:
    """Normalize an optional datetime to UTC for safe serialization."""

    if value is None:
        return None
    return _ensure_utc(value)
