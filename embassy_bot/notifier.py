from __future__ import annotations

from datetime import date

import requests


def format_slot_message(dates: list[date]) -> str:
    rendered = ", ".join(day.isoformat() for day in dates)
    plural = "appointment dates" if len(dates) != 1 else "appointment date"
    return f"US visa {plural} available: {rendered}"


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
