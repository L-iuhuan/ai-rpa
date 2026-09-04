# -*- coding: utf-8 -*-
"""vision.py — 元素识别核心: 截图 -> RapidOCR -> 表格结构化数据

技术路线(M3实验验证):
  整图RapidOCR识别(中文表头+数字质量已验证) -> 按锚点列头定位上下表 -> 
  y聚类分行 -> 按列x归属单元格 -> 结构化行数据; 复选框用v1模板匹配精确定位
"""

import os
import time
import ctypes
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

import cv2
import numpy as np

from .rules import parse_qty

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 上表锚点列(委外入库单)
UPPER_ANCHORS = ["委外订单号", "采购类型", "入库数量", "件数"]
# 下表锚点列(委外材料出库单)
LOWER_ANCHORS = ["出库数量", "未核销数量", "本次核销数量"]

ROW_Y_TOL = 7          # 行聚类y容差(px)
HEADER_BAND_TOL = 14   # 表头y带容差(px)——表头行各列文本块常有高低差, 用带聚合代替严格聚类
HEADER_SEARCH_TOP = 0.02  # 表头搜索起点(窗口高度比例)


@dataclass
class Block:
    text: str
    conf: float
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def cx(self):
        return (self.x0 + self.x1) / 2

    @property
    def cy(self):
        return (self.y0 + self.y1) / 2


@dataclass
class RowData:
    """一行数据: y=窗口内y中心; cols=列名->原始文本; 复选框点击点(窗口坐标)"""
    y: float
    cols: Dict[str, str] = field(default_factory=dict)
    checkbox: Optional[Tuple[float, float]] = None

    def num(self, name) -> Optional[float]:
        return parse_qty(self.cols.get(name))


def ensure_dpi_aware():
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def norm_text(s) -> str:
    return "".join(str(s).split())


class OcrEngine:
    """RapidOCR 单例封装"""

    def __init__(self):
        self._engine = None

    @property
    def engine(self):
        if self._engine is None:
            from rapidocr_onnxruntime import RapidOCR
            self._engine = RapidOCR()
        return self._engine

    def blocks(self, img) -> List[Block]:
        """整图OCR -> Block列表"""
        result, _ = self.engine(img)
        out = []
        if result:
            for box, text, conf in result:
                xs = [float(p[0]) for p in box]
                ys = [float(p[1]) for p in box]
                out.append(Block(norm_text(text), float(conf),
                                 min(xs), min(ys), max(xs), max(ys)))
        return out


_OCR = OcrEngine()


def _select_window(titles: List[str], title: str) -> Optional[int]:
    """从窗口标题列表选目标: 精确匹配优先, 子串兜底; 返回索引或None.

    背景(2026-09-02实锤): 用户环境同时存在 标题含"委外核销处理"的 Excel 文件
    和 终端(路径含U8委外核销自动化), 子串匹配+取首个会随机选错窗口, 造成
    间歇性"未找到表头"与"捕获到无关窗口内容"。
    """
    for i, t in enumerate(titles):
        if t == title:
            return i
    for i, t in enumerate(titles):
        if title in t:
            return i
    return None


def grab_window(title: str):
    """定位窗口并截图, 返回 (img BGR, (win_left, win_top)) ; 找不到返回 (None, None)"""
    import pyautogui
    try:
        import pygetwindow as gw
        wins = [w for w in gw.getAllWindows()]
    except Exception:
        return None, None
    idx = _select_window([(w.title or "") for w in wins], title)
    if idx is None:
        return None, None
    w = wins[idx]
    # 2026-09-02修复: 原先整体 try/except 会把"还原/激活失败"吞成"窗口不存在";
    # 现在还原/激活失败不致命(仍尝试截图), 仅截图本身失败才返回 None
    try:
        if w.isMinimized:
            w.restore()
            time.sleep(0.2)
    except Exception:
        pass
    try:
        # 拉到前台再截屏: pyautogui截的是屏幕区域, 目标窗口被其他最大化
        # 窗口遮挡时截到的是遮挡者; run模式的坐标点击也要求窗口在前台
        w.activate()
        time.sleep(0.15)
    except Exception:
        pass
    try:
        left, top = w.left, w.top
        img = pyautogui.screenshot(region=(left, top, w.width, w.height))
        return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR), (left, top)
    except Exception:
        return None, None


