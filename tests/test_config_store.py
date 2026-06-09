import tempfile
import unittest
from datetime import date
from pathlib import Path

from embassy_bot.config_store import persist_booking_date_limit_to_config, persist_tokens_to_config


class ConfigStoreTests(unittest.TestCase):
    def test_persist_tokens_rewrites_config_constants(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.py"
            config_path.write_text(
                'USERNAME = "user"\n'
                'AUTHORIZATION_TOKEN = "old"\n'
                'REFRESH_TOKEN = "old-refresh"\n',
                encoding="utf-8",
            )

            persist_tokens_to_config(str(config_path), "Bearer fresh")

            self.assertEqual(
                config_path.read_text(encoding="utf-8"),
                'USERNAME = "user"\n'
                "AUTHORIZATION_TOKEN = 'Bearer fresh'\n",
            )

    def test_persist_booking_date_limit_rewrites_config_constant(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.py"
            config_path.write_text(
                'USERNAME = "user"\n'
                'BOOKING_DATE_LIMIT = "2026-07-08"\n',
                encoding="utf-8",
            )

            persist_booking_date_limit_to_config(config_path, date(2026, 7, 5))

            self.assertEqual(
                config_path.read_text(encoding="utf-8"),
                'USERNAME = "user"\n'
                "BOOKING_DATE_LIMIT = '2026-07-05'\n",
            )


if __name__ == "__main__":
    unittest.main()
