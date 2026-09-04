# U8委外核销自动化 — 开发记录

## 2026-08-26 (v1)

- 从 Quicker 状态文件提取复选框模板(76x30)与区域 [0,50,108,1395]
- 开发 u8_hexiao.py：区域模板匹配批量勾选+核销+确认，含 calibrate/dry-run/select-only/test-one/run/selftest 模式
- 验证：py_compile 通过；selftest 合成图 15/15 命中；dry-run 在用户实屏识别到 10 个未勾选框
- 修复：OpenCV 中文路径 imdecode；DPI 感知
- v1.1: 增加 max_screens=3 批次限制(用户反馈一次勾太多卡顿)

## 2026-08-27 (v2)

### M1 方案+规则文档 ✅
- observer 分析用户截图：窗口"委外核销处理"，上表=委外入库单(24列)，下表=委外材料出库单(21列)，第一列均为"选择"复选框，点上表行下表联动
- librarian 调研 U8 委外核销规则：入库单↔材料出库单配对，BOM+损耗率带出本次核销数量，允许改数部分核销；系统"自动"按钮在跨订单发料/尾差场景不可靠
- 与用户确认判定规则(见 docs/方案规则文档.md 第3节)：
  - 采购类型分两类：A类按件数核对、B类按数量核对；未知类型跳过
  - A类：件数上==件数下 且 Q核==Q未→PASS；件数上==件数下 且 Q核<Q未→MODIFY(Q未)；件数上<件数下→PASS；其余 SKIP；下表多行→SKIP
  - B类：入库数量≤未核销数量→PASS；否则 SKIP；下表多行→SKIP
  - 节奏：A类逐行循环；B类可批量(v1方式，调节奏+翻页循环)
  - 用户明确要求：元素识别而非死坐标(列宽拖动不能失效) → OCR 列头锚定方案
- 产出：docs/方案规则文档.md

### M2 规则引擎+测试基准 ✅
- core/rules.py 纯函数规则引擎；tests/test_rules.py 覆盖每条规则分支+截图实测数据
- 验证：python -m unittest 全绿(23/23, 修复了多行提示语缺失"多行"字样的断言失败)

### M3 OCR 可行性验证 ✅ (技术选型转折点)
- Windows OCR(winsdk) 整图: 锚点0/4, 数字乱码("2026"→"2例斟2") → **否决**
- 修复 await 链 bug 后单格实验仍证明 Windows OCR 中文/数字质量不足
- UIA 元素树: U8 老控件响应极慢(枚举超时120s) → **否决**
- 像素诊断: U8 表格无网格线(纯白底文字), "竖线切列"不可行 → 改文本块坐标方案
- **RapidOCR(onnx) 整图: 锚点5/6, 数字4/4(含千分位1,562,477/小数25.000000), 表头带单格识别锚点全中 → 采纳**
- 产出: tests/rapidocr_experiment.py(EXPERIMENT PASS), diag_pixels.py, debug_bands.py, col_seg_experiment.py

### M4 视觉+执行骨架 ✅
- core/vision.py: grab_window截图 → RapidOCR整图 → 锚点定位上下表头 → y聚类行/x归属列 → RowData结构化; 复选框沿用v1模板匹配挂接到行
- core/executor.py: 点击/修正单元格(双击+全选+输入+回车)/核销/确认弹窗; FAILSAFE+点击预算+SafetyStop
- core/runner.py: 逐行循环(选中上表行→下表联动→规则判定→执行); plan()只读计划; 滚动翻页到底检测
- main.py: selftest/plan/run CLI
- 验证: `python main.py selftest` → 规则23/23 + 视觉fixture回归 PASS(上表16行, 采购类型15, 入库数量16, 下表2行, 表头y=53/560)

### M5 GUI ✅
- fixer(ses_fbf17cd8effeJeD0Cg7mrzOoYi) 开发 gui.py(557行, tkinter+ttk): 连接测试/类型映射编辑/参数区/校准核销按钮(3秒采样)/计划·执行·停止(后台线程+队列日志)/统计显示
- 验证: py_compile 通过, `python gui.py --smoke` → SMOKE OK, RapidOCR lazy加载确认

## 2026-09-01 (M0 前置增强)

- 完成 AuditSink (`core/audit.py`) 与核销结果校验器 (`core/verifier.py`) 挂接 `core/runner.py`；审计失败/校验异常均不阻断主流程，仅落盘警告.
- 新增 `tests/test_verifier.py`，覆盖 `verify_row_hexiao` 全部 6 大分支：VERIFIED(行消失/未核销数量变化/checkbox 变化)、VERIFY_FAIL(数值不变)、VERIFY_UNKNOWN(st_after.ok=False/行匹配歧义/数值缺失且无 checkbox 变化).
- 修复 `tests/test_audit.py::test_io_failure_swallowed`: `AuditSink.start()` 仅在目录创建/初始化全部成功后才置 `_started=True`，并在 Windows 下显式检测只读目录属性，避免 IO 异常后进入半启动状态.
- `main.py selftest` 扩展为「规则+审计+校验单测 + 视觉 fixture + audit 冒烟 + verifier 冒烟」六段式自检，均离线运行、不依赖实机/截图.
- 项目整体从 `E:\3-其他资料\project\U8委外核销自动化` 迁移至 monorepo 新路径 `apps/u8_hexiao/v2`，代码零改动，仅目录移动.

