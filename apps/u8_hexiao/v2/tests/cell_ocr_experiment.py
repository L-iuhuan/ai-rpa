# -*- coding: utf-8 -*-
"""M3实验B: 竖线切列 + 单格放大OCR + 模糊匹配列名 (fixture离线验证)

思路(元素识别核心):
  1. 检测表格区竖直网格线 -> 列边界(列宽拖动后自动适应)
  2. 检测水平网格线 -> 表头带/数据行带
  3. 每个表头单元格裁剪+放大4x+二值化 -> Windows OCR
  4. difflib模糊匹配到已知列名 -> 列名->x坐标映射
"""
import sys
import os
import asyncio
import difflib
import tempfile

_reconf = getattr(sys.stdout, "reconfigure", None)
if _reconf:
    try:
        _reconf(encoding="utf-8", errors="replace")
    except Exception:
        pass

import cv2
import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(BASE, "fixtures", "clipboard.png")

UPPER_HEADERS = ["选择", "委外订单号", "供应商", "入库日期", "入库单号", "仓库", "采购类型",
                 "存货编码", "存货名称", "规格型号", "主计量", "LOT号", "片号", "丝印",
                 "订单号", "入库数量", "件数", "本币单价", "本币金额", "本币税额",
                 "本币价税合计", "材料费", "加工费", "报检数"]
KEY_ANCHORS = ["采购类型", "入库数量", "件数"]


def load_img(path):
    with open(path, "rb") as f:
        data = f.read()
    img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit(f"无法读取 {path}")
    return img


def detect_v_lines(gray, y0, y1, x0=0, x1=None, min_span_ratio=0.5):
    """在[y0,y1]带内检测竖直线x坐标: 二值化暗像素, 竖向形态学开运算"""
    if x1 is None:
        x1 = gray.shape[1]
    band = gray[y0:y1, x0:x1]
    dark = (band < 150).astype(np.uint8)
    h = band.shape[0]
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(9, h // 3)))
    opened = cv2.morphologyEx(dark, cv2.MORPH_OPEN, k)
    colsum = opened.sum(axis=0)
    thresh = min_span_ratio * h
    xs = np.where(colsum >= thresh)[0]
    # 合并相邻(<=2px)
    groups = []
    for x in xs:
        if groups and x - groups[-1][-1] <= 2:
            groups[-1].append(x)
        else:
            groups.append([x])
    return [x0 + int(np.mean(g)) for g in groups]


def detect_h_lines(gray, x0, x1, y0=0, y1=None, min_span_ratio=0.6):
    """检测水平线y坐标"""
    if y1 is None:
        y1 = gray.shape[0]
    band = gray[y0:y1, x0:x1]
    dark = (band < 150).astype(np.uint8)
    w = band.shape[1]
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (max(9, w // 4), 1))
    opened = cv2.morphologyEx(dark, cv2.MORPH_OPEN, k)
    rowsum = opened.sum(axis=1)
    thresh = min_span_ratio * w
    ys = np.where(rowsum >= thresh)[0]
    groups = []
    for y in ys:
        if groups and y - groups[-1][-1] <= 2:
            groups[-1].append(y)
        else:
            groups.append([y])
    return [y0 + int(np.mean(g)) for g in groups]


async def ocr_cell_async(path):
    from winsdk.windows.media.ocr import OcrEngine
    from winsdk.windows.globalization import Language
    from winsdk.windows.graphics.imaging import BitmapDecoder
    from winsdk.windows.storage import StorageFile
    file = await StorageFile.get_file_from_path_async(os.path.abspath(path))
    stream = await file.open_read_async()
    decoder = await BitmapDecoder.create_async(stream)
    bmp = await decoder.get_software_bitmap_async()
    engine = OcrEngine.try_create_from_language(Language("zh-Hans-CN"))
    if engine is None:
        engine = OcrEngine.try_create_from_user_profile_languages()
    result = await engine.recognize_async(bmp)
    return "".join(w.text for line in result.lines for w in line.words)


def ocr_cell(img, tag):
    """单元格裁剪 -> 放大4x -> 反色二值化 -> OCR"""
    h, w = img.shape[:2]
    if w < 3 or h < 3:
        return ""
    scale = 4
    big = cv2.resize(img, (w * scale, h * scale), interpolation=cv2.INTER_LANCZOS4)
    gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
    # 自适应二值化: 文字深色背景浅色
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # OCR对白底黑字更友好
    ink_ratio = (bw == 0).mean()
    if ink_ratio > 0.5:
        bw = cv2.bitwise_not(bw)
    tmp = os.path.join(tempfile.gettempdir(), f"u8_cell_{tag}.png")
    cv2.imwrite(tmp, bw)
    try:
        return asyncio.run(ocr_cell_async(tmp)).strip()
    except Exception as e:
        return f"<ERR {type(e).__name__}>"


def fuzzy_map(text):
    """OCR文本 -> 最相似已知列名"""
    if not text:
        return None, 0.0
    best, score = None, 0.0
    for h in UPPER_HEADERS:
        s = difflib.SequenceMatcher(None, text.replace(" ", ""), h).ratio()
        if s > score:
            best, score = h, s
    return best, score


def main():
    img = load_img(FIXTURE)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    H, W = gray.shape
    print(f"fixture: {W}x{H}")

    # 上表大约在 y [60, H*0.6]; 先粗找上表区域的水平线
    h_lines = detect_h_lines(gray, 0, W, 0, int(H * 0.62))
    print(f"上区水平线 y: {h_lines[:20]}")
    if len(h_lines) < 2:
        print("FAIL: 上区水平线不足")
        return 2
    # 表头带 = 前2条水平线之间(第1条=网格顶, 第2条=表头底)
    grid_top, header_bottom = h_lines[0], h_lines[1]
    header_y0, header_y1 = grid_top + 1, header_bottom - 1
    print(f"表头带: y[{header_y0},{header_y1}] 高{header_y1 - header_y0 + 1}px")

    # 数据带(找竖线用): 表头底往下 300px
    data_y1 = min(header_bottom + 300, int(H * 0.62))
    v_lines = detect_v_lines(gray, header_bottom + 5, data_y1)
    print(f"竖直线 x({len(v_lines)}): {v_lines[:30]}")
    if len(v_lines) < 5:
        print("FAIL: 竖线不足")
        return 2
    # 列边界: 图左缘 + 竖线 + 图右缘
    bounds = [0] + v_lines + [W]

    # 每列表头单元格OCR
    print("--- 表头单元格识别 ---")
    mapping = {}
    for i in range(len(bounds) - 1):
        x0, x1 = bounds[i] + 1, bounds[i + 1]
        if x1 - x0 < 20:
            continue
        cell = img[header_y0:header_y1 + 1, x0:x1]
        text = ocr_cell(cell, f"u{i}")
        name, score = fuzzy_map(text)
        mark = "★" if name in KEY_ANCHORS and score >= 0.6 else " "
        print(f"  {mark} 列{i:2d} x[{x0:4d},{x1:4d}] OCR={text!r} -> {name}({score:.2f})")
        if name and score >= 0.6 and name not in mapping:
            mapping[name] = (x0 + x1) // 2
    hit = [a for a in KEY_ANCHORS if a in mapping]
    print(f"关键锚点命中: {len(hit)}/{len(KEY_ANCHORS)} {hit}")
    return 0 if len(hit) == len(KEY_ANCHORS) else 1


if __name__ == "__main__":
    sys.exit(main())
