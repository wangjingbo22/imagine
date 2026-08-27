# S2-T016 张琪：ArrivalEvidence 接入统一 ExecutionEvent

## 事件接入

- T014 判定为 `ARRIVED` 后，服务端生成统一的 `COMPLETE` ExecutionEvent。
- `tripId`、`taskId` 位于事件主体；`arrivalEvidence` 快照保存
  `evidenceId`、服务端计算的 `distanceMeters`、`accuracy`、`result`、
  `source` 和稳定原因码。
- 普通 `/events` 创建契约不接受客户端自报 `arrivalEvidence`；只能通过
  `/arrival-events` 由服务端生成。
- `TOO_FAR`、`LOW_ACCURACY` 等非到达判断不会写入完成事件。

## 幂等与恢复

- 继续使用统一事件表的 `(tripId, idempotencyKey)` 唯一约束。
- 完全相同的重复提交返回原 `eventId`，不会重复完成任务。
- 同一键改用另一份证据返回 `EVENT_IDEMPOTENCY_CONFLICT`。
- `arrivalEvidence` 以 JSON 快照存入 `execution_events`，旧数据库启动时会
  自动添加兼容字段。
- 刷新或服务重启后可通过统一 `/events` 或 `/arrival-events` 恢复，现有
  `/summary` 同样把该任务识别为已完成。

## API 与验收证据

- `POST /api/v1/trips/{tripId}/arrival-events`
- `GET /api/v1/trips/{tripId}/arrival-events`
- Fixture：`backend/tests/fixtures/s2_t016/arrival_execution_event.json`
- 测试：`backend/tests/test_s2_t016_arrival_execution_event.py`
