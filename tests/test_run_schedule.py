from __future__ import annotations

import unittest
from datetime import datetime

from config import Config
from main import run_schedule_status


class RunScheduleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.saved = Config.as_dict()

    def tearDown(self) -> None:
        Config.apply(self.saved)

    def test_allows_weekday_peak_windows_only_when_enabled(self) -> None:
        Config.apply({**self.saved, "run_schedule_enabled": True})
        self.assertTrue(run_schedule_status(datetime(2026, 7, 13, 9, 0))["allowed"])
        self.assertTrue(run_schedule_status(datetime(2026, 7, 13, 14, 0))["allowed"])
        self.assertFalse(run_schedule_status(datetime(2026, 7, 13, 11, 0))["allowed"])
        self.assertFalse(run_schedule_status(datetime(2026, 7, 12, 9, 0))["allowed"])

    def test_disabled_schedule_never_blocks(self) -> None:
        Config.apply({**self.saved, "run_schedule_enabled": False})
        self.assertTrue(run_schedule_status(datetime(2026, 7, 12, 9, 0))["allowed"])


if __name__ == "__main__":
    unittest.main()
