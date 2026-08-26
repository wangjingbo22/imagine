# S2-T001 多成员 Trip 与 TripUnderstanding 契约设计

- 日期：2026-08-26
- 分支：`czy-S2-T001`
- 创建基线：`origin/main@b88aeee441f1160243acf55521d50e4e1c26d7b9`
- 阶段：实现分析 / 契约冻结，不包含业务代码
- 结论：采用“一个 Trip 业务模型 + 一个非权威理解提案 DTO + 旧单人窄入口”的兼容方案

## 1. 决策摘要

S2-T001 只冻结两个边界：

1. 权威 Trip 从单人兼容扩展为 1—3 人，新增 `GROUP` 模式，并用一个统一模型表达单人和多人；
2. 模型识别结果固定为严格的 `TripUnderstandingProposal` JSON。它只保存成员卡、字段证据、缺失项、歧义和关怀草稿，不产生任何权威业务状态。

推荐实现新增 `CreateDayTrip` 作为 1—3 人统一 DRAFT 入口，同时原样保留 `CreateSingleDayTrip`、`validate_trip_json()` 和旧单人 Schema。模式与人数的唯一合法组合是：

| `mode` | `participants` | 结果 |
|---|---:|---|
| `SINGLE` | 1 | 接受 |
| `SINGLE` | 2—3 | 拒绝 |
| `GROUP` | 1 | 拒绝 |
| `GROUP` | 2—3 | 接受 |
| 任意 | 0 或大于 3 | 拒绝 |

现有规划、PlanVersion、ExecutionEvent、Diff 链路仍保持单人并失败关闭。T001 不得因为基础 Trip 能表达多人，就让尚未适配的下游读取 `participants[0]` 后继续运行。

## 2. 依据与核验范围

本设计交叉核对了以下产品资料：

- `doc/行知旅伴_旅行规划Agent_Scrum项目规划_V2.3.docx`；
- `doc/行知旅伴_V2.3_产品待办列表_含负责人.xlsx`；
- 修订版 `行知旅伴_V2.3_Sprint2待办列表_含负责人 (2).xlsx`；
- 当前工作树内 Trip、Participant、AssistanceProfile、Constraint、TripDraft、planning、PlanVersion、ExecutionEvent、Diff 的实现、Fixture 与相关测试。

资料形成的共同约束是：

- 单人和多人必须复用同一个 `Trip.participants[]`，不得复制一套多人 Trip；
- 多人范围固定为 2—3 人，产品总范围固定为 1—3 人；
- 每位成员拥有独立预算上限、偏好和关怀信息；
- 模型只负责理解、证据和问题草稿；UUID、确认状态、Constraint、HARD 判定、金额计算、Provider 事实、评分、计划和版本状态均由程序负责；
- 邀请链接、成员独立加入/确认、实时协作和跨设备同步不在当前 Sprint 范围。

修订版 Sprint2 表中“运行时尚未接入”的描述已经落后于代码：当前基线的 `app/main.py`、`app/infrastructure/bailian.py` 和相关测试已接入百炼兼容运行时。代码现状优先；T001 不修改或回退该运行时，T004 单独负责其超时、重试、降级和观测。

## 3. 当前实现映射

### 3.1 权威模型

仓库的 Python 包是分层拼接的：根级 `app/__init__.py` 会把 `backend/app` 追加到 `app.__path__`，所以权威 Trip Schema 的真实文件是 `backend/app/schemas/trip.py`；但根级 `app/domain/__init__.py` 没有扩展 `app.domain.__path__`，运行时与测试导入 `app.domain.trip_draft` 时只会命中真实文件 `app/domain/trip_draft.py`。因此 T001 必须分别修改这两个真实位置，禁止按相同前缀臆造 `backend/app/domain/trip_draft.py`。

