# -*- coding: utf-8 -*-
"""规则引擎测试基准 — 覆盖方案文档 3.2/3.3 全部分支 + 截图实测数据回放"""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.rules import (Decision, LowerRow, UpperRow, judge, parse_qty,
                        classify_type, PASS, MODIFY, SKIP)

TYPE_MAP = {"封测编": "A", "普通委外": "B", "镀铜": "B"}
TOL = 0.005


class T_parse_qty(unittest.TestCase):
    def test_thousands(self):
        self.assertEqual(parse_qty("1,562,477.00"), 1562477.0)

    def test_plain_and_decimal(self):
        self.assertEqual(parse_qty("273.00"), 273.0)
        self.assertEqual(parse_qty("25.000000"), 25.0)

    def test_empty_and_invalid(self):
        for s in (None, "", " ", "-", "—", "abc", "1.2.3"):
            self.assertIsNone(parse_qty(s), msg=f"{s!r} 应为None")


class T_classify(unittest.TestCase):
    def test_known(self):
        self.assertEqual(classify_type("封测编", TYPE_MAP), "A")
        self.assertEqual(classify_type(" 普通委外 ", TYPE_MAP), "B")

    def test_unknown_and_none(self):
        self.assertIsNone(classify_type("来料加工", TYPE_MAP))
        self.assertIsNone(classify_type(None, TYPE_MAP))
        self.assertIsNone(classify_type("", TYPE_MAP))


def mk(purchase_type, in_qty=None, in_pieces=None):
    return UpperRow(purchase_type=purchase_type, in_qty=in_qty, in_pieces=in_pieces)


def low(pieces=None, unreconciled=None, this_qty=None):
    return LowerRow(pieces=pieces, unreconciled_qty=unreconciled, this_qty=this_qty)


class T_A类(unittest.TestCase):
    """A类分支: 件数上==件数下 时看 Q核vsQ未; 件数上<件数下 PASS; > SKIP"""

    def test_相等且核销等于未核销_PASS(self):
        d = judge("封测编", mk("封测编", in_pieces=25), [low(pieces=25, unreconciled=20477, this_qty=20477)], TYPE_MAP, TOL)
        self.assertEqual(d.action, PASS)

    def test_相等且核销小于未核销_MODIFY目标为未核销数(self):
        d = judge("封测编", mk("封测编", in_pieces=25), [low(pieces=25, unreconciled=20477, this_qty=20000)], TYPE_MAP, TOL)
        self.assertEqual(d.action, MODIFY)
        self.assertEqual(d.target, 20477)

    def test_相等但核销大于未核销_SKIP(self):
        d = judge("封测编", mk("封测编", in_pieces=25), [low(pieces=25, unreconciled=100, this_qty=120)], TYPE_MAP, TOL)
        self.assertEqual(d.action, SKIP)

    def test_上件数小于下件数_PASS(self):
        d = judge("封测编", mk("封测编", in_pieces=20), [low(pieces=25, unreconciled=20477, this_qty=18000)], TYPE_MAP, TOL)
        self.assertEqual(d.action, PASS)

    def test_上件数大于下件数_SKIP(self):
        d = judge("封测编", mk("封测编", in_pieces=30), [low(pieces=25)], TYPE_MAP, TOL)
        self.assertEqual(d.action, SKIP)

    def test_件数缺失_SKIP(self):
        d = judge("封测编", mk("封测编", in_pieces=None), [low(pieces=25)], TYPE_MAP, TOL)
        self.assertEqual(d.action, SKIP)
        d2 = judge("封测编", mk("封测编", in_pieces=25), [low(pieces=None)], TYPE_MAP, TOL)
        self.assertEqual(d2.action, SKIP)

    def test_浮点容差相等算相等(self):
        d = judge("封测编", mk("封测编", in_pieces=25.0), [low(pieces=25.003, unreconciled=100.0, this_qty=100.0)], TYPE_MAP, TOL)
        self.assertEqual(d.action, PASS)


class T_B类(unittest.TestCase):
    def test_入库小于未核销_PASS(self):
        d = judge("普通委外", mk("普通委外", in_qty=273), [low(unreconciled=20477, this_qty=270)], TYPE_MAP, TOL)
        self.assertEqual(d.action, PASS)

    def test_入库等于未核销_PASS(self):
        d = judge("普通委外", mk("普通委外", in_qty=20477), [low(unreconciled=20477)], TYPE_MAP, TOL)
        self.assertEqual(d.action, PASS)

    def test_入库大于未核销_SKIP(self):
        d = judge("普通委外", mk("普通委外", in_qty=30000), [low(unreconciled=20477)], TYPE_MAP, TOL)
        self.assertEqual(d.action, SKIP)

    def test_数量缺失_SKIP(self):
        d = judge("普通委外", mk("普通委外", in_qty=None), [low(unreconciled=20477)], TYPE_MAP, TOL)
        self.assertEqual(d.action, SKIP)


class T_通用(unittest.TestCase):
    def test_未配置类型_SKIP(self):
        d = judge("来料加工", mk("来料加工", in_qty=1), [low(unreconciled=2)], TYPE_MAP, TOL)
        self.assertEqual(d.action, SKIP)
        self.assertIn("未配置", d.reason)

    def test_下表多行_SKIP(self):
        d = judge("封测编", mk("封测编", in_pieces=25),
                  [low(pieces=25, unreconciled=1, this_qty=1), low(pieces=25, unreconciled=2, this_qty=2)],
                  TYPE_MAP, TOL)
        self.assertEqual(d.action, SKIP)
        self.assertIn("多行", d.reason)

    def test_下表无行_SKIP(self):
        d = judge("封测编", mk("封测编", in_pieces=25), [], TYPE_MAP, TOL)
        self.assertEqual(d.action, SKIP)

    def test_MODIFY必有target(self):
        d = judge("封测编", mk("封测编", in_pieces=25), [low(pieces=25, unreconciled=99.5, this_qty=90)], TYPE_MAP, TOL)
        self.assertEqual(d.action, MODIFY)
        self.assertIsNotNone(d.target)


class T_截图实测数据回放(unittest.TestCase):
    """用户截图(2026-08-27)中的真实行: 采购类型=封测编, 入库数量273/200, 件数上为空,
    下表联动行: 件数25, 未核销20477, 待核销绝对20477, 本次核销0"""

    def test_截图高亮行_件数上为空应SKIP(self):
        # 件数上缺失(空) -> A类规则读不到件数 -> SKIP 留人工(不能猜)
        d = judge("封测编", mk("封测编", in_qty=200, in_pieces=None),
                  [low(pieces=25, unreconciled=20477.0, this_qty=0.0)], TYPE_MAP, TOL)
        self.assertEqual(d.action, SKIP)
        self.assertIn("件数", d.reason)

    def test_截图首行_若件数补齐为25则按件数判定(self):
        # 反证: 若件数上能读到25, 件数相等且本次核销0<未核销20477 -> MODIFY 到 20477
        d = judge("封测编", mk("封测编", in_qty=273, in_pieces=25.0),
                  [low(pieces=25.0, unreconciled=20477.0, this_qty=0.0)], TYPE_MAP, TOL)
        self.assertEqual(d.action, MODIFY)
        self.assertEqual(d.target, 20477.0)

    def test_千分位数字解析_截图值(self):
        self.assertEqual(parse_qty("1,562,477.00"), 1562477.0)
        self.assertEqual(parse_qty("20,477.00"), 20477.0)
        self.assertEqual(parse_qty("25.000000"), 25.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
