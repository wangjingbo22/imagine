# 行知旅伴前端接口契约

## 1. 权威来源

当前已经确认并实现的契约包括 **S1-T001 Trip Schema**、
**S1-T003 AssistanceProfile**、PBI-02-A 城市查询，以及
**PBI-04-B Plan V1 确认与状态守卫**、**PBI-05-C V1/V2 Diff 与接受拒绝**：

- Python 模型：`backend/app/schemas/trip.py`
- JSON Schema：`backend/schemas/trip.schema.json`
- 字段级错误：`backend/app/schemas/validation_error.py`
- 设计说明：`docs/superpowers/specs/2026-08-24-s1-t001-trip-schema-design.md`

本文件、前端 TypeScript 类型和实际请求必须服从上述文件。未在 `.agent/api_contracts.md` 登记的 HTTP URL 不视为正式接口。

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

已经登记的自然语言草稿、约束确认、城市 Provider、PlanVersion、Diff、执行事件和总结接口均调用本地 FastAPI。未登记 URL 和 DTO 前不得新增虚构接口或固定数据回退。

自然语言草稿响应额外返回以下运行证据：

- `recognitionSource`: `BAILIAN`、`DETERMINISTIC_RULES` 或 `DEGRADED_RULES`
- `recognitionModel`: 在线模型名称；非模型路径为 `null`
- `degradedReason`: 百炼失败后的非敏感错误码；未降级时为 `null`

页面只能在 `recognitionSource=BAILIAN` 时显示“百炼识别完成”。模型输出仍是候选字段，不能绕过后续确认和服务端规划校验。

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
  -> POST /api/v1/trips/drafts/parse
  -> 歧义确认清单
  -> POST /api/v1/trips/drafts/confirm
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

## 7. 自然语言草稿接口

已登记：

- `tripApi.createDraft()` → `POST /api/v1/trips/drafts/parse`
- `tripApi.confirmDraft()` → `POST /api/v1/trips/drafts/confirm`

请求携带稳定 `tripId`，解析、约束确认和后续 PlanVersion 使用同一 Trip。
确认清单未清空时 `canPlan=false`，页面不得进入规划。

## 8. 城市 Provider 与 Plan V1 正式接口

设置 `VITE_USE_PLAN_VERSION_API=true` 后，下列调用使用本地 FastAPI；地点和路线结果不得回退为前端固定数据：

- `tripApi.resolveCity()` → `POST /api/v1/cities/resolve`
- `tripApi.suggestPlaces()` → `POST /api/v1/places/suggestions`
- `tripApi.searchPlaces()` → `POST /api/v1/places/search`
- `tripApi.searchNearbyPlaces()` → `POST /api/v1/places/nearby`
- `tripApi.getPlaceDetail()` → `POST /api/v1/places/detail`
- `tripApi.forwardGeocode()` → `POST /api/v1/geocoding/forward`
- `tripApi.reverseGeocode()` → `POST /api/v1/geocoding/reverse`
- `tripApi.planRoute()` → `POST /api/v1/routes/plan`
- `tripApi.generatePlanVersion()` → `POST /api/v1/trips/{tripId}/plan-versions/generate`；提交 `CandidatePlanRequest`，由服务端 T011 重算并签发 V1
- `tripApi.getPlanningFacts()` → `GET /api/v1/trips/{tripId}/planning-facts`；只恢复服务端已签发且摘要匹配的原始候选事实
- `tripApi.confirmPlan()` → `POST /api/v1/trips/{tripId}/plan-versions/{planId}/confirm`
- `tripApi.startExecution()` → `POST /api/v1/trips/{tripId}/execution/start`
- `tripApi.getTrip()` → `GET /api/v1/trips/{tripId}`

计划生成会实际调用城市解析、已确认起终点解析、多个同城 POI 关键词检索和逐段路线规划，并展示 `cityCode`、来源状态、`fetchedAt` 和未知价格。页面原样复用 `/trips/drafts/confirm` 返回的权威 Trip，最后追加回到已确认终点的独立返程任务；不会在客户端重建参与者或把最后一个景点冒充终点。Provider 返回 `amountCents: null + UNKNOWN` 时，页面显示“未知待确认”，计划总额只累计 Provider 已返回的金额。前端地址栏保留 `tripId`。刷新时恢复 `CURRENT` 或 `PROPOSED` 及其服务端签发事实；确认按钮严格按“服务端 T011 生成并签发 → 确认 CURRENT → 开始执行”的顺序调用。公开 `POST /plan-versions` 直登接口会返回 403；前端不构造 PlanVersion、不填写约束 `PASS`、不生成 `planId`。DTO 定义在 `src/domain/trip.ts`，字段名保持 camelCase，不翻译代码契约。

路线 DTO 的 `facilityEvidence[]` 逐项展示电梯、坡道、母婴室和无障碍入口。来源缺失时总状态显示“待确认”，不能显示 `PASS`。

## 9. Plan V2 Diff 与决策正式接口

设置 `VITE_USE_PLAN_VERSION_API=true` 后：

- `tripApi.selectReplan()` → `POST /api/v1/trips/{tripId}/replans`；提交候选事实、原因、满意度损失与锁定任务，由服务端 T011 重算并交 T018 选择、签发 V2。
- `tripApi.getPlanDiff()` → `GET /api/v1/trips/{tripId}/plan-versions/{planId}/diff`
- `tripApi.acceptPlanV2()` → `POST /api/v1/trips/{tripId}/plan-versions/{planId}/accept`
- `tripApi.rejectPlanV2()` → `POST /api/v1/trips/{tripId}/plan-versions/{planId}/reject`

