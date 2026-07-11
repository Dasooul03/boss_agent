from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from main import app


class DashboardTests(unittest.TestCase):
    def test_dashboard_page_is_served(self) -> None:
        with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
            response = client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("BossAgent 控制台", response.text)
        self.assertIn("语义筛选", response.text)


if __name__ == "__main__":
    unittest.main()
