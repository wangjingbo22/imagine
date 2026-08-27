# S2-T013 张琪：一次定位与到达证据服务端契约

## 范围

- 仅实现服务端 DTO/Schema、API、SQLite 持久化和幂等规则。
- 不实现浏览器页面，不调用 `watchPosition`，不保存持续定位会话或轨迹。

## 契约

- `LocationEvidence`：`longitude`、`latitude`、`accuracy`、带时区的
  `capturedAt`、`source`。
- `CreateArrivalEvidence`：`taskId`、`locationEvidence`、`idempotencyKey`。
- `ArrivalEvidence`：服务端补充 `evidenceId`、路径中的 `tripId` 和
  `recordedAt`。
- 坐标范围为经度 `[-180, 180]`、纬度 `[-90, 90]`；`accuracy` 必须为
  有限正数。

## 幂等规则

- 唯一范围：`(tripId, idempotencyKey)`。
- 相同键和完全相同的请求返回原 `ArrivalEvidence`，包括相同的
  `evidenceId` 与 `recordedAt`。
- 相同键用于不同任务、坐标、精度、采集时间或来源时返回
  `ARRIVAL_EVIDENCE_IDEMPOTENCY_CONFLICT`，不写入第二条记录。

## API

- `POST /api/v1/trips/{tripId}/arrival-evidence`
- `GET /api/v1/trips/{tripId}/arrival-evidence/{evidenceId}`
- `GET /api/v1/trips/{tripId}/arrival-evidence?taskId=...`

## 验收证据

- Fixture：`backend/tests/fixtures/s2_t013/arrival_evidence_idempotency.json`
- 测试：`backend/tests/test_s2_t013_arrival_evidence.py`
