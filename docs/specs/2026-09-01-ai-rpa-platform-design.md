# AI 协同 RPA 平台（ai-rpa）项目方案 v1.0

- **日期**: 2026-09-01
- **状态**: 设计定稿，待用户确认后实施（当前明确不实施）
- **决策过程**: librarian 双轮调研（AI 桌面 RPA 技术格局 + GitHub 架构经验教训）→ council 三席辩论（DeepSeek v4-pro / 智谱 glm-5.3 / Kimi k3）→ council 汇总裁决 → 本方案
- **前身项目**: `E:\3-其他资料\project\U8委外核销自动化`（v1 模板匹配批量勾选 + v2 RapidOCR 规则引擎，v2 实机 M6 未验证）

---

## 1. 项目定位

**AI 协同 RPA + 确定性执行链路编排**平台：确定性动作骨架保证可靠可审计，AI（VLM 视觉定位 / LLM 判断）作为受控兜底，服务财务自动化场景。

| 维度 | 内容 |
|---|---|
| 场景 | U8 ERP 桌面操作（委外核销✅已有 v1/v2、批量导出账表、导出业务报表）、浏览器财务操作（网银/税务流水下载、批量网页操作） |
| **一等目标** | **可复用性——后续项目能从此项目吸取经验和可用模块**（用户核心诉求） |
| 约束 | solo 开发者+AI 辅助编码；Windows 企业内网（DSE 透明加密）；财务数据不出内网；本地 vLLM（10.16.2.6，Qwen3-VL-32B 视觉 / GLM-4.7 文本）免费可用 |
| 现实前提 | **v2 从未实机验证**（核销按钮校准/下表联动/改数/弹窗四项全未实测），只能当"高置信草稿" |

## 2. 核心设计决策（council 五问裁决）

| # | 问题 | 裁决 | 理由（来源席位） |
|---|---|---|---|
| 1 | 内核形态 | **monorepo 目录 + `packages/rpa_core` 用 `pip install -e` + import-linter 强制"零业务零模型"**；不做发布型 pip 库 | solo 单一消费方，发布开销无收益；import-linter 保留未来抽库选择权（β）；v2 core 已渗业务（vision.py 硬编码 U8 锚点、executor 有 press_hexiao），现在发库=冻结错误 seam（α） |
| 2 | 动作抽象 | **共享窄协议，不做统一 DSL**：`Step{action, target, expectation, on_fail}` dataclass 即 Plan；动作原语收敛为 Operator 式 `screenshot/click/type/wait/verify`，桌面/浏览器各自实现后端 | 桌面是坐标/OCR 世界，浏览器是 DOM 世界，强统一是假抽象（三席一致）；浏览器健康路径走 selector，禁止为统一绕道截图+VLM（β） |
| 3 | AI 层位置 | **严格可选插件**：降级链的编排逻辑在内核，模型调用是 `GroundingProtocol/JudgeProtocol` 的实现；健康路径零模型调用 | vLLM 宕机任务照跑；内核单测无需模型；避免 robocorp "AI 耦合进 main"反例（三席一致）；LLM judge 只做"未知→建议人审"，**不得自动决策**（β，财务红线） |
| 4 | 经验资产组织 | **按应用为主，通用件沉 shared，教训写 decisions.md** | "应用全套可整体抄走"是可复用性的真形态（γ 强论据，2:1 裁决）；复选框模板/节奏参数等跨应用件沉入 shared/（β）；能力维度的知识用文档承接（α 关切） |
| 5 | 框架提取时机 | **M0 实机通过前不抽完整 core；只下沉 v2 已验证部分；两个实机任务后收敛提取 v0** | 零实机抽平台=冻结错误 seam（三席共识）；"部分提取正当"——executor 安全阀/runner 循环已被 v1/v2 两次迭代验证（γ）；核销手写、导出复制、之后才抽（Rule of Three，β） |

## 3. 总体架构

