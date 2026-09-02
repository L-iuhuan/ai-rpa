# -*- coding: utf-8 -*-
"""verifier.py — 核销结果自动校验(纯函数, 不截图不点鼠标)

核心函数 verify_row_hexiao: 比较核销前后同一行的"未核销数量"变化,
返回 VERIFIED / VERIFY_FAIL / VERIFY_UNKNOWN.
"""

from typing import Optional

VERIFIED = "VERIFIED"
VERIFY_FAIL = "VERIFY_FAIL"
VERIFY_UNKNOWN = "VERIFY_UNKNOWN"


def _find_row_after(st_after, row_y: float, tol: float = 8.0):
    """按 y±tol 在 st_after.upper_rows 中匹配行; 返回 (matched_row_or_None, ambiguous)."""
    hits = [r for r in st_after.upper_rows if abs(r.y - row_y) <= tol]
    if len(hits) > 1:
        return None, True
    return (hits[0], False) if hits else (None, False)


def verify_row_hexiao(st_before, st_after, row_rd, tol=0.005) -> str:
    """核销结果校验.

    - VERIFIED:   行消失 / 未核销数量变小(或变大, 状态变化) / checkbox 状态变化
    - VERIFY_FAIL: 行还在且未核销数量无变化(容差 tol)
    - VERIFY_UNKNOWN: st_after 读取失败 或 行匹配歧义(多行)
    """
    if st_after is None or getattr(st_after, "ok", False) is False:
        return VERIFY_UNKNOWN

    matched, ambiguous = _find_row_after(st_after, getattr(row_rd, "y", None))
    if ambiguous:
        return VERIFY_UNKNOWN

    if matched is None:
        # 行消失 — 核销成功(行被刷新/移除)
        return VERIFIED

    qty_before = row_rd.num("未核销数量") if hasattr(row_rd, "num") else None
    qty_after = matched.num("未核销数量") if hasattr(matched, "num") else None

    if qty_before is None or qty_after is None:
        # 无法比较数值: 看 checkbox 是否变化
        cb_before = getattr(row_rd, "checkbox", None)
        cb_after = getattr(matched, "checkbox", None)
        if (cb_before is None) != (cb_after is None):
            return VERIFIED
        return VERIFY_UNKNOWN

    if abs(qty_before - qty_after) > tol + 1e-9:
        return VERIFIED

    # 数值未变: 检查 checkbox 是否有变化
    cb_before = getattr(row_rd, "checkbox", None)
    cb_after = getattr(matched, "checkbox", None)
    if (cb_before is None) != (cb_after is None):
        return VERIFIED

    return VERIFY_FAIL
