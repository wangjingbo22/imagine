# 接口契约

> 项目尚未最终确定，本文件先固化“统一接口治理规则”和“填写模板”。具体 URL、字段、异常码、状态流转在需求明确后补充，不得由 AI 擅自定义。

## 1. 契约总原则

1. 接口定义必须先由人工确认，再进入开发。
2. 接口变更必须同步更新本文件，禁止代码与文档长期不一致。
3. 前后端、模块间、服务间的交互都视为接口契约的一部分。
4. 新接口未登记前，不允许 AI 自行新增字段或响应结构。

## 2. 统一响应格式

如项目采用 HTTP/REST，默认返回结构为：

```json
{
  "code": 200,
  "message": "success",
  "data": {}
}
```

说明：
- `code`：业务状态码或统一状态码
- `message`：给调用方看的简要结果描述
- `data`：实际业务数据，列表/对象/空结构需保持一致性

> 若项目使用消息流、Graph、LangGraph 状态流或端侧能力调用，请在立项后补充等价的输入输出规范，但仍需保持“字段稳定、错误显式、版本可追踪”。

## 3. 统一错误码约定

当前保留以下通用约定，项目确定后可扩展但不应随意覆盖：

- `200`：成功
- `400`：参数错误
- `401`：未认证 / 凭证失效
- `403`：无权限
- `404`：资源不存在
- `409`：状态冲突 / 幂等冲突
- `422`：业务校验失败
- `500`：服务内部错误

## 4. 字段设计约束

- 字段名必须语义明确，禁止使用 `value`、`data1` 一类模糊命名
- 时间字段必须统一格式，立项后明确时区和序列化规则
- 分页字段命名必须统一，如 `pageNum` / `pageSize` / `total`
- 状态字段必须在本文件中列出可选值及含义
- 枚举值必须定义来源，不允许“代码里写一套、文档里写一套”

## 5. 一致性检查清单

每次新增或修改接口时，至少检查以下内容：

- 请求方法是否正确
- 必填/可选参数是否明确
- 参数类型、长度、枚举范围是否明确
- 返回字段是否与页面/调用方实际使用一致
- 异常码是否覆盖参数异常、权限异常、业务异常、系统异常
- 是否需要幂等、去重、重试、限流说明

## 6. 接口登记模板

复制以下模板新增具体接口：

```md
## {接口名称}
- 用途：{解决什么问题}
- 调用方：{页面 / 模块 / 服务}
- 被调用方：{后端接口 / AI流程节点 / 设备能力}
- 请求方式：{GET / POST / PUT / DELETE / 内部调用}
- 路径或标识：{URL / topic / action / graph node}
- 请求头：{如 Authorization、Content-Type}
- 输入参数：
  - {字段名}：{类型}，{是否必填}，{说明}
- 输出参数：
  - code：number，状态码
  - message：string，结果说明
  - data：{对象结构说明}
- 异常码：
  - {错误码}：{含义}
- 一致性校验：
  - {例如：用户 ID 必须与登录态一致}
- 备注：
  - {幂等要求 / 分页规则 / 排序规则 / 状态流转约束}
```

## 7. 项目确定后必须补充

- 核心业务接口清单
- 模块间内部调用契约
- 鉴权头与刷新机制
- 分页、筛选、排序参数规范
- 文件上传下载规范
- WebSocket / 流式输出 / Agent 状态更新协议

## 8. 行知旅伴 Sprint 1 接口登记

- 当前权威契约为 `backend/app/schemas/trip.py` 导出的 S1-T001
  `CreateSingleDayTrip` 与 S1-T003 `AssistanceProfile`。
- 外部 JSON 使用 camelCase，严格禁止额外字段。
- 金额统一使用非负整数分；日期使用 `YYYY-MM-DD`；时间严格使用
  `HH:mm:ss`。
- `assistanceProfile` 支持 `ORDINARY`、`PARENT_CHILD`、`LOW_STAMINA`
  和 `MOBILITY_ASSISTANCE_BETA`；所有可空字段仍必须显式提供。
- T009 路线风险结果使用 `PASS | WARNING | NEEDS_CONFIRMATION | FAIL`，
  每项必须保留稳定的 `ruleId`、`routeSegment`、`observed` 与 `suggestion`。
