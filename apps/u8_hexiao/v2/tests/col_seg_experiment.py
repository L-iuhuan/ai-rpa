# -*- coding: utf-8 -*-
"""M3实验C: x聚类切列 + 逐格放大OCR (fixture离线验证)

事实依据(diag_pixels): U8表格无竖向网格线, 纯白底文字行(行距约17px), y=336为上下表分隔
方案: 文本带内做x投影聚类得到单元格 -> 表头行OCR模糊匹配定位锚列 -> 数据行按锚列x范围读数
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

HEADERS = ["选择", "委外订单号", "供应商", "入库日期", "入库单号", "仓库", "采购类型",
           "存货编码", "存货名称", "规格型号", "主计量", "LOT号", "片号", "丝印",
           "订单号", "入库数量", "件数", "本币单价", "本币金额", "本币税额",
           "本币价税合计", "材料费", "加工费", "报检数"]
ANCHORS = ["采购类型", "入库数量", "件数"]
TH_DARK = 190   # 文字暗阈值
GAP = 10         # x聚类间隙阈值(px)


def load_img(path):
    with open(path, "rb") as f:
        data = f.read()
    img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit(f"无法读取 {path}")
    return img


def text_bands(gray, y0, y1, min_dark=12):
    """在[y0,y1)内找文本行带: [(by0,by1), ...]"""
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
    """行带内x投影聚类: [(cx0,cx1), ...]"""
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
            else:
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


async def _ocr_path_async(path):
    from winsdk.windows.media.ocr import OcrEngine
    from winsdk.windows.globalization import Language
    from winsdk.windows.graphics.imaging import BitmapDecoder
    from winsdk.windows.storage import StorageFile
    file = await StorageFile.get_file_from_path_async(path)
    stream = await file.open_read_async()
    decoder = await BitmapDecoder.create_async(stream)
    bmp = await decoder.get_software_bitmap_async()
    eng = OcrEngine.try_create_from_language(Language("zh-Hans-CN")) or \
        OcrEngine.try_create_from_user_profile_languages()
    result = await eng.recognize_async(bmp)
    return "".join(w.text for line in result.lines for w in line.words)


def ocr_cell(img, tag, scale=4):
    """单元格裁剪->放大->二值化->OCR"""
    h, w = img.shape[:2]
    if w < 4 or h < 4:
        return ""
    big = cv2.resize(img, (w * scale, h * scale), interpolation=cv2.INTER_LANCZOS4)
    gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if (bw == 0).mean() > 0.5:
        bw = cv2.bitwise_not(bw)
    tmp = os.path.join(tempfile.gettempdir(), f"u8x_{tag}.png")
    cv2.imwrite(tmp, bw)
    try:
        return asyncio.run(_ocr_path_async(tmp)).strip()
    except Exception as e:
        return f"<ERR{type(e).__name__}>"


def fuzzy(text):
    if not text:
        return None, 0.0
    t = "".join(text.split())
    best, score = None, 0.0
    for hd in HEADERS:
        s = difflib.SequenceMatcher(None, t, hd).ratio()
        if s > score:
            best, score = hd, s
    return best, score


def main():
    img = load_img(FIXTURE)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    H, W = gray.shape
    print(f"fixture: {W}x{H}")

    bands = text_bands(gray, 20, 336)
    print(f"上表文本带 {len(bands)} 条: {bands[:6]}...")
    if not bands:
        print("FAIL: 无文本带")
        return 2

    # 逐带OCR找表头(前4条带内必命中则停)
    header_band = None
    header_cells = None
    for bi, (by0, by1) in enumerate(bands[:4]):
        clusters = x_clusters(gray, by0, by1)
        if len(clusters) < 5:
            continue
        hits = 0
        cells = []
        for ci, (cx0, cx1) in enumerate(clusters):
            if cx1 - cx0 < 12:
                cells.append(None)
                continue
            text = ocr_cell(img[by0:by1 + 1, cx0:cx1 + 1], f"h{bi}_{ci}")
            name, score = fuzzy(text)
            cells.append((name, score, text, cx0, cx1))
            if name in ANCHORS and score >= 0.6:
                hits += 1
        print(f"带{bi} y[{by0},{by1}] 聚类{len(clusters)} 锚点命中{hits}")
        if hits >= 2:
            header_band = (by0, by1)
            header_cells = cells
            break
    if not header_band:
        print("FAIL: 前4带内未找到表头")
        return 2

    print(f"表头带: y[{header_band[0]},{header_band[1]}]")
    anchor_x = {}
    for c in header_cells:
        if not c:
            continue
        name, score, text, cx0, cx1 = c
        mark = "★" if name in ANCHORS and score >= 0.6 else " "
        print(f"  {mark} x[{cx0:4d},{cx1:4d}] {text!r} -> {name}({score:.2f})")
        if name in ANCHORS and score >= 0.6 and name not in anchor_x:
            anchor_x[name] = (cx0, cx1)
    hit = [a for a in ANCHORS if a in anchor_x]
    print(f"锚点: {len(hit)}/{len(ANCHORS)} {hit}")
    if len(hit) < len(ANCHORS):
        print("FAIL: 锚点不全")
        return 2

    # 数据行: 表头带之后取2条样本带, 按锚列x范围读单元格
    hb_index = bands.index(header_band)
    samples = bands[hb_index + 1:hb_index + 3]
    print("--- 数据行样本读数 ---")
    ok_num = 0
    for si, (by0, by1) in enumerate(samples):
        for name in ANCHORS:
            ax0, ax1 = anchor_x[name]
            # 在锚列x范围(左右各扩4px)内取该行的实际文字簇
            cl = x_clusters(gray, by0, by1, x0=max(0, ax0 - 4), x1=min(W, ax1 + 5))
            if not cl:
                print(f"  行{si} {name}: <空>")
                continue
            cx0, cx1 = cl[0]
            text = ocr_cell(img[by0:by1 + 1, cx0:cx1 + 1], f"d{si}_{name}")
            print(f"  行{si} {name}: {text!r}")
            t = text.replace(",", "")
            try:
                float(t)
                ok_num += 1
            except ValueError:
                pass
    print(f"数字格解析: {ok_num} 个成功")
    print("EXPERIMENT PASS" if ok_num >= 2 else "EXPERIMENT PARTIAL")
    return 0 if ok_num >= 2 else 1


if __name__ == "__main__":
    sys.exit(main())
