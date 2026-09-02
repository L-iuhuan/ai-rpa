# -*- coding: utf-8 -*-
"""v2 配置管理"""

import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "config_v2.json")

DEFAULT_CONFIG = {
    "window_title": "委外核销处理",
    "type_map": {
        "封测编": "A"
    },
    "type_map_note": "A=按件数核对(逐行), B=按数量核对; 未列出的采购类型一律SKIP留人工",
    "qty_tol": 0.005,
    "pacing": {
        "click_delay_ms": 150,
        "row_settle_ms": 500,
        "post_hexiao_wait_s": 1.2,
        "scroll_clicks": 3,
        "scroll_pause_ms": 400,
        "max_screens": 3
    },
    "checkbox_x_offset": 66,
    "match_threshold": 0.8,
    "hexiao_button": None,
    "confirm_strategy": "enter",
    "confirm_enter_times": 2,
    "max_clicks_total": 800,
    "max_loop_rows": 200,
    "template": "assets/checkbox_raw.png"
}


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception as e:
            print(f"警告: 读取配置失败({e}), 用默认配置")
    return cfg


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
