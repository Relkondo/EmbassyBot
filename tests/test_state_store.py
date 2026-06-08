import unittest
from datetime import datetime, timezone
from tempfile import TemporaryDirectory
from pathlib import Path

from embassy_bot.state_store import PollState, load_poll_state, save_poll_state


class StateStoreTests(unittest.TestCase):
    def test_load_missing_state_returns_empty_state(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            state = load_poll_state(Path(tmp_dir) / "missing.json")

        self.assertEqual(state.announced_start_times, set())
        self.assertEqual(state.failed_call_names, set())

    def test_save_and_load_announced_start_times(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "state.json"
            save_poll_state(
                path,
                PollState(
                    announced_start_times={
                        datetime(2026, 8, 21, 8, 30, tzinfo=timezone.utc),
                    },
                    failed_call_names={"SLOTS"},
                ),
            )

            state = load_poll_state(path)

        self.assertEqual(
            state.announced_start_times,
            {datetime(2026, 8, 21, 8, 30, tzinfo=timezone.utc)},
        )
        self.assertEqual(state.failed_call_names, set())


if __name__ == "__main__":
    unittest.main()