- Schema 错误使用 `TRIP_SCHEMA_INVALID`；歧义确认使用
  `TRIP_CONFIRMATION_REQUIRED`，两者均返回字段级 `errors[]`。
- Trip 创建 HTTP URL 尚未登记；自然语言解析、城市查询与 Plan V1 状态接口已经登记。媒体与总结接口继续保持 Mock。
- 前端对齐说明见 `frontend/src/api/API.md`。

## 9. PBI-02-A 城市地点、路线与可信来源（Schema 1.0）

以下 URL 是张琪任务的本地联调接口，尚未登记为团队正式 HTTP 契约；字段命名和数据定义以第 8 节及 `backend/app/schemas/trip.py` 为准。

### 9.1 成功与失败结构

成功：

```json
{"code": 200, "message": "success", "data": {}}
```

Schema 校验失败沿用人工确认结构：

```json
{
  "code": "TRIP_SCHEMA_INVALID",
  "schemaVersion": "1.0",
  "errors": [{"path": "days[0].timeWindow.end", "code": "missing", "message": "Field required"}]
}
```

其他失败使用相同失败外形，`code` 为稳定业务错误码。已登记错误码：`CITY_CONTEXT_REQUIRED`、`CITY_CONTEXT_MISMATCH`、`AMAP_KEY_MISSING`、`AMAP_AUTH_FAILED`、`AMAP_QUOTA_EXCEEDED`、`AMAP_RATE_LIMITED`、`PROVIDER_TIMEOUT`、`PROVIDER_UNAVAILABLE`、`CITY_CACHE_MISS`、`PLACE_NOT_FOUND`、`ROUTE_NOT_FOUND`、`INVALID_ROUTE_MODE`。

### 9.2 可信来源规则

- `sourceStatus`：`ONLINE | VERIFIED_CACHE | USER_CONFIRMED | ESTIMATED | UNKNOWN`
- 所有地点、路线和价格事实必须带 `provider`、`fetchedAt`、`isStale`。
- 未知价格固定返回 `amountCents: null` 与 `sourceStatus: UNKNOWN`，不得返回 0 冒充已知价格。
- `cityCode` 使用团队 Trip Schema 定义的行政区划码（如北京 `110000`），必须同时进入 Provider 调用上下文和缓存复合键；高德返回的电话区号 `citycode` 仅用于核验，不替代该字段。
- 在线失败只允许读取请求参数完全一致的同城市缓存。

### 9.3 本地联调接口

均为 JSON `POST`，请求必须带 `schemaVersion: "1.0"`；除城市解析外，必须带 `tripId` 与完整 `cityContext`。

- `/api/v1/cities/resolve`：按国内城市名解析 CityContext。
- `/api/v1/places/suggestions`：同城地点输入提示。
- `/api/v1/places/search`：同城关键词/类型地点搜索。
- `/api/v1/places/nearby`：同城中心点周边搜索。
- `/api/v1/places/detail`：地点详情。
- `/api/v1/geocoding/forward`：同城地址转坐标。
- `/api/v1/geocoding/reverse`：坐标转地址并核对城市。
- `/api/v1/routes/plan`：`WALKING | TRANSIT | DRIVING | BICYCLING` 路线规划。

路线返回的 `facilityEvidence[]` 固定逐项表达电梯、坡道、母婴室和无障碍入口事实。Provider 未提供设施来源时，项目返回 `status: NEEDS_CONFIRMATION + sourceStatus: UNKNOWN`，不得显示为 `PASS`。

### 9.4 安全与幂等

- 高德 Key 只允许从 `AMAP_WEB_SERVICE_KEY` 环境变量读取。
- Key 不得出现在响应、日志、缓存键、缓存值或 Git 文件中。
- 查询接口只读；相同城市与相同参数生成稳定缓存摘要。
- 高德错误必须转换为本项目错误码，不向前端暴露内部异常堆栈。

## 10. PBI-04-B Plan V1 确认与状态守卫（Schema 1.0）

本节契约已由张琪于 2026-08-24 确认，用于本地前后端联调。

### 10.1 路由

