# -*- coding: utf-8 -*-
"""audit.py — 审计落盘: 每次运行创建 runs/YYYYMMDD-HHMMSS/ 目录,
记录 steps.jsonl + 截图 + summary.json; 审计失败不阻断主流程.
"""

import os
import time
import json
from datetime import datetime
from typing import Any, Dict, Optional


class AuditSink:
    """审计落盘器. 未 start() 前调用 step/summary 均为 no-op,
    保证 plan/selftest 等不创建 runs 目录也能跑.
    """

    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = base_dir
        self._run_dir: Optional[str] = None
        self._shot_dir: Optional[str] = None
        self._steps_path: Optional[str] = None
        self._seq = 0
        self._started = False
        self._meta: Dict[str, Any] = {}

    def _now_iso(self) -> str:
        return datetime.now().isoformat(timespec="seconds")

    def start(self, window_title: str = "", type_map: Optional[Dict[str, str]] = None):
        """创建 runs/YYYYMMDD-HHMMSS/ 目录结构."""
        try:
            root = self.base_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            runs_root = os.path.join(root, "runs")
            os.makedirs(runs_root, exist_ok=True)
            # 防御: Windows 下 os.chmod 0o555 仍会放行 makedirs/open,
            # 但 st_file_attributes 会置 READONLY 位, 需要显式拒绝.
            st = os.stat(runs_root)
            if getattr(st, "st_file_attributes", 0) & 1:
                raise PermissionError(f"{runs_root} 为只读目录")
            run_name = time.strftime("%Y%m%d-%H%M%S")
            self._run_dir = os.path.join(runs_root, run_name)
            self._shot_dir = os.path.join(self._run_dir, "screenshots")
            os.makedirs(self._shot_dir, exist_ok=True)
            self._steps_path = os.path.join(self._run_dir, "steps.jsonl")
            # 先写空文件确保路径可用
            open(self._steps_path, "w", encoding="utf-8").close()
            self._seq = 0
            self._meta = {
                "start_time": self._now_iso(),
                "window_title": window_title,
                "type_map": dict(type_map) if type_map else {},
            }
            # 目录创建/元数据初始化全部成功后才置位
            self._started = True
        except Exception as e:
            print(f"警告: audit start 失败: {e}")
            self._started = False

    def step(self, name: str, meta: Optional[Dict[str, Any]] = None, img=None):
        """追加步骤; img 非 None 时保存截图."""
        if not self._started:
            return
        try:
            self._seq += 1
            rec = {
                "ts": self._now_iso(),
                "seq": self._seq,
                "name": name,
                "meta": meta if meta is not None else {},
            }
            with open(self._steps_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

            if img is not None:
                self._save_img(img, f"step_{self._seq:03d}.png")
        except Exception as e:
            print(f"警告: audit step '{name}' 失败: {e}")

    def _save_img(self, img, filename: str):
        """cv2.imencode 写中文路径, 避免 cv2.imwrite 中文路径问题."""
        import cv2
        path = os.path.join(self._shot_dir, filename)
        ok, buf = cv2.imencode(".png", img)
        if ok:
            with open(path, "wb") as f:
                f.write(buf.tobytes())

    def summary(self, stats: Dict[str, Any], verify_summary: Dict[str, Any]):
        """写 summary.json."""
        if not self._started:
            return
        try:
            payload = {
                "meta": self._meta,
                "stats": dict(stats),
                "verify_summary": dict(verify_summary),
                "end_time": self._now_iso(),
            }
            path = os.path.join(self._run_dir, "summary.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"警告: audit summary 失败: {e}")
