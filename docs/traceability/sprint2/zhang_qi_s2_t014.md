# S2-T014 张琪：服务端确定性到达判断

## 范围

- 服务端读取 T013 已保存的一次定位证据并计算到目标任务坐标的距离。
- 只输出判断数据，不保存判断、不实现页面或组件。
- 不接受客户端自报距离，也不把权限拒绝或超时伪装为成功定位。

## 确定规则

- 使用 Haversine 公式计算两点球面距离。
- 仅当 `accuracy <= 100m` 且
  `distance <= max(150m, 2 * accuracy)` 时返回 `ARRIVED`。
- 精度超过 100m 返回 `LOW_ACCURACY`。
- 精度合格但距离超过动态阈值返回 `TOO_FAR`。
- 定位权限拒绝、单次定位超时分别返回 `PERMISSION_DENIED`、`TIMEOUT`。
- 除 `ARRIVED` 外均附稳定原因码，并允许人工确认。

## API

- `POST /api/v1/trips/{tripId}/arrival-decision`
- 成功定位必须引用同一 `tripId/taskId` 下的 `arrivalEvidenceId`。
- 相同请求不读取时钟、不写数据库，始终返回相同结果。

## 验收证据

- 五类 Fixture：`backend/tests/fixtures/s2_t014/arrival_decision_cases.json`
- 阈值与 HTTP 测试：`backend/tests/test_s2_t014_arrival_decision.py`
