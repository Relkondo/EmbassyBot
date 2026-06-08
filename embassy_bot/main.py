from __future__ import annotations

import argparse
import json
import logging
import signal
import time
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from threading import Event
from typing import Any

import config
from embassy_bot.client import SlotRequest, VisaAppointmentClient
from embassy_bot.config_store import persist_tokens_to_config
from embassy_bot.notifier import (
    TelegramNotifier,
    format_appointment_time,
    format_booking_message,
    format_time_message,
)
from embassy_bot.slots import SlotTime, find_available_dates, find_slot_times


LOGGER = logging.getLogger("embassy_bot")
STOP_EVENT = Event()


@dataclass(frozen=True)
class AppointmentContext:
    slot_request: SlotRequest
    appointment_id: int
    alert_date_limit: date


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
) -> tuple[str | None, date | None, VisaAppointmentClient, TelegramNotifier]:
    configured_application_id = parse_optional_string(getattr(config, "APPLICATION_ID", ""))
    booking_date_limit = parse_optional_date(getattr(config, "BOOKING_DATE_LIMIT", ""))
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
        slot_referer="",
        correlation_key="",
    )
    notifier = TelegramNotifier(
        bot_token=config.TELEGRAM_BOT_TOKEN,
        chat_id=config.TELEGRAM_CHAT_ID,
        timeout_seconds=config.REQUEST_TIMEOUT_SECONDS,
    )
    return configured_application_id, booking_date_limit, client, notifier


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


def parse_first_month_date(payload: object) -> date | None:
    if not isinstance(payload, dict):
        return None
    if payload.get("present") is False:
        return None
    value = payload.get("date")
    if not isinstance(value, str):
        return None
    return date.fromisoformat(value[:10])


def slot_window_for_first_month(first_month_date: date) -> tuple[str, str]:
    from_date = first_month_date - timedelta(days=1)
    last_day = monthrange(first_month_date.year, first_month_date.month)[1]
    to_date = date(first_month_date.year, first_month_date.month, last_day)
    return from_date.isoformat(), to_date.isoformat()


def month_end(day: date) -> date:
    last_day = monthrange(day.year, day.month)[1]
    return date(day.year, day.month, last_day)


def poll_once(
    client: VisaAppointmentClient,
    configured_application_id: str | None,
    booking_date_limit: date | None,
    notifier: TelegramNotifier,
    notified_dates: set[date],
) -> None:
    landing_payload = client.get_landing_page_details()
    LOGGER.info("GET_LANDING_PAGE_DETAILS response payload: %s", json.dumps(landing_payload, default=str))
    appointment_context = build_appointment_context(landing_payload, configured_application_id)
    slot_request = appointment_context.slot_request
    alert_date_limit = appointment_context.alert_date_limit
    appointment_id = appointment_context.appointment_id
    client.slot_referer = slot_request.as_referer()

    first_month_payload = client.get_first_available_month(slot_request)
    LOGGER.info("FIRST_MONTH response payload: %s", json.dumps(first_month_payload, default=str))
    first_month_date = parse_first_month_date(first_month_payload)
    if not first_month_date:
        LOGGER.info("No first available month returned")
        return

    if first_month_date > alert_date_limit:
        LOGGER.info(
            "First available appointment date %s is after alert limit %s",
            first_month_date.isoformat(),
            alert_date_limit.isoformat(),
        )
        return

    from_date, to_date = slot_window_for_first_month(first_month_date)
    payload = client.get_slot_dates(slot_request, from_date, to_date)
    LOGGER.info("SLOTS response payload: %s", json.dumps(payload, default=str))
    dates = find_available_dates(payload, date.max)
    if not dates:
        LOGGER.info("No appointment dates returned by SLOTS")
        return

    earliest_date = dates[0]
    if earliest_date > alert_date_limit:
        LOGGER.info(
            "Earliest SLOTS appointment date %s is after alert limit %s",
            earliest_date.isoformat(),
            alert_date_limit.isoformat(),
        )
        return

    if earliest_date in notified_dates:
        LOGGER.info("Already notified for earliest appointment date %s", earliest_date.isoformat())
        return

    today = date.today()
    time_to_date = month_end(earliest_date)
    time_payload = client.get_slot_times(
        slot_request,
        today.isoformat(),
        time_to_date.isoformat(),
        earliest_date.isoformat(),
    )
    LOGGER.info("GET_TIME response payload: %s", json.dumps(time_payload, default=str))
    slot_times = find_slot_times(time_payload)
    start_times = [slot_time.start_time for slot_time in slot_times]

    if start_times:
        booking_slot = first_bookable_slot(slot_times, booking_date_limit)
        if booking_slot:
            if appointment_id is None:
                raise ValueError("GET_LANDING_PAGE_DETAILS must return appointmentId before booking")
            booking_payload = client.reschedule_appointment(
                slot_request,
                appointment_id,
                booking_slot.slot_id,
                slot_date_to_api_datetime(booking_slot),
                format_appointment_time(booking_slot.start_time),
            )
            LOGGER.info("BOOKING response payload: %s", json.dumps(booking_payload, default=str))
            message = format_booking_message(
                booking_slot.start_time,
                find_response_message(booking_payload),
            )
        else:
            message = format_time_message(start_times)
        notifier.send(message)
        notified_dates.add(earliest_date)
        LOGGER.info("Found and notified for dates: %s", message)
    else:
        LOGGER.info("No appointment start times returned by GET_TIME")