```
ai-rpa/                              # monorepo
├─ packages/
│  └─ rpa_core/                      # 内核：零业务零模型（import-linter 强制）
│     ├─ contracts/                  # Step/Plan dataclass、GroundingProtocol、JudgeProtocol、Operator 接口
│     ├─ runner/                     # 执行循环：observe→act→verify；expectation guard；identical-action cap
│     ├─ safety/                     # 急停角、点击预算、同动作上限、RiskLevel/ApprovalGate
│     ├─ audit/                      # AuditSink：每步截图+决策+结果落盘 runs/；脱敏边界执行
│     └─ verifier/                   # 结果校验接口（重读界面/查文件，与动作交付分离）
├─ lanes/
│  ├─ desktop/                       # 桌面 Operator 实现：pyautogui/SendInput + 窗口管理（继承 v2 executor）
│  └─ browser/                       # 浏览器 Operator 实现：Playwright，selector 优先
├─ ai/                               # AI 插件（可选，内核不依赖）
│  ├─ vlm_grounding/                 # Qwen3-VL @本地 vLLM：截图→bbox JSON（降级链末端）
│  └─ llm_judge/                     # GLM-4.7 @本地：SKIP 场景→建议人审（不自动决策）
├─ apps/                             # ★ 经验资产按应用组织——整套可抄走
│  ├─ u8_hexiao/                     # v1+v2 迁移：规则+模板+fixture+校准+config+tuning.md
│  ├─ u8_export/                     # M1 新任务：批量导出账表
│  └─ netbank_* / tax_* /            # M2+ 浏览器任务
├─ shared/                           # 跨应用通用件：复选框模板、节奏参数、登录 skill
├─ runs/                             # 审计落盘：每次运行每步截图+决策+结果文件
└─ docs/
   ├─ decisions.md                   # ★ 技术决策记录——"吸取经验"的核心载体
   └─ specs/                         # 本方案及后续设计文档
```

## 4. 执行协议

**Plan = 有序 Step 列表（Python dataclass，不做 DSL）**

```python
Step(action=...,        # click / type / scroll / hotkey / export / wait
     target=...,        # lane 插件解析：桌面=锚点文本/模板/VLM描述；浏览器=selector
     expectation=...,   # 动作前 guard + 动作后验证依据
     on_fail=...)       # retry(1) → 降级 → 暂停求助
```

**每步循环**：observe（感知）→ guard（expectation 校验）→ act（执行）→ **verify（业务结果证明）** → 通过则下一步 / 失败则重试 1 次 → 降级 → 求助。全程 AuditSink 落盘。

**定位降级链**（编排在内核，实现可插拔）：结构/selector → OCR 文本锚点 → OpenCV 模板 → **VLM 兜底（最后档，失败驱动接入）**。

## 5. 架构一等公民（council 三席共同要求，原草案缺失项）

1. **verifier**——与动作交付分离：核销后重读表格证明行状态变化、导出后检查文件存在且非空。false finish（以为成功实际弹窗被吞）比 misclick 致命十倍
2. **audit**——AuditSink 每步截图+决策+结果+时间戳落盘；RiskLevel 分级；高风险动作（核销/提交类）ApprovalGate
3. **safety**——继承 v1/v2 已验证机制：急停角、点击预算、批次限流、同动作上限、doom-loop 检测
4. **数据边界**——财务截图永不出内网；云端模型只收任务描述和脱敏文本
5. **确定性 runner**——健康路径零模型调用，AI 永不在主路径必经之处

## 6. 模型路由

| 用途 | 模型 | 位置 | 触发方式 |
|---|---|---|---|
| 视觉定位兜底 | Qwen3-VL-32B（131k ctx） | 本地 vLLM 10.16.2.6:4435 | 仅当锚点/模板全失败（M3 接入） |
| 判断辅助 | GLM-4.7-PF8（202k ctx） | 本地 vLLM 10.16.2.6:4434 | 仅 SKIP 场景，输出"建议+理由"供人审（M3） |
| 任务规划（远期） | Kimi / DeepSeek | 云端 | 只收任务描述，M4 待定 |

## 7. 里程碑（council 修订版，取消伪并行）

