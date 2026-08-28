# S2-T028 Provider/推荐/规划零调用门禁

**Owner:** 张琪
**Traceability:** PBI-15-A / AC-15-A / S2-T028

## 实现边界

- 所有携带 `tripId` 的 Provider 地点、地理编码和路线接口在调用高德前进入统一 `CollaborationReadinessGuard`。
- FactRef 摘要恢复同样属于 Provider/cache 事实边界，必须在读取注册表前通过门禁。
- 推荐编排在恢复 FactRef、调用千问、构建路线和公平排序前通过门禁。
- V1/V2 生成、候选确认与版本决策在读取规划事实或写入 PlanVersion 前通过门禁。
- 不携带 `tripId` 的城市名称解析仍作为建行程前的非协作作用域能力，不纳入 T028。

## 计数验收

`backend/tests/test_s2_t028_zero_call_gate.py` 对以下四种非就绪状态逐一执行相同矩阵：

- `DRAFT_CONVERSATION`
- `INVITING`
- `COLLECTING_MEMBERS`
- `CONFLICT_REVIEW`

每种状态验证四个 HTTP 边界：地点提示、FactRef 摘要恢复、唯一推荐、Plan V1 生成。断言响应均为 `409 / COLLABORATION_NOT_READY`，并断言以下调用计数全部为 0：

- 高德 Provider；
- Provider FactRef 注册表恢复；
- 千问候选提议；
- 真实路线构建；
- 确定性候选排序；
- PlanVersion、Workflow 和可信规划存储。

## 验证结果

- T028 定向测试：`4 passed`。
- T003/T006/T009/T028 相关回归：`62 passed`。
- 后端完整回归：`630 passed`。

本地 `.env` 的百炼超时仍为旧值 45 秒；测试仅通过进程环境临时覆盖为 10 秒，没有修改密钥或 `.env`。
