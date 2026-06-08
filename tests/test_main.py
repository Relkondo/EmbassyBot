import unittest
from datetime import date

from embassy_bot.main import (
    build_appointment_context,
    parse_first_month_date,
    poll_once,
    slot_window_for_first_month,
)


class FakeClient:
    def __init__(self) -> None:
        self.calls = []

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
        return [
            {
                "responseMsg": (
                    "You have made 1 successful reschedule and 9 more reschedule options "
                    "are available."
                )
            }
        ]


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

        poll_once(client, "application", None, notifier, set())

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

    def test_poll_once_books_slot_before_booking_limit(self) -> None:
        client = FakeClient()
        notifier = FakeNotifier()

        poll_once(
            client,
            "application",
            date(2026, 8, 21),
            notifier,
            set(),
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
                "US visa appointment booked: August 20, 2026 at 8:30 AM UTC\n"
                "You have made 1 successful reschedule and 9 more reschedule options "
                "are available."
            ),
        )

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
