import unittest
from datetime import date

from embassy_bot.slots import find_available_dates


class SlotTests(unittest.TestCase):
    def test_find_available_dates_before_current_appointment(self) -> None:
        payload = {
            "fromDate": "2026-06-07",
            "toDate": "2026-08-05",
            "slotDates": [
                {"date": "2026-07-01T00:00:00"},
                {"date": "2026-08-06"},
                {"date": "2026-05-30"},
            ],
        }

        self.assertEqual(
            find_available_dates(payload, date(2026, 8, 6)),
            [
                date(2026, 5, 30),
                date(2026, 7, 1),
            ],
        )

    def test_ignores_request_echo_dates(self) -> None:
        payload = {"fromDate": "2026-06-07", "toDate": "2026-08-05"}

        self.assertEqual(find_available_dates(payload, date(2026, 8, 6)), [])


if __name__ == "__main__":
    unittest.main()
