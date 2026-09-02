# -*- coding: utf-8 -*-
"""OCR 可行性基准 (M3): 用用户实测截图验证 Windows OCR 能否定位列头锚点并读出数字

用法: python tests/ocr_probe.py [图片路径]   (默认 fixtures/clipboard.png)
输出: 锚点命中率 / 数字命中率 / 明细, 退出码 0=全部通过
"""

import sys
import os
import asyncio
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
sys.path.insert(0, os.path.join(BASE, ".."))

# 锚点: 上表表头 / 下表表头 的关键列名
UPPER_ANCHORS = ["采购类型", "入库数量", "件数", "入库单号"]
LOWER_ANCHORS = ["未核销数量", "本次核销数量", "出库数量", "待核销绝对数量"]
# 截图中已知存在的数值(人工标注): 千分位/多位小数是难点
KNOWN_NUMBERS = ["1562477", "20477", "25.000000", "273"]


def load_img(path):
    with open(path, "rb") as f:
        data = f.read()
    img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit(f"错误: 无法读取图片 {path}")
    return img


async def ocr_words_async(path):
    """对图片文件做 Windows OCR, 返回 {line_idx: [(text, x, y, w, h), ...]}"""
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
    if engine is None:
        raise SystemExit("错误: 系统无可用OCR语言包(需装中文语言)")
    result = await engine.recognize_async(bmp)
    lines = {}
    for li, line in enumerate(result.lines):
        words = []
        for word in line.words:
            r = word.bounding_rect
            words.append((word.text, r.x, r.y, r.width, r.height))
        lines[li] = words
    return lines


def ocr_scaled(img, scale, max_dim):
    """缩放后写临时文件OCR, 坐标映射回原图; 超尺寸自动封顶"""
    h, w = img.shape[:2]
    factor = scale
    if max(h, w) * factor > max_dim:
        factor = max_dim / max(h, w)
    if factor == 1.0:
        scaled = img
    else:
        scaled = cv2.resize(img, (int(w * factor), int(h * factor)), interpolation=cv2.INTER_CUBIC)
    tmp = os.path.join(tempfile.gettempdir(), "u8_ocr_probe.png")
    ok, buf = cv2.imencode(".png", scaled)
    with open(tmp, "wb") as f:
        f.write(buf.tobytes())
    lines = asyncio.run(ocr_words_async(tmp))
    return {li: [(t, x / factor, y / factor, ww / factor, hh / factor) for (t, x, y, ww, hh) in ws]
            for li, ws in lines.items()}


def norm(s):
    return "".join(str(s).split())


def find_anchor(lines, anchor):
    """行级匹配: 整行词拼接后找子串, 命中则返回覆盖词的联合bbox中心; 兼容任意拆词"""
    a = norm(anchor)
    for li, words in lines.items():
        items = [(norm(w[0]), w) for w in words]
        if not any(s for s, _ in items):
            continue
        full = "".join(s for s, _ in items)
        pos = full.find(a)
        if pos < 0:
            continue
        # 定位覆盖该子串的词区间
        acc = 0
        boxes = []
        for s, w in items:
            start, end = acc, acc + len(s)
            acc = end
            if end > pos and start < pos + len(a):
                boxes.append(w)
        if boxes:
            x0 = min(b[1] for b in boxes)
            x1 = max(b[1] + b[3] for b in boxes)
            y0 = min(b[2] for b in boxes)
            y1 = max(b[2] + b[4] for b in boxes)
            return ((x0 + x1) / 2, (y0 + y1) / 2)
    return None


def run(path):
    from winsdk.windows.media.ocr import OcrEngine
    max_dim = OcrEngine.max_image_dimension
    print(f"OCR基准测试: {path} (引擎最大尺寸 {max_dim})")
    img = load_img(path)
    best = None
    for scale in (1, 2, 3):
        try:
            lines = ocr_scaled(img, scale, max_dim)
        except Exception as e:
            print(f"  [scale={scale}] OCR失败: {type(e).__name__}: {e}")
            continue
        text_norm = "".join(t for ws in lines.values() for (t, *__) in ws).replace(",", "").replace(" ", "")
        n_up = sum(1 for a in UPPER_ANCHORS if find_anchor(lines, a))
        n_low = sum(1 for a in LOWER_ANCHORS if find_anchor(lines, a))
        n_num = sum(1 for n in KNOWN_NUMBERS if n in text_norm or n.rstrip("0").rstrip(".") in text_norm)
        print(f"  [scale={scale}] 行数={len(lines)} 上表锚点 {n_up}/{len(UPPER_ANCHORS)} "
              f"下表锚点 {n_low}/{len(LOWER_ANCHORS)} 数字 {n_num}/{len(KNOWN_NUMBERS)}")
        if best is None or (n_up + n_low + n_num) > best[0]:
            best = (n_up + n_low + n_num, scale, lines, n_up, n_low, n_num, text_norm)
        if n_up == len(UPPER_ANCHORS) and n_low == len(LOWER_ANCHORS) and n_num == len(KNOWN_NUMBERS):
            break
    if best is None:
        print("FAIL: 所有缩放均OCR失败")
        return 1
    _, scale, lines, n_up, n_low, n_num, text_norm = best
    print(f"采用 scale={scale}")
    for a in UPPER_ANCHORS + LOWER_ANCHORS:
        pos = find_anchor(lines, a)
        print(f"  锚点 {a}: {'命中 x=%.0f y=%.0f' % pos if pos else '未命中'}")
    for n in KNOWN_NUMBERS:
        print(f"  数字 {n}: {'命中' if (n in text_norm or n.rstrip('0').rstrip('.') in text_norm) else '未命中'}")
    # 调试: 打印疑似表头行(含2个以上锚点片段的行)
    print("  [调试] 疑似表头行内容:")
    frag = "类型数量件数单号核销出库绝对"
    for li, ws in lines.items():
        line_text = "".join(t for (t, *__) in ws)
        if sum(1 for c in frag if c in line_text) >= 3:
            print(f"    行{li}: {line_text[:120]}")
    total = n_up + n_low + n_num
    expect = len(UPPER_ANCHORS) + len(LOWER_ANCHORS) + len(KNOWN_NUMBERS)
    rate = total / expect
    print(f"总命中率: {total}/{expect} = {rate:.0%}")
    if n_up == len(UPPER_ANCHORS) and n_low == len(LOWER_ANCHORS):
        print("PROBE PASS (锚点全中, 数字>=80%)" if rate >= 0.8 else "PROBE PARTIAL (锚点全中, 数字不足)")
        return 0 if rate >= 0.8 else 1
    print("PROBE FAIL (锚点缺失, OCR方案不可行, 需换引擎)")
    return 2


if __name__ == "__main__":
    img_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, "fixtures", "clipboard.png")
    if not os.path.exists(img_path):
        print(f"文件不存在: {img_path}")
        sys.exit(3)
    sys.exit(run(img_path))
