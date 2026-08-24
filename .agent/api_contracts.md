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
- Trip 创建 HTTP URL 尚未登记；城市查询与 Plan V1 状态接口分别见第 9、10 节。自然语言解析、媒体与总结接口继续保持 Mock。
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

### 9.4 安全与幂等

- 高德 Key 只允许从 `AMAP_WEB_SERVICE_KEY` 环境变量读取。
- Key 不得出现在响应、日志、缓存键、缓存值或 Git 文件中。
- 查询接口只读；相同城市与相同参数生成稳定缓存摘要。
- 高德错误必须转换为本项目错误码，不向前端暴露内部异常堆栈。

## 10. PBI-04-B Plan V1 确认与状态守卫（Schema 1.0）

本节契约已由张琪于 2026-08-24 确认，用于本地前后端联调。

### 10.1 路由

- `POST /api/v1/trips/{tripId}/plan-versions`：登记通过确定性校验的 `PROPOSED` Plan V1。请求体必须包含不可变的 `tripSnapshot`、`days`、`metrics`、`constraintsSnapshot` 和 `sourcesSnapshot`。
- `POST /api/v1/trips/{tripId}/plan-versions/{planId}/confirm`：原子地将该版本从 `PROPOSED` 改为唯一 `CURRENT`，同时将 Trip 从 `PLAN_REVIEW` 改为 `CONFIRMED`。
- `POST /api/v1/trips/{tripId}/execution/start`：仅在存在 `CURRENT` 版本且 Trip 为 `CONFIRMED` 时迁移到 `EXECUTING`。
- `GET /api/v1/trips/{tripId}`：恢复 Trip 状态、当前/候选 PlanVersion 和原始快照。

成功响应沿用 `{ "code": 200, "message": "success", "data": ... }`。Schema 校验失败沿用 `TRIP_SCHEMA_INVALID` 字段级结构。

### 10.2 状态与不变量

- `PlanVersion.status`：`PROPOSED | CURRENT | REJECTED | SUPERSEDED`。
- 初始确认链路：`Trip.PLAN_REVIEW + PlanVersion.PROPOSED -> Trip.CONFIRMED + PlanVersion.CURRENT -> Trip.EXECUTING`。
- 同一 Trip 最多一个 `CURRENT`，由数据库部分唯一索引和事务共同保证。
- 已保存 PlanVersion 不允许原地替换快照；相同 `planId` 和完全相同请求可幂等重放。
- `days` 当前固定单日；每天 3—4 个任务，`order` 必须从 1 连续递增。
- 任务金额、步行距离、预算缓冲必须与 `metrics` 精确相等；所有硬约束必须为 `PASS`。
- 未确认的 `PROPOSED` 绝不能进入执行状态，大模型也不得直接写状态。

### 10.3 错误码

- `PLAN_NOT_CONFIRMED`：没有 `CURRENT` 版本，不允许开始执行（HTTP 409）。
- `PLAN_STATE_TRANSITION_INVALID`：非法 Trip/PlanVersion 状态迁移（HTTP 409）。
- `PLAN_VERSION_IMMUTABLE`、`TRIP_SNAPSHOT_IMMUTABLE`：尝试原地更换已保存快照（HTTP 409）。
- `PLAN_CURRENT_CONFLICT`、`PLAN_VERSION_CONFLICT`：唯一 CURRENT 或版本号冲突（HTTP 409）。
- `PLAN_TRIP_MISMATCH`：路径 Trip 与 Plan 不匹配（HTTP 409）。
- `TRIP_NOT_FOUND`、`PLAN_VERSION_NOT_FOUND`：资源不存在（HTTP 404）。

### 10.4 T014 snapshot boundary

- `tripSnapshot` MUST be a single-person, single-day `PLAN_REVIEW` snapshot.
- Invalid V1/V2 snapshots return HTTP 422 `TRIP_SCHEMA_INVALID` with stable
  field path/code; rejected V1 writes no Trip state, while rejected V2 preserves
  the full CURRENT V1 and `EXECUTING` state.

## 11. PBI-05-C V1/V2 Diff 与接受拒绝（Schema 1.0）

本节契约已由张琪于 2026-08-24 确认。

### 11.1 候选 V2

- `POST /api/v1/trips/{tripId}/plan-versions` 同时登记 V1 和 V2。
- V2 必须使用 `version: 2`，`parentId` 必须指向该 Trip 唯一的 `CURRENT`，Trip 必须为 `EXECUTING`。
- V2 原因固定为 `EXPENSE_CHANGE | DELAY | FATIGUE | USER_FEEDBACK | OTHER`；`INITIAL_PLAN` 只允许 V1。
- 登记成功后 V2 为 `PROPOSED`，Trip 从 `EXECUTING` 进入 `REPLAN_REVIEW`；V1 和 Trip 快照保持不可变。

### 11.2 路由与返回

- `GET /api/v1/trips/{tripId}/plan-versions/{planId}/diff`：服务端比较 V2 与其父版本。
- `POST /api/v1/trips/{tripId}/plan-versions/{planId}/accept`：接受 V2。
- `POST /api/v1/trips/{tripId}/plan-versions/{planId}/reject`：拒绝 V2。
- Diff 分类固定为 `PLACE | TIME | ROUTE | COST | CARE`，变化类型固定为 `RETAINED | REMOVED | ADDED | CHANGED`。
- Diff 同时返回 `totalCostCents`、`totalWalkMeters`、`transferCount` 的差值；正数代表 V2 增加，负数代表 V2 减少。

### 11.3 原子状态守卫与幂等

- 接受：父版本 `CURRENT -> SUPERSEDED`，V2 `PROPOSED -> CURRENT`，Trip `REPLAN_REVIEW -> EXECUTING`，全部在一个事务中完成。
- 拒绝：V2 `PROPOSED -> REJECTED`，父版本继续为唯一 `CURRENT`，Trip `REPLAN_REVIEW -> EXECUTING`。
- 相同决策可幂等重试；终态后执行相反决策返回 `PLAN_STATE_TRANSITION_INVALID`（HTTP 409）。
- `PLAN_PARENT_NOT_FOUND` 返回 HTTP 404；父版本、路径 Trip 或不可变 Trip 快照不一致均被拒绝。
- 页面只能调用决策接口，不得直接改写状态；候选 V2 在接受前不得覆盖当前方案。
