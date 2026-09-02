# -*- coding: utf-8 -*-
"""gui.py — U8委外核销自动化 v2 图形界面 (tkinter)

仅实现 GUI 层, 复用 core/ 与 config_v2.json; 禁止修改 core/ 和 main.py。

用法:
  python gui.py          启动图形界面
  python gui.py --smoke  冒烟测试: 2秒后自动关闭并打印 SMOKE OK

说明:
  - RapidOCR 采用 lazy 加载, 只会在后台线程生成 Runner 并首次截图时载入(约2-5秒),
    不影响 GUI 启动。
  - 生成计划(dry-run)/开始执行 均在后台线程运行, 通过 queue 把日志送回 UI 线程。
  - 运行会移动鼠标并点击(真实操作), 急停 = 鼠标甩到屏幕左上角。
"""

import copy
import os
import queue
import sys
import threading
import time
from collections import Counter
import tkinter as tk
from tkinter import ttk, scrolledtext

import pyautogui

from core.config import load_config, save_config
from core.applog import Logger
from core.executor import Executor, SafetyStop
from core.runner import Runner
from core.vision import ensure_dpi_aware, grab_window

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

ACTION_CN = {"PASS": "通过", "MODIFY": "修正", "SKIP": "跳过", "ERROR": "异常"}


