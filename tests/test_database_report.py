from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import database
from config import Config


class DatabaseReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_name = Config.app_db_name
        Config.app_db_name = str(Path(self.temp_dir.name) / "report.db")
        database.init_db()

    def tearDown(self) -> None:
        Config.app_db_name = self.original_db_name
        self.temp_dir.cleanup()

    def test_reports_current_run_and_all_recent_jobs(self) -> None:
        database.upsert_job(
            {"url": "one", "company": "A", "title": "Python", "run_id": "run-one"},
            {"recommendation": "greet"},
        )
        database.update_job_status("one", final_action="greeted", greeted=True)
        database.upsert_job(
            {"url": "two", "company": "B", "title": "Java", "run_id": "run-two"},
            {"recommendation": "skip"},
        )

        current = database.job_report(run_id="run-one")
        all_jobs = database.job_report()

        self.assertEqual(current["total"], 1)
        self.assertEqual(current["greeted"], 1)
        self.assertEqual(current["outcomes"], {"greeted": 1})
        self.assertEqual(all_jobs["total"], 2)
        self.assertEqual(all_jobs["recommended"], 1)
        self.assertEqual(all_jobs["skipped"], 1)


if __name__ == "__main__":
    unittest.main()