- `POST /api/v1/trips/{tripId}/plan-versions/generate`：接收严格的 `CandidatePlanRequest`。服务端先核对 T004 已确认画像和 `/trips/drafts/confirm` 保存的完整 Trip 快照，再由 T011 重新编译 T007 约束、核验 T006/T009 路线事实并重算时间与整数分预算；只有完整 `PASS` 的结果才会登记为 `PROPOSED` Plan V1，并留下候选事实、校验结果和提案摘要的 `ISSUED` 记录。
- `GET /api/v1/trips/{tripId}/planning-facts`：仅返回当前服务端已签发且摘要匹配的 `CandidatePlanRequest`，供页面刷新后恢复 V2 所需的可信原始事实。
- `POST /api/v1/trips/{tripId}/plan-versions`：禁止客户端直接登记，统一返回 HTTP 403 `PLAN_VERSION_DIRECT_REGISTRATION_FORBIDDEN`；V1/V2 只能由服务端可信规划边界在内部登记，避免客户端抢占 `(tripId, version)` 或伪造 Trip 状态。
- `POST /api/v1/trips/{tripId}/plan-versions/{planId}/confirm`：先校验该 V1 的服务端签发记录与当前不可变快照摘要一致，再原子地将其从 `PROPOSED` 改为唯一 `CURRENT`，同时将 Trip 从 `PLAN_REVIEW` 改为 `CONFIRMED`。
- `POST /api/v1/trips/{tripId}/execution/start`：仅在存在 `CURRENT` 版本且 Trip 为 `CONFIRMED` 时迁移到 `EXECUTING`。
- `GET /api/v1/trips/{tripId}`：恢复 Trip 状态、当前/候选 PlanVersion 和原始快照。

成功响应沿用 `{ "code": 200, "message": "success", "data": ... }`。Schema 校验失败沿用 `TRIP_SCHEMA_INVALID` 字段级结构。

### 10.2 状态与不变量

- `PlanVersion.status`：`PROPOSED | CURRENT | REJECTED | SUPERSEDED`。
- 初始确认链路：`Trip.PLAN_REVIEW + PlanVersion.PROPOSED -> Trip.CONFIRMED + PlanVersion.CURRENT -> Trip.EXECUTING`。
- 同一 Trip 最多一个 `CURRENT`，由数据库部分唯一索引和事务共同保证。
- 已保存 PlanVersion 不允许重复登记或原地替换快照；相同 `planId` 和完全相同请求返回 `PLAN_VERSION_ALREADY_EXISTS`。确认接口本身保持幂等。
- `days` 当前固定单日；每天 3—4 个任务，`order` 必须从 1 连续递增。
- 任务金额、步行距离、预算缓冲必须与 `metrics` 精确相等；所有硬约束必须为 `PASS`。
- 未确认的 `PROPOSED` 绝不能进入执行状态，大模型也不得直接写状态。
- 客户端提交的 `validationStatus`、约束 `PASS` 或随机 `planId` 均不是可信验证证据；确认边界只认可服务端 T011 签发的 canonical SHA-256 摘要。

### 10.3 错误码

- `PLAN_NOT_CONFIRMED`：没有 `CURRENT` 版本，不允许开始执行（HTTP 409）。
- `PLAN_STATE_TRANSITION_INVALID`：非法 Trip/PlanVersion 状态迁移（HTTP 409）。
- `PLAN_VERSION_ALREADY_EXISTS`：同一 PlanVersion 重复登记（HTTP 409）。
- `PLAN_VERSION_IMMUTABLE`、`TRIP_SNAPSHOT_IMMUTABLE`：尝试原地更换已保存快照（HTTP 409）。
- `PLAN_CURRENT_CONFLICT`、`PLAN_VERSION_CONFLICT`：唯一 CURRENT 或版本号冲突（HTTP 409）。
- `PLAN_TRIP_MISMATCH`：路径 Trip 与 Plan 不匹配（HTTP 409）。
- `PLANNING_PLAN_NOT_ISSUED`：版本没有服务端规划签发记录，不能确认或接受（HTTP 409）。
- `PLANNING_PROPOSAL_DIGEST_MISMATCH`：已存快照与签发摘要不一致（HTTP 409）。
- `PLAN_VERSION_DIRECT_REGISTRATION_FORBIDDEN`：客户端尝试绕过 T011/T018 直接登记版本（HTTP 403）。
- `CONSTRAINTS_NOT_CONFIRMED`、`CONSTRAINT_PROFILE_MISMATCH`：T004 画像未确认或与规划请求不一致（HTTP 409）。
- `TRIP_NOT_CONFIRMED`、`CONFIRMED_TRIP_MISMATCH`：没有权威 Trip 快照，或规划请求改变了已确认的参与者、预算、时间窗或起终点（HTTP 409）。
- `CONFIRMED_TRIP_CONFLICT`：同一 `tripId` 再次确认了不同的 Trip 内容；权威快照保持不可变（HTTP 409）。
- `TRIP_NOT_FOUND`、`PLAN_VERSION_NOT_FOUND`：资源不存在（HTTP 404）。

