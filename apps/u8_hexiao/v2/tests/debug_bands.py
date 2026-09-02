# -*- coding: utf-8 -*-
"""逐带调试: 每条文本带整体放大OCR, 看清OCR实际读出的内容(定位表头带+评估中文识别质量)"""
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
FIXTURE = os.path.join(BASE, "fixtures", "clipboard.png")
TH_DARK = 190


def load_img(path):
    with open(path, "rb") as f:
        data = f.read()
    return cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)


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


async def _ocr_async(path):
    from winsdk.windows.media.ocr import OcrEngine
    from winsdk.windows.globalization import Language
    from winsdk.windows.graphics.imaging import BitmapDecoder
    from winsdk.windows.storage import StorageFile
    f = await StorageFile.get_file_from_path_async(path)
    stream = await f.open_read_async()
    decoder = await BitmapDecoder.create_async(stream)
    bmp = await decoder.get_software_bitmap_async()
    eng = OcrEngine.try_create_from_language(Language("zh-Hans-CN")) or \
        OcrEngine.try_create_from_user_profile_languages()
    r = await eng.recognize_async(bmp)
    return " | ".join("".join(w.text for w in line.words) for line in r.lines)


def ocr_band(img, by0, by1, tag, scale=4):
    crop = img[by0:by1 + 1, :]
    h, w = crop.shape[:2]
    big = cv2.resize(crop, (w * scale, h * scale), interpolation=cv2.INTER_LANCZOS4)
    gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if (bw == 0).mean() > 0.5:
        bw = cv2.bitwise_not(bw)
    tmp = os.path.join(tempfile.gettempdir(), f"u8band_{tag}.png")
    cv2.imwrite(tmp, bw)
    try:
        return asyncio.run(_ocr_async(tmp))
    except Exception as e:
        return f"<ERR{type(e).__name__}:{e}>"


def main():
    img = load_img(FIXTURE)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    H, W = gray.shape
    print(f"fixture: {W}x{H}")
    # 上区带
    bands = text_bands(gray, 20, 336)
    print(f"=== 上区 {len(bands)} 带 ===")
    for i, (by0, by1) in enumerate(bands):
        text = ocr_band(img, by0, by1, f"u{i}")
        print(f"带{i:2d} y[{by0:4d},{by1:4d}]: {text[:150]}")
    # 下区带
    bands2 = text_bands(gray, 340, H)
    print(f"=== 下区 {len(bands2)} 带(前6) ===")
    for i, (by0, by1) in enumerate(bands2[:6]):
        text = ocr_band(img, by0, by1, f"l{i}")
        print(f"带{i:2d} y[{by0:4d},{by1:4d}]: {text[:150]}")


if __name__ == "__main__":
    main()
