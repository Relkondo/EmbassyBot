from __future__ import annotations

import json
import logging
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable, TypeVar

from embassy_bot import client as client_module
from embassy_bot.client import SlotRequest, VisaAppointmentClient
from embassy_bot.notifier import (
    TelegramNotifier,
    format_appointment_time,
    format_booking_failure_message,
    format_booking_message,
    format_call_failure_message,
    format_time_message,
    format_time_unavailable_message,
)
from embassy_bot.slots import SlotTime, find_available_dates, find_slot_times
from embassy_bot.state_store import PollState


LOGGER = logging.getLogger("embassy_bot")
MAX_TELEGRAM_FAILURE_BODY_LENGTH = 1000
T = TypeVar("T")
URL_FAILURE_LABELS = {
    client_module.LOGIN_URL: "LOGIN",
    client_module.LANDING_PAGE_DETAILS_URL: "GET_LANDING_PAGE_DETAILS",
    client_module.FIRST_MONTH_URL: "FIRST_MONTH",
    client_module.SLOT_URL: "SLOTS",
    client_module.GET_TIME_URL: "GET_TIME",
    client_module.RESCHEDULE_URL: "BOOKING",
}


@dataclass(frozen=True)
class AppointmentContext:
    slot_request: SlotRequest
    appointment_id: int
    alert_date_limit: date


@dataclass(frozen=True)
class FailureDetails:
    status_code: int | None
    message: str
    response_body: str | None


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
    state: PollState,
) -> None:
    appointment_context = get_appointment_context(
        client,
        configured_application_id,
        notifier,
        state,
    )
    slot_request = appointment_context.slot_request
    alert_date_limit = appointment_context.alert_date_limit
    appointment_id = appointment_context.appointment_id
    client.slot_referer = slot_request.as_referer()

    first_month_payload = call_or_notify(
        "FIRST_MONTH",
        notifier,
        state,
        lambda: client.get_first_available_month(slot_request),
    )
    LOGGER.info("FIRST_MONTH response payload: %s", json.dumps(first_month_payload, default=str))
    first_month_date = parse_first_month_date(first_month_payload)
    if not first_month_date:
        LOGGER.info("No first available month returned")
        notify_availability_changes([], state.announced_start_times, notifier)
        return

    if first_month_date > alert_date_limit:
        LOGGER.info(
            "First available appointment date %s is after alert limit %s",
            first_month_date.isoformat(),
            alert_date_limit.isoformat(),
        )
        notify_availability_changes([], state.announced_start_times, notifier)
        return

    from_date, to_date = slot_window_for_first_month(first_month_date)
    payload = call_or_notify(
        "SLOTS",
        notifier,
        state,
        lambda: client.get_slot_dates(slot_request, from_date, to_date),
    )
    LOGGER.info("SLOTS response payload: %s", json.dumps(payload, default=str))
    dates = find_available_dates(payload, date.max)
    if not dates:
        LOGGER.info("No appointment dates returned by SLOTS")
        notify_availability_changes([], state.announced_start_times, notifier)
        return

    earliest_date = dates[0]
    if earliest_date > alert_date_limit:
        LOGGER.info(
            "Earliest SLOTS appointment date %s is after alert limit %s",
            earliest_date.isoformat(),
            alert_date_limit.isoformat(),
        )
        notify_availability_changes([], state.announced_start_times, notifier)
        return

    today = date.today()
    time_to_date = month_end(earliest_date)
    time_payload = call_or_notify(
        "GET_TIME",
        notifier,
        state,
        lambda: client.get_slot_times(
            slot_request,
            today.isoformat(),
            time_to_date.isoformat(),
            earliest_date.isoformat(),
        ),
    )
    LOGGER.info("GET_TIME response payload: %s", json.dumps(time_payload, default=str))
    slot_times = find_slot_times(time_payload)
    start_times = unique_start_times(slot_times)

    if start_times:
        booking_slot = first_bookable_slot(slot_times, booking_date_limit)
        if booking_slot:
            notify_booking_attempt(client, slot_request, appointment_id, booking_slot, notifier, state)
        else:
            notify_availability_changes(start_times, state.announced_start_times, notifier)
    else:
        LOGGER.info("No appointment start times returned by GET_TIME")
        notify_availability_changes([], state.announced_start_times, notifier)


def get_appointment_context(
    client: VisaAppointmentClient,
    configured_application_id: str | None,
    notifier: TelegramNotifier,
    state: PollState,
) -> AppointmentContext:
    if isinstance(state.appointment_context, AppointmentContext):
        LOGGER.info("Using cached appointment context")
        return state.appointment_context

    landing_payload = call_or_notify(
        "GET_LANDING_PAGE_DETAILS",
        notifier,
        state,
        client.get_landing_page_details,
    )
    LOGGER.info("GET_LANDING_PAGE_DETAILS response payload: %s", json.dumps(landing_payload, default=str))
    appointment_context = build_appointment_context(landing_payload, configured_application_id)
    state.appointment_context = appointment_context
    return appointment_context


