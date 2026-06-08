from __future__ import annotations

import argparse
import logging
import signal
from datetime import date
from pathlib import Path
from threading import Event

import config
from embassy_bot.client import VisaAppointmentClient
from embassy_bot.config_store import persist_tokens_to_config
from embassy_bot.notifier import TelegramNotifier
from embassy_bot.state_store import DEFAULT_STATE_FILE, PollState, load_poll_state, save_poll_state
from embassy_bot.workflow import poll_once


LOGGER = logging.getLogger("embassy_bot")
STOP_EVENT = Event()


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
        anchor=config.ANCHOR_BASE_64,
        reload=config.RELOAD_BASE_64,
        slot_referer="",
        correlation_key="",
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
    configured_application_id, booking_date_limit, _state_path, client, notifier = build_runtime(force_login=force_login)
    poll_once(
        client,
        configured_application_id,
        booking_date_limit,
        notifier,
        PollState(),
    )


def run_forever() -> None:
    configure_logging()
    configured_application_id, booking_date_limit, state_path, client, notifier = build_runtime()
    state = load_poll_state(state_path)

    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)

    LOGGER.info("Starting polling every %s seconds", config.POLL_INTERVAL_SECONDS)

    try:
        while not STOP_EVENT.is_set():
            try:
                poll_once(
                    client,
                    configured_application_id,
                    booking_date_limit,
                    notifier,
                    state,
                )
            except Exception:
                LOGGER.exception("Polling attempt failed")

            STOP_EVENT.wait(config.POLL_INTERVAL_SECONDS)
    finally:
        save_poll_state(state_path, state)
        LOGGER.info("Stopped polling")


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