### 10.4 T014 snapshot boundary

- 内部 `tripSnapshot` MUST be a single-person, single-day `PLAN_REVIEW` snapshot；`ProposedPlanVersion` 仍按 T014 Schema 严格校验。
- 公开 raw PlanVersion 路由在读取快照前即返回 HTTP 403。V1/V2 的正式入口分别校验 `CandidatePlanRequest` 与 `ReplanGenerationRequest`；任何 422/409 拒绝都不得写入正式 PlanVersion，V2 拒绝还必须保留完整 CURRENT V1 与 `EXECUTING` 状态。

## 11. PBI-05-C V1/V2 Diff 与接受拒绝（Schema 1.0）

本节契约已由张琪于 2026-08-24 确认。

### 11.1 候选 V2

- `POST /api/v1/trips/{tripId}/replans`：接收 `reason`、`lockedTaskIds` 和 1—20 个 `{ request: CandidatePlanRequest, satisfactionLoss }` 候选。服务端读取唯一 `CURRENT` 和真实 `ExecutionEvent`，逐个调用 T011 重算，再由 T018 按最小扰动规则选择；只有 `SELECTED` 候选会登记并签发为 V2 `PROPOSED`。
- 公开 `POST /api/v1/trips/{tripId}/plan-versions` 不接受 V2；V2 只能由 `/replans` 经 T011 校验与 T018 选择后在服务端内部登记和签发。
- V2 必须使用 `version: 2`，`parentId` 必须指向该 Trip 唯一且具有匹配 `ISSUED` 摘要的 `CURRENT` V1，Trip 必须为 `EXECUTING`；旧库中未签发的 CURRENT 不能作为可信父版本。
- V2 原因固定为 `EXPENSE_CHANGE | DELAY | FATIGUE | USER_FEEDBACK | OTHER`；`INITIAL_PLAN` 只允许 V1。
- 登记成功后 V2 为 `PROPOSED`，Trip 从 `EXECUTING` 进入 `REPLAN_REVIEW`；V1 和 Trip 快照保持不可变。

### 11.2 路由与返回

- `GET /api/v1/trips/{tripId}/plan-versions/{planId}/diff`：服务端比较 V2 与其父版本。
- `POST /api/v1/trips/{tripId}/plan-versions/{planId}/accept`：校验 T018 签发记录和快照摘要后接受 V2。
- `POST /api/v1/trips/{tripId}/plan-versions/{planId}/reject`：拒绝 V2。
- Diff 分类固定为 `PLACE | TIME | ROUTE | COST | CARE`，变化类型固定为 `RETAINED | REMOVED | ADDED | CHANGED`。
- Diff 同时返回 `totalCostCents`、`totalWalkMeters`、`transferCount` 的差值；正数代表 V2 增加，负数代表 V2 减少。

### 11.3 原子状态守卫与幂等

- 接受：父版本 `CURRENT -> SUPERSEDED`，V2 `PROPOSED -> CURRENT`，Trip `REPLAN_REVIEW -> EXECUTING`，全部在一个事务中完成。
- 拒绝：V2 `PROPOSED -> REJECTED`，父版本继续为唯一 `CURRENT`，Trip `REPLAN_REVIEW -> EXECUTING`。
- 相同决策可幂等重试；终态后执行相反决策返回 `PLAN_STATE_TRANSITION_INVALID`（HTTP 409）。
- `PLAN_PARENT_NOT_FOUND` 返回 HTTP 404；父版本、路径 Trip 或不可变 Trip 快照不一致均被拒绝。
- 当前 Sprint 1 只允许从 V1 生成一次 V2；CURRENT 已为 V2 时返回 `REPLAN_S1_VERSION_LIMIT`，V2 已拒绝后的再次生成也因版本唯一性 fail-closed。
- 页面只能调用决策接口，不得直接改写状态；候选 V2 在接受前不得覆盖当前方案。

