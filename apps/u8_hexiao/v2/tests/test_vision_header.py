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
    def test_horizontally_fragmented_anchor(self):
        """OCR把"出库数量"打碎成"出库"+"数量"两个相邻块 -> 带内按x拼接后仍命中(2026-09-04实锤场景)"""
        blocks = [
            blk("委外订单号", 100, 70), blk("采购类型", 300, 70),
            blk("入库数量", 500, 70), blk("件数", 650, 70),
            blk("未核销数量", 600, 722),
            blk("出库", 400, 724), blk("数量", 435, 724),  # 碎块
        ]
        low_y = _header_y(blocks, LOWER_ANCHORS, 80, 1400)
        self.assertIsNotNone(low_y, "碎块'出库'+'数量'拼接后应命中'出库数量'锚点")

    def test_confusable_char_misread(self):
        """形近字误读: 出库教量/未核销激量/本次核销全额(数↔教/激/全) -> 模糊匹配仍命中(2026-09-04实锤)"""
        blocks = [
            blk("委外订单号", 100, 70), blk("采购类型", 300, 70),
            blk("入库数量", 500, 70), blk("件数", 650, 70),
            blk("出库教量", 1070, 721),           # 数→教
            blk("未核销激量待核销绝对数量", 1487, 721),  # 数→激+合并
            blk("本次核销全额", 1771, 721),        # 数→全
        ]
        low_y = _header_y(blocks, LOWER_ANCHORS, 80, 1400)
        self.assertIsNotNone(low_y, "形近字误读下模糊锚点匹配应命中>=2")

    def test_upper_in库_not_confused_when_excluded(self):
        """上表'入库数量'与'出库数量'距离1, 但下表搜索从up_y+10开始天然排除"""
        blocks = [blk("入库数量", 500, 70), blk("出库单号", 100, 70)]
        # 上表头区域若被误纳入下表搜索范围, 单靠"入库数量"模糊命中"出库数量"
        # 只得1锚点, 仍不过>=2门槛
        self.assertIsNone(_header_y(blocks, LOWER_ANCHORS, 80, 1400))

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