| 区域 | 当前事实 | T001 影响 |
|---|---|---|
| `TripMode` | 只有 `SINGLE` | 增加 `GROUP` |
| `Trip.participants` | 仅有 `min_length=1`，理论上无上限 | 固定 `1..3`，增加模式/人数不变量 |
| `CreateSingleDayTrip` | `mode=SINGLE`、参与者恰好 1、天数恰好 1 | 作为旧入口保留，不扩宽 |
| `PlanReviewTripSnapshot` | `mode=SINGLE`、参与者恰好 1 | T001 不改；T005 扩展 |
| `Participant` | UUID4、昵称、成员预算、偏好、可选关怀画像 | 继续作为唯一权威成员模型 |
| `AssistanceProfile` | 完整且可编译的权威关怀输入 | 不允许模型直接生成；由后续程序适配 |
| `Constraint` | 程序拥有规则 ID、范围、硬度和值 | T001 不改、不由模型输出 |

基础 `Trip` 当前“最少 1 人但不封顶”，而真正的创建、计划快照和前端类型又全部锁死为 1 人。这不是多人支持，只是基础模型缺少上限。T001 必须同时封顶和提供统一创建 DTO，不能只把旧单人 DTO 的 `max_length` 改为 3。

### 3.2 TripDraft 与模型运行时

当前 `TripDraftParseRequest`、`ParsedTripFields`、`LlmTripDraftFields` 和 `TripDraftParseResult` 都是全局单人字段；`TripDraftService` 最终固定创建昵称为“单人旅客”的一个 Participant。旧 `DraftContractModel` 还没有全局 strict 模式。

当前确认接口会再次执行 parse，从而可能再次调用模型；这是 T002 的“草稿版本一次识别、确认不二次调用”问题，不属于 T001。T001 只增加严格 DTO 与 Schema，不改路由、服务编排或百炼调用。

### 3.3 规划、版本、执行和公平性

| 消费者 | 当前单人假设 | T001 决策 |
|---|---|---|
| `CandidatePlanRequest` | 明确要求 `SINGLE`、恰好 1 人、恰好 1 天 | 保持，收到 GROUP 必须拒绝 |
| 候选请求构建 | 只编译 `participants[0].assistanceProfile` | 保持单人，不做隐式聚合 |
| `PlanReviewTripSnapshot` | 恰好 1 人 | 保持，T005 扩展 |
| `PlanVersionService` | 用快照第一个成员核对关怀约束 | 保持，T005/T003 扩展 |
| Workflow/存储 | 确认入口类型是 `CreateSingleDayTrip`，每个 Trip 保存一个关怀画像 | 保持，T002/T003/T005 接手 |
| ExecutionEvent/Diff | 绑定 Trip/Plan/Task，不含成员协作状态 | 模型本身不改，T005 做多人回归 |
| S2-T007 fairness | 已遍历 `Trip.participants`，但测试借助 `model_copy(update=...)` 绕过重校验构造 2 人 Trip | 作为消费者风险记录；T001 不改其实现或测试，新契约测试自行使用合法 GROUP Fixture |

## 4. 方案比较

### 方案 A：直接放宽 `CreateSingleDayTrip.participants` 到 1—3

优点是文件改动最少。缺点是 `mode=SINGLE` 可以携带 2—3 人，类名、模式和数据互相矛盾；旧调用方可能在没有准备的情况下收到多人数组；规划链会继续静默只取第一个成员。该方案不接受。

### 方案 B：统一 Trip + 新统一入口 + 旧单人窄入口（推荐）

基础 `Trip` 新增 `GROUP` 和人数不变量；新增 `CreateDayTrip` 表达 1—3 人的单日 DRAFT；旧 `CreateSingleDayTrip` 继续只接受单人。`TripUnderstandingProposal` 是边界 DTO，确认后只能由程序转换为同一个 `Participant[]`/`Trip`。

该方案兼顾统一业务模型、旧客户端兼容和下游失败关闭，且能为 T002/T003/T005 提供清楚的接力点。

### 方案 C：新增 `GroupTrip`/`GroupParticipant` 及独立规划链

判别联合可以让类型看起来清楚，但会复制 Trip、状态机、持久化、计划和执行模型，直接违背 V2.3 的“单人/多人同模”要求，也使版本、事件和 Diff 出现双轨。该方案不接受。

## 5. 权威 Trip 契约

### 5.1 类型与不变量

T001 实现后的权威类型关系应为：

