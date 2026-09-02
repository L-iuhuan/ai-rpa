# ai-rpa

AI 协同 RPA 平台：**确定性动作骨架 + AI 可选兜底**（VLM 视觉定位 / LLM 判断），面向财务自动化场景。设计原则：健康路径零模型调用、verify/audit/safety 为架构一等公民、财务数据不出内网。

## 当前状态（2026-09）

**M0：U8 委外核销 v2 实机验证**（设计文档见 `docs/specs/`）

| 里程碑 | 内容 | 状态 |
|---|---|---|
| M0 | v2 实机验证 + 审计落盘 + 结果校验 | 🔵 进行中 |
| M1 | U8 批量导出账表（第二任务，刻意允许重复） | ⚪ |
| M2 | 从两任务重叠提取 `packages/rpa_core` v0 + 浏览器 lane 接入 | ⚪ |
| M3 | AI 兜底接入（失败驱动：VLM 定位降级链末端 + LLM judge 建议人审） | ⚪ |
| M4 | 自然语言规划器 | 待定 |

## 结构

```
apps/u8_hexiao/        第一个任务：U8 委外核销（v1 模板匹配 + v2 规则引擎）
docs/specs/            设计文档（架构裁决、里程碑、风险登记）
packages/rpa_core/     (M2) 内核：零业务零模型，import-linter 强制
lanes/                 (M2) desktop / browser Operator 实现
ai/                    (M3) VLM grounding / LLM judge 插件
```

## 敏感数据红线

- 真实 U8 / 财务系统截图**永不入库**（`.gitignore` 已排除），fixtures 需本地拷贝
- 云端模型只收任务描述与脱敏文本，截图只进内网
- `runs/` 审计目录本地保留，不入库

## 开发约束（详见 docs/specs 设计文档）

- 识别/规则/执行层改动必须保持 23+ 单测全绿
- 实机验证是唯一可信验收：任何任务上线走 fixture 回归 → dry-run → 小批量 → 完整批次四层
- 急停机制（鼠标甩左上角）与点击预算是硬性安全阀，禁止移除
