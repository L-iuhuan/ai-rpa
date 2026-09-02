# -*- coding: utf-8 -*-
"""typematch.py 单测 — 白名单精确/模糊匹配"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.typematch import normalize, resolve_type


KNOWN = [
    "CP委外",
    "CU Pillar工艺委外",
    "Cu Thick工艺委外",
    "封测编",
    "FT测编委外加工",
    "FT封装委外加工",
]


class T_normalize(unittest.TestCase):
    def test_removes_spaces_and_casefolds(self):
        self.assertEqual(normalize("  Cu Thick 工艺委外 "), "cuthick工艺委外")
        self.assertEqual(normalize("CUPillar工艺委外"), "cupillar工艺委外")


class T_resolve_type(unittest.TestCase):
    def test_exact_all_six(self):
        for k in KNOWN:
            self.assertEqual(resolve_type(k, KNOWN), k)

    def test_exact_case_and_space_insensitive(self):
        self.assertEqual(resolve_type("cp委外", KNOWN), "CP委外")
        self.assertEqual(resolve_type("cu  pillar工艺委外", KNOWN), "CU Pillar工艺委外")
        self.assertEqual(resolve_type("  CuThick工艺委外  ", KNOWN), "Cu Thick工艺委外")

    def test_fuzzy_real_ocr_errors(self):
        self.assertEqual(resolve_type("封规编", KNOWN), "封测编")
        self.assertEqual(resolve_type("封测痛", KNOWN), "封测编")
        self.assertEqual(resolve_type("FI测编委外加工", KNOWN), "FT测编委外加工")
        self.assertEqual(resolve_type("CUPillar工艺委外", KNOWN), "CU Pillar工艺委外")

    def test_garbage_and_empty(self):
        self.assertIsNone(resolve_type("乱串", KNOWN))
        self.assertIsNone(resolve_type("", KNOWN))
        self.assertIsNone(resolve_type(None, KNOWN))

    def test_ambiguous_returns_none(self):
        # "测编" 与 "FT测编委外加工" 距离 2, 与 "FT封装委外加工" 距离 4 — 不算并列,
        # 这里构造一个与两个候选距离都为 1 的情况
        self.assertIsNone(resolve_type("XX", ["XY", "YX"], max_distance=1))

    def test_distance_more_than_max(self):
        self.assertIsNone(resolve_type("完全不同", KNOWN, max_distance=1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
