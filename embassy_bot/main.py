from __future__ import annotations

import argparse
import json
import logging
import signal
import time
from datetime import date
from threading import Event

import config
from embassy_bot.client import SlotRequest, VisaAppointmentClient
from embassy_bot.config_store import persist_tokens_to_config
from embassy_bot.notifier import TelegramNotifier, format_slot_message
from embassy_bot.slots import find_available_dates


LOGGER = logging.getLogger("embassy_bot")
STOP_EVENT = Event()


def _request_stop(signum: int, _frame: object) -> None:
    LOGGER.info("Received signal %s; shutting down after current attempt", signum)
    STOP_EVENT.set()


def build_slot_request() -> SlotRequest:
    return SlotRequest(
        from_date=config.FROM_DATE,
        to_date=config.TO_DATE,
        post_user_id=config.POST_USER_ID,
        applicant_id=config.APPLICANT_ID,
        visa_type=config.VISA_TYPE,
        visa_class=config.VISA_CLASS,
        location_type=config.LOCATION_TYPE,
        application_id=getattr(config, "APP_UUID", config.APPLICATION_ID),
    )


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def build_runtime(force_login: bool = False) -> tuple[date, SlotRequest, VisaAppointmentClient, TelegramNotifier]:
    before_date = date.fromisoformat(config.CURRENT_APPOINTMENT_DATE)
    slot_request = build_slot_request()
    slot_referer = getattr(config, "SLOT_REFERER", "") or slot_request.as_referer()
    client = VisaAppointmentClient(
        username=config.USERNAME,
        password=config.PASSWORD,
        capsolver_api_key=config.CAPSOLVER_API_KEY,
        captcha_url=config.CAPTCHA_URL,
        captcha_key=config.CAPTCHA_KEY,
        timeout_seconds=config.REQUEST_TIMEOUT_SECONDS,
        authorization_token="" if force_login else getattr(config, "AUTHORIZATION_TOKEN", ""),
        refresh_token=getattr(config, "REFRESH_TOKEN", ""),
        on_tokens_updated=lambda authorization, refresh: persist_tokens_to_config(
            config.__file__,
            authorization,
            refresh,
        ),
        anchor=config.ANCHOR_BASE_64,
        reload=config.RELOAD_BASE_64,
        slot_referer=slot_referer,
    )
    notifier = TelegramNotifier(
        bot_token=config.TELEGRAM_BOT_TOKEN,
        chat_id=config.TELEGRAM_CHAT_ID,
        timeout_seconds=config.REQUEST_TIMEOUT_SECONDS,
    )
    return before_date, slot_request, client, notifier


def poll_once(
    client: VisaAppointmentClient,
    slot_request: SlotRequest,
    before_date: date,
    notifier: TelegramNotifier,
    notified_dates: set[date],
) -> None:
    payload = client.get_slot_dates(slot_request)
    LOGGER.info("SLOTS response payload: %s", json.dumps(payload, default=str))
    dates = find_available_dates(payload, before_date)
    new_dates = [day for day in dates if day not in notified_dates]

    if new_dates:
        message = format_slot_message(new_dates)
        notifier.send(message)
        notified_dates.update(new_dates)
        LOGGER.info("Found and notified for dates: %s", message)
    else:
        LOGGER.info("No new appointment dates before %s", before_date.isoformat())


def run_once(force_login: bool = False) -> None:
    configure_logging()
    before_date, slot_request, client, notifier = build_runtime(force_login=force_login)
    poll_once(client, slot_request, before_date, notifier, set())


def run_forever() -> None:
    configure_logging()
    before_date, slot_request, client, notifier = build_runtime()
    notified_dates: set[date] = set()

    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)

    LOGGER.info("Starting polling every %s seconds", config.POLL_INTERVAL_SECONDS)

    while not STOP_EVENT.is_set():
        try:
            poll_once(client, slot_request, before_date, notifier, notified_dates)
        except Exception:
            LOGGER.exception("Polling attempt failed")

        STOP_EVENT.wait(config.POLL_INTERVAL_SECONDS)

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
