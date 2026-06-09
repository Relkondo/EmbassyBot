from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path


LOGGER = logging.getLogger(__name__)


def persist_config_value(config_path: str | Path, name: str, value: str) -> None:
    path = Path(config_path)
    text = path.read_text(encoding="utf-8")
    assignment = f"{name} = {value!r}"
    pattern = re.compile(rf"^{name}\s*=.*$", re.MULTILINE)
    if pattern.search(text):
        text = pattern.sub(assignment, text, count=1)
    else:
        text = f"{text.rstrip()}\n{name} = {value!r}\n"

    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(path)


def persist_tokens_to_config(
    config_path: str,
    authorization_token: str,
) -> None:
    path = Path(config_path)
    text = path.read_text(encoding="utf-8")
    assignment = f"AUTHORIZATION_TOKEN = {authorization_token!r}"
    pattern = re.compile(r"^AUTHORIZATION_TOKEN\s*=.*$", re.MULTILINE)
    if pattern.search(text):
        text = pattern.sub(assignment, text, count=1)
    else:
        text = f"{text.rstrip()}\nAUTHORIZATION_TOKEN = {authorization_token!r}\n"

    text = re.sub(r"^REFRESH_TOKEN\s*=.*\n?", "", text, flags=re.MULTILINE)

    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(path)
    LOGGER.info("Persisted fresh authorization tokens to %s", path)


def persist_booking_date_limit_to_config(config_path: str | Path, booking_date_limit: date) -> None:
    persist_config_value(config_path, "BOOKING_DATE_LIMIT", booking_date_limit.isoformat())
    LOGGER.info(
        "Persisted booking date limit %s to %s",
        booking_date_limit.isoformat(),
        config_path,
    )
