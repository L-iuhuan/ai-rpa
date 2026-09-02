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

### M6 实测调优 (待用户实测)
- 已知待验证点: 核销按钮坐标需GUI校准; 下表联动刷新时间(row_settle_ms); MODIFY改数后单元格回车是否生效; 确认弹窗形态
