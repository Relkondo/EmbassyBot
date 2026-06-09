from __future__ import annotations

import argparse
import logging
import random
import signal
import time
from datetime import date
from pathlib import Path
from threading import Event

import config
from embassy_bot.client import VisaAppointmentClient
from embassy_bot.config_store import persist_booking_date_limit_to_config, persist_tokens_to_config
from embassy_bot.config_values import load_optional_config_text
from embassy_bot.notifier import TelegramNotifier
from embassy_bot.state_store import DEFAULT_STATE_FILE, PollState, load_poll_state, save_poll_state
from embassy_bot.workflow import (
    is_access_temporarily_restricted,
    is_transient_remote_disconnect,
    poll_once,
)


LOGGER = logging.getLogger("embassy_bot")
STOP_EVENT = Event()
TRANSIENT_DISCONNECT_BACKOFF_SECONDS = 8 * 60
CHAIN_DELAY_MIN_SECONDS = 1.0
CHAIN_DELAY_MAX_SECONDS = 4.0


def _request_stop(signum: int, _frame: object) -> None:
    LOGGER.info("Received signal %s; shutting down after current attempt", signum)
    STOP_EVENT.set()


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def build_runtime(
    force_login: bool = False,
) -> tuple[str | None, date | None, Path, VisaAppointmentClient, TelegramNotifier]:
    configured_application_id = parse_optional_string(getattr(config, "APPLICATION_ID", ""))
    booking_date_limit = parse_optional_date(getattr(config, "BOOKING_DATE_LIMIT", ""))
    state_path = Path(getattr(config, "STATE_FILE", DEFAULT_STATE_FILE))
    if not state_path.is_absolute():
        state_path = Path(config.__file__).resolve().parent / state_path
    client = VisaAppointmentClient(
        username=config.USERNAME,
        password=config.PASSWORD,
        capsolver_api_key=config.CAPSOLVER_API_KEY,
        captcha_url=config.CAPTCHA_URL,
        captcha_key=config.CAPTCHA_KEY,
        timeout_seconds=config.REQUEST_TIMEOUT_SECONDS,
        authorization_token="" if force_login else getattr(config, "AUTHORIZATION_TOKEN", ""),
        on_tokens_updated=lambda authorization: persist_tokens_to_config(
            config.__file__,
            authorization,
        ),
        anchor=load_optional_config_text(config, "ANCHOR_BASE_64", "ANCHOR_BASE_64_FILE"),
        reload=load_optional_config_text(config, "RELOAD_BASE_64", "RELOAD_BASE_64_FILE"),
        slot_referer="",
    )
    notifier = TelegramNotifier(
        bot_token=config.TELEGRAM_BOT_TOKEN,
        chat_id=config.TELEGRAM_CHAT_ID,
        timeout_seconds=config.REQUEST_TIMEOUT_SECONDS,
    )
    return configured_application_id, booking_date_limit, state_path, client, notifier


def parse_optional_date(value: object) -> date | None:
    if value in {None, ""}:
        return None
    if not isinstance(value, str):
        raise ValueError("Optional date config values must be strings in YYYY-MM-DD format")
    return date.fromisoformat(value)


def parse_optional_string(value: object) -> str | None:
    if value in {None, ""}:
        return None
    if not isinstance(value, str):
        raise ValueError("Optional string config values must be strings")
    return value


def run_once(force_login: bool = False) -> None:
    configure_logging()
    configured_application_id, booking_date_limit, _state_path, client, notifier = build_runtime(
        force_login=force_login
    )

    def update_booking_date_limit(booked_date: date) -> None:
        persist_booking_date_limit_to_config(config.__file__, booked_date)

    poll_once(
        client,
        configured_application_id,
        booking_date_limit,
        notifier,
        PollState(),
        sleep_between_chained_calls,
        update_booking_date_limit,
    )


def run_forever() -> None:
    configure_logging()
    configured_application_id, booking_date_limit, state_path, client, notifier = build_runtime()
    state = load_poll_state(state_path)

    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)

    base_interval_seconds = getattr(config, "BASE_INTERVAL_SECONDS", 180)
    jitter_seconds = getattr(config, "JITTER_SECONDS", 45)
    LOGGER.info(
        "Starting polling every %s seconds +/- %s seconds",
        base_interval_seconds,
        jitter_seconds,
    )

    def update_booking_date_limit(booked_date: date) -> None:
        nonlocal booking_date_limit
        booking_date_limit = booked_date
        persist_booking_date_limit_to_config(config.__file__, booked_date)

    try:
        while not STOP_EVENT.is_set():
            wait_seconds = jittered_interval_seconds(base_interval_seconds, jitter_seconds)
            try:
                poll_once(
                    client,
                    configured_application_id,
                    booking_date_limit,
                    notifier,
                    state,
                    sleep_between_chained_calls,
                    update_booking_date_limit,
                )
            except Exception as exc:
                if is_access_temporarily_restricted(exc):
                    LOGGER.exception("Access temporarily restricted; stopping polling")
                    STOP_EVENT.set()
                    break
                if is_transient_remote_disconnect(exc):
                    wait_seconds = TRANSIENT_DISCONNECT_BACKOFF_SECONDS
                    LOGGER.exception(
                        "Polling attempt failed due to transient remote disconnect; "
                        "waiting %s seconds before retry",
                        wait_seconds,
                    )
                else:
                    LOGGER.exception("Polling attempt failed")

            if STOP_EVENT.is_set():
                break
            LOGGER.info("Waiting %.1f seconds before next poll", wait_seconds)
            STOP_EVENT.wait(wait_seconds)
    finally:
        save_poll_state(state_path, state)
        LOGGER.info("Stopped polling")


def jittered_interval_seconds(base_interval_seconds: int, jitter_seconds: int) -> float:
    if jitter_seconds <= 0:
        return float(base_interval_seconds)
    return max(
        1.0,
        float(base_interval_seconds + random.uniform(-jitter_seconds, jitter_seconds)),
    )


def sleep_between_chained_calls() -> None:
    delay_seconds = random.uniform(CHAIN_DELAY_MIN_SECONDS, CHAIN_DELAY_MAX_SECONDS)
    LOGGER.info("Waiting %.1f seconds before next chained appointment API call", delay_seconds)
    time.sleep(delay_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Poll US visa appointment availability")
    parser.add_argument(
        "--once",
        action="store_true",
        help="login, poll once, notify if a matching appointment exists, then exit",
    )
    parser.add_argument(
        "--force-login",
        action="store_true",
        help="ignore configured authorization token and perform a fresh login first",
    )
    args = parser.parse_args()

    if args.once:
        run_once(force_login=args.force_login)
    else:
        run_forever()


if __name__ == "__main__":
    main()
