# -*- coding: utf-8 -*-
"""runner.py — v2 运行循环: 逐行扫描上表 -> 联动下表 -> 规则判定 -> 执行核销

流程(方案文档 4.1):
  激活窗口 -> 循环{ 截图+OCR读两表 -> 取下一未处理上表行 -> 点击行选中(下表联动) ->
  等待刷新 -> 重读下表 -> 规则判定 -> PASS:勾选两行+核销 / MODIFY:改本次核销数量+核销 / SKIP:跳过 }
  -> 滚动翻页继续, 直到底部或达到 max_loop_rows
"""

import time
from typing import Optional, List

from . import vision
from .rules import UpperRow, LowerRow, judge, PASS, MODIFY, SKIP
from .executor import SafetyStop
from .audit import AuditSink
from .verifier import verify_row_hexiao, VERIFIED, VERIFY_FAIL, VERIFY_UNKNOWN
from . import typematch
from .vlmtype import VLMTypeClassifier


class Runner:
    def __init__(self, cfg, executor, log, template=None, audit=None):
        self.cfg = cfg
        self.ex = executor
        self.log = log
        self.audit = audit if audit is not None else AuditSink()
        self.template = template if template is not None else vision.load_template(cfg.get("template", "assets/checkbox_raw.png"))
        self.type_map = cfg.get("type_map", {})
        self.known_types = list(self.type_map.keys())
        self.type_match_cfg = cfg.get("type_match", {})
        self.fuzzy_max_distance = int(self.type_match_cfg.get("fuzzy_max_distance", 2))
        vlm_cfg = cfg.get("vlm", {})
        self.classifier = None
        if vlm_cfg.get("enabled"):
            self.classifier = VLMTypeClassifier(
                base_url=vlm_cfg.get("base_url", ""),
                api_key=vlm_cfg.get("api_key", ""),
                model=vlm_cfg.get("model", ""),
                known_types=self.known_types,
                timeout_s=float(vlm_cfg.get("timeout_s", 30)),
            )
        self.tol = float(cfg.get("qty_tol", 0.005))
        p = cfg.get("pacing", {})
        self.row_settle_ms = float(p.get("row_settle_ms", 500))
        self.click_delay_ms = float(p.get("click_delay_ms", 150))
        self.max_loop_rows = int(cfg.get("max_loop_rows", 200))
        # 统计
        self.stats = {"pass": 0, "modify": 0, "skip": 0, "error": 0,
                      "verify_verified": 0, "verify_fail": 0, "verify_unknown": 0}
        self.stop_requested = False
        self._processed_ys: List[float] = []  # 已处理行的y(窗口坐标, 防重复)

    def stop(self):
        self.stop_requested = True
        self.ex.stop()

    # ---- 感知 ----
    def _grab(self):
        img, off = vision.grab_window(self.cfg.get("window_title", ""))
        if img is None:
            raise RuntimeError(f"未找到窗口: {self.cfg.get('window_title')}")
        return img, off

    def _read(self):
        img, off = self._grab()
        st = vision.read_tables(img, self.template, float(self.cfg.get("match_threshold", 0.8)))
        return img, off, st

    # ---- 单行处理 ----
    def _to_upper(self, rd) -> UpperRow:
        return UpperRow(
            purchase_type=rd.cols.get("采购类型"),
            in_qty=rd.num("入库数量"),
            in_pieces=rd.num("件数"),
        )

    def _to_lowers(self, rows) -> List[LowerRow]:
        out = []
        for rd in rows:
            out.append(LowerRow(
                pieces=rd.num("件数"),
                unreconciled_qty=rd.num("未核销数量"),
                this_qty=rd.num("本次核销数量"),
            ))
        return out

    def _resolve_type(self, raw, img, col_x, row_y) -> tuple:
        """三层类型解析: exact -> fuzzy -> vlm. 返回 (resolved_known_or_None, method)."""
        if raw is None:
            return None, "none"
        raw_norm = typematch.normalize(raw)
        if not raw_norm:
            return None, "none"

        # 1) exact
        for k in self.known_types:
            if typematch.normalize(k) == raw_norm:
                return k, "exact"

        # 2) fuzzy
        resolved = typematch.resolve_type(raw, self.known_types, self.fuzzy_max_distance)
        if resolved is not None:
            return resolved, "fuzzy"

        # 3) vlm
        if self.classifier is not None and img is not None:
            try:
                h, w = img.shape[:2]
                x1 = max(0, int(col_x) - 8)
                x2 = min(w, int(col_x) + 130)
                y1 = max(0, int(row_y) - 13)
                y2 = min(h, int(row_y) + 13)
                if x1 < x2 and y1 < y2:
                    cell_img = img[y1:y2, x1:x2]
                    resolved, info = self.classifier.classify(cell_img)
                    if resolved is not None:
                        return resolved, "vlm"
                    return None, f"vlm:{info}"
            except Exception as e:
                return None, f"vlm_error:{type(e).__name__}:{e}"

        return None, "none"

    def _pick_next_row(self, st):
        """上表里下一个未处理行. 优先选"采购类型"可读的行, 类型缺失的行沉底.

        2026-09-04实锤: 初始读屏偶发漏检下表头时, 上表行扫描延伸到底部会把
        下表数据行当幻影行纳入(其采购类型列恒为None)——优先选有类型的行,
        幻影行天然沉底; 处理真实行后下表通常已被正确检出, 幻影自然消失.
        """
        fallback = None
        for rd in st.upper_rows:
            if any(abs(rd.y - py) <= 8 for py in self._processed_ys):
                continue
            txt = "".join(rd.cols.values())
            if "合计" in txt:
                continue
            if rd.cols.get("采购类型"):
                return rd
            if fallback is None:
                fallback = rd
        return fallback

    def _wait_settle(self):
        time.sleep(self.row_settle_ms / 1000.0)

    def _process_row(self, st, rd, off, img):
        """处理一行: 选中 -> 联动 -> 判定 -> 执行. 返回 action"""
        # 1) 类型解析(exact/fuzzy/vlm)
        col_x = st.upper_cols.get("采购类型", (60, 0))[0] if st.upper_cols else 60
        raw_type = rd.cols.get("采购类型")
        resolved_type, method = self._resolve_type(raw_type, img, col_x, rd.y)
        purchase_type = resolved_type if resolved_type is not None else raw_type
        self.log(f"类型解析 行y={rd.y:.0f} [{raw_type}] -> {resolved_type} ({method})")
        self.audit.step("type_resolve", {"raw": raw_type, "resolved": resolved_type, "method": method})

        # 2) 点击行选中(用行的委外订单号块位置; 没有则用行y+第一列)
        anchor_block = rd.cols.get("委外订单号")
        click_x = None
        if anchor_block is not None and st.upper_cols.get("委外订单号"):
            click_x = st.upper_cols["委外订单号"][0]
        if click_x is None:
            click_x = st.upper_cols.get("委外订单号", (60, 0))[0] if st.upper_cols else 60
        self.ex.click_row(click_x, rd.y, off, "选中上表行")
        self._processed_ys.append(rd.y)
        self._wait_settle()

        # 3) 重读下表(联动刷新后; 初始态点击行后下表才出现)
        img2, off2, st2 = self._read()
        if not st2.ok or not getattr(st2, "lower_found", True):
            self.stats["error"] += 1
            self.log(f"行y={rd.y:.0f}: 点击选中后下表未出现({st2.msg}), 跳过")
            return "ERROR"
        lowers = self._to_lowers(st2.lower_rows)
        # 过滤掉合计行
        lowers = [lw for lw, lrd in zip(lowers, st2.lower_rows)
                  if "合计" not in "".join(lrd.cols.values())]

        # 4) 规则判定
        dec = judge(purchase_type, self._to_upper(rd), lowers, self.type_map, self.tol)
        self.log(f"行y={rd.y:.0f} [{purchase_type}] -> {dec.action}: {dec.reason}")
        self.audit.step("judge", {"row_y": rd.y, "action": dec.action, "reason": dec.reason})

        # 5) 执行
        if dec.action == SKIP:
            self.stats["skip"] += 1
            return SKIP
        # 勾选上表行复选框
        if rd.checkbox:
            self.ex.click_row(rd.checkbox[0], rd.checkbox[1], off, "上表复选框")
            time.sleep(self.click_delay_ms / 1000.0)
        # 勾选下表全部行复选框(联动行; 多行时规则已SKIP, 这里只会是单行)
        for lrd in st2.lower_rows:
            if "合计" in "".join(lrd.cols.values()):
                continue
            if lrd.checkbox:
                self.ex.click_row(lrd.checkbox[0], lrd.checkbox[1], off2, "下表复选框")
                time.sleep(self.click_delay_ms / 1000.0)
        # MODIFY: 修正本次核销数量(重读后的当前值再改, 用最新读数)
        if dec.action == MODIFY and dec.target is not None and st2.lower_rows:
            lrd = st2.lower_rows[0]
            col = st2.lower_cols.get("本次核销数量")
            if col:
                self.ex.set_cell_value(col[0], lrd.y, off2, f"{dec.target:g}", "本次核销数量")
                self._wait_settle()
        # 核销 + 确认
        self.ex.press_hexiao()
        self.ex.confirm_dialog()
        self.stats["pass" if dec.action == PASS else "modify"] += 1

        # 6) 核销结果校验
        try:
            post_img, _ = self._grab()
            self.audit.step("post_hexiao", img=post_img)
        except Exception as e:
            self.audit.step("post_hexiao", {"error": str(e)})
            post_img = None

        try:
            _, _, st3 = self._read()
        except Exception:
            st3 = None
        result = verify_row_hexiao(st, st3, rd, self.tol)
        self.audit.step("verify", {"row_y": rd.y, "result": result})
        if result == VERIFIED:
            self.stats["verify_verified"] += 1
        elif result == VERIFY_FAIL:
            self.stats["verify_fail"] += 1
            self.log(f"行y={rd.y:.0f}: 核销结果校验失败(未核销数量未变), 继续下一行(不自动重试)")
        else:
            self.stats["verify_unknown"] += 1

        self._wait_settle()
        return dec.action

    # ---- 主循环 ----
    def run(self, max_rows: Optional[int] = None):
        import pyautogui
        limit = max_rows or self.max_loop_rows
        self.audit.start(
            window_title=self.cfg.get("window_title", ""),
            type_map=self.type_map,
        )
        self.log(f"开始运行: 上限{limit}行 | 类型映射={self.type_map}")
        countdown_done = False
        while not self.stop_requested:
            img, off, st = self._read()
            if not st.ok:
                self.log(f"读取失败: {st.msg}")
                return self.stats
            rd = self._pick_next_row(st)
            if rd is None:
                # 当前屏无未处理行: 尝试滚动
                self.log("当前屏无未处理行, 向下滚动")
                pyautogui.scroll(-int(self.cfg.get("pacing", {}).get("scroll_clicks", 3)))
                time.sleep(float(self.cfg.get("pacing", {}).get("scroll_pause_ms", 400)) / 1000.0)
                img2, off2, st2 = self._read()
                rd2 = self._pick_next_row(st2) if st2.ok else None
                if rd2 is None and self._screen_unchanged(img, img2):
                    self.log("已到列表底部(滚动后无新行且画面无变化), 结束")
                    break
                continue
            processed = sum(v for k, v in self.stats.items() if not k.startswith("verify_"))
            if processed >= limit:
                self.log(f"已处理 {processed} 行, 达到上限{limit}, 结束本批")
                break
            if not countdown_done:
                self.log("3秒后开始操作鼠标, 急停=鼠标甩左上角")
                time.sleep(3)
                countdown_done = True
            try:
                self._process_row(st, rd, off, img)
            except SafetyStop as e:
                self.log(f"安全停止: {e}")
                break
            except Exception as e:
                self.stats["error"] += 1
                self.log(f"行处理异常: {type(e).__name__}: {e}, 继续下一行")
        self.audit.summary(
            self.stats,
            {
                "verified": self.stats.get("verify_verified", 0),
                "fail": self.stats.get("verify_fail", 0),
                "unknown": self.stats.get("verify_unknown", 0),
            },
        )
        self.log(f"结束: {self.stats}")
        return self.stats

    def _screen_unchanged(self, img1, img2):
        if img1 is None or img2 is None:
            return img1 is img2
        import cv2 as _cv
        import numpy as _np
        if img1.shape != img2.shape:
            return False
        diff = _cv.absdiff(img1, img2).mean()
        return diff < 0.5

    # ---- dry-run: 只出判定计划 ----
    def plan(self):
        img, off, st = self._read()
        if not st.ok:
            self.log(f"读取失败: {st.msg}")
            return []
        plans = []
        col_x = st.upper_cols.get("采购类型", (60, 0))[0] if st.upper_cols else 60
        for rd in st.upper_rows:
            txt = "".join(rd.cols.values())
            if "合计" in txt:
                continue
            raw_type = rd.cols.get("采购类型")
            resolved_type, method = self._resolve_type(raw_type, img, col_x, rd.y)
            purchase_type = resolved_type if resolved_type is not None else raw_type
            self.log(f"计划 类型解析 行y={rd.y:.0f} [{raw_type}] -> {resolved_type} ({method})")
            self.audit.step("type_resolve", {"raw": raw_type, "resolved": resolved_type, "method": method})
            dec = judge(purchase_type, self._to_upper(rd),
                        self._to_lowers([]), self.type_map, self.tol)
            plans.append({
                "y": rd.y, "采购类型": raw_type, "resolved_type": resolved_type,
                "method": method, "入库数量": rd.cols.get("入库数量", ""),
                "件数": rd.cols.get("件数", ""),
                "action": dec.action, "reason": dec.reason,
            })
            self.log(f"计划 行y={rd.y:.0f} [{purchase_type}] {dec.action}: {dec.reason}")
        self.log(f"共 {len(plans)} 行(注意: dry-run未逐行联动, 下表数据未读取, 仅按上表预判)")
        return plans
