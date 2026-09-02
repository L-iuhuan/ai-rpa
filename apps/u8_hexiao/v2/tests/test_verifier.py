# -*- coding: utf-8 -*-
"""verifier.py 单测: 核销结果校验全分支覆盖(纯函数, 离线)"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.verifier import verify_row_hexiao, VERIFIED, VERIFY_FAIL, VERIFY_UNKNOWN


class _Row:
    """模拟 RowData: y / cols / checkbox / num(列名)"""

    def __init__(self, y, unreconciled=None, checkbox=None):
        self.y = y
        self.cols = {"未核销数量": "" if unreconciled is None else str(unreconciled)}
        self.checkbox = checkbox

    def num(self, col):
        try:
            return float(self.cols.get(col, ""))
        except (TypeError, ValueError):
            return None


class _St:
    """模拟 vision.read_tables 结构化结果"""

    def __init__(self, rows, ok=True):
        self.ok = ok
        self.upper_rows = rows


class T_VerifyRowHexiao(unittest.TestCase):
    def test_verified_row_disappeared(self):
        """行消失 -> VERIFIED"""
        row = _Row(100, unreconciled=50)
        st_b, st_a = _St([row]), _St([])  # 核销后行不在了
        self.assertEqual(verify_row_hexiao(st_b, st_a, row), VERIFIED)

    def test_verified_qty_decreased(self):
        """未核销数量变小 -> VERIFIED"""
        row = _Row(100, unreconciled=50)
        st_b, st_a = _St([row]), _St([_Row(100, unreconciled=25)])
        self.assertEqual(verify_row_hexiao(st_b, st_a, row), VERIFIED)

    def test_verified_qty_increased(self):
        """数值变化(变大也算状态变化) -> VERIFIED"""
        row = _Row(100, unreconciled=25)
        st_b, st_a = _St([row]), _St([_Row(100, unreconciled=50)])
        self.assertEqual(verify_row_hexiao(st_b, st_a, row), VERIFIED)

    def test_verified_checkbox_toggled(self):
        """数值不变但 checkbox 出现 -> VERIFIED"""
        row = _Row(100, unreconciled=50, checkbox=None)
        st_b = _St([row])
        st_a = _St([_Row(100, unreconciled=50, checkbox=(10, 100))])
        self.assertEqual(verify_row_hexiao(st_b, st_a, row), VERIFIED)

    def test_verified_qty_none_checkbox_change(self):
        """数值读不到但 checkbox 变化 -> VERIFIED (L44-50 分支)"""
        row = _Row(100, unreconciled=None, checkbox=None)
        st_b = _St([row])
        st_a = _St([_Row(100, unreconciled=None, checkbox=(10, 100))])
        self.assertEqual(verify_row_hexiao(st_b, st_a, row), VERIFIED)

    def test_fail_qty_unchanged(self):
        """行还在、数值不变、checkbox 无变化 -> VERIFY_FAIL"""
        row = _Row(100, unreconciled=50, checkbox=(10, 100))
        st_b = _St([row])
        st_a = _St([_Row(100, unreconciled=50, checkbox=(12, 101))])  # 坐标微移=存在性未变
        self.assertEqual(verify_row_hexiao(st_b, st_a, row), VERIFY_FAIL)

    def test_unknown_read_failed(self):
        """st_after.ok=False -> VERIFY_UNKNOWN"""
        row = _Row(100, unreconciled=50)
        st_b, st_a = _St([row]), _St([], ok=False)
        self.assertEqual(verify_row_hexiao(st_b, st_a, row), VERIFY_UNKNOWN)

    def test_unknown_ambiguous_match(self):
        """y±8 命中多行(歧义) -> VERIFY_UNKNOWN"""
        row = _Row(100, unreconciled=50)
        st_b = _St([row])
        st_a = _St([_Row(96, unreconciled=50), _Row(104, unreconciled=50)])
        self.assertEqual(verify_row_hexiao(st_b, st_a, row), VERIFY_UNKNOWN)

    def test_unknown_qty_none_no_checkbox_change(self):
        """数值读不到且 checkbox 无变化 -> VERIFY_UNKNOWN"""
        row = _Row(100, unreconciled=None, checkbox=None)
        st_b = _St([row])
        st_a = _St([_Row(100, unreconciled=None, checkbox=None)])
        self.assertEqual(verify_row_hexiao(st_b, st_a, row), VERIFY_UNKNOWN)


if __name__ == "__main__":
    unittest.main(verbosity=2)
