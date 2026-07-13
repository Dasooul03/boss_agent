from __future__ import annotations

import unittest
from unittest.mock import patch

from config import Config
from decision_service import evaluate_preflight


class PreflightDecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.saved = Config.as_dict()
        Config.apply({
            **self.saved,
            "skip_contacted_companies": True,
            "job_filter_cities": ["上海"],
            "job_filter_title_keywords": [],
            "job_filter_target_roles": [],
            "job_filter_blocked_companies": [],
            "job_filter_employment_type": "any",
            "job_filter_salary_min_k": 0,
            "job_filter_salary_max_k": 0,
            "max_contacts_per_company": 1,
        })

    def tearDown(self) -> None:
        Config.apply(self.saved)

    def test_page_contacted_has_priority_over_other_filters(self) -> None:
        decision = evaluate_preflight({"talked": True, "talked_reason": "已沟通", "city": "北京"}, None)
        self.assertEqual(decision.source, "page_contacted")
        self.assertEqual(decision.final_action, "already_contacted")

    def test_config_filter_precedes_history(self) -> None:
        decision = evaluate_preflight({"city": "北京"}, {"greeted": 1})
        self.assertEqual(decision.source, "config_filter")

    def test_company_limit_is_applied_after_filters_and_history(self) -> None:
        with patch("decision_service.database.count_greeted_company", return_value=1):
            decision = evaluate_preflight({"city": "上海", "company": "示例公司"}, None)
        self.assertEqual(decision.source, "company_limit")


if __name__ == "__main__":
    unittest.main()
