# S2-T017 张琪：MemoryTimeline 聚合接口

## 数据来源

- 完成率与实际费用：统一 `ExecutionEvent`，使用 `occurredAt`。
- 计划费用与版本变化：全部不可变 `PlanVersion` 快照及其时间、状态。
- 关怀：已确认 `AssistanceProfile` 及 `confirmedAt`。
- 照片：`task_media` 中 `deleted_at IS NULL` 的记录。

## 稳定时间线

- 所有条目按 `occurredAt` 升序排列。
- 同一时间使用固定类型优先级和稳定 `itemId` 排序。
- 乱序写入 ExecutionEvent 不影响返回顺序；重复读取返回相同 JSON。
- 每笔费用保留 `eventId`、`planVersionId` 和累计实际费用；当前计划条目
  保留计划费用，因此计划与实际费用均可追溯。

## 空场景与删除过滤

- 0 张照片时仍返回完成率、费用、关怀和版本总结。
- 没有 V2 时仍返回完整 V1 总结，`planChangeCount=0`。
- 已删除或被替换的照片不会出现在 summary、items 或序列化结果中。

## API 与验收证据

- `GET /api/v1/trips/{tripId}/memory-timeline`
- 四场景 Fixture：`backend/tests/fixtures/s2_t017/memory_timeline_scenarios.json`
- 聚合测试：`backend/tests/test_s2_t017_memory_timeline.py`