| # | 内容 | 要点 | 依赖 |
|---|---|---|---|
| **M0** | **v2 实机验证**（不可谈判的门槛） | 四项验证清单：①核销按钮校准 ②下表联动刷新 ③MODIFY 改数生效 ④确认弹窗处理；**强制补两项（直接在 v2 代码内实现，不依赖内核提取）**：核销结果自动校验（重读表格）+ AuditSink 落盘。过关标准：连续 2 批核销零人工干预且有审计留痕。**等待期允许 ≤2 天独立 Playwright 冒烟脚本**（网银或税务登录+下载），但只作为独立脚本，不建 lane 不进框架 | 无 |
| **M1** | U8 批量导出账表（第二任务） | **复制 v2 代码修改，刻意允许重复**，不预先抽象；跑通实机并积累第二组真实数据点 | M0 过关（或降级结论） |
| **M2** | 提取 rpa_core v0 | 从 M0+M1 两任务的重叠代码收敛提取（此刻"哪些真通用"自然显形）；同时浏览器 lane 接入 runner，验证内核 lane 无关性 | M1 |
| **M3** | AI 兜底接入（失败驱动） | VLM 定位作降级链末端 + LLM judge 处理 SKIP（建议人审制）；由 M0-M2 积累的真实失败样本驱动 | M2 + 有真实失败样本 |
| **M4** | 自然语言规划器（**待定，不排期**） | 需求形态未知；Plan dataclass 在 M2 定义好即保留接口 | M3 后重新评估 |

**M0 失败分支**：识别问题→修 vision；执行问题→修 executor；修不动→降级用 v1 内核（v1 有实机 dry-run 10/10 记录），平台化照常，v2 规则引擎降为参考实现。

## 8. 风险登记（Top3，按优先级）

1. **在未验证地基上抽平台**（solo 多线并行 + 零实机任务提取 = 冻结错误 seam 全线返工）→ 对策：M0 置顶不可谈判、M1 刻意重复、M2 才收敛
2. **false finish 不被捕获**（静默错核比报错致命十倍）→ 对策：verifier 一等公民，每任务必须能用重读界面/查文件证明业务结果
3. **AI 干预确定性链路**（LLM 自动决策误导核销金额）→ 对策：judge 只建议不决策、人审兜底、数据不出域

## 9. 复用性设计专节（回答用户核心诉求）

其他项目从 ai-rpa 获取价值的三条路径，按成本从低到高：
1. **抄经验**：`docs/decisions.md`（技术决策记录：UIA 为何对 U8 判死、OCR 选型、节奏参数调优过程）+ 本方案文档
2. **抄应用全套**：`apps/<某应用>/` 目录整体复制——模板、fixture、规则、校准、config 自包含，新项目改改就能跑
3. **复用内核**：`packages/rpa_core` 经 `pip install -e` 引用——但按 Rule of Three，**出现第三个真实消费方时才发布为独立库**

## 附录 A：调研项目清单（librarian）

robocorp/rpaframework（多包分层，core 无业务知识）· microsoft/UFO²（HostAgent+AppAgent 分治）· OpenAdapt（Workflow IR + 能力阶梯 + 健康路径零模型）· browser-use（DOM 优先，loop detector）· UI-TARS-desktop（Operator 接口解耦模型与后端）· OS-Copilot/Agent-E（感知/动作 skill 原子）· FinRPA/WebRPA/EasyTHS（金融场景审批/审计/脱敏一等公民）· 生产博客（misclick/stale-world/doom-loop/false-finish 四大失效 + Rule of Three）

## 附录 B：council 辩论纪要

- **共识**（三席一致）：monorepo 非 pip 库；共享窄协议不做统一 DSL；AI 严格可选插件；反对零实机抽平台；verify/audit 一等公民；VLM 移出 M1；规划器不排期
- **分歧裁决**：经验资产按应用（β/γ）vs 按能力（α）→ **按应用为主+shared+decisions.md**（2:1）；浏览器并行（γ 激进）vs 全串行（α）→ **β 折中：M0 等待期 ≤2 天独立脚本**
- **独有洞察**：α——verify/audit 与"提取什么"绑定；β——import-linter + dataclass 即 Plan；γ——verifier 与动作交付分离、false finish 致命性
