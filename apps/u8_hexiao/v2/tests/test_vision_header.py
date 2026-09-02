# -*- coding: utf-8 -*-
"""vision._header_y 表头y带聚合的回归测试(纯函数, 不依赖OCR/实机)

背景: 2026-09-02 实机 plan 间歇性报"未找到下表表头"。根因是宽表头行的各列
文本块 y 中心常有高低差, 严格行聚类(ROW_Y_TOL=7)把它拆成多个聚类, 各带
部分锚点导致单聚类命中数<2。修复后用±HEADER_BAND_TOL的y带聚合统计。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.vision import Block, _header_y, HEADER_BAND_TOL, HEADER_SEARCH_TOP
from core.vision import UPPER_ANCHORS, LOWER_ANCHORS


def blk(text, cx, cy):
    return Block(text=text, conf=0.9, x0=cx - 30, y0=cy - 6, x1=cx + 30, y1=cy + 6)


class T_HeaderY(unittest.TestCase):
    def test_split_lower_header_now_found(self):
        """下表表头被OCR拆成两个高度差8px的块, 各带1-2个锚点 -> 带聚合后仍能命中"""
        blocks = [
            # 上表表头(正常)
            blk("委外订单号", 100, 70), blk("采购类型", 300, 70),
            blk("入库数量", 500, 70), blk("件数", 650, 70),
            # 上表数据行噪声
            blk("1", 100, 200), blk("封测编", 300, 200), blk("100.00", 500, 200),
            # 下表表头: 拆成两层, y差8px(超过ROW_Y_TOL=7, 旧实现会拆簇)
            blk("出库单号", 100, 716), blk("仓库", 200, 716),
            blk("出库数量", 400, 724), blk("未核销数量", 600, 722),
            blk("本次核销数量", 800, 724),
            # 下表数据行
            blk("CLCK260821", 100, 745), blk("25.000000", 600, 745),
        ]
        low_y = _header_y(blocks, LOWER_ANCHORS, 80, 1400)
        self.assertIsNotNone(low_y, "拆分表头必须能被y带聚合找到")
        self.assertAlmostEqual(low_y, (716 + 716 + 724 + 722 + 724) / 5, delta=1.0)

    def test_normal_header_still_found(self):
        """单层表头(无拆分)不受影响"""
        blocks = [blk("委外订单号", 100, 70), blk("采购类型", 300, 70),
                  blk("入库数量", 500, 70), blk("件数", 650, 70)]
        up_y = _header_y(blocks, UPPER_ANCHORS, 0, 1400)
        self.assertIsNotNone(up_y)
        self.assertAlmostEqual(up_y, 70.0, delta=1.0)

    def test_insufficient_anchors_returns_none(self):
        """锚点命中<2时仍返回None(不降低安全阈值)"""
        blocks = [blk("出库数量", 400, 724), blk("仓库", 200, 716)]
        self.assertIsNone(_header_y(blocks, LOWER_ANCHORS, 0, 1400))

    def test_band_tolerance_covers_offset(self):
        """带容差值覆盖已知实测拆分幅度(8px < HEADER_BAND_TOL)"""
        self.assertGreaterEqual(HEADER_BAND_TOL, 8)

    def test_range_respected(self):
        """搜索范围外的块不参与"""
        blocks = [blk("出库数量", 400, 724), blk("未核销数量", 600, 722),
                  blk("本次核销数量", 800, 724)]
        self.assertIsNone(_header_y(blocks, LOWER_ANCHORS, 0, 700))
        self.assertIsNotNone(_header_y(blocks, LOWER_ANCHORS, 0, 800))


if __name__ == "__main__":
    unittest.main(verbosity=2)
