import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


DATE_RE = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")
IGNORED_DATE_KEYS = {"fromdate", "todate"}


@dataclass(frozen=True)
class SlotTime:
    slot_id: str
    slot_date: date
    start_time: datetime


def parse_iso_date(value: str) -> date:
    return date.fromisoformat(value)


def parse_iso_datetime(value: str) -> datetime:
    if value.endswith("Z"):
        value = f"{value[:-1]}+00:00"
    return datetime.fromisoformat(value)


def find_available_dates(payload: Any, before_date: date) -> list[date]:
    dates = {
        found
        for found in _walk_dates(payload)
        if found < before_date
    }
    return sorted(dates)


def find_slot_times(payload: Any) -> list[SlotTime]:
    slots = {
        found
        for found in _walk_slot_times(payload)
    }
    return sorted(slots, key=lambda slot: slot.start_time)


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


def _walk_slot_times(value: Any) -> Iterable[SlotTime]:
    if isinstance(value, list):
        for item in value:
            yield from _walk_slot_times(item)
        return

    if not isinstance(value, dict):
        return

    slot_status = value.get("slotStatus")
    if slot_status not in {None, "UNBOOKED"}:
        return

    slot_id = value.get("slotId")
    start_time = value.get("startTime")
    slot_date = value.get("slotDate") or value.get("date")
    if not all(isinstance(item, str) for item in (slot_id, start_time, slot_date)):
        return

    try:
        parsed_start_time = parse_iso_datetime(start_time)
        parsed_slot_date = parse_iso_date(slot_date[:10])
    except ValueError:
        return

    yield SlotTime(
        slot_id=slot_id,
        slot_date=parsed_slot_date,
        start_time=parsed_start_time,
    )
