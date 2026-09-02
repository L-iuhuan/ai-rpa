# -*- coding: utf-8 -*-
"""
U8委外核销自动化工具

用法:
  python u8_hexiao.py calibrate   交互式校准(采集模板/区域/按钮坐标)
  python u8_hexiao.py dry-run     只识别不点击, 生成 preview.png 预览
  python u8_hexiao.py select-only 只滚动勾选全部复选框, 不点核销(手动确认用)
  python u8_hexiao.py test-one    勾选当前屏可见项 + 点核销 + 确认(单批测试)
  python u8_hexiao.py run         完整自动: 滚动勾选全部 -> 核销 -> 确认
  python u8_hexiao.py selftest    自动化自检(不动鼠标, 不依赖U8)

急停: 把鼠标猛甩到屏幕左上角 (pyautogui FAILSAFE), 或控制台 Ctrl+C
"""

import sys
import os

_reconf = getattr(sys.stdout, "reconfigure", None)
if _reconf:
    try:
        _reconf(encoding="utf-8", errors="replace")
    except Exception:
        pass

import argparse
import json
import time
import random
import hashlib
import ctypes

import cv2
import numpy as np

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05
except ImportError:
    print("错误: 缺少 pyautogui, 请先运行: python -m pip install -r requirements.txt")
    sys.exit(1)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

DEFAULT_CONFIG = {
    "window_title": "核销",
    "region": [0, 50, 108, 1395],
    "template": "assets/checkbox_raw.png",
    "match_threshold": 0.85,
    "click_delay_ms": 200,
  "scroll_clicks": 3,
  "scroll_pause_ms": 400,
  "max_screens": 3,
    "hexiao_button": None,
    "confirm_strategy": "enter",
    "confirm_button": None,
    "confirm_enter_times": 3,
    "post_hexiao_wait_s": 1.5,
    "max_clicks_total": 500,
    "endless_scroll_guard": 2,
}

MAX_ROUNDS = 300  # 最大滚动轮数安全阀


# ---------------- 基础工具 ----------------

def ensure_dpi_aware():
    """高分屏下保证截图像素坐标与真实屏幕坐标一致"""
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception as e:
            print(f"警告: 读取 config.json 失败({e}), 使用默认配置")
    else:
        print(f"提示: 未找到 config.json, 使用默认配置")
    return cfg


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print(f"配置已保存: {CONFIG_PATH}")


def resolve_path(p):
    if os.path.isabs(p):
        return p
    return os.path.join(BASE_DIR, p)


def load_template(path):
    """用Python读字节再imdecode, 规避OpenCV在Windows下无法处理中文路径的问题"""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        raise SystemExit(f"错误: 无法读取模板图 {path}: {e}")
    img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit(f"错误: 模板图解码失败 {path}")
    if img.ndim == 3 and img.shape[2] == 4:
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    return img


def imwrite_safe(path, img):
    ext = os.path.splitext(path)[1] or ".png"
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        return False
    with open(path, "wb") as f:
        f.write(buf.tobytes())
    return True


def clamp_region(region):
    sw, sh = pyautogui.size()
    l, t, r, b = [int(v) for v in region]
    l = max(0, min(l, sw - 1))
    t = max(0, min(t, sh - 1))
    r = max(l + 1, min(r, sw - 1))
    b = max(t + 1, min(b, sh - 1))
    return [l, t, r, b]


def grab_region(region):
    """region: [left, top, right, bottom] (含端点), 返回 BGR ndarray"""
    l, t, r, b = region
    img = pyautogui.screenshot(region=(l, t, r - l + 1, b - t + 1))
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def img_hash(arr):
    return hashlib.md5(np.ascontiguousarray(arr).tobytes()).hexdigest()


# ---------------- 识别 ----------------

def find_matches(screenshot, template, threshold):
    """模板匹配 + 简易NMS去重, 返回按(y,x)排序的左上角坐标列表(区域局部坐标)"""
    th, tw = template.shape[:2]
    sh_, sw_ = screenshot.shape[:2]
    if th >= sh_ or tw >= sw_:
        return []
    res = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)
    ys, xs = np.where(res >= threshold)
    if len(xs) == 0:
        return []
    cand = sorted(zip(res[ys, xs].tolist(), xs.tolist(), ys.tolist()), reverse=True)
    min_dist = 0.8 * th
    kept = []
    for _score, x, y in cand:
        if all((x - kx) ** 2 + (y - ky) ** 2 >= min_dist ** 2 for kx, ky in kept):
            kept.append((int(x), int(y)))
    kept.sort(key=lambda p: (p[1], p[0]))
    return kept


