import unittest
from datetime import date, datetime, timezone

from embassy_bot.slots import SlotTime, find_available_dates, find_slot_times, find_start_times


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

    def test_top_level_slot_date_strings(self) -> None:
        payload = [
            "2026-08-20T00:00:00.000+00:00",
            "2026-08-21T00:00:00.000+00:00",
            "2026-08-25T00:00:00.000+00:00",
            "2026-08-28T00:00:00.000+00:00",
        ]

        self.assertEqual(
            find_available_dates(payload, date(2026, 8, 26)),
            [
                date(2026, 8, 20),
                date(2026, 8, 21),
                date(2026, 8, 25),
            ],
        )

    def test_find_start_times(self) -> None:
        payload = [
            {
                "slotId": "slot-1",
                "slotDate": "2026-07-31T00:00:00.000+00:00",
                "startTime": "2026-07-31T08:30:00.000+00:00",
                "endTime": "2026-07-31T08:45:00.000+00:00",
                "slotStatus": "UNBOOKED",
            },
            {
                "slotId": "slot-2",
                "slotDate": "2026-07-31T00:00:00.000+00:00",
                "startTime": "2026-07-31T09:00:00.000+00:00",
            },
            {
                "slotId": "slot-3",
                "slotDate": "2026-07-31T00:00:00.000+00:00",
                "startTime": "2026-07-31T09:30:00.000+00:00",
                "slotStatus": "BOOKED",
            },
        ]

        self.assertEqual(
            find_start_times(payload),
            [
                datetime(2026, 7, 31, 8, 30, tzinfo=timezone.utc),
                datetime(2026, 7, 31, 9, 0, tzinfo=timezone.utc),
            ],
        )

    def test_find_slot_times(self) -> None:
        payload = [
            {
                "slotId": "slot-1",
                "slotDate": "2026-07-31T00:00:00.000+00:00",
                "startTime": "2026-07-31T08:30:00.000+00:00",
                "slotStatus": "UNBOOKED",
            }
        ]

        self.assertEqual(
            find_slot_times(payload),
            [
                SlotTime(
                    slot_id="slot-1",
                    slot_date=date(2026, 7, 31),
                    start_time=datetime(2026, 7, 31, 8, 30, tzinfo=timezone.utc),
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
