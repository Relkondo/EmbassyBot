import unittest
from datetime import date, datetime, timezone
from http.client import RemoteDisconnected
from types import SimpleNamespace

import requests
from urllib3.exceptions import ProtocolError

from embassy_bot import client as client_module
from embassy_bot.state_store import PollState
from embassy_bot.workflow import (
    build_appointment_context,
    parse_first_month_date,
    poll_once,
    slot_window_for_first_month,
)


class FakeClient:
    def __init__(self, booking_error: Exception | None = None) -> None:
        self.calls = []
        self.booking_error = booking_error

    def get_landing_page_details(self):
        self.calls.append("GET_LANDING_PAGE_DETAILS")
        return landing_payload()

    def get_first_available_month(self, request):
        self.calls.append("FIRST_MONTH")
        return {
            "date": "2026-08-20T00:00:00.000+00:00",
            "message": "Slot is available",
            "present": True,
        }

    def get_slot_dates(self, request, from_date, to_date):
        self.calls.append(("SLOTS", from_date, to_date))
        return [
            "2026-08-20T00:00:00.000+00:00",
            "2026-08-21T00:00:00.000+00:00",
        ]

    def get_slot_times(self, request, from_date, to_date, slot_date):
        self.calls.append(("GET_TIME", from_date, to_date, slot_date))
        return [
            {
                "slotId": "slot-id",
                "slotDate": "2026-08-20T00:00:00.000+00:00",
                "startTime": "2026-08-20T08:30:00.000+00:00",
                "slotStatus": "UNBOOKED",
            }
        ]

    def reschedule_appointment(
        self,
        request,
        appointment_id,
        slot_id,
        appointment_date,
        appointment_time,
    ):
        self.calls.append(
            ("BOOKING", appointment_id, slot_id, appointment_date, appointment_time)
        )
        if self.booking_error:
            raise self.booking_error
        return [
            {
                "responseMsg": (
                    "You have made 1 successful reschedule and 9 more reschedule options "
                    "are available."
                )
            }
        ]


class FakeHttpError(RuntimeError):
    def __init__(
        self,
        message: str,
        status_code: int,
        body: str,
        url: str = "https://www.usvisaappt.com/visaadministrationapi/v1/modifyslot/getSlotDates",
    ) -> None:
        super().__init__(message)
        self.response = SimpleNamespace(
            status_code=status_code,
            text=body,
            request=SimpleNamespace(url=url),
        )


class FailingSlotsClient(FakeClient):
    def get_slot_dates(self, request, from_date, to_date):
        self.calls.append(("SLOTS", from_date, to_date))
        raise FakeHttpError("500 Server Error", 500, '{"message":"slot server error"}')


class FailingLoginClient(FakeClient):
    def get_landing_page_details(self):
        self.calls.append("GET_LANDING_PAGE_DETAILS")
        raise FakeHttpError(
            "401 Client Error",
            401,
            '{"message":"login failed"}',
            client_module.LOGIN_URL,
        )


class TransientFirstMonthClient(FakeClient):
    def get_first_available_month(self, request):
        self.calls.append("FIRST_MONTH")
        raise requests.exceptions.ConnectionError(
            ProtocolError(
                "Connection aborted.",
                RemoteDisconnected("Remote end closed connection without response"),
            )
        )


class LateFirstMonthClient(FakeClient):
    def get_first_available_month(self, request):
        self.calls.append("FIRST_MONTH")
        return {
            "date": "2026-10-01T00:00:00.000+00:00",
            "message": "Slot is available",
            "present": True,
        }


class NoFirstMonthClient(FakeClient):
    def get_first_available_month(self, request):
        self.calls.append("FIRST_MONTH")
        return {"present": False}


class FakeNotifier:
    def __init__(self) -> None:
        self.messages = []

    def send(self, message: str) -> None:
        self.messages.append(message)


