import unittest
from datetime import date

from embassy_bot.main import parse_first_month_date, poll_once, slot_window_for_first_month


class FakeClient:
    def __init__(self) -> None:
        self.calls = []

    def get_user(self):
        self.calls.append("GET_USER")
        return {"user": "ok"}

    def get_first_available_month(self, request):
        self.calls.append("FIRST_MONTH")
        return {
            "date": "2026-08-20T00:00:00.000+00:00",
            "message": "Slot is available",
            "present": True,
        }

    def get_slot_dates(self, request, from_date, to_date):
        self.calls.append(("SLOTS", from_date, to_date))
        return ["2026-08-20T00:00:00.000+00:00"]


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

    def test_poll_once_gets_user_before_first_month(self) -> None:
        client = FakeClient()
        notifier = FakeNotifier()

        poll_once(client, object(), date(2026, 9, 15), notifier, set())

        self.assertEqual(
            client.calls,
            ["GET_USER", "FIRST_MONTH", ("SLOTS", "2026-08-19", "2026-08-31")],
        )
        self.assertEqual(len(notifier.messages), 1)


if __name__ == "__main__":
    unittest.main()
