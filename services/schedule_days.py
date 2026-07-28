"""Shared school-day constants for schedules."""
from __future__ import annotations

from typing import Tuple

SCHOOL_DAYS: Tuple[str, ...] = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
)

ALL_DAYS: Tuple[str, ...] = (*SCHOOL_DAYS, "sunday")


def is_valid_schedule_day(day: str) -> bool:
    return day in ALL_DAYS
