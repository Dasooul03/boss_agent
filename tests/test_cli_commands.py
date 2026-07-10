from __future__ import annotations

import unittest

from cli_console import _positive_argument, _split_command


class CliCommandTests(unittest.TestCase):
    def test_splits_a_command_and_optional_argument(self) -> None:
        self.assertEqual(_split_command("  report  30  "), ("report", "30"))
        self.assertEqual(_split_command("STATUS"), ("status", ""))

    def test_parses_positive_argument_with_safe_default(self) -> None:
        self.assertEqual(_positive_argument("25", 7, 365), 25)
        self.assertEqual(_positive_argument("", 7, 365), 7)
        self.assertEqual(_positive_argument("0", 7, 365), 7)
        self.assertEqual(_positive_argument("bad", 7, 365), 7)


if __name__ == "__main__":
    unittest.main()
