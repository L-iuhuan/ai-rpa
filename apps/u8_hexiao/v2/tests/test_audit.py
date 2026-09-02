# -*- coding: utf-8 -*-
"""audit.py 单测: 验证 AuditSink 产物与 IO 异常不抛错"""

import os
import sys
import unittest
import tempfile
import shutil
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
from core.audit import AuditSink


class T_AuditSink(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sink = AuditSink(base_dir=self.tmp.name)

    def test_no_op_before_start(self):
        """未 start 前 step/summary 不抛错、不创建目录"""
        self.sink.step("x", {"a": 1})
        self.sink.summary({}, {})
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "runs")))

    def test_start_creates_dirs(self):
        self.sink.start()
        self.assertTrue(os.path.isdir(self.sink._run_dir))
        self.assertTrue(os.path.isdir(self.sink._shot_dir))
        self.assertTrue(os.path.isfile(self.sink._steps_path))

    def test_step_jsonl_and_screenshot(self):
        self.sink.start()
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        self.sink.step("judge", {"row_y": 120, "action": "PASS"}, img=img)
        self.sink.step("verify", {"result": "VERIFIED"})

        with open(self.sink._steps_path, encoding="utf-8") as f:
            lines = [l for l in f if l.strip()]
        self.assertEqual(len(lines), 2)

        rec1 = json.loads(lines[0])
        self.assertEqual(rec1["seq"], 1)
        self.assertEqual(rec1["name"], "judge")
        self.assertEqual(rec1["meta"]["action"], "PASS")
        self.assertIn("ts", rec1)

        shot_path = os.path.join(self.sink._shot_dir, "step_001.png")
        self.assertTrue(os.path.isfile(shot_path))
        self.assertGreater(os.path.getsize(shot_path), 0)

    def test_summary_fields(self):
        self.sink.start(window_title="委外核销处理", type_map={"封测编": "A"})
        self.sink.summary(
            {"pass": 1, "modify": 0, "skip": 0, "error": 0},
            {"verified": 1, "fail": 0, "unknown": 0},
        )
        path = os.path.join(self.sink._run_dir, "summary.json")
        self.assertTrue(os.path.isfile(path))
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
        self.assertEqual(payload["meta"]["window_title"], "委外核销处理")
        self.assertEqual(payload["meta"]["type_map"], {"封测编": "A"})
        self.assertEqual(payload["stats"]["pass"], 1)
        self.assertEqual(payload["verify_summary"]["verified"], 1)
        self.assertIn("start_time", payload["meta"])
        self.assertIn("end_time", payload)

    def test_io_failure_swallowed(self):
        """只读目录导致写入失败时, 不应抛异常"""
        runs_dir = os.path.join(self.tmp.name, "runs")
        os.makedirs(runs_dir)
        # 将 runs 目录设为只读(Windows: 去掉写入权限)
        os.chmod(runs_dir, 0o555)
        try:
            sink = AuditSink(base_dir=self.tmp.name)
            sink.start()
            sink.step("x", {})
            sink.summary({}, {})
            self.assertFalse(sink._started)
        finally:
            os.chmod(runs_dir, 0o755)


if __name__ == "__main__":
    unittest.main(verbosity=2)