```text
Trip
  schemaVersion: "1.0"
  mode: "SINGLE" | "GROUP"
  participants: Participant[1..3]
  invariant:
    mode == "SINGLE" => len(participants) == 1
    mode == "GROUP"  => 2 <= len(participants) <= 3

CreateDayTrip extends Trip
  status: "DRAFT"
  days: exactly 1

CreateSingleDayTrip extends CreateDayTrip (legacy narrow contract)
  mode: "SINGLE"
  participants: exactly 1
```

`Trip.schemaVersion` 继续为 `1.0`。这是对同一模型接受范围的向后兼容扩展；任何新增 GROUP 数据只能通过新统一入口产生，旧入口不会改变其已发布行为。

### 5.2 兼容策略

以下兼容项是强制门禁：

1. 现有三个单人 Trip Fixture 继续逐字节可用；
2. `CreateSingleDayTrip.model_json_schema(...)` 的旧快照保持不变；如果 Pydantic `$defs` 排序造成机械差异，必须证明外部 JSON 结构、const、上下限和 required 集合完全一致，不能借机放宽；
3. `validate_trip_json()` 继续校验 `CreateSingleDayTrip`，不悄悄改成多人入口；
4. 新增命名明确的 `validate_create_day_trip_json()` 校验统一入口；
5. 旧 TripDraft Parse/Confirm 响应仍返回 `CreateSingleDayTrip | null`，直到 T002 以版本化草稿接口替换；
6. 候选规划、计划快照、工作流和执行入口对 GROUP 继续显式报错，不降级为使用第一个成员；
7. 不自动填充缺失成员预算、偏好或关怀值，也不把总预算等分给成员。

前端镜像类型必须同样保持窄入口：`TripMode` 可扩展为 `"SINGLE" | "GROUP"`，新增 1—3 人 `CreateDayTrip`，但 `CreateSingleDayTrip.mode` 和 `CandidatePlanningTrip.mode` 必须覆盖为 literal `"SINGLE"`，不能因为扩展联合类型而让旧 planner 在编译期接受 GROUP。

### 5.3 程序拥有的转换规则

从已确认理解草稿转换为 Trip 时，程序必须：

- 依据最终成员数写入 `SINGLE` 或 `GROUP`；
- 为每个成员分配 UUID4 `participantId`，模型不得提供；
- 将 `interests`、`mustVisit`、`avoidPlaces` 分别映射为 `INTEREST`、`MUST_VISIT`、`AVOID_PLACE`；
- 沿用当前权威默认：普通兴趣 `isHard=false, weight=4`，必去/避开 `isHard=true, weight=5`；模型不得决定硬度和权重；
- 仅在关怀项完成确认和确定性校验后构建 `AssistanceProfile`；
- 仅在 T003 的必填、类型、时间、预算和冲突校验通过后构建 `CreateDayTrip`。

这些规则冻结转换方向，不要求 T001 实现转换服务。

## 6. TripUnderstanding 固定 JSON 契约

### 6.1 定位

`TripUnderstandingProposal` 是模型输出的候选理解，不是 Trip、TripDraft 聚合、Participant、AssistanceProfile 或 Constraint。它没有数据库身份、确认状态或规划权限。

请求和提案均使用 camelCase、UTF-8 JSON、`schemaVersion="1.0"`。每一层对象都必须 `additionalProperties=false`，并通过 Pydantic strict JSON 校验；不得进行字符串到数字、字符串到布尔、浮点到整数或未知枚举的隐式转换。

### 6.2 请求 DTO

```text
TripUnderstandingRequest
  schemaVersion: literal "1.0"                         required
  referenceDate: string, format date                  required
  rawConversation: string, length 0..8000             required
  explicitFields: TripUnderstandingExplicitFields     required

TripUnderstandingExplicitFields
  cityName: string[1..80] | null                      required
  travelDate: string(date) | null                     required
  startTime: string(^HH:mm$) | null                   required
  endTime: string(^HH:mm$) | null                     required
  startLocationText: string[1..120] | null            required
  endLocationText: string[1..120] | null              required
  budgetCents: integer >= 0 | null                    required
  participants: ExplicitParticipantHint[0..3]         required

ExplicitParticipantHint
  memberKey: string(^member-[1-3]$)                   required
  nickname: string[1..40] | null                      required
  budgetCapCents: integer >= 0 | null                 required
  interests: string[1..120][0..20]                    required
  mustVisit: string[1..120][0..20]                    required
  avoidPlaces: string[1..120][0..20]                  required
  careText: string[1..1000] | null                    required
```