## 12. PBI-01-B / PBI-05-A / PBI-06-A 工作流接口

### 12.1 约束状态

- `PUT /api/v1/trips/{tripId}/constraints`：保存严格 `AssistanceProfile`，状态为 `DRAFT`；修改已确认内容后回退 DRAFT。
- `POST /api/v1/trips/{tripId}/constraints/confirm`：幂等确认，状态为 `CONSTRAINT_CONFIRMED`。
- `GET /api/v1/trips/{tripId}/constraints`：恢复约束状态。
- 生成 Plan V1 前必须存在已确认的约束记录，并使用完全相同的 Profile；同时必须匹配 `/trips/drafts/confirm` 保存的完整 Trip。

### 12.2 执行事件

- `POST /api/v1/trips/{tripId}/events`
- `GET /api/v1/trips/{tripId}/events`

请求字段：`taskId`、`planVersionId`、`eventType`、`amountCents`、`idempotencyKey`。
事件类型固定为 `START | COMPLETE | SKIP | EXPENSE`。相同幂等键和相同请求返回原事件；相同键不同请求返回 `EVENT_IDEMPOTENCY_CONFLICT`。

`schemaVersion` 固定为 `1.0`；`occurredAt` 必须包含时区。`EXPENSE` 必须提供非负整数分 `amountCents`，其他事件禁止携带金额。实际消费从 Trip 的全部 `EXPENSE` 事件复算，`remainingBudgetCents = plannedBudgetCents - actualSpentCents`，允许负数表示超支；刷新页面通过 Trip 状态中的 `events` 与 `actualBudget` 恢复。

### 12.3 基础总结

- `GET /api/v1/trips/{tripId}/summary`

总结由服务端从 CURRENT PlanVersion 和 ExecutionEvent 复算，返回计划/实际金额、差额、完成/跳过任务、当前版本、版本历史和事件。

## 13. PBI-11-B 执行中迟到/疲劳草稿与临时约束（Schema 1.0）

### 13.1 事件草稿

- `POST /api/v1/execution-adjustments/parse`
- 请求固定为 `schemaVersion/rawText/taskId/currentTask`，且 `currentTask.taskId` 必须与顶层 `taskId` 相同。
- 响应体固定为 `schemaVersion/eventType/taskId/lateMinutes/fatigueLevel/clarificationQuestions`；禁止模型输出 Constraint、Profile、PlanVersion 或状态。
- `eventType` 只允许 `LATE | FATIGUE | null`；`lateMinutes` 为 1—240；`fatigueLevel` 为 `MILD | MODERATE | SEVERE`。
- 不明确时由程序生成固定 `questionKey`；百炼输出非法、不可用或超过 10 秒时只调用一次并降级到固定表单。
- 该接口零写入，不进入现有 START/COMPLETE/SKIP/EXPENSE 事件流。

### 13.2 已确认事件转换

- `POST /api/v1/execution-adjustments/trips/{tripId}/events`：在用户确认后保存服务端 LATE/FATIGUE 事件。
- `GET /api/v1/execution-adjustments/trips/{tripId}/events`：按真实发生时间恢复已确认事件。
- 保存请求必须包含当前 `planVersionId`、稳定 `idempotencyKey` 和带时区 `occurredAt`；同键同内容返回原事件，同键不同内容返回 `EVENT_IDEMPOTENCY_CONFLICT`。
- `POST /api/v1/execution-adjustments/compile`
- 只接受 `confirmationStatus: CONFIRMED`。
- `LATE` 只收紧 `remaining.timeBudgetMinutes`；`FATIGUE` 只收紧剩余总步行、单段步行和休息间隔。
- 输出为瞬时 `EventConstraintSet`，供 S2-T021 在服务端从可信 CURRENT/任务事实重新编译并消费。
- `EventConstraintSet` 绝不能追加到 T007 `confirmedConstraints`，不得修改长期 AssistanceProfile 或任何 PlanVersion 状态。
- 同一严格输入和同一 `policyVersion` 必须得到相同约束、原因和 SHA-256 摘要；摘要仅用于幂等比较，不是签名。

### 13.3 S2-T021 服务端后缀重规划

