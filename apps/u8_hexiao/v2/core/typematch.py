# -*- coding: utf-8 -*-
"""typematch.py — 采购类型白名单匹配(确定性层)

- normalize: 去全部空白 + casefold
- resolve_type: 先精确等值, 再标准 Levenshtein 编辑距离(中文字符每字计 1)模糊匹配,
  唯一最近且距离≤max_distance 才返回 known 原文.
"""

from typing import List, Optional


def normalize(s) -> str:
    """去全部空白(含制表符/全角空格) + casefold."""
    if s is None:
        return ""
    return "".join(str(s).split()).casefold()


def _levenshtein(a: str, b: str) -> int:
    """标准 Levenshtein 距离; 每个字符(含中文)计 1."""
    m, n = len(a), len(b)
    if m == 0:
        return n
    if n == 0:
        return m
    # 滚动数组, O(min(m,n)) 空间
    prev = list(range(n + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr.append(min(curr[-1] + 1, prev[j] + 1, prev[j - 1] + cost))
        prev = curr
    return prev[n]


def resolve_type(raw: str, known: List[str], max_distance: int = 2) -> Optional[str]:
    """返回匹配到的 known 原文; 无匹配/并列/空串 返回 None."""
    raw_norm = normalize(raw)
    if not raw_norm:
        return None

    # 1) 精确等值(在 normalize 后)
    for k in known:
        if normalize(k) == raw_norm:
            return k

    # 2) Levenshtein 模糊匹配
    candidates = []
    for k in known:
        d = _levenshtein(raw_norm, normalize(k))
        if d <= max_distance:
            candidates.append((d, k))

    if not candidates:
        return None

    min_d = min(c[0] for c in candidates)
    best = [c[1] for c in candidates if c[0] == min_d]
    if len(best) == 1:
        return best[0]
    return None