# ---------------- 执行 ----------------

class ClickBudget:
    def __init__(self, limit):
        self.limit = int(limit)
        self.count = 0

    def click(self, x, y):
        if self.count >= self.limit:
            raise RuntimeError(f"已达到最大点击数 {self.limit}, 自动停止(安全限制)")
        pyautogui.click(int(x), int(y))
        self.count += 1


def activate_window(title):
    try:
        import pygetwindow as gw
        wins = [w for w in gw.getAllWindows() if title in (w.title or "")]
        if not wins:
            print(f"警告: 未找到标题含\"{title}\"的窗口, 将在当前桌面继续执行")
            return False
        w = wins[0]
        if w.isMinimized:
            w.restore()
            time.sleep(0.3)
        w.activate()
        time.sleep(0.5)
        return True
    except Exception as e:
        print(f"警告: 激活窗口失败({e}), 继续")
        return False


def countdown(seconds=3):
    print(f"{seconds}秒后开始, 请勿移动鼠标! 急停方法: 鼠标猛甩到屏幕左上角, 或 Ctrl+C")
    for i in range(seconds, 0, -1):
        print(f"  {i}...")
        time.sleep(1)


def select_pass(cfg, tpl, budget, allow_scroll=True):
    """勾选流程: 循环(识别可见未勾选项->点击->滚动), 勾满 max_screens 屏即停(防卡顿)"""
    region = clamp_region(cfg["region"])
    rl, rt = region[0], region[1]
    th, tw = tpl.shape[:2]
    threshold = float(cfg["match_threshold"])
    delay = float(cfg["click_delay_ms"]) / 1000.0
    scroll_clicks = int(cfg["scroll_clicks"])
    scroll_pause = float(cfg["scroll_pause_ms"]) / 1000.0
    guard = int(cfg["endless_scroll_guard"])
    max_screens = max(1, int(cfg.get("max_screens", 3)))
    total = 0
    rounds = 0
    screens = 0  # 有点击的一轮记为1屏
    stuck = 0
    stop_reason = ""

    while True:
        rounds += 1
        if rounds > MAX_ROUNDS:
            stop_reason = f"已超过 {MAX_ROUNDS} 轮安全限制"
            break
        shot = grab_region(region)
        matches = find_matches(shot, tpl, threshold)
        if matches:
            batch = 0
            for (mx, my) in matches:
                ax, ay = rl + mx + tw // 2, rt + my + th // 2
                budget.click(ax, ay)
                batch += 1
                total += 1
                print(f"[第{rounds}轮] 勾选 {batch}/{len(matches)} 屏幕({ax},{ay}) 累计{total}")
                time.sleep(delay)
            stuck = 0
            screens += 1
            if not allow_scroll:
                stop_reason = "当前屏勾选完成(未滚动)"
                break
            if screens >= max_screens:
                stop_reason = f"已勾选 {screens} 屏, 达到单批上限 max_screens={max_screens} (防卡顿), 本批到此为止"
                break
            pyautogui.scroll(-scroll_clicks)
            time.sleep(scroll_pause)
        else:
            if not allow_scroll:
                print("当前屏幕无未勾选项")
                stop_reason = "当前屏无未勾选项"
                break
            sig1 = img_hash(shot)
            pyautogui.scroll(-scroll_clicks)
            time.sleep(scroll_pause)
            sig2 = img_hash(grab_region(region))
            if sig1 == sig2:
                stuck += 1
                print(f"无匹配且滚动后画面无变化 ({stuck}/{guard})")
                if stuck >= guard:
                    stop_reason = "已到列表底部, 全部勾选完成"
                    break
            else:
                stuck = 0
    print(f"勾选阶段结束: 共勾选 {total} 项, 扫描{rounds}轮/{screens}屏")
    print(f"停止原因: {stop_reason}")
    return total


def do_hexiao_and_confirm(cfg, budget):
    btn = cfg.get("hexiao_button")
    if not btn:
        raise SystemExit("错误: 尚未校准核销按钮坐标, 请先运行: python u8_hexiao.py calibrate")
    print(f"点击核销按钮 ({btn[0]},{btn[1]}) ...")
    budget.click(btn[0], btn[1])
    time.sleep(float(cfg["post_hexiao_wait_s"]))
    times = int(cfg.get("confirm_enter_times", 3))
    if cfg.get("confirm_strategy") == "click" and cfg.get("confirm_button"):
        cb = cfg["confirm_button"]
        print(f"点击确认按钮 ({cb[0]},{cb[1]}) ...")
        budget.click(cb[0], cb[1])
        time.sleep(1.0)
        pyautogui.press("enter")  # 兜底
    else:
        for i in range(times):
            print(f"按 Enter 处理确认弹窗 ({i + 1}/{times}) ...")
            pyautogui.press("enter")
            time.sleep(1.0)


