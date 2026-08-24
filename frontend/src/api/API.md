# 行知旅伴前端接口契约

## 1. 权威来源

当前已经确认并实现的契约包括 **S1-T001 Trip Schema**、
**S1-T003 AssistanceProfile**、PBI-02-A 城市查询，以及
**PBI-04-B Plan V1 确认与状态守卫**、**PBI-05-C V1/V2 Diff 与接受拒绝**：

- Python 模型：`backend/app/schemas/trip.py`
- JSON Schema：`backend/schemas/trip.schema.json`
- 字段级错误：`backend/app/schemas/validation_error.py`
- 设计说明：`docs/superpowers/specs/2026-08-24-s1-t001-trip-schema-design.md`

本文件、前端 TypeScript 类型和 Mock 必须服从上述文件。未在 `.agent/api_contracts.md` 登记的 HTTP URL 不视为正式接口。

## 2. 当前范围

S1-T001 与 S1-T003 当前确认：

- 单人模式
- 单日行程
- `DRAFT` 状态
- 完整且已经规范化的 Trip JSON
- 严格 Schema 校验和字段级错误
- 四类可序列化的关怀 Profile

Trip Schema 本身**不包含**：

- 自然语言解析接口
- 城市搜索或 CityContext 解析结果
- PlanVersion、计划生成或执行状态
- 途中反馈接口
- 照片或视频接口
- 旅行总结接口

其中已经在第 8、9 节登记的城市解析、PlanVersion 状态和 Diff 决策接口可正式调用；其余能力继续使用前端 Mock，未登记 URL 和 DTO 前不得当作正式接口调用。

## 3. CreateSingleDayTrip

前端类型：`src/domain/trip.ts` 中的 `CreateSingleDayTrip`。

```json
{
  "schemaVersion": "1.0",
  "tripId": "00000000-0000-4000-8000-000000000001",
  "mode": "SINGLE",
  "status": "DRAFT",
  "cityContext": {
    "countryCode": "CN",
    "cityCode": "110000",
    "cityName": "北京市",
    "center": {
      "longitude": 116.407387,
      "latitude": 39.904179
    },
    "providerConfig": {
      "provider": "AMAP",
      "coordinateSystem": "GCJ02"
    }
  },
  "startDate": "2026-09-05",
  "endDate": "2026-09-05",
  "currency": "CNY",
  "totalBudgetCents": 35000,
  "participants": [
    {
      "participantId": "10000000-0000-4000-8000-000000000001",
      "nickname": "单人旅客",
      "budgetCapCents": 35000,
      "preferences": [
        {
          "type": "INTEREST",
          "value": "历史",
          "weight": 4,
          "isHard": false
        },
        {
          "type": "MUST_VISIT",
          "value": "中国国家博物馆",
          "weight": 5,
          "isHard": true
        }
      ],
      "assistanceProfile": {
        "type": "LOW_STAMINA",
        "childAge": null,
        "walkLimits": {
          "maxContinuousMeters": 500,
          "maxDailyMeters": null
        },
        "maxTransfers": 2,
        "restInterval": 90,
        "napWindow": null,
        "avoidStairs": false
      }
    }
  ],
  "days": [
    {
      "dayIndex": 0,
      "date": "2026-09-05",
      "dailyBudgetCents": 32000,
      "startLocationText": "北京林业大学",
      "endLocationText": "北京林业大学",
      "timeWindow": {
        "start": "09:00:00",
        "end": "20:00:00"
      }
    }
  ]
}
```

## 4. 字段规则

### 顶层

| 字段 | 规则 |
| --- | --- |
| `schemaVersion` | 固定为 `"1.0"` |
| `tripId` | UUID4 |
| `mode` | 当前固定为 `"SINGLE"` |
| `status` | 创建入口固定为 `"DRAFT"` |
| `currency` | 固定为 `"CNY"` |
| `totalBudgetCents` | 非负整数，单位为分 |
| `participants` | 当前必须且只能有 1 项 |
| `days` | 当前必须且只能有 1 项 |

### CityContext

- `countryCode` 固定为 `CN`
- `cityCode` 是 Provider 分配的不透明字符串，不由前端猜测
- `provider` 固定为 `AMAP`
- `coordinateSystem` 固定为 `GCJ02`
- 地图密钥不得进入 Trip

### Preference

| type | weight | isHard |
| --- | --- | --- |
| `INTEREST` | `1..5` | `false` |
| `MUST_VISIT` | `1..5` | `true` |
| `AVOID_PLACE` | `1..5` | `true` |

同一个地点不能同时为 `MUST_VISIT` 和 `AVOID_PLACE`。

### 日期和时间

- `startDate == endDate == days[0].date`
- `dayIndex` 固定为 `0`
- 时间必须使用 `HH:mm:ss`
- 不接受毫秒、时区后缀和跨午夜时间窗
- `timeWindow.end` 必须晚于 `timeWindow.start`

### AssistanceProfile

S1-T003 已支持四类正式值：

| UI 模式 | `type` | 关键预设 |
| --- | --- | --- |
| `standard` | `ORDINARY` | 不附加人群约束 |
| `family` | `PARENT_CHILD` | 午休 `13:00:00`–`14:00:00` |
| `low-mobility` | `LOW_STAMINA` | 使用页面填写的步行、换乘和休息上限 |
| `assisted` | `MOBILITY_ASSISTANCE_BETA` | `avoidStairs: true` |

`childAge`、`walkLimits.maxDailyMeters` 等暂未采集的字段必须显式传
`null`，不能省略；`assistanceProfile: null` 仍用于兼容旧的 T001 payload。