T001 只冻结 DTO；当前 `TripDraftParseRequest` 通过适配器仍可形成该请求，但 T001 不修改实际调用链。`rawConversation` 允许空字符串，是为了支持完全由结构化表单提供的输入。

### 6.3 提案 DTO

```text
TripUnderstandingProposal
  schemaVersion: literal "1.0"                        required
  trip: TripUnderstandingTrip                         required
  participants: ParticipantUnderstanding[1..3]        required
  fieldEvidence: FieldEvidence[0..100]                 required
  missingFields: MissingField[0..50]                  required
  ambiguities: Ambiguity[0..50]                       required
  confirmationQuestions: ConfirmationQuestion[0..50] required

TripUnderstandingTrip
  cityName: string[1..80] | null                      required
  travelDate: string(date) | null                     required
  startTime: string(^([01]\d|2[0-3]):[0-5]\d$) | null required
  endTime: string(^([01]\d|2[0-3]):[0-5]\d$) | null required
  startLocationText: string[1..120] | null            required
  endLocationText: string[1..120] | null              required
  budgetCents: integer >= 0 | null                    required

ParticipantUnderstanding
  memberKey: string(^member-[1-3]$)                   required
  nickname: string[1..40] | null                      required
  budgetCapCents: integer >= 0 | null                 required
  interests: string[1..120][0..20]                    required
  mustVisit: string[1..120][0..20]                    required
  avoidPlaces: string[1..120][0..20]                  required
  careDraft: CareDraft | null                         required

CareDraft
  assistanceTypeHint: AssistanceType | null           required
  childAge: integer[0..17] | null                     required
  walkLimits: CareWalkLimits                          required
  maxTransfers: integer >= 0 | null                   required
  restIntervalMinutes: integer >= 1 | null            required
  napWindow: CareNapWindow | null                     required
  avoidStairs: boolean | null                         required

CareWalkLimits
  maxContinuousMeters: integer >= 1 | null            required
  maxDailyMeters: integer >= 1 | null                 required

CareNapWindow
  start: string(^([01]\d|2[0-3]):[0-5]\d$) | null  required
  end: string(^([01]\d|2[0-3]):[0-5]\d$) | null    required

AssistanceType
  "ORDINARY" | "PARENT_CHILD" | "LOW_STAMINA" |
  "MOBILITY_ASSISTANCE_BETA"
```

关怀字段保持可空，是因为它们还是草稿。`null` 代表模型没有证据，不能被预设值替代；即使 `assistanceTypeHint` 非空，程序仍需在确认后用既有 factory 产生完整 `AssistanceProfile`。

### 6.4 证据、缺失、歧义与问题

```text
FieldEvidence
  fieldPath: CanonicalFieldPath                       required
  memberKey: string(^member-[1-3]$) | null           required
  sourceType: "USER_TEXT" | "EXPLICIT_FIELD"        required
  sourceText: string[1..240]                          required

MissingField
  fieldPath: CanonicalFieldPath                       required
  memberKey: string(^member-[1-3]$) | null           required
  code: literal "MISSING"                            required
  questionKey: QuestionKey                            required

Ambiguity
  fieldPath: CanonicalFieldPath                       required
  memberKey: string(^member-[1-3]$) | null           required
  code: literal "AMBIGUOUS"                          required
  reason: string[1..240]                              required
  candidates: string[2..5], each length 1..120       required
  questionKey: QuestionKey                            required

ConfirmationQuestion
  fieldPath: CanonicalFieldPath                       required
  memberKey: string(^member-[1-3]$) | null           required
  questionKey: QuestionKey                            required
  prompt: string[1..160]                              required
  choices: string[0..5], each length 1..120          required
```

`QuestionKey` 固定为：

```text
CITY_NAME | TRAVEL_DATE | START_TIME | END_TIME |
START_LOCATION | END_LOCATION | TRIP_BUDGET | PARTY_SIZE |
MEMBER_NICKNAME | MEMBER_BUDGET | MEMBER_INTERESTS |
MEMBER_MUST_VISIT | MEMBER_AVOID_PLACES |
MEMBER_CARE_PRESET | MEMBER_CARE_DETAILS
```

