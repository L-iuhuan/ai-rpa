# Grill: ai-rpa 平台架构决策
Date: 2026-09-01

## Intent
构建"AI 协同 RPA + 确定性执行链路编排"平台。一等目标不是功能多，而是**可复用性：后续其他项目能从此项目吸取经验和可用模块**。场景优先级：U8 ERP 桌面操作（委外核销→批量导出）> 浏览器财务操作。

## Constraints
- solo 开发者，依赖 AI 辅助编码（opencode+OMO）
- Windows 企业内网，DSE 透明加密，财务数据不出内网（截图禁出网）
- 本地 vLLM（内网 Linux 服务器 10.16.2.6）免费模型：Qwen3-VL-32B / GLM-4.7
- v2 项目实机 M6 从未验证——不可当已验证资产
- 用户明确"先不着急实施"

## Key decisions
- 架构=确定性骨架+AI可选插件（用户选"骨架确定+AI兜底"，council 三席一致强化为"AI 严格可选"）
- monorepo + packages/rpa_core（pip -e + import-linter），不做发布型库
- 共享窄协议（Step dataclass + Operator 接口），不做统一 DSL
- 经验资产按应用组织（apps/），通用件沉 shared/，决策记录 decisions.md
- 里程碑 M0 实机验证置顶 → M1 第二任务刻意重复 → M2 才提取内核；VLM/LLM 失败驱动接入（M3）；规划器搁置
- verify/audit/safety 为架构一等公民

## Surfaced assumptions
- 用户最初自称"刚开始探索"，实际已有完整 v1/v2 项目（AI 辅助建造，用户本人对技术细节了解有限）
- U8 的 UIA 已在 v2 开发中被判死（120s 枚举超时），桌面 lane 只能 OCR/模板/视觉
- "可复用"的真实含义：其他项目能整套抄走一个应用的自动化资产

## Open questions
- v2 实机 M0 验证结果未知（可能推翻 runner 设计假设）
- LLM judge 的人审交互形态未定稿
- 第三个真实消费方何时出现（决定是否发布独立库）

## Out of scope
- 自然语言任务规划器（M4 待定，不排期）
- 跨应用多 Agent 编排（UFO 式 HostAgent，未来 revisit）
- 移动端/非 Windows 平台
