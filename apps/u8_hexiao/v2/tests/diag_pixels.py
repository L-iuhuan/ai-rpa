# -*- coding: utf-8 -*-
"""诊断fixture像素结构: 定位文本行带/网格线灰度分布, 为切列检测调参提供依据"""
import sys
import os

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

with open(FIXTURE, "rb") as f:
    data = f.read()
img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
H, W = gray.shape
print(f"尺寸: {W}x{H}")
print(f"灰度分布: p5={np.percentile(gray,5):.0f} p25={np.percentile(gray,25):.0f} "
      f"p50={np.percentile(gray,50):.0f} p75={np.percentile(gray,75):.0f} p95={np.percentile(gray,95):.0f}")

# 行暗像素计数(多阈值对比, 找文本行带)
for th in (150, 190, 220):
    rowcnt = (gray < th).sum(axis=1)
    # 聚合连续非零行成带
    bands = []
    inband = False
    for y, c in enumerate(rowcnt):
        if c > 15 and not inband:
            bands.append([y, y, int(c)])
            inband = True
        elif c > 15 and inband:
            bands[-1][1] = y
            bands[-1][2] = max(bands[-1][2], int(c))
        elif c <= 15 and inband and y - bands[-1][1] > 2:
            inband = False
    print(f"\n--- 行暗像素带 (阈值{th}, 前25带) ---")
    for b in bands[:25]:
        print(f"  y[{b[0]:4d},{b[1]:4d}] 高{b[1]-b[0]+1:3d} 最大暗数{b[2]}")

# 用阈值190看上表数据区的竖向暗列分布(取文本行带之一)
rowcnt = (gray < 190).sum(axis=1)
text_rows = np.where(rowcnt > 30)[0]
if len(text_rows) > 0:
    y0 = int(text_rows.min())
    y1 = int(text_rows.max())
    print(f"\n文本行范围: y[{y0},{y1}]")
    band = gray[y0:y1 + 1, :]
    colcnt = (band < 190).sum(axis=0)
    # 竖线候选: 列暗像素数 >= 带高的60%
    h = band.shape[0]
    cand = np.where(colcnt >= h * 0.6)[0]
    print(f"竖线候选(列暗>=60%带高, 共{len(cand)}): {cand[:40].tolist()}")
    # 也看较宽松的40%
    cand2 = np.where(colcnt >= h * 0.4)[0]
    print(f"竖线候选(40%): {cand2[:60].tolist()}")
else:
    print("无文本行")
