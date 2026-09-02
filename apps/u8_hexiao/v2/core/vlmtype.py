# -*- coding: utf-8 -*-
"""vlmtype.py — VLM 封闭集分类兜底层

HTTP 仅使用标准库 urllib.request; 图像编码使用已有 opencv + base64.
VLM 失败永不抛出、永不阻断.
"""

import base64
import json
import urllib.request
from typing import List, Optional, Tuple

import cv2

from . import typematch


class VLMTypeClassifier:
    def __init__(self, base_url: str, api_key: str, model: str, known_types: List[str], timeout_s: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.known_types = list(known_types)
        self.timeout_s = float(timeout_s)

    def _build_prompt(self) -> str:
        return (
            "这是ERP表格\"采购类型\"单元格截图。候选类型：\n"
            + "\n".join(self.known_types)
            + "\n判断截图中文字是哪个候选。只输出候选原文，一字不差；无法确定输出 UNKNOWN"
        )

    def _build_payload(self, b64_image: str) -> dict:
        return {
            "model": self.model,
            "temperature": 0,
            "max_tokens": 30,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64_image}"},
                        },
                        {"type": "text", "text": self._build_prompt()},
                    ],
                }
            ],
        }

    def _chat(self, payload: dict) -> dict:
        """发起 OpenAI 格式请求; 独立方法供测试 monkeypatch."""
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def classify(self, cell_img_bgr) -> Tuple[Optional[str], str]:
        """返回 (解析出的 known 原文或 None, 模型原始回答/错误信息)."""
        try:
            ok, buf = cv2.imencode(".png", cell_img_bgr)
            if not ok:
                return None, "cv2.imencode failed"
            b64_image = base64.b64encode(buf).decode("ascii")
            payload = self._build_payload(b64_image)
            resp = self._chat(payload)
            text = resp["choices"][0]["message"]["content"]
            stripped = text.strip()
            # 后处理: normalize 后精确等值匹配 known 原文
            for k in self.known_types:
                if typematch.normalize(k) == typematch.normalize(stripped):
                    return k, text
            return None, text
        except Exception as e:
            return None, f"{type(e).__name__}: {e}"
