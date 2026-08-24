# 行知旅伴前端 API 联调契约

> 状态：Sprint 1 联调基线。响应统一使用 `{ "code": 200, "message": "success", "data": {} }`。金额均为整数分，时间使用 ISO 8601，业务失败必须返回明确错误码，不允许返回成功形状的兜底数据。

## 环境

- 前端变量：`VITE_API_BASE_URL`
- Mock 开关：`VITE_USE_MOCK_API=true`
- API 前缀：`/api/v1`

## 1. 创建行程草稿

- `POST /api/v1/trips/drafts`
- 用途：提交城市、日期、时间、预算、兴趣、关怀模式和自然语言需求。
- 请求：

```json
{
  "cityName": "北京",
  "travelDate": "2026-08-26",
  "startTime": "09:00",
  "endTime": "20:00",
  "budgetCents": 35000,
  "interests": ["历史文化", "特色餐饮"],
  "mustVisit": ["中国国家博物馆"],
  "avoidPlaces": ["排队过久的网红店"],
  "assistanceMode": "low-mobility",
  "assistanceProfile": {
    "maxSegmentWalkMeters": 500,
    "maxTransfers": 2,
    "restIntervalMinutes": 90
  },
  "naturalLanguageRequest": "希望少走路，晚上八点前结束"
}
```

- 返回 `data`：`tripId`、结构化后的 `draft`、需要确认的 `ambiguities[]`。
- 错误：`400` 参数错误；`422` 城市或约束无法解析；`500` 结构化服务失败。

## 2. 确认关怀约束

- `PUT /api/v1/trips/{tripId}/constraints`
- 用途：保存用户确认后的 AssistanceProfile 和约束。
- 状态要求：修改任一字段后回到 `DRAFT`；完整确认后进入 `CONSTRAINT_CONFIRMED`。
- 错误：`404` 行程不存在；`409` 当前状态不可修改；`422` 约束互斥。

## 3. 生成候选计划

- `POST /api/v1/trips/{tripId}/plans`
- 返回 `data`：`PlanSnapshot`，包括版本、任务、费用、步行、换乘、来源状态和校验结果。
- 状态要求：所有硬约束为 `PASS` 才可返回可确认方案。
- 错误：`409` 约束未确认；`422` 无可行方案；`500` Provider 或规划服务失败。

## 4. 确认 Plan V1

- `POST /api/v1/trips/{tripId}/plans/{planId}/confirm`
- 用途：将通过校验的候选方案设为唯一 `CURRENT`。
- 错误：`409` 非法状态转换或已存在冲突版本；`422` 校验未通过。

## 5. 查询行程

- `GET /api/v1/trips/{tripId}`
- 返回当前 Trip、当前 PlanVersion、任务执行状态和已记录事件。
- 用途：页面刷新恢复。

## 6. 创建执行事件

- `POST /api/v1/trips/{tripId}/events`
- 请求：

```json
{
  "taskId": "task-2",
  "eventType": "EXPENSE",
  "amountCents": 18800,
  "idempotencyKey": "trip-demo-task-2-expense-1"
}
```

- `eventType`：`START | COMPLETE | SKIP | EXPENSE`。
- 幂等：同一 `idempotencyKey` 不得重复生成事件或重复扣减金额。
- 错误：`404` 任务不存在；`409` 幂等或状态冲突；`422` 金额或事件不合法。

## 7. 持续反馈并更新当前计划

- `POST /api/v1/trips/{tripId}/plan-feedback`
- 用途：基于消费、疲劳或文字反馈更新尚未执行的任务。
- 状态要求：已完成和已跳过任务不可修改；更新结果重新通过硬约束校验。
- 错误：`409` 当前状态不可调整；`422` 无可行后续方案。

## 8. 上传任务媒体

- `POST /api/v1/trips/{tripId}/tasks/{taskId}/media`
- 请求格式：`multipart/form-data`，支持 `photo` 和 `video`。
- 图片建议不超过 5MB，视频建议不超过 30MB。
- 删除：`DELETE /api/v1/trips/{tripId}/media/{mediaId}`。

## 9. 获取基础总结

- `GET /api/v1/trips/{tripId}/summary`
- 返回：计划费用、实际费用、差额、完成/跳过任务、计划调整记录和任务媒体。

## 前端类型来源

前端 DTO 与 Mock 适配器集中维护在 `frontend/src/domain/trip.ts`、`frontend/src/api/` 和 `frontend/src/mocks/`。页面不得直接拼接 API URL 或自行定义响应结构。
