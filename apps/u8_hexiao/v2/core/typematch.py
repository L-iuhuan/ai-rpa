# -*- coding: utf-8 -*-
"""typematch.py — 采购类型白名单匹配(确定性层)

- normalize: 去全部空白 + 去截断省略号(.…) + casefold
- resolve_type: 精确等值 -> 唯一前缀(U8窄列截断显示容错) -> Levenshtein 模糊匹配,
  各层唯一命中才返回 known 原文.
"""

from typing import List, Optional


def normalize(s) -> str:
    """去全部空白(含制表符/全角空格) + 截断省略号(.…) + casefold.

    2026-09-04实锤: U8 采购类型列过窄, "CU Pillar工艺委外"被截断显示为
    "CUPilla..", OCR 读到的就是带省略号的截断文本.
    """
    if s is None:
        return ""
    t = "".join(str(s).split())
    return t.replace("…", "").replace(".", "").casefold()


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

    # 2) 唯一前缀匹配: U8 窄列截断显示容错(如"CUPilla.."->"CU Pillar工艺委外")
    #    长度门槛>=5 防短前缀误配
    if len(raw_norm) >= 5:
        prefix_hits = [k for k in known if normalize(k).startswith(raw_norm)]
        if len(prefix_hits) == 1:
            return prefix_hits[0]

    # 3) Levenshtein 模糊匹配
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
