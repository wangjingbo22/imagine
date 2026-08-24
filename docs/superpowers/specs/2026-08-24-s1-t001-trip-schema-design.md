# S1-T001 Trip Schema 设计

## 范围

S1-T001 为 `PBI-01-A / AC-01-A` 定义统一的 `CityContext`、`Trip`、`Participant`、`TripDayInput` 结构，并提供结构化校验、JSON Schema 快照和字段级错误。当前公开入口严格限制为单人、单日、`DRAFT`；全国城市通过不透明的 `cityCode` 和 Provider 配置表达，不设置北京默认值。

本任务不实现自然语言解析、确认 UI、城市 Provider、AssistanceProfile 规则、Plan V1 持久化、多日/多人、GPS、照片、迟到/疲劳或完整旅行回忆。未解析的歧义值由 T002 通过确认错误契约处理，不能进入完整 Trip。

## 方案

使用 Pydantic v2 作为唯一模型源，外部 JSON 使用 camelCase，Python 属性使用 snake_case 别名。模型配置为：严格模式、`extra="forbid"`、字符串去首尾空格、错误路径使用外部别名。业务版本由模型字段 `schemaVersion: Literal["1.0"]` 固定；`model_json_schema()` 只负责导出 JSON Schema，不能替代该字段约束。JSON Schema 自身的 `$schema` 元数据与业务 `schemaVersion` 是两个不同概念。

除明确标注为可选的字段外，以下字段全部必填：

| 对象 | JSON 字段 | 类型 | 约束 |
| --- | --- | --- | --- |
| `GeoPoint` | `longitude` | `float` | `-180 <= longitude <= 180` |
|  | `latitude` | `float` | `-90 <= latitude <= 90` |
| `ProviderConfig` | `provider` | `Literal["AMAP"]` | 当前 Sprint 1 Provider；不得包含凭据 |
|  | `coordinateSystem` | `Literal["GCJ02"]` | 与 AMAP 坐标保持一致 |
| `CityContext` | `countryCode` | `Literal["CN"]` | 中国城市统一入口 |
|  | `cityCode` | `str` | 去首尾空格后长度 `1..64`；Provider 分配的不透明标识，无城市默认值 |
|  | `cityName` | `str` | 去首尾空格后长度 `1..80` |
|  | `center` | `GeoPoint` | 必填 |
|  | `providerConfig` | `ProviderConfig` | 必填 |
| `Preference` | `type` | `PreferenceType` | `INTEREST / MUST_VISIT / AVOID_PLACE` |
|  | `value` | `str` | 去首尾空格后长度 `1..120` |
|  | `weight` | `int` | `1..5`，严格整数 |
|  | `isHard` | `bool` | `INTEREST=false`；`MUST_VISIT/AVOID_PLACE=true` |
| `Participant` | `participantId` | `UUID4` | 由应用生成 |
|  | `nickname` | `str` | 去首尾空格后长度 `1..40` |
|  | `budgetCapCents` | `int` | `>= 0`，单位为人民币分 |
|  | `preferences` | `list[Preference]` | 可选，默认空数组 |
|  | `assistanceProfile` | `None` | 可选；S1-T001 只允许省略或 `null`，由 T003 扩展为对象 |
| `TimeWindow` | `start` | ISO `time` | 序列化为 `HH:mm:ss` |
|  | `end` | ISO `time` | 必须晚于 `start`；S1 不支持跨午夜 |
| `TripDayInput` | `dayIndex` | `int` | `>= 0`；当前公开入口必须为 `0` |
|  | `date` | ISO `date` | 必填 |
|  | `dailyBudgetCents` | `int` | `>= 0`，单位为人民币分 |
|  | `startLocationText` | `str` | 去首尾空格后长度 `1..120` |
|  | `endLocationText` | `str` | 去首尾空格后长度 `1..120` |
|  | `timeWindow` | `TimeWindow` | 必填；不包含 PlanTask |
| `TripCore` | `schemaVersion` | `Literal["1.0"]` | 业务 Schema 版本 |
|  | `tripId` | `UUID4` | 由应用生成 |
|  | `mode` | `TripMode` | 当前值 `SINGLE` |
|  | `status` | `TripStatus` | 见下方枚举；创建入口仅允许 `DRAFT` |
|  | `cityContext` | `CityContext` | 必填 |
|  | `startDate` | ISO `date` | 必填 |
|  | `endDate` | ISO `date` | 必填 |
|  | `currency` | `Literal["CNY"]` | 必填 |
|  | `totalBudgetCents` | `int` | `>= 0`，单位为人民币分 |
|  | `participants` | `list[Participant]` | 基础集合；公开入口长度必须为 1 |
|  | `days` | `list[TripDayInput]` | 基础集合；公开入口长度必须为 1 |

`TripStatus` 定义为 `DRAFT / CONSTRAINT_CONFIRMED / PLANNING / PLAN_REVIEW / CONFIRMED / EXECUTING / REPLAN_REVIEW / COMPLETED`。PlanVersion 状态使用独立枚举，不复用 `TripStatus`。

对外校验入口 `CreateSingleDayTrip` 约束：

1. `mode == SINGLE`、`status == DRAFT`。
2. `participants` 与 `days` 恰好各一个元素。
3. `startDate == endDate == days[0].date`，且 `days[0].dayIndex == 0`。
4. 时间窗结束时间晚于开始时间；S1 不支持跨午夜。
5. 日预算总和不超过总预算；金额以 CNY 分的非负整数表示。
6. `budgetCapCents` 与 `totalBudgetCents` 暂不建立相等或大小关系，避免在语义确认前形成错误耦合。
7. 偏好值经 Unicode NFKC、去首尾空格和大小写折叠后，同一地点不得同时出现在 `MUST_VISIT` 和 `AVOID_PLACE`。
8. `INTEREST` 必须为软偏好；`MUST_VISIT` 和 `AVOID_PLACE` 必须为硬约束。

`cityCode` 不使用六位正则，也不与城市静态表绑定；高德六位编码只用于北京、上海、成都 Fixture。Provider 适配层负责城市代码和坐标的一致性校验，凭据不进入 Trip。

Plan V1 后续接收 Trip 的不可变 JSON 快照；`PlanDay.tasks[]` 归 PlanVersion，不回写 `TripDayInput`。T003 使用 `participants[i].assistanceProfile` 作为唯一挂载点。

## 校验错误

结构错误统一输出：

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

Pydantic 的 `loc` 元组转换成 `days[0].timeWindow.end` 形式。跨字段规则通过独立 policy 校验器返回同样的错误对象，避免所有错误退化为根路径。

歧义由 T002 产生确认错误：

```json
{
  "code": "TRIP_CONFIRMATION_REQUIRED",
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

`context` 是可选的错误诊断信息，不属于 Trip。涉及相对日期时必须携带 `referenceDate`，从而保证错误用例在任何执行日期都可重复。

## 测试与证据

参数化 Fixture：北京 `110000`、上海 `310000`、成都 `510100`；每份必须严格校验成功，并在 `model_dump_json(by_alias=True)` 后再次校验且保持 `cityCode`、`participants[0]`、`days[0]` 可恢复。

失败用例至少覆盖：缺少 `cityContext.cityCode`、缺少 `participants`、缺少 `days[0].timeWindow.end`、空参与者数组、双参与者、日期不一致、结束时间早于开始时间、日预算超总预算、偏好冲突和未知字段。

完成证据：测试日志、Schema 快照、嵌套缺字段错误示例、三城 Fixture、生产目录 `北京|北京市|110000` 扫描无结果。生产代码不包含北京默认值；北京仅存在于测试 Fixture。
