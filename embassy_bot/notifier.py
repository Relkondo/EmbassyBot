from __future__ import annotations

from datetime import datetime, timezone

import requests


def format_time_message(start_times: list[datetime]) -> str:
    start_times = sorted(set(start_times))
    rendered = "\n".join(f"- {format_start_time(start_time)}" for start_time in start_times)
    plural = "appointment times" if len(start_times) != 1 else "appointment time"
    return f"US visa {plural} available:\n{rendered}"


def format_time_unavailable_message(start_times: list[datetime]) -> str:
    start_times = sorted(set(start_times))
    rendered = "\n".join(f"- {format_start_time(start_time)}" for start_time in start_times)
    plural = "appointment times are" if len(start_times) != 1 else "appointment time is"
    return f"US visa {plural} no longer available:\n{rendered}"


def format_booking_message(start_time: datetime, response_message: str | None = None) -> str:
    message = f"US visa appointment booking succeeded: {format_start_time(start_time)}"
    if response_message:
        message = f"{message}\n{response_message}"
    return message


def format_booking_failure_message(
    start_time: datetime,
    error_message: str,
    status_code: int | None = None,
    response_body: str | None = None,
) -> str:
    return (
        f"US visa appointment booking failed: {format_start_time(start_time)}\n"
        f"Call: BOOKING\n"
        f"{format_failure_details(status_code, error_message, response_body)}"
    )


def format_call_failure_message(
    call_name: str,
    status_code: int | None,
    error_message: str,
    response_body: str | None = None,
) -> str:
    return (
        f"US visa appointment polling call failed: {call_name}\n"
        f"{format_failure_details(status_code, error_message, response_body)}"
    )


def format_failure_details(
    status_code: int | None,
    error_message: str,
    response_body: str | None = None,
) -> str:
    status = str(status_code) if status_code is not None else "unavailable"
    message = f"Status: {status}\nMessage: {error_message or '<empty>'}"
    if response_body:
        message = f"{message}\nBody: {response_body}"
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