## 2026-09-02 (M0 实机验证: 感知层三连修)

- 实机 plan 多轮取证, 定位并修复感知层三个缺陷(全部有实锤证据):
  1. **窗口选择错误**: 标题子串匹配+取首个, 在「U8窗口/标题含同名的Excel文件/路径含U8委外核销的终端」间随机选错 → 新增 `_select_window` 精确匹配优先+子串兜底
  2. **窗口遮挡**: pyautogui 截的是屏幕区域, U8 被其他最大化窗口覆盖时截到遮挡者内容 → `grab_window` 捕获前 `w.activate()` 拉前台(plan/run 自愈, run 模式坐标点击本就要求前台)
  3. **表头聚类脆弱**: 宽表头行各列文本块 y 中心常有高低差, 严格行聚类拆簇后单簇锚点<2 → `_header_y` 改 ±HEADER_BAND_TOL(14px) y带聚合
- 类型识别双层方案实机验证通过: 28行 exact=17 / fuzzy=11 / none=0; vlm=0(兜底未出动, fuzzy 已全覆盖)
- 连续两次 plan 结果完全一致(间歇性故障根除)
- 新增测试: test_vision_grab.py(5) + test_vision_header.py(5); 全量 58 单测绿 + selftest 全段 PASS

## 2026-09-02 (类型识别双层加固)

- 实机 plan 验证发现「采购类型」OCR 误识率高(封测编→封规编/封测痛、FT测编委外加工→FI测编委外加工), 引入双层解析兜底:
  - `core/typematch.py`: 白名单精确匹配 + 标准 Levenshtein 编辑距离模糊匹配(中文字符每字计 1, max_distance=2), 纯函数, 确定性层.
  - `core/vlmtype.py`: `VLMTypeClassifier` 调用本地 vLLM 端点(Qwen3-VL-32B-Instruct@10.16.2.6:4435); HTTP 使用标准库 `urllib.request`, 图像编码使用已有 opencv+base64; VLM 失败永不抛出、永不阻断.
  - `core/runner.py`: `__init__` 构建 known_types/classifier; 新增 `_resolve_type` 三层命中(exact→fuzzy→vlm), 在 `_process_row`/`plan` 的 `judge` 前插入类型解析; 解析结果写入 `audit.step("type_resolve")`.
- `config_v2.json`: type_map 权威化为六项(CP委外/CU Pillar工艺委外/Cu Thick工艺委外= A; 封测编/FT测编委外加工/FT封装委外加工= B), 并修正「封测编」从旧 A 改为 B; 新增 `type_match.fuzzy_max_distance=2` 与 `vlm` 配置节.
- 测试: 新增 `tests/test_typematch.py`(6 真实类型精确命中/大小写空格容错/实机误读样本/乱串并列) + `tests/test_vlmtype.py`(正常/噪声/UNKNOWN/异常四类 monkeypatch).
- 验证: `python -m unittest discover -s tests -v` → 既有 37 + 新增全绿; `python main.py selftest` → 全部 PASS.

## 2026-09-04 (M0 终局结论: 视觉方案不达标, 停止并转向)

- 实机两轮试跑(--rows 2 / --rows 10)基础设施全部稳住: 完整循环(点击→联动→读表→判定)10行零错误; 类型三层解析、表头三级容错、窗口管理、审计落盘全部按设计工作
- **但 M0 按自身过关标准判定: 不通过**:
  1. **可靠性致命伤**: 报告"下表联动多行(2行)"而用户确认实际无多行——视觉误读导致**错误业务判定**(该核的没核), 财务场景零容忍
  2. **速度不达标**: 整窗 OCR 每次10-15秒, 每行全流程约30秒, 200行批次约100分钟
  3. 本会话累计五代补丁(窗口选择/遮挡激活/表头带聚合/形近字模糊/截断前缀)——工程上每步都修对了, 但**方向天花板已到**: OCR 随机性使识别不可复现=不可信任
- **用户决策: 停止视觉路线在 U8 桌面 lane 的继续投入, 重新调研替代路线**
- 已派调研(librarian): ①用友U8官方接口(U8API/EAI/OpenAPI 委外核销覆盖面) ②UIA正确姿势重测(定向查询+CacheRequest, 当年全树枚举120s超时的否决可能是方法问题) ③商业RPA(UiPath/影刀)对PB老应用的实际做法
- 沉淀资产(不被推翻): 安全机制(急停/预算/审计)、规则引擎、verifier、类型封闭集匹配思想、窗口管理——新路线可直接复用; 浏览器 lane(Playwright)不受影响