`CanonicalFieldPath` 只允许以下形态，不能是任意 JSONPath：

```text
trip.cityName
trip.travelDate
trip.startTime
trip.endTime
trip.startLocationText
trip.endLocationText
trip.budgetCents
participants
participants[i].nickname
participants[i].budgetCapCents
participants[i].interests[j]
participants[i].mustVisit[j]
participants[i].avoidPlaces[j]
participants[i].careDraft.assistanceTypeHint
participants[i].careDraft.childAge
participants[i].careDraft.walkLimits.maxContinuousMeters
participants[i].careDraft.walkLimits.maxDailyMeters
participants[i].careDraft.maxTransfers
participants[i].careDraft.restIntervalMinutes
participants[i].careDraft.napWindow.start
participants[i].careDraft.napWindow.end
participants[i].careDraft.avoidStairs
```

其中 `i` 必须落在实际成员数组索引，`j` 必须落在实际对应列表索引。Trip 字段或 `participants` 路径的 `memberKey` 必须为 `null`；成员路径的 `memberKey` 必须与该索引成员的 `memberKey` 相同。

### 6.5 跨字段严格规则

JSON Schema 负责结构约束，Pydantic model validator 负责以下语义约束：

1. `memberKey` 必须按数组顺序连续为 `member-1`、`member-2`、`member-3`，不得重复或跳号；它只是提案内临时键，不是身份；
2. 每个非空、由模型填写的标量和每个非空列表项必须恰有至少一条证据；`schemaVersion`、`memberKey` 不需要证据；
3. `USER_TEXT.sourceText` 必须是输入 `rawConversation` 的原文片段；`EXPLICIT_FIELD.sourceText` 必须等于结构化输入的规范显示值；
4. 同一 `fieldPath` 不能同时出现在 `missingFields` 和 `ambiguities`；两组内均不得重复；
5. 每个 missing/ambiguity 必须恰好对应一个相同 `fieldPath + memberKey + questionKey` 的问题，问题不得无来源；
6. `choices`：歧义问题必须等于其 candidates；缺失问题允许为空或给出固定 UI 选项；
7. 同一成员同一偏好列表按 NFKC、去首尾空白、Unicode casefold 后不得重复；不同列表之间的冲突不在 T001 判定，由 T003 产生可追溯冲突；
8. 当用户只表达单人意图或没有多人证据时，输出一个 `member-1`；当明确是多人但人数未知时，仍输出一个组织者临时卡，并对 `participants` 输出 `PARTY_SIZE` 缺失项，T002 新 revision 根据回答扩卡；
9. 模型不得根据成员数输出 `mode`，程序在确认后确定 `SINGLE/GROUP`，从而不存在 mode/人数矛盾；
10. 日期先后、起止时间、总预算与成员预算关系、关怀组合、必去/避开冲突都是 T003 的确定性业务校验，不由 T001 的理解 Schema 擅自裁决。

此外，`careDraft` 非空时至少要有一个关怀标量非空并带证据；如果没有任何关怀证据，整个字段必须为 `null`，不能输出“全字段为 null”的空壳对象。

### 6.6 明确禁止的输出

提案任意层出现以下字段或同义结构都因 `additionalProperties=false` 被拒绝：

- `tripId`、`participantId`、邀请 token、用户账号或协作会话 ID；
- `status`、`confirmed`、`canPlan`、成员确认状态；
- `Constraint`、`ruleId`、`hardness`、冲突裁决或 relaxation；
- Provider、FactRef、来源可信状态、实时价格/路线事实；
- 候选计划、任务、评分、公平性排名、PlanVersion、Diff、ExecutionEvent；
- 模型、供应商、重试、超时或降级等运行时元数据。

## 7. Fixture 与 Schema 证据

实现阶段必须提供以下正向 Fixture：

| Fixture | 场景 | 必证内容 |
|---|---|---|
| `one_participant.json` | 旧单人完整表达 | 单卡、旧字段能无损适配、证据齐全、空缺失/歧义数组 |
| `two_participants.json` | 两人预算/兴趣/关怀不同 | 两张成员卡、成员键/路径匹配、至少一个成员级问题 |
| `three_participants.json` | 三人且一人低体力、一人字段缺失 | 三卡上限、关怀草稿、成员级 missing/ambiguity 不串人 |

