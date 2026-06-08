import unittest
from datetime import datetime, timezone

from embassy_bot.notifier import (
    format_appointment_time,
    format_booking_message,
    format_time_message,
)


class NotifierTests(unittest.TestCase):
    def test_format_time_message(self) -> None:
        self.assertEqual(
            format_time_message(
                [
                    datetime(2026, 7, 31, 8, 30, tzinfo=timezone.utc),
                    datetime(2026, 7, 31, 9, 0, tzinfo=timezone.utc),
                ]
            ),
            (
                "US visa appointment times available:\n"
                "- July 31, 2026 at 8:30 AM UTC\n"
                "- July 31, 2026 at 9:00 AM UTC"
            ),
        )

    def test_format_booking_message(self) -> None:
        self.assertEqual(
            format_booking_message(
                datetime(2026, 7, 31, 8, 30, tzinfo=timezone.utc),
                "Booked successfully.",
            ),
            "US visa appointment booked: July 31, 2026 at 8:30 AM UTC\nBooked successfully.",
        )

    def test_format_appointment_time(self) -> None:
        self.assertEqual(format_appointment_time(datetime(2026, 7, 31, 8, 30)), "8:30 AM")


if __name__ == "__main__":
    unittest.main()
