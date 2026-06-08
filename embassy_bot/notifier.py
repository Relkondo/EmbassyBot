from __future__ import annotations

from datetime import date, datetime, timezone

import requests


def format_slot_message(dates: list[date]) -> str:
    rendered = ", ".join(day.isoformat() for day in dates)
    plural = "appointment dates" if len(dates) != 1 else "appointment date"
    return f"US visa {plural} available: {rendered}"


def format_time_message(start_times: list[datetime]) -> str:
    rendered = "\n".join(f"- {format_start_time(start_time)}" for start_time in start_times)
    plural = "appointment times" if len(start_times) != 1 else "appointment time"
    return f"US visa {plural} available:\n{rendered}"


def format_booking_message(start_time: datetime, response_message: str | None = None) -> str:
    message = f"US visa appointment booked: {format_start_time(start_time)}"
    if response_message:
        message = f"{message}\n{response_message}"
    return message


def format_start_time(start_time: datetime) -> str:
    if start_time.tzinfo is not None:
        start_time = start_time.astimezone(timezone.utc)
        suffix = " UTC"
    else:
        suffix = ""

    hour = start_time.hour % 12 or 12
    period = "AM" if start_time.hour < 12 else "PM"
    return (
        f"{start_time.strftime('%B')} {start_time.day}, {start_time.year} "
        f"at {hour}:{start_time.minute:02d} {period}{suffix}"
    )


def format_appointment_time(start_time: datetime) -> str:
    hour = start_time.hour % 12 or 12
    period = "AM" if start_time.hour < 12 else "PM"
    return f"{hour}:{start_time.minute:02d} {period}"


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str, timeout_seconds: int = 30) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.timeout_seconds = timeout_seconds

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def send(self, message: str) -> None:
        if not self.is_configured:
            return

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        response = requests.post(
            url,
            json={"chat_id": self.chat_id, "text": message},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