同时提供合法的权威 `CreateDayTrip` 1/2/3 人 Fixture：单人继续复用现有 Fixture；新增 GROUP 两人、三人 Fixture。2/3 人 Fixture 必须具有真实不同的 Participant UUID、预算、偏好和关怀信息，不能只复制同一成员。

负向测试至少覆盖：

- 0 人、4 人、`SINGLE+2人`、`GROUP+1人`；
- 任意层 extra 字段；
- `"1000"` 代替整数、`1` 代替布尔、浮点金额；
- 非 UUID4 权威 participantId、非法/跳号/重复 memberKey；
- 证据路径越界、成员键与索引不匹配、无证据非空值；
- 同一路径同时 missing 和 ambiguous；
- 问题缺失、多余或 candidates 不一致；
- 日期/时间格式不合法；
- 提案注入 `participantId`、Constraint、Provider、plan、score 或确认状态。

发布物必须包含 `CreateDayTrip` 和 `TripUnderstandingProposal` 的 validation-mode JSON Schema 快照；所有对象的 `additionalProperties` 必须为 `false`，所有可空字段仍必须出现在 `required` 中。

## 8. 后续实现文件白名单

本次分析提交只允许修改本文档。后续 T001 业务实现只允许修改/新增以下文件；超出白名单必须重新评审：

### 8.1 生产契约

- `backend/app/schemas/trip.py`（既有，权威 Trip Schema 实现）
- `app/domain/trip_draft.py`（既有，`app.domain.trip_draft` 的真实导入目标）
- `frontend/src/domain/trip.ts`（既有；仅 DTO/联合类型，不改页面和行为）
- `backend/schemas/trip.schema.json`（既有旧单人发布物，兼容基准，原则上不改）
- `backend/schemas/create-day-trip.schema.json`（新增统一入口发布物）
- `backend/schemas/trip-understanding.schema.json`（新增理解提案发布物）

`app/domain/trip_draft.py` 中的新理解类型必须使用 strict `ContractModel` 语义；不得为了复用而把旧 `DraftContractModel` 全局改为 strict，避免改变旧解析兼容性。`backend/app/domain/` 当前不存在且不在 `app.domain` 的扩展导入路径中，不得创建同名影子模块。

### 8.2 测试、快照与 Fixture

- `backend/tests/test_trip_schema.py`（既有）
- `backend/tests/test_trip_understanding_schema.py`（新增）
- `backend/tests/snapshots/create_single_day_trip.schema.json`（既有兼容基准，原则上不改）
- `backend/tests/snapshots/create_day_trip.schema.json`（新增）
- `backend/tests/snapshots/trip_understanding.schema.json`（新增）
- `backend/tests/fixtures/trips/group_two_participants.json`（新增）
- `backend/tests/fixtures/trips/group_three_participants.json`（新增）
- `backend/tests/fixtures/trip_understanding/one_participant.json`（新增）
- `backend/tests/fixtures/trip_understanding/two_participants.json`（新增）
- `backend/tests/fixtures/trip_understanding/three_participants.json`（新增）

### 8.3 明确禁止修改

- `app/infrastructure/bailian.py`、`app/main.py`、`app/core/config.py` 及其他 Provider/runtime 文件（均为既有文件）；
- `app/application/trip_draft_service.py`、`app/api/trip_draft_routes.py`（均为既有文件，归 T002/T004）；
- Constraint 编译器、冲突状态机、成员确认接口（T003）；
- candidate planning、PlanReview、PlanVersion、ExecutionEvent、Diff、workflow/store/replan（T005）；
- Provider/FactRef/推荐/公平裁决实现（T006/T007/T008/T009）；
- 邀请 token、成员独立加入/确认、协作会话、实时同步；
- 前端页面、成员卡交互和 WorkspacePage（T010）。

如严格契约无法在该白名单内落地，应停止并拆分任务，不得“顺手”修改下游。

## 9. 测试与用户验收

### 9.1 T001 范围测试

实现时采用以下强门禁：

