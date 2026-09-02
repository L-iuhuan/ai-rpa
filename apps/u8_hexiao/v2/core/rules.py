# -*- coding: utf-8 -*-
"""规则引擎(纯函数, 无UI/无鼠标依赖) — 判定逻辑的唯一权威实现

规则来源: docs/方案规则文档.md 第3节(用户确认)
  A类(按件数): 先看下表是否多行(多行SKIP), 再按件数比对
  B类(按数量): 先看下表是否多行(多行SKIP), 再按数量比对
  未知采购类型: SKIP
任何字段缺失/无法解析 -> 一律 SKIP, 绝不猜
"""

from dataclasses import dataclass, field
from typing import Optional, List

PASS = "PASS"      # 直接点核销
MODIFY = "MODIFY"  # 先把本次核销数量改成 target, 再点核销
SKIP = "SKIP"      # 留人工


@dataclass
class Decision:
    action: str                 # PASS / MODIFY / SKIP
    reason: str                 # 人话原因(写日志/GUI展示)
    target: Optional[float] = None  # MODIFY 时的本次核销数量目标值


@dataclass
class UpperRow:
    """上表(委外入库单)一行的关键字段"""
    purchase_type: Optional[str] = None   # 采购类型
    in_qty: Optional[float] = None        # 入库数量
    in_pieces: Optional[float] = None     # 件数(可能为空)


@dataclass
class LowerRow:
    """下表(委外材料出库单)一行的关键字段"""
    pieces: Optional[float] = None        # 件数
    unreconciled_qty: Optional[float] = None  # 未核销数量
    this_qty: Optional[float] = None      # 本次核销数量(系统带出)


def parse_qty(text) -> Optional[float]:
    """解析界面数字: 去千分位/空格; 空/非法返回 None"""
    if text is None:
        return None
    s = str(text).strip().replace(",", "").replace(" ", "").replace("\u3000", "")
    if s in ("", "-", "—"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def classify_type(purchase_type: Optional[str], type_map: dict) -> Optional[str]:
    """采购类型 -> 'A'/'B'; 未配置/None -> None(跳过留人工)"""
    if not purchase_type:
        return None
    return type_map.get(str(purchase_type).strip())


def _eq(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol + 1e-9


def judge(purchase_type: Optional[str], upper: UpperRow, lowers: List[LowerRow],
          type_map: dict, qty_tol: float = 0.005) -> Decision:
    """总入口: 按采购类型分派到 A/B 判定"""
    cat = classify_type(purchase_type, type_map)
    if cat is None:
        return Decision(SKIP, f"采购类型\"{purchase_type}\"未配置分类, 请在配置中维护")
    if not lowers:
        return Decision(SKIP, "下表无联动行(可能刷新未完成), 留人工")
    if len(lowers) > 1:
        return Decision(SKIP, f"下表联动多行({len(lowers)}行), 规则约定不处理, 留人工")
    low = lowers[0]
    if cat == "A":
        return _judge_a(upper, low, qty_tol)
    return _judge_b(upper, low, qty_tol)


def _judge_a(upper: UpperRow, low: LowerRow, tol: float) -> Decision:
    """A类(按件数核对)"""
    up, dn = upper.in_pieces, low.pieces
    if up is None or dn is None:
        return Decision(SKIP, f"件数无法读取(上={upper.in_pieces}, 下={low.pieces}), 留人工")
    if _eq(up, dn, tol):
        q_he, q_wei = low.this_qty, low.unreconciled_qty
        if q_he is None or q_wei is None:
            return Decision(SKIP, f"核销数量无法读取(本次={q_he}, 未核销={q_wei}), 留人工")
        if _eq(q_he, q_wei, tol):
            return Decision(PASS, f"件数一致({up:g})且本次核销={q_he:g}==未核销={q_wei:g}, 直接核销")
        if q_he < q_wei:
            return Decision(MODIFY, f"件数一致({up:g})但本次核销{q_he:g}<未核销{q_wei:g}, 修正本次核销数量", target=q_wei)
        return Decision(SKIP, f"件数一致但本次核销{q_he:g}>未核销{q_wei:g}(异常), 留人工")
    if up < dn:
        return Decision(PASS, f"上件数{up:g}<下件数{dn:g}(入库不足出库), 直接核销留余量")
    return Decision(SKIP, f"上件数{up:g}>下件数{dn:g}(出库不足), 留人工")


def _judge_b(upper: UpperRow, low: LowerRow, tol: float) -> Decision:
    """B类(按数量核对)"""
    q_in, q_wei = upper.in_qty, low.unreconciled_qty
    if q_in is None or q_wei is None:
        return Decision(SKIP, f"数量无法读取(入库={q_in}, 未核销={q_wei}), 留人工")
    if q_in < q_wei or _eq(q_in, q_wei, tol):
        return Decision(PASS, f"入库数量{q_in:g}<=未核销数量{q_wei:g}, 直接核销")
    return Decision(SKIP, f"入库数量{q_in:g}>未核销数量{q_wei:g}, 留人工")