def notify_booking_attempt(
    client: VisaAppointmentClient,
    slot_request: SlotRequest,
    appointment_id: int,
    booking_slot: SlotTime,
    notifier: TelegramNotifier,
    state: PollState,
) -> None:
    try:
        booking_payload = client.reschedule_appointment(
            slot_request,
            appointment_id,
            booking_slot.slot_id,
            slot_date_to_api_datetime(booking_slot),
            format_appointment_time(booking_slot.start_time),
        )
    except Exception as exc:
        LOGGER.exception("BOOKING attempt failed")
        failure = extract_failure_details(exc)
        if "BOOKING" in state.failed_call_names:
            return
        state.failed_call_names.add("BOOKING")
        notifier.send(
            format_booking_failure_message(
                booking_slot.start_time,
                failure.message,
                failure.status_code,
                failure.response_body,
            )
        )
        return

    state.failed_call_names.discard("BOOKING")
    state.appointment_context = None
    state.announced_start_times.clear()
    LOGGER.info("BOOKING response payload: %s", json.dumps(booking_payload, default=str))
    message = format_booking_message(
        booking_slot.start_time,
        find_response_message(booking_payload),
    )
    notifier.send(message)
    LOGGER.info("Found and notified for booking: %s", message)


def unique_start_times(slot_times: list[SlotTime]) -> list[datetime]:
    return sorted({slot_time.start_time for slot_time in slot_times})


def notify_availability_changes(
    current_start_times: list[datetime],
    announced_start_times: set[datetime],
    notifier: TelegramNotifier,
) -> None:
    current = set(current_start_times)
    stopped = sorted(announced_start_times - current)
    if stopped:
        message = format_time_unavailable_message(stopped)
        notifier.send(message)
        LOGGER.info("Notified for no longer available times: %s", message)

    new = sorted(current - announced_start_times)
    if new:
        message = format_time_message(new)
        notifier.send(message)
        LOGGER.info("Notified for newly available times: %s", message)

    announced_start_times.clear()
    announced_start_times.update(current)


def call_or_notify(
    call_name: str,
    notifier: TelegramNotifier,
    state: PollState,
    callback: Callable[[], T],
) -> T:
    try:
        result = callback()
    except Exception as exc:
        failed_call_name = infer_failed_call_name(call_name, exc)
        failure = extract_failure_details(exc)
        if should_notify_call_failure(failure):
            notify_call_failure(
                failed_call_name,
                failure.status_code,
                failure.message,
                failure.response_body,
                notifier,
                state.failed_call_names,
            )
        else:
            LOGGER.warning(
                "Suppressed Telegram notification for transient %s failure: %s",
                failed_call_name,
                failure.message,
            )
        raise

    state.failed_call_names.discard(call_name)
    return result


def should_notify_call_failure(failure: FailureDetails) -> bool:
    if failure.status_code is not None:
        return True

    message = failure.message
    return not (
        "Connection aborted" in message
        and "RemoteDisconnected" in message
        and "Remote end closed connection without response" in message
    )


def notify_call_failure(
    call_name: str,
    status_code: int | None,
    message: str,
    response_body: str | None,
    notifier: TelegramNotifier,
    failed_call_names: set[str],
) -> None:
    if call_name in failed_call_names:
        return
    notifier.send(
        format_call_failure_message(
            call_name,
            status_code,
            message,
            response_body,
        )
    )
    failed_call_names.add(call_name)


def extract_failure_details(exc: Exception) -> FailureDetails:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    reason = getattr(response, "reason", None)
    message = str(exc) or (str(reason) if reason else exc.__class__.__name__)
    response_body = getattr(response, "text", None)
    if isinstance(response_body, str):
        response_body = response_body[:MAX_TELEGRAM_FAILURE_BODY_LENGTH].replace("\n", "\\n")
    else:
        response_body = None
    return FailureDetails(
        status_code=status_code if isinstance(status_code, int) else None,
        message=message,
        response_body=response_body,
    )


def infer_failed_call_name(default_call_name: str, exc: Exception) -> str:
    response = getattr(exc, "response", None)
    request = getattr(response, "request", None)
    url = getattr(request, "url", "")
    if isinstance(url, str):
        for known_url, label in URL_FAILURE_LABELS.items():
            if url.startswith(known_url):
                return label
    return default_call_name


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
