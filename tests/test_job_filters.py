from __future__ import annotations

import unittest

from config import Config
from job_filters import blocked_reason, is_internship, salary_range_k


class JobFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.saved = Config.as_dict()
        Config.apply({
            **self.saved,
            "job_filter_cities": [],
            "job_filter_title_keywords": [],
            "job_filter_required_title_keywords": [],
            "job_filter_blocked_companies": [],
            "job_filter_employment_type": "any",
            "job_filter_salary_min_k": 0,
            "job_filter_salary_max_k": 0,
        })

    def tearDown(self) -> None:
        Config.apply(self.saved)

    def test_extracts_boss_salary_range(self) -> None:
        self.assertEqual(salary_range_k("15-30K·14薪"), (15.0, 30.0))
        self.assertEqual(salary_range_k("20K"), (20.0, 20.0))
        self.assertIsNone(salary_range_k("面议"))

    def test_applies_city_title_company_and_salary_filters(self) -> None:
        Config.apply({
            **Config.as_dict(),
            "job_filter_cities": ["上海"],
            "job_filter_title_keywords": ["Python", "后端"],
            "job_filter_blocked_companies": ["外包"],
            "job_filter_salary_min_k": 20,
            "job_filter_salary_max_k": 35,
        })
        valid = {"city": "上海", "title": "Python 后端工程师", "company": "示例科技", "salary": "25-35K"}
        self.assertEqual(blocked_reason(valid), "")
        self.assertIn("城市", blocked_reason({**valid, "city": "北京"}))
        self.assertIn("职位名称", blocked_reason({**valid, "title": "产品经理"}))
        self.assertIn("屏蔽", blocked_reason({**valid, "company": "某外包服务"}))
        self.assertIn("低于", blocked_reason({**valid, "salary": "10-15K"}))
        self.assertIn("高于", blocked_reason({**valid, "salary": "40-50K"}))

    def test_unknown_salary_does_not_reject_job(self) -> None:
        Config.apply({**Config.as_dict(), "job_filter_salary_min_k": 20})
        self.assertEqual(blocked_reason({"salary": "面议"}), "")

    def test_filters_internship_and_full_time_jobs(self) -> None:
        internship = {"title": "Python 实习生", "detail": "暑期 internship"}
        formal = {"title": "Python 工程师", "detail": "全职岗位"}
        self.assertTrue(is_internship(internship))
        self.assertFalse(is_internship(formal))

        Config.apply({**Config.as_dict(), "job_filter_employment_type": "internship"})
        self.assertEqual(blocked_reason(internship), "")
        self.assertIn("实习", blocked_reason(formal))

        Config.apply({**Config.as_dict(), "job_filter_employment_type": "full_time"})
        self.assertEqual(blocked_reason(formal), "")
        self.assertIn("正式", blocked_reason(internship))

    def test_requires_explicit_title_keyword_before_model_scoring(self) -> None:
        Config.apply({**Config.as_dict(), "job_filter_required_title_keywords": ["Agent开发"]})
        self.assertEqual(blocked_reason({"title": "Agent开发工程师"}), "")
        self.assertIn("硬性关键词", blocked_reason({"title": "AI训练师", "detail": "负责模型训练"}))


if __name__ == "__main__":
    unittest.main()
