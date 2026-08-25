# S1-T015 ExecutionEvent 设计

**Owner:** 王敬博
**Traceability:** PBI-05-A / AC-05-A / S1-T015
**Dependencies:** S1-T013、S1-T014

## 事件契约

事件类型：

- `START`
- `COMPLETE`
- `SKIP`
- `EXPENSE`

所有事件包含：

- `eventId`
- `tripId`
- `taskId`
- `planVersionId`
- `eventType`
- `amountCents`
- `idempotencyKey`
- `occurredAt`

`EXPENSE` 必须提供非负整数分；其他事件禁止提供金额。

## 写入守卫

服务端写入前检查：

1. Trip 存在且为 `EXECUTING`。
2. `planVersionId` 是唯一 `CURRENT`。
3. `taskId` 属于当前 Plan。
4. 同一任务只能出现一个 `COMPLETE` 或 `SKIP` 终态。
5. 同一 `(tripId, idempotencyKey)`：
   - 完全相同请求返回原事件。
   - 不同请求返回 `EVENT_IDEMPOTENCY_CONFLICT`。

## 持久化与恢复

SQLite 表 `execution_events` 使用稳定时间顺序查询。`GET /api/v1/trips/{tripId}` 返回真实事件数组，前端据此恢复：

- 当前任务
- 已完成任务
- 已跳过任务
- 实际消费

所有任务均为 `COMPLETE/SKIP` 后，Trip 自动迁移为 `COMPLETED`。

## 接口

- `POST /api/v1/trips/{tripId}/events`
- `GET /api/v1/trips/{tripId}/events`

## 测试

`tests/test_workflow_execution.py` 覆盖幂等、冲突、SQLite 重开恢复、金额聚合、全部任务结束和 HTTP 刷新恢复。
