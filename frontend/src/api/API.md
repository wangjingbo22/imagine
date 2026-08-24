# 行知旅伴前后端 API 对接文档

## 1. 基本约定

- API 前缀：`/api/v1`
- 请求格式：`application/json`
- 金额单位：整数分，例如 `35000` 表示 `350.00 元`
- 日期格式：`YYYY-MM-DD`
- 时间格式：`HH:mm`
- 前端请求入口：`src/api/tripApi.ts`
- 通用请求封装：`src/api/client.ts`

### 环境变量

```env
VITE_API_BASE_URL=http://localhost:8000
VITE_USE_MOCK_API=false
```

开发前端页面但暂不连接后端时：

```env
VITE_USE_MOCK_API=true
```

## 2. 统一响应格式

```json
{
  "code": 200,
  "message": "success",
  "data": {}
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `code` | `number` | 业务状态码，成功固定为 `200` |
| `message` | `string` | 可展示或用于定位问题的结果说明 |
| `data` | `object` | 实际业务数据 |

### 通用错误码

| code | 含义 |
| --- | --- |
| `400` | 请求参数错误 |
| `401` | 未登录或凭证失效 |
| `403` | 无权访问 |
| `404` | 行程、计划或任务不存在 |
| `409` | 状态转换或幂等冲突 |
| `422` | 业务规则或硬约束校验失败 |
| `500` | 服务内部错误 |

失败时不得返回 `code: 200` 或虚假的成功数据。

## 3. 创建行程草稿

```http
POST /api/v1/trips/drafts
```

### 请求体

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

`assistanceMode` 可选值：

- `standard`
- `family`
- `low-mobility`
- `assisted`

### 成功响应

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "tripId": "trip_01",
    "status": "DRAFT",
    "draft": {},
    "ambiguities": []
  }
}
```

## 4. 确认关怀约束

```http
PUT /api/v1/trips/{tripId}/constraints
```

请求体为用户最终确认的 `assistanceProfile` 和约束字段。

成功后行程状态变为：

```text
CONSTRAINT_CONFIRMED
```

修改已确认字段后应重新回到 `DRAFT`，不可直接沿用旧计划。

## 5. 生成候选计划

```http
POST /api/v1/trips/{tripId}/plans
```

### 成功响应 data

```json
{
  "id": "plan_v1",
  "version": 1,
  "cityName": "北京",
  "totalCostCents": 29800,
  "bufferCents": 5200,
  "totalWalkMeters": 2650,
  "transferCount": 2,
  "validationStatus": "PASS",
  "tasks": [
    {
      "id": "task_1",
      "order": 1,
      "title": "中国国家博物馆",
      "category": "历史文化",
      "timeRange": "09:40 — 11:40",
      "durationMinutes": 120,
      "transport": "地铁 8 号线 · 38 分钟",
      "costCents": 600,
      "walkMeters": 420,
      "note": "无障碍入口信息待确认",
      "status": "upcoming",
      "coordinates": [116.397, 39.903]
    }
  ]
}
```

只有 `validationStatus: "PASS"` 的计划才允许用户确认。

## 6. 确认 Plan V1

```http
POST /api/v1/trips/{tripId}/plans/{planId}/confirm
```

成功响应：

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "tripId": "trip_01",
    "planId": "plan_v1",
    "status": "CURRENT"
  }
}
```

同一行程只能存在一个 `CURRENT` 版本。

## 7. 查询行程及刷新恢复

```http
GET /api/v1/trips/{tripId}
```

返回内容至少包括：

- 行程草稿与已确认约束
- 当前 PlanVersion
- 历史 PlanVersion
- 任务执行状态
- ExecutionEvent 列表

前端刷新页面后通过该接口恢复状态。

## 8. 创建执行事件

```http
POST /api/v1/trips/{tripId}/events
```

### 请求体

```json
{
  "taskId": "task_2",
  "eventType": "EXPENSE",
  "amountCents": 18800,
  "idempotencyKey": "trip_01-task_2-expense-1"
}
```

`eventType` 可选值：

- `START`
- `COMPLETE`
- `SKIP`
- `EXPENSE`

相同的 `idempotencyKey` 不得重复创建事件或重复扣减预算。

## 9. 生成 Plan V2

```http
POST /api/v1/trips/{tripId}/replans
```

要求：

- 已完成任务保持不变
- 用户锁定任务保持不变
- 只调整未完成后缀
- 新计划必须重新通过硬约束校验
- 候选 V2 未被接受前不得覆盖当前 V1

无可行方案时返回 `422`，并说明冲突规则及可放宽项。

## 10. 接受或拒绝 Plan V2

```http
POST /api/v1/trips/{tripId}/plans/{planId}/decision
```

### 接受

```json
{
  "decision": "ACCEPT"
}
```

- 原 V1：`CURRENT` → `SUPERSEDED`
- 新 V2：`PROPOSED` → `CURRENT`

### 拒绝

```json
{
  "decision": "REJECT"
}
```

- 新 V2：`PROPOSED` → `REJECTED`
- 当前 V1 和执行状态保持不变

## 11. 获取旅行总结

```http
GET /api/v1/trips/{tripId}/summary
```

### 成功响应 data

```json
{
  "plannedCostCents": 29800,
  "actualCostCents": 34300,
  "completedTasks": 3,
  "totalTasks": 4,
  "currentPlanVersion": 2
}
```

还应返回任务完成/跳过记录及版本变化，且能追溯到对应事件。

## 12. 联调步骤

1. 后端按本文实现接口并启动服务。
2. 复制 `.env.example` 为 `.env.local`。
3. 设置后端地址：

   ```env
   VITE_API_BASE_URL=http://localhost:8000
   VITE_USE_MOCK_API=false
   ```

4. 重启前端开发服务器。
5. 按以下顺序联调：
   - 创建草稿
   - 确认约束
   - 生成并确认 Plan V1
   - 创建执行事件
   - 生成 Plan V2
   - 接受或拒绝 V2
   - 获取总结

## 13. 前端文件对应关系

| 文件 | 用途 |
| --- | --- |
| `src/domain/trip.ts` | 请求与响应 TypeScript 类型 |
| `src/api/client.ts` | Fetch、统一响应和错误处理 |
| `src/api/tripApi.ts` | 具体接口方法及 Mock 切换 |
| `src/mocks/trip.ts` | 前端演示数据 |

新增或修改字段时，必须同步更新本文、TypeScript 类型和后端 Schema。
