from __future__ import annotations

import unittest
from unittest.mock import patch

from core import calculate_job_score


class SemanticRoleIntentTests(unittest.TestCase):
    def test_passes_target_role_intent_to_scoring_model(self) -> None:
        captured: dict[str, object] = {}

        def fake_stream(label, messages, **kwargs):
            captured["messages"] = messages
            return '{"学历专业": 80, "技术栈": 10, "项目经验": 10}'

        with patch("core._stream_messages", side_effect=fake_stream):
            scores, _ = calculate_job_score("职位：AI训练师", "候选人画像", ["Agent开发"])

        self.assertEqual(scores, {"学历专业": 80, "技术栈": 10, "项目经验": 10})
        messages = captured["messages"]
        self.assertTrue(any("Agent开发" in item["content"] for item in messages))
        self.assertTrue(any("semantic gate" in item["content"] for item in messages))


if __name__ == "__main__":
    unittest.main()