def first_bookable_slot(
    slot_times: list[SlotTime],
    booking_date_limit: date | None,
) -> SlotTime | None:
    if booking_date_limit is None:
        return None
    for slot_time in slot_times:
        if slot_time.slot_date < booking_date_limit:
            return slot_time
    return None


def slot_date_to_api_datetime(slot_time: SlotTime) -> str:
    return f"{slot_time.slot_date.isoformat()}T00:00:00.000+00:00"


def find_response_message(payload: object) -> str | None:
    if isinstance(payload, list):
        for item in payload:
            message = find_response_message(item)
            if message:
                return message
        return None

    if not isinstance(payload, dict):
        return None

    value = payload.get("responseMsg") or payload.get("responseMessage")
    if isinstance(value, str) and value:
        return value
    return None


def build_appointment_context(
    payload: object,
    configured_application_id: str | None,
) -> AppointmentContext:
    application = select_landing_application(payload, configured_application_id)
    applicant, appointment = find_current_appointment(application)
    ofc_post_details = appointment.get("ofcPostDetails") if isinstance(appointment.get("ofcPostDetails"), dict) else {}

    application_id = require_string(appointment.get("applicationId") or application.get("applicationId"), "applicationId")
    applicant_id = require_string(applicant.get("applicantId") or appointment.get("applicantId"), "applicantId")
    appointment_uuid = require_string(appointment.get("appointmentUUID"), "appointmentUUID")
    appointment_id = require_int(appointment.get("appointmentId"), "appointmentId")
    post_user_id = require_int(
        ofc_post_details.get("postUserId") or appointment.get("postUserId"),
        "postUserId",
    )
    appointment_date = require_date(appointment.get("appointmentDt"), "appointmentDt")
    appointment_type = require_string(appointment.get("appointmentType"), "appointmentType")
    location_type = require_string(appointment.get("appointmentLocationType"), "appointmentLocationType")
    visa_class = require_string(appointment.get("visaClass"), "visaClass")

    return AppointmentContext(
        slot_request=SlotRequest(
            post_user_id=post_user_id,
            applicant_id=applicant_id,
            visa_type=visa_type_from_appointment_type(appointment_type),
            visa_class=visa_class,
            location_type=location_type,
            application_id=application_id,
            app_uuid=appointment_uuid,
        ),
        appointment_id=appointment_id,
        alert_date_limit=appointment_date,
    )


def select_landing_application(
    payload: object,
    configured_application_id: str | None,
) -> dict[str, Any]:
    if not isinstance(payload, list):
        raise ValueError("GET_LANDING_PAGE_DETAILS response must be a list")

    applications = [item for item in payload if isinstance(item, dict)]
    if not applications:
        raise ValueError("GET_LANDING_PAGE_DETAILS returned no applications")

    if configured_application_id:
        for application in applications:
            if application.get("applicationId") == configured_application_id:
                return application
        raise ValueError(f"GET_LANDING_PAGE_DETAILS returned no applicationId {configured_application_id}")

    return max(applications, key=landing_application_created_at)


def landing_application_created_at(application: dict[str, Any]) -> datetime:
    value = application.get("createdDt")
    if not isinstance(value, str):
        return datetime.min
    try:
        return parse_api_datetime(value)
    except ValueError:
        return datetime.min


def find_current_appointment(application: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    applicants = application.get("gssApplicants")
    if not isinstance(applicants, list):
        raise ValueError("Selected landing application has no gssApplicants list")

    for applicant in applicants:
        if not isinstance(applicant, dict):
            continue
        appointments = applicant.get("appointmentDetails")
        if not isinstance(appointments, list):
            continue
        for appointment in appointments:
            if isinstance(appointment, dict):
                return applicant, appointment

    raise ValueError("Selected landing application has no appointmentDetails")


def visa_type_from_appointment_type(appointment_type: str) -> str:
    parts = appointment_type.split("_")
    return parts[1] if len(parts) > 1 else appointment_type


def require_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"GET_LANDING_PAGE_DETAILS missing {field_name}")
    return value


def require_int(value: object, field_name: str) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    raise ValueError(f"GET_LANDING_PAGE_DETAILS missing {field_name}")


def require_date(value: object, field_name: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"GET_LANDING_PAGE_DETAILS missing {field_name}")
    return date.fromisoformat(value[:10])


def parse_api_datetime(value: str) -> datetime:
    if value.endswith("Z"):
        value = f"{value[:-1]}+00:00"
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=None)


def run_once(force_login: bool = False) -> None:
    configure_logging()
    configured_application_id, booking_date_limit, client, notifier = build_runtime(force_login=force_login)
    poll_once(
        client,
        configured_application_id,
        booking_date_limit,
        notifier,
        set(),
    )


def run_forever() -> None:
    configure_logging()
    configured_application_id, booking_date_limit, client, notifier = build_runtime()
    notified_dates: set[date] = set()

    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)

    LOGGER.info("Starting polling every %s seconds", config.POLL_INTERVAL_SECONDS)

    while not STOP_EVENT.is_set():
        try:
            poll_once(
                client,
                configured_application_id,
                booking_date_limit,
                notifier,
                notified_dates,
            )
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