def _match_header(band_blocks: List[Block], anchors: List[str], min_hits: int):
    """在候选块中找锚点命中数; 返回命中数"""
    hits = 0
    for a in anchors:
        for b in band_blocks:
            if b.text == a or a in b.text:
                hits += 1
                break
    return hits


def _header_y(blocks: List[Block], anchors: List[str], y_min: float, y_max: float) -> Optional[float]:
    """在[y_min,y_max]内找锚点命中最多的y带(表头行y中心).

    宽容表头分块: 以±HEADER_BAND_TOL的y带聚合统计锚点命中,
    应对OCR把宽表头行拆成多个高度略有差异的文本块(各自带部分锚点)导致
    严格行聚类下任何单聚类都凑不满2个锚点的间歇性失败.
    """
    cand = [b for b in blocks if y_min <= b.cy <= y_max]
    if not cand:
        return None
    best_y, best_hits = None, 0
    for b in cand:
        band = [c for c in cand if abs(c.cy - b.cy) <= HEADER_BAND_TOL]
        hits = 0
        for a in anchors:
            if any(a in c.text for c in band):
                hits += 1
        if hits > best_hits:
            best_y = sum(c.cy for c in band) / len(band)
            best_hits = hits
    return best_y if best_hits >= 2 else None


def _cluster_rows(blocks: List[Block], tol: float = ROW_Y_TOL) -> List[List[Block]]:
    """按y中心聚类成行(排序后顺序合并)"""
    bs = sorted(blocks, key=lambda b: b.cy)
    rows: List[List[Block]] = []
    for b in bs:
        if rows and abs(b.cy - rows[-1][0].cy) <= tol:
            rows[-1].append(b)
        else:
            rows.append([b])
    return rows


def _columns_from_header(blocks: List[Block], header_y: float) -> Dict[str, Tuple[float, float]]:
    """表头行 -> {列名: (cx, half_width)}; 与_header_y同带宽, 覆盖被拆分的表头块"""
    header_row = [b for b in blocks if abs(b.cy - header_y) <= HEADER_BAND_TOL]
    cols = {}
    for b in header_row:
        cols[b.text] = (b.cx, (b.x1 - b.x0) / 2)
    return cols


def _assign_block_to_col(b: Block, cols: Dict[str, Tuple[float, float]]) -> Optional[str]:
    """数据块归属到最近列(列中心距离加权列宽)"""
    best, best_d = None, None
    for name, (cx, hw) in cols.items():
        d = abs(b.cx - cx)
        # 惩罚过窄列: 若块中心明显越过列边界则加大距离
        if d > max(hw, 30) * 2.0:
            d *= 1.5
        if best_d is None or d < best_d:
            best, best_d = name, d
    return best


def _rows_in_range(blocks: List[Block], y_top: float, y_bottom: float,
                   cols: Dict[str, Tuple[float, float]],
                   exclude_ys=None) -> List[RowData]:
    """[y_top,y_bottom]内聚类行并归属列"""
    if exclude_ys is None:
        exclude_ys = []
    cand = [b for b in blocks if y_top <= b.cy <= y_bottom]
    rows = []
    for cl in _cluster_rows(cand):
        y = sum(b.cy for b in cl) / len(cl)
        if any(abs(y - ey) <= ROW_Y_TOL for ey in exclude_ys):
            continue
        rd = RowData(y=y)
        for b in cl:
            name = _assign_block_to_col(b, cols)
            if name:
                # 先到先得(同行同列取先出现的块); 数字列一般单块
                rd.cols.setdefault(name, b.text)
        rows.append(rd)
    return rows