1. 新增测试先失败，再实现；
2. T001 定向 Schema/Fixture 测试必须 0 fail、0 error、0 xfail；
3. 旧 `test_trip_schema.py`、关怀 Schema、TripDraft LLM 集成和公平性测试全部通过；
4. 旧单人 Fixture 和发布 Schema 兼容断言通过；
5. 前端 `npm.cmd test` 不少于当前 31 项且 0 fail；
6. 前端 `npm.cmd run build` 通过，防止 `TripMode` 联合类型遗漏；
7. 全量后端即使仍命中已知基线失败，也不得出现任何新增失败、错误、跳过或收集差异。

### 9.2 用户验收脚本

产品验收按以下可观察结果执行：

1. 输入“我一个人，北京一天，预算 500 元”，得到 1 张成员卡，旧单人确认路径可继续使用；
2. 输入“两个人，我预算 500，她预算 300；我喜欢博物馆，她少走路”，得到 2 张独立成员卡，预算、兴趣、关怀证据不串人；
3. 输入“三个人，带 6 岁孩子和老人，老人每次最多走 500 米”，得到 3 张卡，孩子/老人关怀草稿分别落在正确 memberKey；
4. 输入“我们几个人去上海”，不得猜 2 或 3 人，输出 `participants + PARTY_SIZE` 问题；
5. 输入同一成员“想去外滩但又不要去外滩”，T001 保留两类候选和证据，不伪造 HARD 冲突；T003 后续确定性识别；
6. 在提案中注入额外 `participantId`、字符串预算或第 4 人，严格 Schema 拒绝；
7. 把合法 GROUP Trip 送入当前单人 planner，必须显式拒绝，不能生成只考虑第一个人的计划。

## 10. 基线与不掩盖门禁

### 10.1 2026-08-26 实跑结果

在指定 worktree、基线提交和仓库 `.venv` 上实跑：

```text
frontend/npm.cmd test
31 passed, 0 failed

repository root/python -m pytest -q
181 passed, 2 failed

backend directory/python -m pytest -q
181 passed, 2 failed

focused contract/runtime/fairness suite
57 passed, 0 failed
```

委派输入记录的“4 个 ModuleNotFoundError”在本工作树没有复现。实际两个失败均来自：

```text
backend/tests/test_day2_traceability.py::
  test_day2_tasks_map_to_real_code_tests_fixtures_and_integrations
backend/tests/test_day2_traceability.py::
  test_cross_task_integrations_are_machine_traceable
```

两者都断言已不存在的根级 `tests/test_trip_draft_parser.py` 必须是文件。根 `tests` 包缺失仍是共同根因，但当前表现是 2 个 assertion failure，而不是 4 个 import/collection error。T001 不修复 traceability 或恢复根 tests。

### 10.2 基线指纹规则

CI/人工验收不得把全量后端标记为绿色。允许的临时基线必须同时满足：

- 退出码仍为非零；
- 恰好只有上述两个测试 ID 失败；
- 每个失败都仍指向缺失 `tests/test_trip_draft_parser.py`；
- 通过数不得低于 181 加上本任务新增测试数；
- 0 个 collection error、0 个 ModuleNotFoundError、0 个其他 failure；
- T001 定向测试单独执行必须全绿。

若其他环境仍复现“4 个 ModuleNotFoundError”，应单独保存其四个 node ID/模块名作为该环境的基线指纹；不能用宽泛的 `pytest || true`、`continue-on-error`、`xfail` 或忽略整个文件来吞掉新回归。基线变化必须先解释，再更新指纹。

全量测试生成的 `backend/data/*.sqlite3` 是运行产物，验收后必须清理，不能进入提交。

## 11. 风险与降级

