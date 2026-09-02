# -*- coding: utf-8 -*-
"""executor.py — 鼠标/键盘执行器: 点击/修正单元格/核销/确认弹窗 (带安全阀)"""

import time
import ctypes

import pyautogui

pyautogui.FAILSAFE = True   # 鼠标甩左上角急停
pyautogui.PAUSE = 0.05


class SafetyStop(Exception):
    """用户主动/安全阀触发的停止"""


class Executor:
    def __init__(self, cfg, log):
        self.cfg = cfg
        self.log = log
        self.max_clicks = int(cfg.get("max_clicks_total", 800))
        self.clicks = 0
        self.stopped = False

    # ---- 安全 ----
    def stop(self):
        self.stopped = True

    def _check(self):
        if self.stopped:
            raise SafetyStop("已停止(用户请求)")
        if self.clicks >= self.max_clicks:
            raise SafetyStop(f"已达到最大点击数 {self.max_clicks}(安全阀)")

    # ---- 基础动作 ----
    def click(self, x, y, desc=""):
        self._check()
        self.clicks += 1
        pyautogui.click(int(x), int(y))
        if desc:
            self.log(f"点击 {desc} ({int(x)},{int(y)}) [{self.clicks}/{self.max_clicks}]")

    def click_row(self, wx, wy, win_off, desc=""):
        """窗口坐标 -> 屏幕坐标点击"""
        self.click(wx + win_off[0], wy + win_off[1], desc)

    def set_cell_value(self, wx, wy, win_off, value, desc=""):
        """双击单元格 -> 全选 -> 输入 -> 回车"""
        self._check()
        sx, sy = int(wx + win_off[0]), int(wy + win_off[1])
        self.clicks += 2  # 双击计2次
        pyautogui.doubleClick(sx, sy)
        time.sleep(0.15)
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.05)
        pyautogui.typewrite(str(value), interval=0.02)
        time.sleep(0.1)
        pyautogui.press("enter")
        self.log(f"修正 {desc}: ({sx},{sy}) 输入 {value}")

    def press_hexiao(self):
        """点击核销按钮"""
        btn = self.cfg.get("hexiao_button")
        if not btn:
            raise SafetyStop("核销按钮坐标未校准(config_v2.json: hexiao_button), 请先在GUI中校准")
        self.click(btn[0], btn[1], "核销按钮")
        time.sleep(float(self.cfg.get("pacing", {}).get("post_hexiao_wait_s", 1.2)))

    def confirm_dialog(self):
        """确认弹窗: enter策略按N次回车"""
        times = int(self.cfg.get("confirm_enter_times", 2))
        for i in range(times):
            self._check()
            pyautogui.press("enter")
            self.log(f"确认弹窗: 按回车 ({i + 1}/{times})")
            time.sleep(0.8)
