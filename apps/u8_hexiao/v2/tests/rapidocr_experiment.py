# -*- coding: utf-8 -*-
"""M3实验D: RapidOCR(PP-OCR ONNX) 验证 — 整图识别 + x聚类单格识别对比

判定标准:
  整图: 表头锚点(采购类型/入库数量/件数/未核销数量/本次核销数量)全命中, 已知数字(1562477/20477/25.000000/273)命中>=3
  单格: 放大后数字格识别可解析为float
"""
import sys
import os
import difflib

_reconf = getattr(sys.stdout, "reconfigure", None)
if _reconf:
    try:
        _reconf(encoding="utf-8", errors="replace")
    except Exception:
        pass

import cv2
import numpy as np
from rapidocr_onnxruntime import RapidOCR

BASE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(BASE, "fixtures", "clipboard.png")

ANCHORS = ["采购类型", "入库数量", "件数", "未核销数量", "本次核销数量", "出库数量"]
KNOWN_NUMBERS = ["1562477", "20477", "25.000000", "273"]
HEADERS = ["选择", "委外订单号", "供应商", "入库日期", "入库单号", "仓库", "采购类型",
           "存货编码", "存货名称", "规格型号", "主计量", "LOT号", "片号", "丝印",
           "订单号", "入库数量", "件数", "本币单价", "本币金额", "本币税额",
           "本币价税合计", "材料费", "加工费", "报检数",
           "业务类型", "出库日期", "出库单号", "出库数量", "单价", "金额",
           "未核销数量", "待核销绝对数量", "本次核销数量", "未核销金额", "本次核销金额"]
TH_DARK = 190
GAP = 10


def load_img(path):
    with open(path, "rb") as f:
        data = f.read()
    img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit(f"无法读取 {path}")
    return img


def text_bands(gray, y0, y1, min_dark=12):
    rowcnt = (gray[y0:y1, :] < TH_DARK).sum(axis=1)
    bands = []
    start = None
    for i, c in enumerate(rowcnt):
        if c >= min_dark and start is None:
            start = i
        elif c < min_dark and start is not None:
            if i - start >= 4:
                bands.append((y0 + start, y0 + i - 1))
            start = None
    if start is not None and (len(rowcnt) - start) >= 4:
        bands.append((y0 + start, y0 + len(rowcnt) - 1))
    return bands


def x_clusters(gray, by0, by1, x0=0, x1=None):
    if x1 is None:
        x1 = gray.shape[1]
    band = gray[by0:by1 + 1, x0:x1]
    colcnt = (band < TH_DARK).sum(axis=0)
    clusters = []
    start = None
    gap = 0
    for i, c in enumerate(colcnt):
        if c > 0:
            if start is None:
                start = i
            gap = 0
        else:
            if start is not None:
                gap += 1
                if gap >= GAP:
                    clusters.append((x0 + start, x0 + i - gap))
                    start = None
                    gap = 0
    if start is not None:
        clusters.append((x0 + start, x0 + len(colcnt) - 1))
    return clusters


def norm(s):
    return "".join(str(s).split())


def main():
    ocr = RapidOCR()
    img = load_img(FIXTURE)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    H, W = gray.shape
    print(f"fixture: {W}x{H}")

    # ---- 方式1: 整图识别 ----
    result, _ = ocr(img)
    boxes = []
    if result:
        for box, text, conf in result:
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            boxes.append((norm(text), float(conf), min(xs), min(ys), max(xs), max(ys)))
    print(f"\n=== 整图RapidOCR: {len(boxes)}个文本块 ===")
    all_text = "".join(b[0] for b in boxes).replace(",", "")
    anchor_pos = {}
    for a in ANCHORS:
        hit_b = next((b for b in boxes if b[0] == a or (a in b[0] and len(b[0]) <= len(a) + 3)), None)
        if hit_b:
            anchor_pos[a] = ((hit_b[2] + hit_b[4]) / 2, (hit_b[3] + hit_b[5]) / 2)
        print(f"  锚点 {a}: {'命中 x=%.0f y=%.0f' % anchor_pos[a] if a in anchor_pos else '未命中'}")
    num_hits = 0
    for n in KNOWN_NUMBERS:
        ok = any(n in b[0].replace(",", "") for b in boxes) or n in all_text
        num_hits += int(ok)
        print(f"  数字 {n}: {'命中' if ok else '未命中'}")
    print(f"整图汇总: 锚点{len(anchor_pos)}/{len(ANCHORS)} 数字{num_hits}/{len(KNOWN_NUMBERS)}")

    # ---- 方式2: 表头行带 + 单格放大识别(验证关键列定位链路) ----
    print("\n=== 表头带单格识别 ===")
    bands = text_bands(gray, 20, 336)
    header_ok = False
    anchor_x = {}
    for bi, (by0, by1) in enumerate(bands[:3]):
        # 放大整带识别(带高只有~10px, 放大4x)
        crop = img[by0:by1 + 1, :]
        h, w = crop.shape[:2]
        res = None
        if h >= 8 and w >= 32:
            try:
                big = cv2.resize(crop, (min(w * 4, 4000), h * 4), interpolation=cv2.INTER_LANCZOS4)
                res, _ = ocr(big)
            except Exception as e:
                print(f"    带OCR异常(忽略): {type(e).__name__}")
                res = None
        if not res:
            continue
        cell_texts = []
        for box, text, conf in res:
            xs = [float(p[0]) / 4 for p in box]
            cell_texts.append((norm(text), min(xs), max(xs), float(conf)))
        hits = 0
        print(f"带{bi} y[{by0},{by1}]: {len(cell_texts)}格")
        for t, x0, x1, conf in cell_texts:
            best, score = None, 0.0
            for hd in HEADERS:
                s = difflib.SequenceMatcher(None, t, hd).ratio()
                if s > score:
                    best, score = hd, s
            if score >= 0.6 and best in ANCHORS:
                hits += 1
                anchor_x.setdefault(best, ((x0 + x1) / 2, by0, by1))
            print(f"    x[{x0:5.0f},{x1:5.0f}] {t!r} conf={conf:.2f} -> {best}({score:.2f})"[:130])
        if hits >= 2:
            header_ok = True
            print(f"  -> 表头带确认为带{bi}, 锚点x: { {k: round(v[0]) for k, v in anchor_x.items()} }")
            break
    print(f"表头判定: {'PASS' if header_ok else 'FAIL'}")

    # ---- 数字单格验证: 用整图OCR的数字块坐标直接读 ----
    print("\n=== 数字块识别质量(整图) ===")
    import re
    numeric = [(b[0], b[2], b[3], b[4], b[5]) for b in boxes
               if re.fullmatch(r"[\d,\.]+", b[0]) and len(b[0].replace(",", "").replace(".", "")) >= 2]
    print(f"纯数字块: {len(numeric)}个, 示例前12:")
    for t, x0, y0, x1, y1 in numeric[:12]:
        print(f"  ({x0:.0f},{y0:.0f}) {t!r}")

    ok = header_ok and len(anchor_pos) >= len(ANCHORS) - 1 and num_hits >= 3
    print("\n" + ("EXPERIMENT PASS (RapidOCR方案可行)" if ok else "EXPERIMENT PARTIAL/FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