| 风险 | 触发方式 | 降级/控制 |
|---|---|---|
| 旧消费者穷举 `TripMode` | 收到 `GROUP` 后分支遗漏 | GROUP 只经新入口产生；前端 build 门禁；旧入口不返回 GROUP |
| 下游只读第一个成员 | 基础 Trip 开放后直接送 planner | planner/快照继续 exact-one，显式失败关闭到 T005 |
| 理解 DTO 演变成第二套业务模型 | 在提案加入 UUID、Constraint、状态 | strict extra forbid；只允许程序转换为权威模型 |
| 模型无证据补默认值 | 空预算/关怀被猜测 | 非空值必须有证据；无证据保持 null/missing |
| 成员重排导致证据串人 | revision 中数组顺序改变 | `memberKey + fieldPath` 双重核对；T002 固定 revision 内顺序 |
| JSON Schema 无法表达全部规则 | 只做结构校验漏过错配 | Pydantic model validator + 负向测试双门禁 |
| 旧 Schema 被无意扩宽 | 直接修改旧创建 DTO | 保留旧窄入口与快照；新增独立统一入口 |
| 模型/Provider 不可用 | 运行时超时或无配置 | T001 不碰运行时；旧规则解析/显式表单继续可用，T004 负责降级 |
| 任务边界膨胀 | 为跑通多人计划顺改状态机 | 白名单强制；GROUP 到当前 planner 必须失败 |

## 12. T002/T003 冻结的接力契约

### 12.1 T002：草稿版本与一次识别

T002 必须原样持久化本设计的 `TripUnderstandingProposal`，不能另造相似字段。建议的程序拥有 envelope 为：

```text
TripDraftRevision
  draftId: UUID4                    server-owned
  revision: integer >= 1           server-owned
  tripId: UUID4                    server-owned
  understanding: TripUnderstandingProposal
  memberBindings:
    - memberKey: member-[1-3]
      participantId: UUID4         server-owned
  sourceDigest: string             server-owned
  createdAt: datetime              server-owned
```

冻结规则：

- 首次识别只调用模型一次并保存 exact proposal；确认读取同一 `draftId + revision`，不得二次调用模型；
- 同一 revision 的 memberKey、顺序、证据和问题不可变；
- 新 revision 中保留的 memberKey 继续绑定原 participantId，新增 key 分配新 UUID，删除的 key 不复用；
- 用户修改任一关键字段创建新 revision；不得原地改写已确认版本；
- 邀请、独立成员确认和协作会话不进入该 envelope。

### 12.2 T003：确定性校验与确认

T003 只消费 `TripDraftRevision`，并由程序生成确认项：

```text
ConfirmationItem
  itemId: server-owned stable id
  fieldPath: CanonicalFieldPath
  participantId: UUID4 | null
  ruleId: string | null
  code: MISSING | AMBIGUOUS | CONFLICT | INVALID
  reason: string
  candidates: string[]
  relaxations: string[]
```

冻结规则：

- proposal 的 missing/ambiguity 是输入线索，最终确认项、冲突、ruleId 和 relaxation 必须由确定性程序生成；
- 成员级项必须由 memberBindings 解析到 participantId；Trip 级项为 null；
- 未解决项大于 0 时禁止生成 `CreateDayTrip`、调用 Provider 或进入 planner；
- 解决后由程序执行第 5.3 节转换，构建唯一权威 `CreateDayTrip`；
- T003 不改变本设计的 JSON 字段名、memberKey 规则或 canonical field path。

### 12.3 T005 及更后任务

T005 才能扩展 `PlanReviewTripSnapshot`、`CandidatePlanRequest`、Workflow、PlanVersion、ExecutionEvent 和 Diff 的 1/2/3 人兼容，并必须证明 1/2/3 人复用同一状态机。T006 负责 Provider/FactRef，T007 负责公平裁决，T008/T009 负责候选网关和推荐。它们均不得反向修改 T001 的成员身份、证据路径或 Trip 模式/人数不变量；如确需变更，必须提升 `TripUnderstandingProposal.schemaVersion` 并提供迁移。

## 13. 完成定义

S2-T001 的后续实现只有在以下条件同时满足时才算完成：

- 一个 Trip 业务模型合法表达 1/2/3 人；
- 旧单人入口和 Fixture 保持兼容；
- TripUnderstanding 严格 Schema、正负 Fixture 与快照齐全；
- 成员卡、证据、缺失、歧义和关怀草稿可按成员追踪；
- 模型无法写入程序拥有的身份、确认、约束、Provider、计划或版本字段；
- 未适配的规划/执行链对 GROUP 失败关闭；
- 白名单外无业务文件改动；
- 定向测试全绿，全量基线只有已指纹化的既有失败且未增加。