class MainWorkflowTests(unittest.TestCase):
    def test_parse_first_month_date(self) -> None:
        self.assertEqual(
            parse_first_month_date(
                {
                    "date": "2026-08-20T00:00:00.000+00:00",
                    "message": "Slot is available",
                    "present": True,
                }
            ),
            date(2026, 8, 20),
        )

    def test_parse_first_month_date_absent(self) -> None:
        self.assertIsNone(parse_first_month_date({"present": False}))

    def test_slot_window_for_first_month(self) -> None:
        self.assertEqual(
            slot_window_for_first_month(date(2026, 8, 20)),
            ("2026-08-19", "2026-08-31"),
        )

    def test_poll_once_starts_with_first_month(self) -> None:
        client = FakeClient()
        notifier = FakeNotifier()

        poll_once(client, "application", None, notifier, PollState())

        today = date.today().isoformat()
        self.assertEqual(
            client.calls,
            [
                "GET_LANDING_PAGE_DETAILS",
                "FIRST_MONTH",
                ("SLOTS", "2026-08-19", "2026-08-31"),
                ("GET_TIME", today, "2026-08-31", "2026-08-20"),
            ],
        )
        self.assertEqual(len(notifier.messages), 1)
        self.assertEqual(
            notifier.messages[0],
            "US visa appointment time available:\n- August 20, 2026 at 8:30 AM UTC",
        )

    def test_poll_once_does_not_repeat_same_appointment_time(self) -> None:
        notifier = FakeNotifier()
        state = PollState()

        poll_once(FakeClient(), "application", None, notifier, state)
        poll_once(FakeClient(), "application", None, notifier, state)

        self.assertEqual(
            notifier.messages,
            ["US visa appointment time available:\n- August 20, 2026 at 8:30 AM UTC"],
        )
        self.assertEqual(
            state.announced_start_times,
            {datetime(2026, 8, 20, 8, 30, tzinfo=timezone.utc)},
        )

    def test_poll_once_reuses_landing_context_between_polls(self) -> None:
        client = FakeClient()
        notifier = FakeNotifier()
        state = PollState()

        poll_once(client, "application", None, notifier, state)
        poll_once(client, "application", None, notifier, state)

        self.assertEqual(client.calls.count("GET_LANDING_PAGE_DETAILS"), 1)
        self.assertEqual(client.calls.count("FIRST_MONTH"), 2)

    def test_poll_once_stops_after_first_month_when_date_is_after_alert_limit(self) -> None:
        client = LateFirstMonthClient()
        notifier = FakeNotifier()
        delay_calls = []

        poll_once(
            client,
            "application",
            None,
            notifier,
            PollState(),
            lambda: delay_calls.append("delay"),
        )

        self.assertEqual(client.calls, ["GET_LANDING_PAGE_DETAILS", "FIRST_MONTH"])
        self.assertEqual(delay_calls, [])
        self.assertEqual(notifier.messages, [])

    def test_poll_once_delays_between_deeper_api_calls(self) -> None:
        delay_calls = []

        poll_once(
            FakeClient(),
            "application",
            None,
            FakeNotifier(),
            PollState(),
            lambda: delay_calls.append("delay"),
        )

        self.assertEqual(delay_calls, ["delay", "delay"])

    def test_poll_once_notifies_when_appointment_time_stops_being_available(self) -> None:
        notifier = FakeNotifier()
        state = PollState()

        poll_once(FakeClient(), "application", None, notifier, state)
        poll_once(NoFirstMonthClient(), "application", None, notifier, state)

        self.assertEqual(
            notifier.messages,
            [
                "US visa appointment time available:\n- August 20, 2026 at 8:30 AM UTC",
                (
                    "US visa appointment time is no longer available:\n"
                    "- August 20, 2026 at 8:30 AM UTC"
                ),
            ],
        )
        self.assertEqual(state.announced_start_times, set())

    def test_poll_once_books_slot_before_booking_limit(self) -> None:
        client = FakeClient()
        notifier = FakeNotifier()
        state = PollState()

        poll_once(
            client,
            "application",
            date(2026, 8, 21),
            notifier,
            state,
        )

        self.assertEqual(
            client.calls,
            [
                "GET_LANDING_PAGE_DETAILS",
                "FIRST_MONTH",
                ("SLOTS", "2026-08-19", "2026-08-31"),
                ("GET_TIME", date.today().isoformat(), "2026-08-31", "2026-08-20"),
                (
                    "BOOKING",
                    2484255,
                    "slot-id",
                    "2026-08-20T00:00:00.000+00:00",
                    "8:30 AM",
                ),
            ],
        )
        self.assertEqual(
            notifier.messages[0],
            (
                "US visa appointment booking succeeded: August 20, 2026 at 8:30 AM UTC\n"
                "You have made 1 successful reschedule and 9 more reschedule options "
                "are available."
            ),
        )
        self.assertIsNone(state.appointment_context)
        self.assertEqual(state.announced_start_times, set())

    def test_poll_once_notifies_when_booking_fails(self) -> None:
        client = FakeClient(booking_error=RuntimeError("booking exploded"))
        notifier = FakeNotifier()

        poll_once(
            client,
            "application",
            date(2026, 8, 21),
            notifier,
            PollState(),
        )

        self.assertEqual(
            notifier.messages[0],
            (
                "US visa appointment booking failed: August 20, 2026 at 8:30 AM UTC\n"
                "Call: BOOKING\n"
                "Status: unavailable\n"
                "Message: booking exploded"
            ),
        )

    def test_poll_once_notifies_when_api_call_fails(self) -> None:
        client = FailingSlotsClient()
        notifier = FakeNotifier()

        with self.assertRaises(FakeHttpError):
            poll_once(
                client,
                "application",
                None,
                notifier,
                PollState(),
            )

        self.assertEqual(
            notifier.messages,
            [
                (
                    "US visa appointment polling call failed: SLOTS\n"
                    "Status: 500\n"
                    "Message: 500 Server Error\n"
                    'Body: {"message":"slot server error"}'
                )
            ],
        )

    def test_poll_once_reports_login_failure_label(self) -> None:
        client = FailingLoginClient()
        notifier = FakeNotifier()

        with self.assertRaises(FakeHttpError):
            poll_once(
                client,
                "application",
                None,
                notifier,
                PollState(),
            )

        self.assertEqual(
            notifier.messages,
            [
                (
                    "US visa appointment polling call failed: LOGIN\n"
                    "Status: 401\n"
                    "Message: 401 Client Error\n"
                    'Body: {"message":"login failed"}'
                )
            ],
        )

    def test_poll_once_suppresses_repeated_call_failures_until_success(self) -> None:
        notifier = FakeNotifier()
        state = PollState()

        with self.assertRaises(FakeHttpError):
            poll_once(
                FailingSlotsClient(),
                "application",
                None,
                notifier,
                state,
            )
        with self.assertRaises(FakeHttpError):
            poll_once(
                FailingSlotsClient(),
                "application",
                None,
                notifier,
                state,
            )

        self.assertEqual(len(notifier.messages), 1)

        poll_once(
            FakeClient(),
            "application",
            None,
            notifier,
            state,
        )
        with self.assertRaises(FakeHttpError):
            poll_once(
                FailingSlotsClient(),
                "application",
                None,
                notifier,
                state,
            )

        self.assertEqual(len(notifier.messages), 3)
        self.assertEqual(
            notifier.messages[-1],
            (
                "US visa appointment polling call failed: SLOTS\n"
                "Status: 500\n"
                "Message: 500 Server Error\n"
                'Body: {"message":"slot server error"}'
            ),
        )

    def test_poll_once_suppresses_remote_disconnected_notifications(self) -> None:
        client = TransientFirstMonthClient()
        notifier = FakeNotifier()

        with self.assertRaises(requests.exceptions.ConnectionError):
            poll_once(
                client,
                "application",
                None,
                notifier,
                PollState(),
            )

        self.assertEqual(notifier.messages, [])

    def test_build_appointment_context(self) -> None:
        context = build_appointment_context(landing_payload(), "application")

        self.assertEqual(context.appointment_id, 2484255)
        self.assertEqual(context.alert_date_limit, date(2026, 9, 15))
        self.assertEqual(context.slot_request.applicant_id, "applicant")
        self.assertEqual(context.slot_request.application_id, "application")
        self.assertEqual(context.slot_request.app_uuid, "appointment-uuid")
        self.assertEqual(context.slot_request.post_user_id, 481)
        self.assertEqual(context.slot_request.visa_type, "NIV")
        self.assertEqual(context.slot_request.visa_class, "H1B")
        self.assertEqual(context.slot_request.location_type, "POST")


def landing_payload():
    return [
        {
            "applicationId": "older-application",
            "createdDt": "2026-01-01T00:00:00.000+00:00",
            "gssApplicants": [],
        },
        {
            "applicationId": "application",
            "createdDt": "2026-06-03T13:33:02.264+00:00",
            "gssApplicants": [
                {
                    "applicantId": "applicant",
                    "appointmentDetails": [
                        {
                            "appointmentId": 2484255,
                            "applicationId": "application",
                            "appointmentUUID": "appointment-uuid",
                            "appointmentDt": "2026-09-15T00:00:00.000+00:00",
                            "appointmentType": "REGULAR_NIV",
                            "appointmentLocationType": "POST",
                            "visaClass": "H1B",
                            "postUserId": 481,
                            "ofcPostDetails": {
                                "postUserId": 481,
                            },
                        }
                    ],
                }
            ],
        },
    ]


if __name__ == "__main__":
    unittest.main()
