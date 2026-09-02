# -*- coding: utf-8 -*-
"""vlmtype.py 单测 — monkeypatch _chat, 不访问网络"""

import os
import sys
import unittest
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.vlmtype import VLMTypeClassifier


KNOWN = ["封测编", "FT测编委外加工", "CP委外"]


def _make_classifier():
    return VLMTypeClassifier(
        base_url="http://localhost/v1",
        api_key="fake",
        model="fake-model",
        known_types=KNOWN,
        timeout_s=5,
    )


class T_VLMTypeClassifier(unittest.TestCase):
    def test_normal_answer_returns_known(self):
        clf = _make_classifier()

        def fake_chat(payload):
            return {"choices": [{"message": {"content": "  封测编  "}}]}

        clf._chat = fake_chat
        img = np.zeros((20, 120, 3), dtype=np.uint8)
        result, info = clf.classify(img)
        self.assertEqual(result, "封测编")
        self.assertEqual(info.strip(), "封测编")

    def test_noisy_answer_normalize_hit(self):
        clf = _make_classifier()

        def fake_chat(payload):
            return {"choices": [{"message": {"content": "FT 测编委外加工\n"}}]}

        clf._chat = fake_chat
        img = np.zeros((20, 120, 3), dtype=np.uint8)
        result, info = clf.classify(img)
        self.assertEqual(result, "FT测编委外加工")
        self.assertIn("FT", info)

    def test_unknown_answer_returns_none(self):
        clf = _make_classifier()

        def fake_chat(payload):
            return {"choices": [{"message": {"content": "UNKNOWN"}}]}

        clf._chat = fake_chat
        img = np.zeros((20, 120, 3), dtype=np.uint8)
        result, info = clf.classify(img)
        self.assertIsNone(result)
        self.assertEqual(info, "UNKNOWN")

    def test_exception_returns_none_no_raise(self):
        clf = _make_classifier()

        def fake_chat(payload):
            raise RuntimeError("boom")

        clf._chat = fake_chat
        img = np.zeros((20, 120, 3), dtype=np.uint8)
        result, info = clf.classify(img)
        self.assertIsNone(result)
        self.assertIn("RuntimeError", info)
        self.assertIn("boom", info)


if __name__ == "__main__":
    unittest.main(verbosity=2)
