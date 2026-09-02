# -*- coding: utf-8 -*-
"""运行日志: 控制台 + 文件"""

import os
import sys
import time

_reconf = getattr(sys.stdout, "reconfigure", None)
if _reconf:
    try:
        _reconf(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, "logs")


class Logger:
    def __init__(self, name="run"):
        os.makedirs(LOG_DIR, exist_ok=True)
        self.path = os.path.join(LOG_DIR, f"{name}_{time.strftime('%Y%m%d_%H%M%S')}.log")
        self._fh = open(self.path, "a", encoding="utf-8")

    def __call__(self, msg):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line)
        try:
            self._fh.write(line + "\n")
            self._fh.flush()
        except Exception:
            pass

    def close(self):
        try:
            self._fh.close()
        except Exception:
            pass
