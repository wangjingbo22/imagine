# S1-T021 单人基础总结设计

**Owner:** 王敬博
**Traceability:** PBI-06-A / AC-06-A / S1-T021
**Dependencies:** S1-T015、S1-T019

## 聚合来源

总结只使用服务端持久化事实：

- CURRENT PlanVersion 的计划金额和任务数。
- `EXPENSE` 事件的整数分总和。
- `COMPLETE` 和 `SKIP` 事件。
- 全部 PlanVersion 的版本、状态和原因。

## 接口

`GET /api/v1/trips/{tripId}/summary`

返回：

- `plannedCostCents`
- `actualCostCents`
- `differenceCents`
- `completedTaskIds`
- `skippedTaskIds`
- `totalTasks`
- `currentPlanVersion`
- `planHistory`
- `events`

## 页面行为

- Trip 未完成时总结入口禁用。
- Trip 完成后自动加载真实总结。
- 页面显示计划/实际/差额、完成比例、关怀满足和版本历史。
- 导出 HTML 使用服务端总结数字，素材仍为 Sprint 2 前端扩展。

## 测试

`tests/test_workflow_execution.py` 固化 3 完成、1 跳过、实际金额少于计划金额的路径，并验证 Trip 自动进入 `COMPLETED`。
