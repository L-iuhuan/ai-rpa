# -*- coding: utf-8 -*-
"""main.py — v2 CLI 入口

用法:
  python main.py selftest      规则引擎+视觉离线自检(fixture回归, 不动鼠标)
  python main.py plan          截图当前窗口, 输出判定计划(不动鼠标)
  python main.py run           完整逐行核销循环(动鼠标!)
  python main.py run --rows 3  只处理前3行(试跑)
"""

import sys
import os
import argparse

_reconf = getattr(sys.stdout, "reconfigure", None)
if _reconf:
    try:
        _reconf(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)


def cmd_selftest():
    import unittest
    suite = unittest.defaultTestLoader.discover(os.path.join(BASE_DIR, "tests"), pattern="test_rules.py")
    runner = unittest.TextTestRunner(verbosity=2)
    ok1 = runner.run(suite).wasSuccessful()
    ok2 = vision_fixture_test()
    print(f"\n自检总结: 规则引擎={'PASS' if ok1 else 'FAIL'} 视觉fixture={'PASS' if ok2 else 'FAIL'}")
    return 0 if (ok1 and ok2) else 1


def vision_fixture_test():
    """离线视觉回归: 用 fixture 截图验证 read_tables 结构化"""
    from core import vision
    import cv2
    import numpy as np

    path = os.path.join(BASE_DIR, "tests", "fixtures", "clipboard.png")
    with open(path, "rb") as f:
        img = cv2.imdecode(np.frombuffer(f.read(), dtype=np.uint8), cv2.IMREAD_COLOR)
    template = vision.load_template("assets/checkbox_raw.png")
    st = vision.read_tables(img, template, 0.8)
    if not st.ok:
        print(f"视觉fixture: FAIL - {st.msg}")
        return False
    n_up = len(st.upper_rows)
    n_low = len(st.lower_rows)
    # 已知事实: 截图上表约17数据行, 下表1数据行(高亮联动)+表头
    has_type = sum(1 for r in st.upper_rows if r.cols.get("采购类型"))
    has_qty = sum(1 for r in st.upper_rows if r.cols.get("入库数量"))
    print(f"视觉fixture: 上表{n_up}行(采购类型{has_type}/入库数量{has_qty}) 下表{n_low}行 "
          f"上表头y={st.upper_header_y:.0f} 下表头y={st.lower_header_y:.0f}")
    ok = n_up >= 10 and has_type >= 8 and has_qty >= 8 and n_low >= 1
    print(f"视觉fixture: {'PASS' if ok else 'FAIL'}")
    if not ok:
        for r in st.upper_rows[:20]:
            print("   行", round(r.y), dict(list(r.cols.items())[:8]))
    return ok


def cmd_plan():
    from core import vision, config as cfgmod
    from core.runner import Runner
    from core.executor import Executor
    from core.applog import Logger

    cfg = cfgmod.load_config()
    log = Logger("plan")
    ex = Executor(cfg, log)
    runner = Runner(cfg, ex, log)
    try:
        plans = runner.plan()
        print(f"\n共 {len(plans)} 行判定计划(详见日志 {log.path})")
    finally:
        log.close()
    return 0


def cmd_run(max_rows=None):
    from core import vision, config as cfgmod
    from core.runner import Runner
    from core.executor import Executor
    from core.applog import Logger

    cfg = cfgmod.load_config()
    log = Logger("run")
    ex = Executor(cfg, log)
    runner = Runner(cfg, ex, log)
    try:
        stats = runner.run(max_rows)
        print(f"\n结果: {stats}")
    finally:
        log.close()
    return 0


def main():
    parser = argparse.ArgumentParser(description="U8委外核销自动化 v2")
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("selftest", help="离线自检(不动鼠标)")
    sub.add_parser("plan", help="输出判定计划(不动鼠标)")
    p_run = sub.add_parser("run", help="执行核销循环(动鼠标)")
    p_run.add_argument("--rows", type=int, default=None, help="最多处理行数")
    args = parser.parse_args()

    from core.vision import ensure_dpi_aware
    ensure_dpi_aware()

    if args.mode == "selftest":
        sys.exit(cmd_selftest())
    if args.mode == "plan":
        sys.exit(cmd_plan())
    if args.mode == "run":
        sys.exit(cmd_run(args.rows))


if __name__ == "__main__":
    main()