def _now_ts():
    return time.strftime("%H:%M:%S")


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("U8委外核销助手")
        # 2026-09-02: 规则表扩到6类型后左栏(规则配置+参数)超出600px默认高,
        # "校准核销按钮"被裁出可视区(M0-③实机踩坑), 提高默认/最小尺寸
        self.root.geometry("960x760")
        self.root.minsize(900, 700)
        self.root.option_add("*Font", ("Microsoft YaHei UI", 10))

        self.cfg = load_config()
        self.q = queue.Queue()
        self._busy = False          # 是否有后台任务/校准在进行
        self._op_thread = None
        self._runner = None
        self._executor = None
        self._cal_seconds = 0
        self._type_names = []       # Listbox 显示的 类型名 列表(与条目顺序一致)

        self._build_ui()
        self._refresh_type_list()
        self._refresh_hexiao()
        self.root.after(100, self._poll)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ==================== UI 构建 ====================
    def _build_ui(self):
        root = self.root
        root.columnconfigure(0, weight=0, minsize=430)
        root.columnconfigure(1, weight=1, minsize=420)
        root.rowconfigure(0, weight=0)
        root.rowconfigure(1, weight=1)   # 规则区(左)/参数区(右) 拉伸
        root.rowconfigure(2, weight=1)   # 操作区(左)/日志区(右) 拉伸
        root.rowconfigure(3, weight=0)

        self._build_status(root)
        self._build_rules(root)
        self._build_params(root)
        self._build_log(root)           # 右列跨行
        self._build_actions(root)
        self._build_bottom(root)

    def _build_status(self, root):
        frm = ttk.LabelFrame(root, text=" 连接状态 ", padding=6)
        frm.grid(row=0, column=0, columnspan=2, sticky="ew", padx=6, pady=(6, 3))
        frm.columnconfigure(1, weight=1)
        frm.columnconfigure(3, weight=1)

        ttk.Label(frm, text="窗口标题:").grid(row=0, column=0, sticky="w")
        self.var_title = tk.StringVar(value=self.cfg.get("window_title", "委外核销处理"))
        ttk.Entry(frm, textvariable=self.var_title, width=30).grid(
            row=0, column=1, sticky="ew", padx=4)
        self.btn_test = ttk.Button(frm, text="测试连接", command=self._test_connection)
        self.btn_test.grid(row=0, column=2, padx=(8, 4))
        ttk.Label(frm, text="状态:").grid(row=0, column=3, sticky="w", padx=(8, 2))
        self.var_status = tk.StringVar(value="就绪")
        ttk.Label(frm, textvariable=self.var_status, foreground="#0a6").grid(
            row=0, column=4, sticky="w")

    def _build_rules(self, root):
        frm = ttk.LabelFrame(root, text=" 规则配置 (采购类型 -> 分类) ", padding=6)
        frm.grid(row=1, column=0, sticky="nsew", padx=(6, 3), pady=3)
        frm.columnconfigure(0, weight=1)
        frm.columnconfigure(1, weight=1)
        frm.rowconfigure(0, weight=1)   # listbox 行拉伸

        box = ttk.Frame(frm)
        box.grid(row=0, column=0, columnspan=4, sticky="nsew", pady=(0, 6))
        self.lst_types = tk.Listbox(box, height=7, selectmode="browse",
                                    font=("Microsoft YaHei UI", 10))
        sb = ttk.Scrollbar(box, orient="vertical", command=self.lst_types.yview)
        self.lst_types.configure(yscrollcommand=sb.set)
        self.lst_types.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        ttk.Label(frm, text="采购类型:").grid(row=1, column=0, sticky="w")
        self.var_type_name = tk.StringVar()
        ttk.Entry(frm, textvariable=self.var_type_name).grid(
            row=1, column=1, sticky="ew", padx=4)
        ttk.Label(frm, text="分类:").grid(row=1, column=2, sticky="w")
        self.var_type_cat = tk.StringVar(value="A")
        ttk.Combobox(frm, textvariable=self.var_type_cat, values=["A", "B"],
                     state="readonly", width=4).grid(row=1, column=3, sticky="w")

        self.btn_add = ttk.Button(frm, text="添加", command=self._add_type)
        self.btn_add.grid(row=2, column=2, sticky="ew", padx=(4, 2), pady=(6, 0))
        self.btn_del = ttk.Button(frm, text="删除选中", command=self._del_type)
        self.btn_del.grid(row=2, column=3, sticky="ew", pady=(6, 0))

        note = ttk.Label(
            frm, justify="left", foreground="#777", wraplength=390,
            text=self.cfg.get(
                "type_map_note",
                "A=按件数核对(逐行), B=按数量核对; 未列出的采购类型一律SKIP留人工"))
        note.grid(row=3, column=0, columnspan=4, sticky="w", pady=(6, 0))

    def _build_params(self, root):
        frm = ttk.LabelFrame(root, text=" 参数 ", padding=6)
        frm.grid(row=1, column=1, sticky="nsew", padx=(3, 6), pady=3)
        frm.columnconfigure(1, weight=1)

        r = 0
        ttk.Label(frm, text="确认回车次数:").grid(row=r, column=0, sticky="w", pady=2)
        self.spin_confirm = ttk.Spinbox(frm, from_=1, to=5, width=6)
        self.spin_confirm.set(str(int(self.cfg.get("confirm_enter_times", 2))))
        self.spin_confirm.grid(row=r, column=1, sticky="w", padx=6)
        ttk.Label(frm, text="次 (确认弹窗按回车)").grid(row=r, column=2, sticky="w")
        r += 1

        ttk.Label(frm, text="最大点击数:").grid(row=r, column=0, sticky="w", pady=2)
        self.var_max_clicks = tk.StringVar(
            value=str(self.cfg.get("max_clicks_total", 800)))
        ttk.Entry(frm, textvariable=self.var_max_clicks, width=10).grid(
            row=r, column=1, sticky="w", padx=6)
        ttk.Label(frm, text="(安全阀)").grid(row=r, column=2, sticky="w")
        r += 1

        ttk.Label(frm, text="行间隔 (ms):").grid(row=r, column=0, sticky="w", pady=2)
        self.var_row_settle = tk.StringVar(
            value=str(self.cfg.get("pacing", {}).get("row_settle_ms", 500)))
        ttk.Entry(frm, textvariable=self.var_row_settle, width=10).grid(
            row=r, column=1, sticky="w", padx=6)
        ttk.Label(frm, text="(每行联动等待)").grid(row=r, column=2, sticky="w")
        r += 1

        ttk.Label(frm, text="核销按钮坐标:").grid(row=r, column=0, sticky="w", pady=2)
        self.var_hexiao = tk.StringVar(value="未校准")
        ttk.Label(frm, textvariable=self.var_hexiao, relief="sunken",
                  width=18, anchor="w").grid(
            row=r, column=1, columnspan=2, sticky="w", padx=6, pady=2)
        r += 1

        self.btn_cal = ttk.Button(frm, text="校准核销按钮",
                                  command=self._calibrate_start)
        self.btn_cal.grid(row=r, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        r += 1
        ttk.Label(frm, text="点击后3秒内把鼠标移到U8核销按钮上, 自动采样坐标",
                  foreground="#777").grid(
            row=r, column=0, columnspan=3, sticky="w", pady=(2, 0))
        r += 1
        self.var_cal_countdown = tk.StringVar(value="")
        ttk.Label(frm, textvariable=self.var_cal_countdown,
                  foreground="#c00", font=("Microsoft YaHei UI", 14, "bold")).grid(
            row=r, column=0, columnspan=3, sticky="ew")

    def _build_actions(self, root):
        frm = ttk.LabelFrame(root, text=" 操作 ", padding=6)
        frm.grid(row=2, column=0, sticky="nsew", padx=(6, 3), pady=3)
        frm.columnconfigure(0, weight=1)
        frm.columnconfigure(1, weight=1)

        self.btn_plan = ttk.Button(frm, text="生成计划 (dry-run)",
                                   command=self._start_plan)
        self.btn_plan.grid(row=0, column=0, sticky="ew", padx=(0, 2), pady=2)
        self.btn_run = ttk.Button(frm, text="开始执行", command=self._start_run)
        self.btn_run.grid(row=0, column=1, sticky="ew", padx=(2, 0), pady=2)

        self.btn_stop = ttk.Button(frm, text="停止", command=self._stop,
                                   state="disabled")
        self.btn_stop.grid(row=1, column=0, columnspan=2, sticky="ew", pady=2)

        ttk.Label(frm, text="行数上限:").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.var_max_rows = tk.StringVar(value="")
        ttk.Entry(frm, textvariable=self.var_max_rows, width=10).grid(
            row=2, column=1, sticky="w", padx=6, pady=(6, 0))
        ttk.Label(frm, text="(留空=不限)").grid(row=2, column=2, sticky="w", pady=(6, 0))

        ttk.Separator(frm).grid(row=3, column=0, columnspan=3,
                                sticky="ew", pady=(8, 4))
        ttk.Label(frm, text="统计:  ").grid(row=4, column=0, sticky="w")
        self.var_stat_pass = tk.StringVar(value="通过 0")
        self.var_stat_modify = tk.StringVar(value="修正 0")
        self.var_stat_skip = tk.StringVar(value="跳过 0")
        self.var_stat_error = tk.StringVar(value="异常 0")
        stats = ttk.Frame(frm)
        stats.grid(row=4, column=1, columnspan=2, sticky="w")
        ttk.Label(stats, textvariable=self.var_stat_pass, foreground="#0a6").pack(side="left")
        ttk.Label(stats, text="  ").pack(side="left")
        ttk.Label(stats, textvariable=self.var_stat_modify, foreground="#06c").pack(side="left")
        ttk.Label(stats, text="  ").pack(side="left")
        ttk.Label(stats, textvariable=self.var_stat_skip, foreground="#a80").pack(side="left")
        ttk.Label(stats, text="  ").pack(side="left")
        ttk.Label(stats, textvariable=self.var_stat_error, foreground="#c00").pack(side="left")

    def _build_log(self, root):
        frm = ttk.LabelFrame(root, text=" 运行日志 ", padding=6)
        # 2026-09-02修复: 原先 (row=1,column=1,rowspan=2) 与参数框(row=1,column=1)
        # 同格重叠, 后渲染的日志框盖住参数框内的校准按钮 → 挪到独立格子(row=2)
        frm.grid(row=2, column=1, sticky="nsew", padx=(3, 6), pady=3)
        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(0, weight=1)
        self.txt_log = scrolledtext.ScrolledText(
            frm, state="disabled", wrap="word",
            font=("Microsoft YaHei UI", 9), height=12)
        self.txt_log.grid(row=0, column=0, sticky="nsew")

    def _build_bottom(self, root):
        frm = ttk.Frame(root, padding=(6, 3))
        frm.grid(row=3, column=0, columnspan=2, sticky="ew")
        frm.columnconfigure(0, weight=1)
        ttk.Label(frm, text="日志文件目录: logs/   (运行会移动鼠标并点击, 急停=甩鼠标到左上角)",
                  foreground="#777").grid(row=0, column=0, sticky="w")
        self.btn_save = ttk.Button(frm, text="保存配置", command=self._save_cfg)
        self.btn_save.grid(row=0, column=1, sticky="e")

    # ==================== 配置同步 ====================
    def _sync_cfg(self):
        """把界面控件值写回 self.cfg (窗口标题/参数; type_map 已在编辑时维护)"""
        self.cfg["window_title"] = self.var_title.get().strip() or "委外核销处理"

        try:
            v = int(self.spin_confirm.get())
            self.cfg["confirm_enter_times"] = max(1, min(5, v))
        except (ValueError, tk.TclError):
            self.cfg["confirm_enter_times"] = 2
            self.spin_confirm.set("2")

        try:
            v = int(self.var_max_clicks.get().strip())
            if v > 0:
                self.cfg["max_clicks_total"] = v
        except ValueError:
            self.var_max_clicks.set(str(self.cfg.get("max_clicks_total", 800)))

        try:
            v = int(self.var_row_settle.get().strip())
            self.cfg.setdefault("pacing", {})["row_settle_ms"] = max(50, v)
        except ValueError:
            self.var_row_settle.set(
                str(self.cfg.get("pacing", {}).get("row_settle_ms", 500)))

    def _save_cfg(self):
        self._sync_cfg()
        try:
            save_config(self.cfg)
            self.var_status.set("配置已保存: config_v2.json")
            self._append_log(_now_ts(), "配置已保存")
        except Exception as e:
            self.var_status.set(f"保存失败: {e}")

    def _parse_max_rows(self):
        s = self.var_max_rows.get().strip()
        if not s:
            return None
        try:
            n = int(s)
            return n if n > 0 else None
        except ValueError:
            self.var_status.set("行数上限格式错误, 按不限处理")
            return None

    # ==================== type_map 编辑 ====================
    def _refresh_type_list(self):
        tm = self.cfg.get("type_map", {})
        self._type_names = sorted(tm.keys())
        self.lst_types.delete(0, "end")
        for name in self._type_names:
            self.lst_types.insert("end", f"{name} -> {tm[name]}")

    def _add_type(self):
        name = self.var_type_name.get().strip()
        cat = self.var_type_cat.get().strip()
        if not name:
            self.var_status.set("请先输入采购类型")
            return
        if cat not in ("A", "B"):
            cat = "A"
        self.cfg.setdefault("type_map", {})[name] = cat
        self._refresh_type_list()
        self.var_type_name.set("")
        self.var_status.set(f"已添加: {name} -> {cat} (记得点[保存配置])")

    def _del_type(self):
        sel = self.lst_types.curselection()
        if not sel:
            self.var_status.set("请先在列表中选中要删除的类型")
            return
        name = self._type_names[sel[0]]
        self.cfg.setdefault("type_map", {}).pop(name, None)
        self._refresh_type_list()
        self.var_status.set(f"已删除: {name} (记得点[保存配置])")

    # ==================== 核销按钮校准 ====================
    def _refresh_hexiao(self):
        btn = self.cfg.get("hexiao_button")
        if btn:
            self.var_hexiao.set(f"({int(btn[0])}, {int(btn[1])})")
        else:
            self.var_hexiao.set("未校准")

    def _calibrate_start(self):
        if self._busy:
            return
        self._busy = True
        self._set_busy_ui(True)
        self._cal_seconds = 3
        self.var_status.set("校准: 请把鼠标移到U8核销按钮上, 3秒后自动采样")
        self.var_cal_countdown.set("3")
        self.root.after(1000, self._cal_tick)

    def _cal_tick(self):
        self._cal_seconds -= 1
        if self._cal_seconds <= 0:
            try:
                pos = pyautogui.position()
                self.cfg["hexiao_button"] = [int(pos.x), int(pos.y)]
                self._refresh_hexiao()
                self.var_status.set(
                    f"已校准核销按钮: ({int(pos.x)}, {int(pos.y)}) (记得保存)")
            except Exception as e:
                self.var_status.set(f"校准失败: {e}")
            self.var_cal_countdown.set("")
            self._busy = False
            self._set_busy_ui(False)
            return
        self.var_cal_countdown.set(str(self._cal_seconds))
        self.root.after(1000, self._cal_tick)

    # ==================== 测试连接 ====================
    def _test_connection(self):
        if self._busy:
            return
        self._busy = True
        self._set_busy_ui(True)
        self.var_status.set("正在查找窗口...")
        title = self.var_title.get().strip()
        threading.Thread(target=self._test_worker, args=(title,), daemon=True).start()

    def _test_worker(self, title):
        try:
            img, off = grab_window(title)
            if img is None:
                self.q.put(("status", _now_ts(), f"未找到窗口: '{title}'"))
                self.q.put(("log", _now_ts(), f"[测试连接] 未找到窗口: '{title}'"))
            else:
                h, w = img.shape[:2]
                self.q.put(("status", _now_ts(),
                            f"找到窗口 '{title}': {w}x{h}  屏幕左上角{off}"))
                self.q.put(("log", _now_ts(),
                            f"[测试连接] 找到窗口: {w}x{h}  屏幕左上角{off}"))
        except Exception as e:
            self.q.put(("status", _now_ts(), f"测试连接出错: {e}"))
            self.q.put(("log", _now_ts(), f"[测试连接] 出错: {e}"))
        finally:
            self.q.put(("op_done", _now_ts(), None))

    # ==================== 后台任务 (计划/执行) ====================
    def _start_plan(self):
        if self._busy:
            self.var_status.set("已有任务在运行, 请先停止或等待")
            return
        self._sync_cfg()
        cfg = copy.deepcopy(self.cfg)
        self._busy = True
        self._set_busy_ui(True)
        self.var_status.set("正在生成计划 (首次会加载OCR模型, 约2-5秒)...")
        self._append_log(_now_ts(), "== 开始生成计划(dry-run) ==")
        threading.Thread(target=self._plan_worker, args=(cfg,), daemon=True).start()

    def _plan_worker(self, cfg):
        logger = Logger("plan")
        def log(msg):
            logger(msg)
            self.q.put(("log", _now_ts(), str(msg)))
        try:
            ex = Executor(cfg, log)
            runner = Runner(cfg, ex, log)
            self.q.put(("init", _now_ts(), (runner, ex)))
            plans = runner.plan()
            self.q.put(("plan_result", _now_ts(), plans))
        except SafetyStop as e:
            self.q.put(("log", _now_ts(), f"[生成计划] 停止: {e}"))
        except BaseException as e:
            self.q.put(("log", _now_ts(),
                        f"[生成计划] 异常: {type(e).__name__}: {e}"))
        finally:
            try:
                logger.close()
            except Exception:
                pass
            self.q.put(("op_done", _now_ts(), None))

    def _start_run(self):
        if self._busy:
            self.var_status.set("已有任务在运行, 请先停止或等待")
            return
        if not self.cfg.get("hexiao_button"):
            self.var_status.set("提示: 核销按钮未校准, 执行会在点击核销时自动停止")
        self._sync_cfg()
        cfg = copy.deepcopy(self.cfg)
        max_rows = self._parse_max_rows()
        self._busy = True
        self._set_busy_ui(True)
        self.var_status.set("开始执行... (首次会加载OCR模型, 然后3秒倒计时后动鼠标)")
        self._append_log(_now_ts(), "== 开始执行 ==")
        threading.Thread(target=self._run_worker,
                         args=(cfg, max_rows), daemon=True).start()

    def _run_worker(self, cfg, max_rows):
        logger = Logger("run")
        def log(msg):
            logger(msg)
            self.q.put(("log", _now_ts(), str(msg)))
        try:
            ex = Executor(cfg, log)
            runner = Runner(cfg, ex, log)
            self.q.put(("init", _now_ts(), (runner, ex)))
            stats = runner.run(max_rows)
            self.q.put(("stats", _now_ts(), stats))
        except SafetyStop as e:
            self.q.put(("log", _now_ts(), f"[运行] 安全停止: {e}"))
        except BaseException as e:
            self.q.put(("log", _now_ts(), f"[运行] 异常: {type(e).__name__}: {e}"))
        finally:
            try:
                logger.close()
            except Exception:
                pass
            self.q.put(("op_done", _now_ts(), None))

    def _stop(self):
        if self._runner is not None:
            try:
                self._runner.stop()
            except Exception:
                pass
        if self._executor is not None:
            try:
                self._executor.stop()
            except Exception:
                pass
        self.var_status.set("已发送停止请求...")

    # ==================== UI 状态 / 消息轮询 ====================
    def _set_busy_ui(self, busy):
        st = "disabled" if busy else "normal"
        for b in (self.btn_plan, self.btn_run, self.btn_test,
                  self.btn_cal, self.btn_add, self.btn_del, self.btn_save):
            b.configure(state=st)
        self.btn_stop.configure(state="normal" if busy else "disabled")

    def _append_log(self, ts, msg):
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", f"[{ts}] {msg}\n")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _poll(self):
        try:
            while True:
                self._handle_item(self.q.get_nowait())
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _handle_item(self, item):
        kind, ts, payload = item
        if kind == "log":
            self._append_log(ts, payload)
        elif kind == "status":
            self.var_status.set(payload)
        elif kind == "init":
            self._runner, self._executor = payload
        elif kind == "plan_result":
            plans = payload
            self._append_log(ts, f"生成计划完成, 共 {len(plans)} 行:")
            c = Counter(p["action"] for p in plans)
            for p in plans:
                self._append_log(
                    ts,
                    f"  y={p['y']:.0f} [{p.get('采购类型', '?')}] "
                    f"{ACTION_CN.get(p['action'], p['action'])}: {p['reason']}")
            self._update_stats(c.get("PASS", 0), c.get("MODIFY", 0),
                               c.get("SKIP", 0), 0)
            self.var_status.set(f"生成计划完成: {len(plans)} 行 (见日志)")
        elif kind == "stats":
            st = payload
            self._update_stats(st.get("pass", 0), st.get("modify", 0),
                               st.get("skip", 0), st.get("error", 0))
            self._append_log(
                ts,
                f"运行结束统计: 通过={st.get('pass', 0)} 修正={st.get('modify', 0)} "
                f"跳过={st.get('skip', 0)} 异常={st.get('error', 0)}")
            self.var_status.set("运行结束")
        elif kind == "op_done":
            self._busy = False
            self._runner = None
            self._executor = None
            self._set_busy_ui(False)
            self._append_log(ts, "---- 任务结束 ----")

    def _update_stats(self, p, m, s, e):
        self.var_stat_pass.set(f"通过 {p}")
        self.var_stat_modify.set(f"修正 {m}")
        self.var_stat_skip.set(f"跳过 {s}")
        self.var_stat_error.set(f"异常 {e}")

    def _on_close(self):
        try:
            if self._runner is not None:
                self._runner.stop()
            if self._executor is not None:
                self._executor.stop()
        except Exception:
            pass
        self.root.destroy()


def main():
    ensure_dpi_aware()
    app = App()
    if "--smoke" in sys.argv:

        def _smoke_exit():
            app.root.destroy()
            print("SMOKE OK")
        app.root.after(2000, _smoke_exit)
    app.root.mainloop()


if __name__ == "__main__":
    main()
