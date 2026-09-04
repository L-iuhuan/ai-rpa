# -*- coding: utf-8 -*-
"""vision.find_button_center 按钮免校准自动定位测试(纯函数)"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import vision
from core.vision import Block, find_button_center


def blk(text, cx, cy):
    return Block(text=text, conf=0.9, x0=cx - 25, y0=cy - 8, x1=cx + 25, y1=cy + 8)


class T_FindButtonCenter(unittest.TestCase):
    def test_exact_match_found(self):
        """工具栏独立"核销"文本块被精确定位"""
        with mock.patch.object(vision._OCR, "blocks",
                               return_value=[blk("委外核销处理", 500, 15),
                                             blk("核销", 1200, 43),
                                             blk("未核销数量", 600, 720)]):
            pos = find_button_center(object(), "核销")
        self.assertIsNotNone(pos)
        self.assertAlmostEqual(pos[0], 1200.0, delta=1.0)
        self.assertAlmostEqual(pos[1], 43.0, delta=1.0)

    def test_substring_blocks_ignored(self):
        """"未核销数量"/标题等包含式文本块不误命中"""
        with mock.patch.object(vision._OCR, "blocks",
                               return_value=[blk("委外核销处理", 500, 15),
                                             blk("未核销数量", 600, 720),
                                             blk("本次核销数量", 800, 720)]):
            self.assertIsNone(find_button_center(object(), "核销"))

    def test_multiple_hits_take_topmost(self):
        """多个精确命中取最靠上(工具栏在上)"""
        with mock.patch.object(vision._OCR, "blocks",
                               return_value=[blk("核销", 900, 1300),
                                             blk("核销", 1200, 43)]):
            pos = find_button_center(object(), "核销")
        self.assertAlmostEqual(pos[1], 43.0, delta=1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
