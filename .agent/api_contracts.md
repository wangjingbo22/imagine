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
  `CreateSingleDayTrip`。
- 外部 JSON 使用 camelCase，严格禁止额外字段。
- 金额统一使用非负整数分；日期使用 `YYYY-MM-DD`；时间严格使用
  `HH:mm:ss`。
- Schema 错误使用 `TRIP_SCHEMA_INVALID`；歧义确认使用
  `TRIP_CONFIRMATION_REQUIRED`，两者均返回字段级 `errors[]`。
- 当前尚未登记正式 HTTP URL。自然语言解析、城市查询、计划、执行、媒体与总结接口均保持 Mock，等待责任人补充契约。
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
