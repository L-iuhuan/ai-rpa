# -*- coding: utf-8 -*-
"""vision._select_window 窗口选择优先级测试(纯函数)

背景: 2026-09-02 实锤——环境里同时存在标题含"委外核销处理"的 U8 窗口(精确)、
Excel 文件窗口(标题含该词+.xlsx)和终端(路径含U8委外核销自动化), 子串匹配
取首个会随机捕获错窗口。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.vision import _select_window


class T_SelectWindow(unittest.TestCase):
    def test_exact_beats_substring(self):
        """Excel/终端在前, U8 精确标题在后——必须选中精确命中的 U8"""
        titles = [
            "委外核销处理单列表-2026.xlsx - Excel",
            "E:\\3-其他资料\\project\\ai-rpa\\apps\\u8_hexiao - cmd",
            "Telegram (46)",
            "委外核销处理",
        ]
        self.assertEqual(_select_window(titles, "委外核销处理"), 3)

    def test_substring_fallback(self):
        """无精确命中时保持旧子串兜底行为"""
        titles = ["委外核销处理 [设计模式]", "记事本"]
        self.assertEqual(_select_window(titles, "委外核销处理"), 0)

    def test_no_match_returns_none(self):
        self.assertIsNone(_select_window(["记事本", "Excel"], "委外核销处理"))

    def test_empty_titles(self):
        self.assertIsNone(_select_window([], "委外核销处理"))

    def test_first_exact_wins_on_duplicates(self):
        titles = ["委外核销处理", "委外核销处理"]
        self.assertEqual(_select_window(titles, "委外核销处理"), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