前端展示 `PLACE | TIME | ROUTE | COST | CARE` 五类及 `RETAINED | REMOVED | ADDED | CHANGED` 四种变化。前端不直接登记 V2，也不自报 `validationStatus: PASS`；接受前不得用候选数据替换当前计划。决策完成后重新调用 `getTrip()`，以服务端唯一 `CURRENT` 为准。S1 仅支持一次 V2 调整：CURRENT 已为 V2 或已经完成一次 V2 决策时，前端不再调用重规划接口。

## 10. 执行消费事件正式接口

- `tripApi.createExecutionEvent()` → `POST /api/v1/trips/{tripId}/events`
- `tripApi.getTrip()` 同时恢复 `events[]` 与 `actualBudget`

消费使用 `EXPENSE` 事件，金额为整数分；页面使用稳定 `idempotencyKey`，刷新后以服务端事件流复算的 `actualSpentCents` 和 `remainingBudgetCents` 为准。

## 11. 执行中迟到/疲劳草稿与临时约束

- `POST /api/v1/execution-adjustments/parse`：输入 `rawText/taskId/currentTask`，只返回 `LATE | FATIGUE` 零写入草稿或固定确认问题。百炼超过 10 秒、输出非法或未配置时降级为固定表单。
- `POST /api/v1/execution-adjustments/trips/{tripId}/events`：用户确认后保存 LATE/FATIGUE 事件；必须携带 CURRENT `planVersionId`、稳定 `idempotencyKey` 和带时区 `occurredAt`。
- `GET /api/v1/execution-adjustments/trips/{tripId}/events`：恢复服务端已确认事件；同键同内容幂等，同键不同内容冲突。
- `POST /api/v1/execution-adjustments/compile`：只接受 `confirmationStatus=CONFIRMED`，确定性返回临时 `EventConstraintSet` 和可见原因。

这两个接口都不会写现有 `/trips/{tripId}/events`、长期关怀画像或 PlanVersion。T023 页面可以消费草稿和原因；真正生成 V2 由 T021 使用服务端可信 CURRENT/任务事实重新编译。

## 12. 执行中迟到/疲劳重规划与 Diff

- `POST /api/v1/trips/{tripId}/replans/from-adjustment`：提交服务端返回的 `adjustmentEventId`、与之完全一致的已确认事件、锁定任务 ID 与是否请求解释。客户端不得提交候选、事实、约束 PASS 或 planId；服务端恢复 `CURRENT V1` 和可信规划事实，冻结前缀并重验预算、时间、路线、关怀和瞬时 HARD。
- 成功响应返回 `candidatePlan + diff + eventConstraints + derivedContext + frozenTaskIds + validationReport + explanation`。候选接受前不会替换 `CURRENT`。
- `POST /api/v1/trips/{tripId}/replans/{planId}/decision`：请求 `{schemaVersion:"1.0", decision:"ACCEPT"|"REJECT"}`。接受原子切换唯一 CURRENT；拒绝保留原计划。
- 预览会绑定当时的 `readinessDigest/currentRevision`；成员资料变化后旧候选决策会失败。迟到/疲劳候选不能改用通用 V2 accept/reject 绕过此检查。
- 百炼解释是可选展示字段。`UNAVAILABLE` 只表示解释降级，页面仍必须使用完整结构化候选和 Diff；不得根据解释文案改写任务、价格或状态。
- 协作 Trip 调用以上接口必须继续携带 `X-Organizer-Token`。S2-T023 页面已接入迟到/疲劳草稿、确认事件、结构化 Diff 与专用接受/拒绝；解释 `UNAVAILABLE` 不阻断结构化结果或决策。

## 13. 多人硬冲突与组织者处理

- `GET /api/v2/trips/{tripId}/collaboration`：携带 `X-Organizer-Token` 恢复协作进度和 `confirmationItems[]`。
- 冲突项公开字段固定为 `participantId/relatedParticipantIds/ruleId/reason/allowedRelaxations`。页面必须点名成员与规则，不能只显示一条笼统错误。
- `POST /api/v2/trips/{tripId}/confirmation-items/{itemId}/resolve`：携带组织者凭证、`Idempotency-Key`，并提交当前 `baseRevision/expectedVersion/relaxationId`。
- 组织者只能点击 `actorScope=ORGANIZER` 的选项；成员选项显示“需对应成员本人处理”，不得由前端绕过权限。
- 页面只有在 `status=READY_TO_PLAN && canPlan=true && readinessDigest!=null` 时显示唯一推荐入口。冲突解决后若成员状态为 `NEEDS_RECONFIRMATION`，应继续显示等待重新确认，不得直接进入规划。
- 组织者创建入口已接入 T002 `TripDraftRevision` 生产实现；任何 revision、权限或 readiness 校验失败仍必须 fail-closed，前端不得伪造成功状态。

## 14. 尚未登记的远端接口

以下能力目前没有远端 HTTP 契约：

- 照片与视频上传

照片与视频当前仅保存在浏览器本地；团队若需要跨设备同步，必须先补充 URL、请求 DTO、响应 DTO、状态转换和错误码，不得伪造上传成功。
