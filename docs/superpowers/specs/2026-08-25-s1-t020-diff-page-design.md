# S1-T020 V1/V2 Diff 页面验收设计

**Owner:** 王敬博
**Traceability:** PBI-05-C / AC-05-C / S1-T020
**Dependency:** S1-T019

## 数据来源

页面不自行计算最终 Diff，调用：

- `GET /api/v1/trips/{tripId}/plan-versions/{planId}/diff`
- `POST .../{planId}/accept`
- `POST .../{planId}/reject`

## 展示范围

固定展示：

- 地点 `PLACE`
- 时间 `TIME`
- 路线 `ROUTE`
- 费用 `COST`
- 关怀 `CARE`

变化类型：

- 保留
- 删除
- 新增
- 变更

页面同时展示费用、步行、换乘的指标差值。

## 状态安全

- 候选 V2 未接受时，CURRENT V1 不变。
- 接受后服务端原子切换。
- 拒绝后 V1 和执行状态保持不变。
- 页面刷新时从 `TripPlanState.proposedPlans` 恢复候选和 Diff。

## 自动化证据

- `tests/test_plan_v2_diff.py`：服务端 Diff、接受、拒绝和幂等。
- `tests/test_plan_versions.py`：唯一 CURRENT、状态守卫和刷新恢复。
- 前端 build/lint：类型和组件契约门禁。

浏览器截图/录屏需在有浏览器环境的 Review 机器补录；本次不伪造截图。
