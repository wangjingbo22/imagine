# 林粲涵 Sprint 2 Day1：S2-T019 / S2-T020 追溯

本追溯以团队 `main@a43ad37a5c8b97d2b90507fa9966998bfee038b9` 为验证基线，林粲涵 Day1/Day2 联动修复的核心实现提交为 `f376574a5c8c5c577d6ed43efd200293023b3b32`，`occurredAt` 必填与幂等合同加固提交为 `0856b745075156e3da5365e74852aaa192329325`。两者保留 Day1 的 T019/T020 边界，并补齐已确认事件到 T021 的 `eventId` 联动。

## PBI / AC / Task

| PBI | AC | Task | Day1 状态 | 主要证据 |
|---|---|---|---|---|
| PBI-11-B | AC-11-B | S2-T019 | IMPLEMENTED | 严格事件草稿、10 秒截止、任意普通异常固定表单降级、草稿零写入；确认后事件独立持久化并支持 UTC 时间幂等和 Trip 内 `eventId` 查询 |
| PBI-11-B | AC-11-B | S2-T020 | IMPLEMENTED / PRODUCT THRESHOLDS PENDING | 确定性 HARD 约束、边界 Fixture、稳定摘要及 Profile/Plan 状态不变断言；疲劳等级和超时处置阈值仍待 PO 确认 |
| PBI-11-B | AC-11-B | S2-T021 / S2-T022 | OUTSIDE DAY1 / NOW INTEGRATED | T021 通过 `adjustmentEventId` 恢复 T019 服务端确认事件，并校验 Trip、CURRENT PlanVersion 与内联确认字段 |

需求原文来自 `doc/行知旅伴_V2.3_Sprint2待办列表_含负责人_新增需求修订版.xlsx` 的 `SprintBacklog模板!A23:V24`、`PBI追溯!A11:J11` 与 `LLM接入设计!A5:K5`。

## 可执行联动

```text
S2-T019 rawText/currentTask
  → 百炼严格 JSON（总计 10 秒截止）或固定表单降级
  → ExecutionEventDraft
  → 用户显式确认
  → ConfirmedExecutionAdjustment
  → POST /api/v1/execution-adjustments/trips/{tripId}/events
  → ConfirmedExecutionAdjustmentEvent(eventId/idempotencyKey/occurredAt/planVersionId)
  → T021 以 adjustmentEventId 在同一 Trip 内恢复事件并校验 CURRENT/内联字段
  → S2-T020 确定性编译
  → EventConstraintSet + 可见原因 + 稳定摘要
  → S2-T021 从可信 CURRENT/FactRef 重编译并规划未完成后缀
  → S2-T022 Diff/接受/拒绝
```

现有 S1 `ExecutionEventType` 仍严格为 START/COMPLETE/SKIP/EXPENSE。只有用户确认后的 LATE/FATIGUE 才进入独立 `execution_adjustment_events` 持久化；草稿解析零写入，同键重放必须同时匹配事件字段与统一 UTC 后的 `occurredAt`。跨 Trip 或不存在的 `eventId` 均按 404 处理。`EventConstraintSet` 不会追加到 S1-T007 `confirmedConstraints`，因此不会改写长期 AssistanceProfile 或既有 PlanVersion。

## 验收结果

- S2-T019/T020 专项：`24 passed`
- 后端全量：`528 passed`
- 前端 Node 测试：`32 passed`
- 前端生产构建与 lint：PASS
- `git diff --check`：PASS

机器可读文件为 `docs/traceability/sprint2/lin_canhan_day1.json`；测试会逐项验证新版需求范围、提交哈希、模块与验收文件、已确认事件幂等、T019→T021 `eventId` 联动以及产品阈值的 `PENDING` 状态。

## 待团队确认

产品阈值状态：`PENDING`。

1. 待 PO 最终确认疲劳三级的总步行、单段步行和休息间隔阈值；当前项目值只能视为待确认默认值。
2. 待 PO 确认迟到超过剩余时间时，是编译为 0 后交 T021 判无解，还是立即返回冲突。
3. 待王敬博确认 T023 的接口调用方式和固定问题文案；本交付提供 HTTP 契约与 Fixture，不实现页面。
4. 在线百炼验收需要一枚已轮换的 Key，仅放部署 Secret；不要发送到聊天或提交仓库。
