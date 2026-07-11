from __future__ import annotations

import unittest

from desktop_gui import split_terms


class DesktopGuiTests(unittest.TestCase):
    def test_splits_native_form_terms(self) -> None:
        self.assertEqual(split_terms("Agent开发， RAG, Agent开发"), ["Agent开发", "RAG"])


if __name__ == "__main__":
    unittest.main()
