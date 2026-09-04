# -*- coding: utf-8 -*-
"""main.py — v2 CLI 入口

用法:
  python main.py selftest      全量离线自检(规则+审计+校验单测/视觉fixture/冒烟, 不动鼠标)
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
    suite = unittest.defaultTestLoader.discover(os.path.join(BASE_DIR, "tests"), pattern="test_*.py")
    runner = unittest.TextTestRunner(verbosity=2)
    ok1 = runner.run(suite).wasSuccessful()
    ok2 = vision_fixture_test()
    ok3 = audit_smoke_test()
    ok4 = verifier_smoke_test()
    print(f"\n自检总结: 单测(规则+审计+校验)={'PASS' if ok1 else 'FAIL'} 视觉fixture={'PASS' if ok2 else 'FAIL'} "
          f"审计冒烟={'PASS' if ok3 else 'FAIL'} 校验冒烟={'PASS' if ok4 else 'FAIL'}")
    return 0 if (ok1 and ok2 and ok3 and ok4) else 1


def audit_smoke_test():
    """离线审计冒烟: 临时目录 start/step/summary 走一遍并断言产物存在"""
    import tempfile
    from core.audit import AuditSink
    with tempfile.TemporaryDirectory() as td:
        sink = AuditSink(base_dir=td)
        sink.start(window_title="smoke", type_map={})
        sink.step("smoke_step", {"k": 1})
        sink.summary({"pass": 0}, {"verified": 0, "fail": 0, "unknown": 0})
        runs_root = os.path.join(td, "runs")
        run_dir = os.path.join(runs_root, os.listdir(runs_root)[0])
        ok = (os.path.isfile(os.path.join(run_dir, "steps.jsonl"))
              and os.path.isfile(os.path.join(run_dir, "summary.json")))
        print(f"审计冒烟: {'PASS' if ok else 'FAIL'}")
        return ok


def verifier_smoke_test():
    """离线校验冒烟: 构造核销前后状态, 断言 VERIFIED"""
    from core.verifier import verify_row_hexiao, VERIFIED

    class _R:
        def __init__(self, y, q):
            self.y, self._q = y, q
        def num(self, col):
            return self._q

    class _S:
        def __init__(self, rows):
            self.ok, self.upper_rows = True, rows

    before = _R(100, 50.0)
    st_b, st_a = _S([before]), _S([_R(100, 30.0)])
    ok = verify_row_hexiao(st_b, st_a, before) == VERIFIED
    print(f"校验冒烟: {'PASS' if ok else 'FAIL'}")
    return ok


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


def cmd_calibrate():
    """交互式校准核销按钮坐标: 倒计时3秒后采样鼠标位置并写入config"""
    import time
    import pyautogui
    from core import config as cfgmod
    cfg = cfgmod.load_config()
    print("即将校准核销按钮坐标: 3秒内把鼠标移到U8界面的[核销]按钮上并停住...")
    for i in range(3, 0, -1):
        print(f"  {i}...")
        time.sleep(1)
    x, y = pyautogui.position()
    # 存窗口内相对坐标(点击时加实时窗口偏移, 窗口移动/缩放不失效)
    from core import vision
    _, off = vision.grab_window(cfg.get("window_title", "委外核销处理"))
    if off:
        x, y = x - off[0], y - off[1]
    cfg["hexiao_button"] = [int(x), int(y)]
    cfgmod.save_config(cfg)
    print(f"已采样核销按钮坐标(窗口内) = ({int(x)}, {int(y)}), 已保存到 config_v2.json")
    return 0


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
    sub.add_parser("calibrate", help="校准核销按钮坐标(倒计时3秒采样鼠标)")
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