## 5. UI 草稿与正式 Trip 的区别

`TripDraftInput` 是前端页面输入模型，不是后端正式 Schema。

转换流程：

```text
用户表单
  -> TripDraftInput
  -> 自然语言/城市解析（后端尚未登记）
  -> 获得 CityContext、UUID、起终点
  -> buildCreateSingleDayTrip()
  -> CreateSingleDayTrip
  -> 后端 Schema 校验
```

转换工具位于：

```text
src/api/tripContract.ts
```

它负责：

- 将 `HH:mm` 转换为 `HH:mm:ss`
- 将兴趣转换为 `INTEREST`
- 将必去地点转换为 `MUST_VISIT`
- 将避开地点转换为 `AVOID_PLACE`
- 填充固定枚举、单日结构和预算
- 将四种 UI 关怀模式转换为完整的 S1-T003 `AssistanceProfile`

## 6. Schema 错误

正式错误不是通用的 `{ code: 422, message, data }` 包装，而是：

```json
{
  "code": "TRIP_SCHEMA_INVALID",
  "schemaVersion": "1.0",
  "errors": [
    {
      "path": "days[0].timeWindow.end",
      "code": "missing",
      "message": "Field required"
    }
  ]
}
```

需要用户确认歧义时：

```json
{
  "code": "TRIP_CONFIRMATION_REQUIRED",
  "schemaVersion": "1.0",
  "errors": [
    {
      "path": "days[0].date",
      "code": "ambiguous_value",
      "message": "“下周六”需确认具体日期",
      "context": {
        "referenceDate": "2026-08-24"
      },
      "candidates": ["2026-08-29", "2026-09-05"]
    }
  ]
}
```

`src/api/client.ts` 已支持解析这两类错误，并通过 `ApiError.issues` 暴露字段级问题。

## 7. HTTP 路由状态

后端当前尚未在本分支实现或登记 Trip 创建 HTTP URL。

因此：

- `tripApi.createDraft()` 仅允许 Mock 模式
- 关闭 Mock 后调用会抛出 `TRIP_DRAFT_ENDPOINT_UNREGISTERED`
- `tripApi.submitNormalizedTrip(path, payload)` 只用于后端负责人确认 URL 后接入
- 不应再默认使用 `/api/v1/trips/drafts`

## 8. 城市 Provider 与 Plan V1 正式接口

设置 `VITE_USE_PLAN_VERSION_API=true` 后，下列调用使用本地 FastAPI，而其他未登记能力仍可保持 Mock：

- `tripApi.resolveCity()` → `POST /api/v1/cities/resolve`
- `tripApi.suggestPlaces()` → `POST /api/v1/places/suggestions`
- `tripApi.searchPlaces()` → `POST /api/v1/places/search`
- `tripApi.searchNearbyPlaces()` → `POST /api/v1/places/nearby`
- `tripApi.getPlaceDetail()` → `POST /api/v1/places/detail`
- `tripApi.forwardGeocode()` → `POST /api/v1/geocoding/forward`
- `tripApi.reverseGeocode()` → `POST /api/v1/geocoding/reverse`
- `tripApi.planRoute()` → `POST /api/v1/routes/plan`
- `tripApi.registerPlanVersion()` → `POST /api/v1/trips/{tripId}/plan-versions`
- `tripApi.confirmPlan()` → `POST /api/v1/trips/{tripId}/plan-versions/{planId}/confirm`
- `tripApi.startExecution()` → `POST /api/v1/trips/{tripId}/execution/start`
- `tripApi.getTrip()` → `GET /api/v1/trips/{tripId}`

计划工作台会实际调用城市解析、同城地点搜索和路线规划，并展示 `cityCode`、来源状态、`fetchedAt` 和未知价格。Provider 返回 `amountCents: null + UNKNOWN` 时，页面固定显示“未知待确认”，不会按 0 元写入预算；当前计划金额仍属于前端估算并显式标注。前端地址栏保留 `tripId`。刷新时恢复 `CURRENT` 或 `PROPOSED`；确认按钮严格按“登记候选 → 确认 CURRENT → 开始执行”的顺序调用。PlanVersion DTO 定义在 `src/domain/trip.ts`，字段名保持 camelCase，不翻译代码契约。

## 9. Plan V2 Diff 与决策正式接口

设置 `VITE_USE_PLAN_VERSION_API=true` 后：

- `tripApi.registerPlanVersion()` 可登记 `version: 2` 的不可变候选，`parentId` 指向当前 V1，原因使用已确认枚举。
- `tripApi.getPlanDiff()` → `GET /api/v1/trips/{tripId}/plan-versions/{planId}/diff`
- `tripApi.acceptPlanV2()` → `POST /api/v1/trips/{tripId}/plan-versions/{planId}/accept`
- `tripApi.rejectPlanV2()` → `POST /api/v1/trips/{tripId}/plan-versions/{planId}/reject`

前端展示 `PLACE | TIME | ROUTE | COST | CARE` 五类及 `RETAINED | REMOVED | ADDED | CHANGED` 四种变化。接受前不得用候选数据替换当前计划；决策完成后重新调用 `getTrip()`，以服务端唯一 `CURRENT` 为准。

## 10. 待后端确认的接口

以下是前端功能需求，不是已确认契约：

- 自然语言解析与歧义确认
- Trip 创建/保存
- AssistanceProfile 确认
- 计划自动生成与持续反馈
- 执行事件
- 照片与视频上传
- 旅行总结

每个接口必须由负责人补充 URL、请求 DTO、响应 DTO、状态转换和错误码后，才能从 Mock 切换为真实请求。
