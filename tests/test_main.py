import unittest
from datetime import date

from embassy_bot.main import parse_first_month_date, slot_window_for_first_month


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


if __name__ == "__main__":
    unittest.main()