# ---------------- 复选框模板匹配(v1验证过) ----------------

def load_template(rel_path="assets/checkbox_raw.png"):
    path = os.path.join(os.path.dirname(BASE_DIR), rel_path)
    with open(path, "rb") as f:
        data = f.read()
    img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit(f"模板读取失败: {path}")
    return img


def find_checkboxes(img, template, threshold=0.8, y_min=0.0, y_max=None) -> List[Tuple[float, float]]:
    """模板匹配未勾选复选框 -> 中心点列表(窗口坐标, 按y排序)"""
    if y_max is None:
        y_max = img.shape[0]
    th, tw = template.shape[:2]
    res = cv2.matchTemplate(img, template, cv2.TM_CCOEFF_NORMED)
    ys, xs = np.where(res >= threshold)
    if len(xs) == 0:
        return []
    cand = sorted(zip(res[ys, xs].tolist(), xs.tolist(), ys.tolist()), reverse=True)
    min_dist = 0.8 * th
    kept = []
    for _s, x, y in cand:
        if all((x - kx) ** 2 + (y - ky) ** 2 >= min_dist ** 2 for kx, ky in kept):
            kept.append((x, y))
    pts = [(x + tw / 2, y + th / 2) for x, y in kept if y_min <= y + th / 2 <= y_max]
    pts.sort(key=lambda p: p[1])
    return pts


# ---------------- 表格总读取 ----------------

@dataclass
class TableState:
    ok: bool
    msg: str = ""
    upper_header_y: float = 0
    lower_header_y: float = 0
    upper_cols: Dict[str, Tuple[float, float]] = field(default_factory=dict)
    lower_cols: Dict[str, Tuple[float, float]] = field(default_factory=dict)
    upper_rows: List[RowData] = field(default_factory=list)
    lower_rows: List[RowData] = field(default_factory=list)


def read_tables(img, template=None, threshold=0.8) -> TableState:
    """整图 -> 上下表结构化. img为窗口截图(BGR)"""
    blocks = _OCR.blocks(img)
    H = img.shape[0]
    if not blocks:
        return TableState(False, "OCR未识别到任何内容")

    up_y = _header_y(blocks, UPPER_ANCHORS, H * HEADER_SEARCH_TOP, H * 0.75)
    if up_y is None:
        return TableState(False, "未找到上表表头(锚点: 委外订单号/采购类型/入库数量/件数)")
    low_y = _header_y(blocks, LOWER_ANCHORS, up_y + 10, H * 0.98)
    if low_y is None:
        return TableState(False, "未找到下表表头(锚点: 出库数量/未核销数量/本次核销数量)")

    upper_cols = _columns_from_header(blocks, up_y)
    lower_cols = _columns_from_header(blocks, low_y)

    upper_rows = _rows_in_range(blocks, up_y + ROW_Y_TOL + 2, low_y - ROW_Y_TOL - 6, upper_cols)
    lower_rows = _rows_in_range(blocks, low_y + ROW_Y_TOL + 2, H, lower_cols)

    # 复选框挂接: 上表区域内匹配, 按y就近挂到行
    if template is not None:
        for name, rows, ymax in (("up", upper_rows, low_y - 10), ("low", lower_rows, H)):
            pts = find_checkboxes(img, template, threshold, 0, ymax)
            # 上表复选框仅取x在左侧区域(前2列宽度内)的点, 避免误匹配
            if rows:
                min_cx = min(c[0] for c in (upper_cols if name == "up" else lower_cols).values())
                pts = [p for p in pts if p[0] < min_cx + 120]
            for p in pts:
                best = min(rows, key=lambda r: abs(r.y - p[1]), default=None)
                if best is not None and abs(best.y - p[1]) <= 15:
                    best.checkbox = p

    return TableState(True, "ok", up_y, low_y, upper_cols, lower_cols, upper_rows, lower_rows)