# ---------------- 各模式 ----------------

def cmd_calibrate(cfg):
    tpl_w, tpl_h = 76, 30
    print("=" * 52)
    print("交互式校准: 按提示把鼠标移到目标位置, 然后回到本窗口按 Enter")
    print("(若本窗口挡住了目标, 可先拖走本窗口)")
    print("=" * 52)

    input("步骤1/5: 把鼠标移到某个【未勾选复选框】中心, 然后按 Enter ...")
    p = pyautogui.position()
    box_pos = (p.x, p.y)
    print(f"  已采集: ({p.x},{p.y})")
    shot = pyautogui.screenshot()
    x0 = max(0, p.x - tpl_w // 2)
    y0 = max(0, p.y - tpl_h // 2)
    crop = shot.crop((x0, y0, x0 + tpl_w, y0 + tpl_h))
    new_tpl = os.path.join(BASE_DIR, "assets", "checkbox_new.png")
    os.makedirs(os.path.dirname(new_tpl), exist_ok=True)
    crop.save(new_tpl)
    print(f"  已截取新模板: {new_tpl}")
    if input("  是否启用新模板替换默认模板? (y/n, 默认n): ").strip().lower() == "y":
        cfg["template"] = "assets/checkbox_new.png"
        print("  已启用新模板")
    else:
        print("  继续使用原模板: " + cfg["template"])

    input("步骤2/5: 把鼠标移到复选框列区域的【左上角】, 按 Enter ...")
    p1 = pyautogui.position()
    print(f"  已采集: ({p1.x},{p1.y})")
    input("步骤3/5: 把鼠标移到复选框列区域的【右下角】, 按 Enter ...")
    p2 = pyautogui.position()
    print(f"  已采集: ({p2.x},{p2.y})")
    cfg["region"] = [min(p1.x, p2.x), min(p1.y, p2.y), max(p1.x, p2.x), max(p1.y, p2.y)]

    input("步骤4/5: 把鼠标移到【核销按钮】上, 按 Enter ...")
    p3 = pyautogui.position()
    cfg["hexiao_button"] = [p3.x, p3.y]
    print(f"  已采集: ({p3.x},{p3.y})")

    ans = input("步骤5/5: 把鼠标移到确认弹窗【确定按钮】上按 Enter; 直接输入 s 跳过(默认用Enter键策略) ...")
    if ans.strip().lower() == "s":
        cfg["confirm_strategy"] = "enter"
        print("  使用 Enter 键策略")
    else:
        p4 = pyautogui.position()
        cfg["confirm_button"] = [p4.x, p4.y]
        cfg["confirm_strategy"] = "click"
        print(f"  已采集: ({p4.x},{p4.y}), 使用点击策略")

    save_config(cfg)
    print("校准完成! 建议先运行: python u8_hexiao.py dry-run 检查识别效果")


def cmd_dryrun(cfg):
    tpl = load_template(resolve_path(cfg["template"]))
    region = clamp_region(cfg["region"])
    print(f"识别区域: {region}, 模板: {cfg['template']}, 阈值: {cfg['match_threshold']}")
    shot = grab_region(region)
    matches = find_matches(shot, tpl, float(cfg["match_threshold"]))
    preview = shot.copy()
    th, tw = tpl.shape[:2]
    for (mx, my) in matches:
        cv2.rectangle(preview, (mx, my), (mx + tw, my + th), (0, 0, 255), 2)
    out = os.path.join(BASE_DIR, "preview.png")
    imwrite_safe(out, preview)
    print(f"匹配到 {len(matches)} 个未勾选复选框, 预览图: {out}")
    for (mx, my) in matches:
        ax = region[0] + mx + tw // 2
        ay = region[1] + my + th // 2
        print(f"  屏幕绝对坐标: ({ax},{ay})")
    if len(matches) == 0:
        print("(0 个匹配: 请确认U8界面已打开且显示未勾选行; 或运行 calibrate 重新截取模板)")
    print("dry-run 不进行任何点击")


def cmd_select_only(cfg):
    tpl = load_template(resolve_path(cfg["template"]))
    budget = ClickBudget(cfg["max_clicks_total"])
    activate_window(cfg.get("window_title") or "")
    countdown(3)
    t0 = time.time()
    n = select_pass(cfg, tpl, budget, allow_scroll=True)
    print(f"完成: 共勾选 {n} 项, 耗时 {time.time() - t0:.1f} 秒。请人工检查后手动点击核销。")
    print("提示: 若列表仍有剩余行, 核销完后再次运行本命令继续下一批")


def cmd_test_one(cfg):
    tpl = load_template(resolve_path(cfg["template"]))
    budget = ClickBudget(cfg["max_clicks_total"])
    activate_window(cfg.get("window_title") or "")
    countdown(3)
    t0 = time.time()
    n = select_pass(cfg, tpl, budget, allow_scroll=False)
    if n == 0:
        print("当前屏无未勾选项, 结束(未点核销)")
        return
    do_hexiao_and_confirm(cfg, budget)
    print(f"单批测试完成: 勾选 {n} 项, 耗时 {time.time() - t0:.1f} 秒, 请到U8中核对结果")


def cmd_run(cfg):
    tpl = load_template(resolve_path(cfg["template"]))
    budget = ClickBudget(cfg["max_clicks_total"])
    activate_window(cfg.get("window_title") or "")
    countdown(3)
    t0 = time.time()
    n = select_pass(cfg, tpl, budget, allow_scroll=True)
    if n == 0:
        print("未发现任何未勾选项, 结束")
        return
    do_hexiao_and_confirm(cfg, budget)
    print(f"本批完成: 共勾选 {n} 项, 耗时 {time.time() - t0:.1f} 秒")
    print("提示: 若列表仍有剩余行, 等界面刷新稳定后【再次运行本命令】即可继续下一批")


def cmd_selftest(cfg):
    """合成图像自检: 验证匹配函数正确性, 不动鼠标"""
    tpl = load_template(resolve_path(cfg["template"]))
    th, tw = tpl.shape[:2]
    threshold = float(cfg["match_threshold"])
    rng = random.Random(42)
    H, W = 1600, 240
    canvas = np.full((H, W, 3), 205, np.uint8)
    noise = np.array(
        [[rng.randint(199, 211) for _ in range(W)] for _ in range(H)], dtype=np.uint8
    )
    for c in range(3):
        canvas[:, :, c] = noise

    slots = list(range(0, H - th, th))
    rng.shuffle(slots)
    n = rng.randint(8, 15)
    n = min(n, len(slots))
    ys = sorted(slots[:n])
    xs = [rng.randint(0, W - tw) for _ in range(n)]
    for x, y in zip(xs, ys):
        canvas[y:y + th, x:x + tw] = tpl
    inp = os.path.join(BASE_DIR, "selftest_input.png")
    imwrite_safe(inp, canvas)

    matches = find_matches(canvas, tpl, threshold)
    print(f"自检: 粘贴 {n} 个模板, 识别到 {len(matches)} 个 (阈值 {threshold})")

    ok = len(matches) == n
    if ok:
        for x, y in zip(xs, ys):
            if not any(abs(mx - x) <= 2 and abs(my - y) <= 2 for mx, my in matches):
                ok = False
                print(f"  缺失: 期望 ({x},{y}) 附近无匹配")
    print(f"自检输入图: {inp}")
    if ok:
        print("SELFTEST PASS")
    else:
        print("SELFTEST FAIL")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="U8委外核销自动化工具")
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("calibrate", help="交互式校准: 采集模板/区域/按钮坐标")
    sub.add_parser("dry-run", help="只识别不点击, 生成 preview.png")
    sub.add_parser("select-only", help="只滚动勾选全部, 不点核销")
    sub.add_parser("test-one", help="勾选当前屏 + 核销 + 确认 (单批测试)")
    sub.add_parser("run", help="完整自动流程")
    sub.add_parser("selftest", help="自动化自检(不动鼠标)")
    args = parser.parse_args()

    ensure_dpi_aware()
    cfg = load_config()
    try:
        {"calibrate": cmd_calibrate,
         "dry-run": cmd_dryrun,
         "select-only": cmd_select_only,
         "test-one": cmd_test_one,
         "run": cmd_run,
         "selftest": cmd_selftest}[args.mode](cfg)
    except KeyboardInterrupt:
        print("\n已手动停止 (Ctrl+C)")
        sys.exit(130)
    except RuntimeError as e:
        print(f"\n安全停止: {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
