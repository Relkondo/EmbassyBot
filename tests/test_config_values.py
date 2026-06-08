import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from embassy_bot.config_values import load_optional_config_text


class ConfigValuesTests(unittest.TestCase):
    def test_load_optional_config_text_reads_relative_file_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            assets = root / "assets"
            assets.mkdir()
            (assets / "anchor_base64.txt").write_text(" payload \n", encoding="utf-8")
            config = SimpleNamespace(
                __file__=str(root / "config.py"),
                ANCHOR_BASE_64_FILE="assets/anchor_base64.txt",
                ANCHOR_BASE_64="inline",
            )

            value = load_optional_config_text(
                config,
                "ANCHOR_BASE_64",
                "ANCHOR_BASE_64_FILE",
            )

        self.assertEqual(value, "payload")

    def test_load_optional_config_text_falls_back_to_inline_value(self) -> None:
        config = SimpleNamespace(
            __file__="/tmp/config.py",
            ANCHOR_BASE_64_FILE="",
            ANCHOR_BASE_64=" inline ",
        )

        self.assertEqual(
            load_optional_config_text(config, "ANCHOR_BASE_64", "ANCHOR_BASE_64_FILE"),
            "inline",
        )

    def test_load_optional_config_text_returns_empty_when_unset(self) -> None:
        config = SimpleNamespace(__file__="/tmp/config.py")

        self.assertEqual(
            load_optional_config_text(config, "ANCHOR_BASE_64", "ANCHOR_BASE_64_FILE"),
            "",
        )


if __name__ == "__main__":
    unittest.main()