- `POST /api/v1/trips/{tripId}/replans/from-adjustment`
- 请求只能包含 `schemaVersion`、服务端签发的 `adjustmentEventId`、与该事件完全一致的已确认 `adjustment`、唯一 `lockedTaskIds[]` 与 `explainDifferences`；禁止客户端提交候选、FactRef 内容、当前计划、编译后约束或校验结果。无 `adjustmentEventId` 仅保留旧客户端兼容，不作为新版验收路径。
- 服务端要求父版本是匹配 `ISSUED` 记录的唯一 `CURRENT V1`，恢复其可信 `CandidatePlanRequest` 与执行事件，并重新编译 S2-T020 瞬时约束。
- 默认确定性后缀规划器只压缩可信路线之外的时间空隙或收紧派生休息计数；地点、路线、价格和设施事实不得改写。可信事实不足或 HARD 无法满足时直接无解，禁止伪造替代路线。
- 已完成、已跳过、已开始、当前和显式锁定任务所覆盖的连续前缀必须逐对象保持不变；只允许调整剩余后缀。
- 候选必须重新覆盖并通过 `BUDGET | TIME | ROUTE | CARE` 全部 HARD 以及本次瞬时 HARD。无解返回 `REPLAN_NO_FEASIBLE_CANDIDATE`、受影响规则与可放宽项，且不得登记 V2 或签发记录。
- S2-T020 瞬时约束只写入本次校验与签发证据，不并入长期 S1-T007 约束。

### 13.4 S2-T022 Diff、解释与决策

- 成功预览返回 `candidatePlan`、`diff`、`eventConstraints`、`derivedContext`、`frozenTaskIds`、候选评估和完整校验报告；候选保持 `PROPOSED`，`currentPlanChanged` 固定为 `false`。
- `POST /api/v1/trips/{tripId}/replans/{planId}/decision` 只接受 `ACCEPT | REJECT`。两种决策都要求候选具有服务端 `ISSUED V2` 记录，并复用既有 PlanVersion 原子事务。
- 候选签发证据绑定生成时的 `readinessDigest/currentRevision`；决策时必须与当前协作版本一致。成员资料变化后，旧候选不能再接受。
- `DELAY | FATIGUE` 候选禁止使用通用 `/plan-versions/{planId}/accept|reject`，必须走本节专用决策接口并复验瞬时 HARD 证据。
- 百炼只读取服务端生成的脱敏 Diff 投影并返回一段展示文案；它不得修改任务、金额、状态或版本。未配置、超时或非法输出只令 `explanation.status=UNAVAILABLE`，结构化候选与 Diff 必须完整返回。

## 14. PBI-15-A 多人硬冲突与组织者处理（S2-T029）

- `GET /api/v2/trips/{tripId}/collaboration` 必须携带 `X-Organizer-Token`，返回当前 `collaborationVersion/currentRevision/status/canPlan/progress/confirmationItems`。
- 每个 `confirmationItems[]` 必须包含 `participantId`、`relatedParticipantIds[]`、`ruleId`、`reason` 与 `allowedRelaxations[]`；旧字段名 `relaxations` 仅保留输入兼容，不作为公开响应字段。
- `POST /api/v2/trips/{tripId}/confirmation-items/{itemId}/resolve` 必须携带 `X-Organizer-Token` 与 `Idempotency-Key`，请求固定为 `schemaVersion/baseRevision/expectedVersion/relaxationId`。
- 组织者只能执行 `actorScope=ORGANIZER` 的放宽项。成员字段的 `PARTICIPANT` 放宽项必须由对应成员会话执行；组织者页面应显示责任成员，但不得代填或越权修改。
- 任何未解决确认项都令 `status=CONFLICT_REVIEW`、`canPlan=false`、`readinessDigest=null`，Provider、推荐和规划边界必须在调用下游前拒绝。
- 放宽会创建新的 T002 revision。旧确认随即变为 `NEEDS_RECONFIRMATION`，状态进入 `COLLECTING_MEMBERS`；只有所有成员在新 revision 重新确认且硬冲突为零，才可进入 `READY_TO_PLAN`。
- `MemberSessionView` 返回 `collaborationVersion`，确保成员解决自己的确认项时能提交严格 `expectedVersion`。
- 当前生产 `POST /api/v2/trips/conversations` 仍等待 T002 `TripDraftRevision` 接入并返回 503；S2-T029 不得伪造该上游能力。
