import re
from collections.abc import Iterable
from datetime import date
from typing import Any


DATE_RE = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")
IGNORED_DATE_KEYS = {"fromdate", "todate"}


def parse_iso_date(value: str) -> date:
    return date.fromisoformat(value)


def find_available_dates(payload: Any, before_date: date) -> list[date]:
    dates = {
        found
        for found in _walk_dates(payload)
        if found < before_date
    }
    return sorted(dates)


def _walk_dates(value: Any, key: str | None = None) -> Iterable[date]:
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            normalized = str(child_key).replace("_", "").lower()
            if normalized in IGNORED_DATE_KEYS:
                continue
            yield from _walk_dates(child_value, str(child_key))
        return

    if isinstance(value, list):
        for item in value:
            yield from _walk_dates(item, key)
        return

    if not isinstance(value, str):
        return

    for match in DATE_RE.finditer(value):
        try:
            yield parse_iso_date(match.group(1))
        except ValueError:
            continue
