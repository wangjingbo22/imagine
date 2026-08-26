# 林粲涵 Sprint 2 Day1：S2-T019 / S2-T020 追溯

本交付最初在团队 `main@3e60435fcfde0705149dbc5f340d60e1aa63103c` 上验证，以林粲涵分支基线 `299341928f7d3c0474328219083e821bcb026498` 开发，核心实现提交为 `f095e6973dced01d0f2498386e7b62779073053a`；现已与 `main@b88aeee441f1160243acf55521d50e4e1c26d7b9` 的 S2-T007 及 `lin_canhan_s2_t008_day1.*` 中的 S2-T008 合并。

## PBI / AC / Task

| PBI | AC | Task | Day1 状态 | 主要证据 |
|---|---|---|---|---|
| PBI-11-B | AC-11-B | S2-T019 | IMPLEMENTED | 严格事件草稿 Schema、口语 Fixture、端到端 10 秒截止时间、固定表单降级、零写入 HTTP 测试 |
| PBI-11-B | AC-11-B | S2-T020 | IMPLEMENTED | 确定性规则表、边界 Fixture、可见原因快照、Profile/Plan 状态不变断言 |
| PBI-11-B | AC-11-B | S2-T021 / S2-T022 | NOT IMPLEMENTED BY DAY1 | 仅冻结下游 `EventConstraintSet` 接口；不伪造 from-events 重规划或 V2 决策完成 |

需求原文来自 Sprint2 待办表的 `SprintBacklog模板!A23:V24`、`PBI追溯!A11:J11`、`LLM JSON契约!A29:H36`。

## 可执行联动

```text
S2-T019 rawText/currentTask
  → 百炼严格 JSON（总计 10 秒截止）或固定表单降级
  → ExecutionEventDraft
  → 用户显式确认
  → ConfirmedExecutionAdjustment
  → S2-T020 确定性编译
  → EventConstraintSet + 可见原因 + 稳定摘要
  → S2-T021（Day2）从可信 CURRENT/FactRef 重编译并规划未完成后缀
  → S2-T022 Diff/接受/拒绝
```

现有 S1 `ExecutionEventType` 仍严格为 START/COMPLETE/SKIP/EXPENSE；本交付没有让未确认的 LATE/FATIGUE 进入持久化。`EventConstraintSet` 也不会追加到 S1-T007 `confirmedConstraints`，因此不会破坏 AssistanceProfile 的 canonical 编译与现有 CandidatePlan 校验。

## 验收结果

- S2-T019/T020 专项：`19 passed in 0.70s`
- 融合 S2-T007 与 S2-T008 后的后端全量：`270 passed in 8.89s`
- 前端 Node 测试：`32 passed`
- 前端生产构建与 lint：PASS
- `git diff --check`：PASS

机器可读文件为 `docs/traceability/sprint2/lin_canhan_day1.json`；测试会逐项验证模块、Fixture、快照、PBI 联动和本交付未越界实现前端/T021。

## 待团队确认

1. 待 PO 最终确认疲劳三级的总步行、单段步行和休息间隔阈值；当前项目默认值记录在规则表中。
2. 待 PO 确认迟到超过剩余时间时，是编译为 0 后交 T021 判无解，还是立即返回冲突。
3. 待王敬博确认 T023 的接口调用方式和固定问题文案；本交付提供 HTTP 契约与 Fixture，不实现页面。
4. Day2 接 S2-T021 前，需要陈梓元交付 S2-T005/S2-T006 的可信 CURRENT、多人执行和 FactRef 最终契约。
5. 在线百炼验收需要一枚已轮换的 Key，仅放部署 Secret；不要发送到聊天或提交仓库。
