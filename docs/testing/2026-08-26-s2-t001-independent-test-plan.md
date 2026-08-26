# S2-T001 多成员 Trip 与 TripUnderstanding 独立测试计划

> 文档日期：2026-08-26
>
> 创建基线：`origin/main@b88aeee441f1160243acf55521d50e4e1c26d7b9`
>
> 冻结设计：`976b261f9f154b55ddc86d17f552bd690b4dad5b`
>
> 唯一设计依据：`docs/superpowers/specs/2026-08-26-s2-t001-multi-participant-contract-design.md`
>
> 目标分支/工作树：`czy-S2-T001` / `C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.worktrees\czy-S2-T001`
>
> 当前活动：只制定计划；不执行测试、不修改业务代码、不产生 `PASS`/`FAIL` 结论。

## 1. 目标、独立性与结论术语

本计划独立验证 S2-T001 是否只扩展契约边界：一个权威 `Trip` 合法表达 1—3 人，旧 `CreateSingleDayTrip` 保持窄入口，新 `CreateDayTrip` 提供统一入口，`TripUnderstandingProposal` 严格保存成员卡、证据、缺失、歧义、问题和关怀草稿；尚未适配的规划、PlanReview、工作流和执行链对 GROUP 失败关闭。

QA 不参与业务实现。收到代码窗口明确 commit SHA 后才执行本计划；失败时只登记并回传可复现缺陷，不修改业务代码。修复后重验失败项、相邻边界和全量回归，直至 `QA_PASS` 或形成有证据的 `QA_BLOCKED`。

| 术语 | 含义 |
|---|---|
| `NOT_RUN` | 仅有计划，尚未对代码交付 SHA 执行。 |
| `PASS` | 指定用例在指定 SHA 上实际执行，期望全部成立且证据完整。 |
| `FAIL` | 已执行且至少一项强制期望不成立，已登记可复现缺陷。 |
| `BLOCKED` | 缺少目标 SHA、环境不可用、设计/实现接口不可达或基线无法归因，不能形成有效结论。 |
| `QA_PASS` | 本文全部强门禁通过，只有已精确指纹化的两个既有后端失败，无新增失败/错误/跳过。 |

## 2. 可测性复审与范围边界

修订设计提交 `976b261f9f154b55ddc86d17f552bd690b4dad5b` 已解决此前 P0：权威 Trip Schema 位于 `backend/app/schemas/trip.py`，TripUnderstanding DTO 的真实导入文件位于 `app/domain/trip_draft.py`，并明确禁止创建不可达的 `backend/app/domain/trip_draft.py`。当前静态复审未发现新的 P0 可测性矛盾。

路径核对结果：15 个抽查既有入口均存在；10 个新增目标中 7 个直接父目录存在，另外 3 个 Understanding Fixture 共享的直接父目录 `backend/tests/fixtures/trip_understanding/` 当前尚未建立，但其祖先目录存在。代码窗口添加三个新 Fixture 时会自然建立该目录；这是非阻断仓库结构风险，不授权创建影子 Python 包。

T001 是契约任务，不改模型运行时、TripDraft 路由、页面或成员卡交互。因此第 10 节“用户可观察验收”采用确定性的请求/提案 Fixture 与公开 DTO/validator 边界，不把真实 LLM 文案稳定性或 UI 展示误记为 T001 能力。旧单人 Parse/Confirm 仅做兼容回归；2/3 人不要求现有路由真正创建 Trip。

下列内容明确不属于 T001 通过条件：邀请与成员独立确认、协作会话、草稿 revision、确定性冲突裁决、多人规划、公平排序、Provider 事实、多人执行、前端页面和 `WorkspacePage.tsx`。发现它们被顺带修改时先判白名单失败，不以“测试通过”豁免范围膨胀。

## 3. 执行前门禁与交付 SHA 核对

### 3.1 必须收到的交付信息

代码窗口必须明确提供一个可解析的 commit SHA，并确认工作树干净。QA 在指定 linked worktree 根目录执行以下只读核对：

```powershell
git rev-parse --show-toplevel
git branch --show-current
git rev-parse HEAD
git status --short
git merge-base --is-ancestor 976b261f9f154b55ddc86d17f552bd690b4dad5b HEAD
git show --stat --oneline --decorate --no-renames HEAD
```

期望：仓库根、分支和 HEAD 与交付声明一致；`git status --short` 无输出；设计提交是 HEAD 祖先。任一不成立则 `BLOCKED`，不得在错误 SHA 上补跑结果。

### 3.2 文件白名单

以修订设计提交为比较基准：

```powershell
git diff --name-status --no-renames 976b261f9f154b55ddc86d17f552bd690b4dad5b..HEAD
```

除本 QA 文档外，业务实现只允许下列路径：

```text
backend/app/schemas/trip.py
app/domain/trip_draft.py
frontend/src/domain/trip.ts
backend/schemas/trip.schema.json
backend/schemas/create-day-trip.schema.json
backend/schemas/trip-understanding.schema.json
backend/tests/test_trip_schema.py
backend/tests/test_trip_understanding_schema.py
backend/tests/snapshots/create_single_day_trip.schema.json
backend/tests/snapshots/create_day_trip.schema.json
backend/tests/snapshots/trip_understanding.schema.json
backend/tests/fixtures/trips/group_two_participants.json
backend/tests/fixtures/trips/group_three_participants.json
backend/tests/fixtures/trip_understanding/one_participant.json
backend/tests/fixtures/trip_understanding/two_participants.json
backend/tests/fixtures/trip_understanding/three_participants.json
docs/testing/2026-08-26-s2-t001-independent-test-plan.md
```

`backend/app/domain/trip_draft.py` 必须不存在。旧发布物 `backend/schemas/trip.schema.json`、旧快照和三个旧单人 Fixture 原则上不得变更。任何白名单外业务文件改动为 P0；先回传代码窗口，不开始功能验收。

### 3.3 旧资产逐字节兼容

以下命令必须无差异：

```powershell
git diff --exit-code 976b261f9f154b55ddc86d17f552bd690b4dad5b..HEAD -- `
  backend/schemas/trip.schema.json `
  backend/tests/snapshots/create_single_day_trip.schema.json `
  backend/tests/fixtures/trips/beijing.json `
  backend/tests/fixtures/trips/shanghai.json `
  backend/tests/fixtures/trips/chengdu.json
```

若仅 Pydantic `$defs` 排序导致快照机械变化，也不能直接放行：必须同时证明外部 JSON 字段、`const`、上下限、`additionalProperties` 和各对象 `required` 集合完全一致，并由分析/代码窗口解释后重新评审。

## 4. 测试数据与判定原则

### 4.1 权威 Trip 数据

- 1 人正向：逐字节复用 `beijing.json`、`shanghai.json`、`chengdu.json`，经旧入口和新入口分别验证。
- 2 人正向：`group_two_participants.json`，`mode=GROUP`，两个真实不同的 UUID4、昵称、预算、偏好和关怀资料。
- 3 人正向：`group_three_participants.json`，`mode=GROUP`，三个真实不同的 UUID4、预算、偏好和关怀资料。
- 所有 `CreateDayTrip` 数据固定 `status=DRAFT`、恰好一天；`schemaVersion` 仍为 `1.0`。
- 负向变体从合法 Fixture 深拷贝后单点变异，避免多个错误互相遮蔽；不得用 `model_copy(update=...)` 绕过重校验。

### 4.2 TripUnderstanding 数据

- 正向：`one_participant.json`、`two_participants.json`、`three_participants.json`。
- 每个提案均配套构造 `TripUnderstandingRequest` 上下文，以验证 `USER_TEXT.sourceText` 是 `rawConversation` 原文片段、`EXPLICIT_FIELD.sourceText` 等于结构化字段规范显示值。
- strict 断言必须走 JSON 验证路径；Python 直接构造与 JSON 严格解析的日期/枚举行为不得混为一谈。
- JSON Schema 只证明结构；memberKey 连续性、路径索引、证据闭合、missing/ambiguity/question 闭环、NFKC 去重和空壳 `careDraft` 必须由 Pydantic 语义验证器另行证明。

### 4.3 错误判定

每个负向用例至少断言：拒绝发生、错误路径稳定指向被变异字段、错误码/错误类型可区分、没有生成权威 Trip/计划/事件或其他副作用。仅断言“抛出任意异常”不足以通过。

## 5. 权威 Trip 与创建入口矩阵

### 5.1 模式/人数完整矩阵

| ID | 入口 | mode | 人数 | 期望 |
|---|---|---:|---:|---|
| TRIP-01 | `Trip` / `CreateDayTrip` | SINGLE | 0 | 拒绝：participants 太短。 |
| TRIP-02 | `Trip` / `CreateDayTrip` | SINGLE | 1 | 接受；新旧入口语义一致。 |
| TRIP-03 | `Trip` / `CreateDayTrip` | SINGLE | 2 | 拒绝：模式/人数不变量。 |
| TRIP-04 | `Trip` / `CreateDayTrip` | SINGLE | 3 | 拒绝：模式/人数不变量。 |
| TRIP-05 | `Trip` / `CreateDayTrip` | SINGLE | 4 | 拒绝：人数上限；不能只报模式不匹配而漏掉封顶。 |
| TRIP-06 | `Trip` / `CreateDayTrip` | GROUP | 0 | 拒绝：participants 太短。 |
| TRIP-07 | `Trip` / `CreateDayTrip` | GROUP | 1 | 拒绝：GROUP 至少两人。 |
| TRIP-08 | `Trip` / `CreateDayTrip` | GROUP | 2 | 接受并完整往返序列化。 |
| TRIP-09 | `Trip` / `CreateDayTrip` | GROUP | 3 | 接受并完整往返序列化。 |
| TRIP-10 | `Trip` / `CreateDayTrip` | GROUP | 4 | 拒绝：participants 最多三人。 |
| TRIP-11 | `Trip` / `CreateDayTrip` | 未知枚举 | 1—3 | strict 拒绝，不回退 SINGLE。 |

对 TRIP-02、08、09 额外断言成员顺序、UUID、成员预算、偏好和关怀对象无串位；序列化后再次解析等于原对象。

### 5.2 旧 `CreateSingleDayTrip` 兼容

| ID | 场景 | 期望 |
|---|---|---|
| LEGACY-01 | 三个旧 Fixture 调用 `validate_trip_json()` | 全部返回 `CreateSingleDayTrip`，字段和 UUID 无损往返。 |
| LEGACY-02 | 旧入口传 `SINGLE+2人` | 拒绝，仍为 exact-one。 |
| LEGACY-03 | 旧入口传任意 `GROUP` | `mode` literal 拒绝。 |
| LEGACY-04 | `validate_trip_json()` 传合法 GROUP Fixture | 拒绝，证明未被偷换成统一入口。 |
| LEGACY-05 | 旧 validation-mode Schema | 与设计 SHA 快照逐字节一致；外部结构未放宽。 |
| LEGACY-06 | 旧 TripDraft Parse/Confirm 回归 | 响应仍为 `CreateSingleDayTrip | null`，既有成功/待确认行为不变。 |
| LEGACY-07 | 旧 `DraftContractModel` 类型兼容 | 未被全局切换 strict；既有 LLM/表单适配测试继续通过。 |

### 5.3 新 `CreateDayTrip` 入口

| ID | 场景 | 期望 |
|---|---|---|
| CREATE-01 | `validate_create_day_trip_json()` + 旧单人 Fixture | 接受为 SINGLE DRAFT，一天。 |
| CREATE-02 | 新 validator + 两人 Fixture | 接受为 GROUP DRAFT，一天。 |
| CREATE-03 | 新 validator + 三人 Fixture | 接受为 GROUP DRAFT，一天。 |
| CREATE-04 | status 非 DRAFT | 拒绝。 |
| CREATE-05 | 0 天或 2 天 | 拒绝，`days` 必须恰好一个。 |
| CREATE-06 | 非 UUID4 participantId、重复 UUID 或复制同一成员 | 非 UUID4 必须拒绝；Fixture 身份/内容重复由测试明确失败。 |
| CREATE-07 | 字符串金额、浮点金额、负数金额、`1` 代替布尔 | strict/范围校验拒绝，不隐式转换。 |
| CREATE-08 | 新发布 Schema 与新快照 | JSON 等价且 validation mode 正确；所有对象 extra-forbid。 |

## 6. TripUnderstanding 严格契约矩阵

### 6.1 请求 DTO

| ID | 场景 | 期望 |
|---|---|---|
| REQ-01 | 完整自然语言请求 | camelCase、`schemaVersion=1.0`、合法日期，接受。 |
| REQ-02 | `rawConversation=""` 且 explicitFields 完整 | 接受，支持纯结构化输入。 |
| REQ-03 | rawConversation 长度 8000/8001 | 8000 接受，8001 拒绝。 |
| REQ-04 | explicit participants 0/1/2/3/4 | 0—3 接受，4 拒绝。 |
| REQ-05 | 非法 referenceDate、travelDate、HH:mm | 拒绝并定位字段。 |
| REQ-06 | `"1000"`/浮点代替整数、未知 memberKey | strict 拒绝。 |
| REQ-07 | request、explicitFields、participant 任意层 extra | 均拒绝。 |
| REQ-08 | 可空字段被省略 | 拒绝；可空不等于非 required。 |

### 6.2 提案结构、strict 与 extra-forbid

| ID | 场景 | 期望 |
|---|---|---|
| PROP-01 | 1/2/3 人正向 Fixture | 全部解析并严格往返；数组数分别为 1/2/3。 |
| PROP-02 | participants 0 或 4 | 拒绝。 |
| PROP-03 | 任一 required 可空字段被删除 | 拒绝 missing；显式 `null` 可按契约接受。 |
| PROP-04 | proposal/trip/participant/careDraft/walkLimits/napWindow/evidence/missing/ambiguity/question 任一层 extra | 各层分别拒绝；发布 Schema 对应对象均 `additionalProperties=false`。 |
| PROP-05 | 字符串整数、浮点整数、`1` 代替布尔 | strict 拒绝。 |
| PROP-06 | 非法日期、`24:00`、带秒、带时区或非法 HH:mm | 拒绝。 |
| PROP-07 | 未知 AssistanceType/sourceType/code/questionKey | 拒绝未知枚举。 |
| PROP-08 | 注入 `mode`、`tripId`、`participantId`、`status`、`confirmed`、`canPlan` | extra-forbid 拒绝。 |
| PROP-09 | 注入 Constraint/ruleId/hardness/relaxation | extra-forbid 拒绝。 |
| PROP-10 | 注入 Provider/FactRef/price/route/model/retry/timeout | extra-forbid 拒绝。 |
| PROP-11 | 注入 plan/task/score/fairness/PlanVersion/Diff/ExecutionEvent | extra-forbid 拒绝。 |
| PROP-12 | validation-mode 发布 Schema 与快照 | JSON 等价；nullable 字段仍在所属对象 `required` 中。 |

### 6.3 memberKey、CanonicalFieldPath 与证据

| ID | 场景 | 期望 |
|---|---|---|
| SEM-01 | memberKey 按 1/2/3 人连续排列 | 接受 `member-1..N`。 |
| SEM-02 | 重复、跳号、倒序、超范围 memberKey | 拒绝。 |
| SEM-03 | trip 路径或 `participants` 路径携带 memberKey | 拒绝，必须为 null。 |
| SEM-04 | 成员路径 memberKey 为 null、错成员或错索引 | 拒绝。 |
| SEM-05 | `participants[i]` 越界 | 拒绝。 |
| SEM-06 | interests/mustVisit/avoidPlaces 的 `[j]` 越界或指向错误列表 | 拒绝。 |
| SEM-07 | 任意未列入白名单的 JSONPath、通配符、负索引 | 拒绝。 |
| SEM-08 | 每个非空 trip/participant/care 标量和每个非空列表项有证据 | 接受；`schemaVersion`、memberKey 不要求证据。 |
| SEM-09 | 删除任一非空值的全部证据 | 拒绝，不能以默认值补齐。 |
| SEM-10 | USER_TEXT sourceText 是 rawConversation 原文片段/伪造片段 | 原文接受，伪造拒绝。 |
| SEM-11 | EXPLICIT_FIELD sourceText 等于/不等于规范显示值 | 相等接受，不等拒绝。 |
| SEM-12 | 同一偏好列表存在 NFKC、trim、casefold 后重复项 | 拒绝。 |
| SEM-13 | 同值分处 mustVisit 与 avoidPlaces | T001 保留两类值及各自证据，不产生 HARD/冲突裁决。 |

SEM-10/11 是代码窗口必须特别说明的可测接口：JSON Schema 无法独立知道请求原文。交付必须存在能把 `TripUnderstandingRequest` 上下文绑定到提案语义验证的确定性调用方式，并由测试直接调用；若实现只能孤立解析 proposal、无法校验 sourceText 来源，则为 P0 契约缺失。

### 6.4 missing、ambiguity 与 confirmationQuestions 闭环

| ID | 场景 | 期望 |
|---|---|---|
| LOOP-01 | 每个 missing 恰有一个同三元组问题 | 接受。 |
| LOOP-02 | 每个 ambiguity 恰有一个同三元组问题，choices 等于 candidates | 接受。 |
| LOOP-03 | 同一路径同时 missing 与 ambiguity | 拒绝。 |
| LOOP-04 | missing 或 ambiguity 组内重复 | 拒绝。 |
| LOOP-05 | 缺少问题、问题重复、问题三元组不匹配 | 拒绝。 |
| LOOP-06 | 无 missing/ambiguity 来源的多余问题 | 拒绝。 |
| LOOP-07 | ambiguity candidates 数量 1/2/5/6 | 1、6 拒绝；2、5 接受。 |
| LOOP-08 | ambiguity choices 与 candidates 顺序或内容不同 | 拒绝。 |
| LOOP-09 | missing question choices 为空或固定 UI 选项 | 两者均可接受。 |
| LOOP-10 | 明确多人但人数未知 | 仅一个组织者 `member-1`，对 `participants + null + PARTY_SIZE` 形成 missing/question 闭环，不猜人数。 |

### 6.5 关怀草稿

| ID | 场景 | 期望 |
|---|---|---|
| CARE-01 | 无关怀证据，careDraft=null | 接受。 |
| CARE-02 | 全字段 null 的 careDraft 空壳 | 拒绝。 |
| CARE-03 | 任一关怀标量非空且证据齐全 | 接受。 |
| CARE-04 | assistanceTypeHint 有值但其余字段未知 | 作为草稿接受；不得生成权威 AssistanceProfile。 |
| CARE-05 | childAge -1/0/17/18 | 0、17 接受；-1、18 拒绝。 |
| CARE-06 | walk limits 0/1，maxTransfers -1/0，restInterval 0/1 | 严格按边界拒绝/接受。 |
| CARE-07 | avoidStairs 为 `1`、`"true"`、true/null | 仅 JSON boolean 或 null 接受。 |
| CARE-08 | napWindow 非法 HH:mm 或空对象缺 required 字段 | 拒绝。 |
| CARE-09 | 关怀字段非空但无对应证据或证据串到另一成员 | 拒绝。 |

## 7. Fixture、Schema 与注入专项

| ID | 资产/攻击 | 通过条件 |
|---|---|---|
| FIX-01 | 旧三城市 Fixture | 文件字节未变，旧 validator 全绿。 |
| FIX-02 | GROUP 2/3 人 Fixture | 合法、成员真实不同、无 UUID/预算/偏好/关怀复制。 |
| FIX-03 | Understanding 1 人 Fixture | 单卡、证据齐、missing/ambiguity/question 为空。 |
| FIX-04 | Understanding 2 人 Fixture | 两卡独立，至少一个成员级问题，证据/路径不串人。 |
| FIX-05 | Understanding 3 人 Fixture | 三卡上限、低体力关怀、一人成员级缺失/歧义，闭环不串人。 |
| INJ-01 | `participantId`/tripId/账号/邀请 token/会话 ID | 严格拒绝。 |
| INJ-02 | Constraint/ruleId/hardness/confirmed/canPlan | 严格拒绝。 |
| INJ-03 | Provider/FactRef/价格/路线/可信状态 | 严格拒绝。 |
| INJ-04 | plan/task/score/fairness/version/diff/event | 严格拒绝。 |
| INJ-05 | prototype-like key、未知嵌套对象、数组项 extra | 作为普通 extra 字段拒绝，不崩溃。 |
| TYPE-01 | `"1000"`、1、1.0、未知枚举、非 UUID4 | 各自按整数/布尔/金额/枚举/身份边界拒绝。 |

Schema 递归审计不能只检查根节点。测试必须遍历根对象和 `$defs` 中所有 object schema，断言 `additionalProperties` 为 `false`；同时对每个 nullable property 验证其字段名仍在该对象 `required` 集合中。

## 8. 当前单人下游的 GROUP 失败关闭

使用合法、完整的 GROUP `Trip`，只在各公开边界所需状态上构造合法输入；不得用无效字段让前置错误遮蔽 GROUP 门禁。

| ID | 边界 | 操作 | 期望 |
|---|---|---|---|
| CLOSE-01 | `CandidatePlanRequest` | GROUP、合法规划状态、一天、完整 facts/constraints | 显式拒绝 `T011 only supports SINGLE trips` 或等价稳定错误；planner 未运行。 |
| CLOSE-02 | 候选 planner | 将 GROUP 请求送入生成入口 | 无 CandidatePlan、无 ProposedPlanVersion、副作用为零。 |
| CLOSE-03 | `PlanReviewTripSnapshot` | GROUP、PLAN_REVIEW、2/3 人 | literal/exact-one 显式拒绝。 |
| CLOSE-04 | 旧 TripDraft/确认入口 | 提交 GROUP payload | 在 `CreateSingleDayTrip` 边界拒绝，不保存为已确认 Trip。 |
| CLOSE-05 | workflow/store | 尝试经现有公开确认路径进入 GROUP | HTTP/应用边界拒绝，数据库不新增或覆盖 Trip。 |
| CLOSE-06 | PlanVersion/执行入口 | 使用未获合法单人计划的 GROUP tripId 发起计划确认/事件 | 明确不存在合法计划/状态，不能产生 PlanVersion、ExecutionEvent 或 Diff。 |
| CLOSE-07 | 公平性回归 | 运行既有 S2-T007 套件 | 既有合法行为全绿；新契约测试不再借 `model_copy(update=...)` 构造非法多人 Trip。 |

失败关闭的核心判定不是“最终报了任意错误”，而是 GROUP 在第一个单人边界被拒绝，且没有读取 `participants[0]` 后继续生成只服务首人的结果。

## 9. 前端纯 DTO 与构建回归

T001 前端只允许修改 `frontend/src/domain/trip.ts`。静态审查必须确认：

- `TripMode` 精确为 `'SINGLE' | 'GROUP'`；
- 新 `CreateDayTrip` 可表达 1/2/3 人；
- `CreateSingleDayTrip.mode` 显式覆盖为 literal `'SINGLE'`，不能继承宽联合；
- `CandidatePlanningTrip.mode` 显式保持 literal `'SINGLE'`；
- 旧 `TripDraftParseResult.trip` 仍为 `CreateSingleDayTrip | null`；
- 未修改页面、API 行为、成员卡或 `WorkspacePage.tsx`。

执行：

```powershell
Push-Location frontend
npm.cmd test
npm.cmd run build
Pop-Location
```

通过条件：test exit 0，实际通过数不少于基线 31 且 0 fail；build exit 0。仅构建成功仍不足以替代上述 literal 静态核对，因为现有调用点可能没有实例化 GROUP 负向类型。

## 10. 用户可观察的契约验收场景

这些场景在 DTO/Fixture 边界执行，不调用真实模型，不要求 T001 范围外 UI。每个场景保留输入 request、输出 proposal/错误、validator 结果和关键字段摘录。

| ID | 用户输入/操作 | 可观察期望 |
|---|---|---|
| UAT-01 | “我一个人，北京一天，预算 500 元” | 1 张 `member-1` 卡；北京、一天、50000 分有原文证据；旧单人 Parse/Confirm 兼容路径既有测试继续通过。 |
| UAT-02 | “两个人，我预算 500，她预算 300；我喜欢博物馆，她少走路” | 2 张连续成员卡；50000/30000、博物馆和少走路分别绑定正确 memberKey/path，关怀证据不串人。 |
| UAT-03 | “三个人，带 6 岁孩子和老人，老人每次最多走 500 米” | 3 张卡；childAge=6 与老人 maxContinuousMeters=500 落在各自成员关怀草稿并有各自证据。 |
| UAT-04 | “我们几个人去上海” | 不猜 2/3 人；仅组织者 `member-1`，产生 `participants + null + PARTY_SIZE` missing/question 闭环。 |
| UAT-05 | 同一成员“想去外滩但又不要去外滩” | mustVisit 和 avoidPlaces 均保留且证据可追溯；提案没有 HARD、Constraint 或冲突裁决字段。 |
| UAT-06 | 注入 participantId、字符串预算或第 4 人 | strict 拒绝并定位字段；无权威 Trip 副作用。 |
| UAT-07 | 合法 GROUP Trip 送入当前单人 planner | 显式失败；无只考虑第一个人的 CandidatePlan/PlanVersion。 |

UAT-02/03 的“得到成员卡”指提案 DTO 中可观察的独立 `participants[]`，不是声称现有页面已支持成员卡。若代码交付以 UI 截图代替 DTO 证据，不能通过本门禁。

## 11. 自动化执行顺序与强门禁

所有命令从指定 worktree 执行，使用仓库 `.venv`，不得用 `|| true`、`continue-on-error`、`xfail` 或忽略文件吞掉失败。

### G01：T001 定向契约

```powershell
& ..\..\.venv\Scripts\python.exe -m pytest -q `
  backend/tests/test_trip_schema.py `
  backend/tests/test_trip_understanding_schema.py
```

期望：0 fail、0 error、0 xfail、0 skip；1/2/3 正向 Fixture、模式人数矩阵、strict/extra、语义闭环、快照与发布物全部被收集。

### G02：旧单人、关怀、运行时与公平性契约回归

```powershell
& ..\..\.venv\Scripts\python.exe -m pytest -q `
  backend/tests/test_assistance_profile_schema.py `
  backend/tests/test_trip_draft_llm_integration.py `
  backend/tests/test_s2_t007_fairness.py
```

期望：全部通过；旧 DraftContractModel/LLM 适配、关怀 Schema 和公平性无回归。

### G03：planner、PlanReview、workflow 与执行相关回归

```powershell
& ..\..\.venv\Scripts\python.exe -m pytest -q `
  backend/tests/test_candidate_planner.py `
  backend/tests/test_planning_http_boundaries.py `
  backend/tests/test_planning_replanning_integration.py `
  backend/tests/test_s1_t017_event_replan.py `
  backend/tests/test_minimum_disruption_replanning.py `
  backend/tests/test_day2_duplicate_plan_registration.py `
  backend/tests/test_s1_t022_summary_paths.py
```

期望：全部通过，并有 T001 定向用例直接证明 CLOSE-01～06。若既有专项全绿但没有 GROUP 负向断言，仍不能把失败关闭标为通过。

### G04：前端纯 DTO

执行第 9 节两条命令。期望不少于 31 passed、0 failed，且 build exit 0。

### G05：仓库根全量后端基线指纹

```powershell
& ..\..\.venv\Scripts\python.exe -m pytest -q
```

允许的唯一非绿色结果必须同时满足：

1. 退出码非零；
2. 恰好只有下列两个 node ID 失败：

```text
backend/tests/test_day2_traceability.py::test_day2_tasks_map_to_real_code_tests_fixtures_and_integrations
backend/tests/test_day2_traceability.py::test_cross_task_integrations_are_machine_traceable
```

3. 两个失败仍都指向缺失根级 `tests/test_trip_draft_parser.py` 的 assertion；
4. 通过数不少于 `181 + N`，其中 `N` 是相对设计提交新增收集的测试 case 数；
5. 0 collection error、0 ModuleNotFoundError、0 其他 failure、0 新增 skip/xfail；
6. G01～G04 已独立全绿。

不得把 G05 标记为全绿；报告应写“`181+N passed, 2 baseline failures`”并列出两个 node ID。

### G06：backend 目录复跑与环境一致性

```powershell
Push-Location backend
& ..\..\..\.venv\Scripts\python.exe -m pytest -q
Pop-Location
```

期望与 G05 同一精确指纹。若某环境复现委派历史中的 4 个 `ModuleNotFoundError`，必须记录四个 node ID、模块名、cwd、Python 路径和完整输出，并将结果标为 `BLOCKED` 等待基线解释；不能把它们自动并入允许列表。

### G07：清洁度与运行产物

验收前后分别保存：

```powershell
git status --short
git diff --check
git diff --name-status --no-renames 976b261f9f154b55ddc86d17f552bd690b4dad5b..HEAD
```

`backend/data/*.sqlite3` 若由本轮测试新生成，只能在核对绝对路径、确认其为本轮未跟踪产物后逐个清理；不得删除验收前已存在或已跟踪的数据文件。最终工作树不得出现 SQLite、缓存、日志、快照漂移或其他非交付改动。

## 12. 基线统计与“不新增失败”算法

设计提交的实际基线是 `181 passed, 2 failed`，不是“4 个 ModuleNotFoundError”。基线总收集为 183 个 case。执行时从 pytest collected 结果和 Git diff 统计 T001 新增参数化 case 数 `N`，并保存 node ID 列表；全量通过数下限为 `181 + N`。

判定顺序：

1. 先比较失败 node ID 集合，必须精确等于两个已知 traceability 用例；
2. 再比较失败根因文本，必须仍是缺失 `tests/test_trip_draft_parser.py`；
3. 再核对 collection/module error、skip、xfail 均未增加；
4. 最后核对通过数下限和 T001 定向全绿。

因此“总失败仍为 2”但 node ID 或根因变化时仍是回归；“通过数上升”也不能掩盖新增 collection error、skip 或第三个 failure。

## 13. 缺陷级别、回传格式与复验

### 13.1 严重级别

| 级别 | 定义 | 示例 |
|---|---|---|
| P0 阻断 | 核心契约不可实现/不可测试、旧单人契约破坏、数据越权写入、白名单越界或 GROUP 静默进入单人计划。 | 旧 Schema 被扩宽；提案可注入 participantId；planner 只取首成员继续运行。 |
| P1 严重 | 主矩阵或严格语义失败，1/2/3 人任一合法模式不可用，0/4 人或类型欺骗被接受，证据/问题串人。 | GROUP+2 被拒；第 4 人被接受；memberKey/path 错配未拒绝。 |
| P2 一般 | 非核心边界、错误定位、快照/文档或单个负向覆盖不完整，但无越权和静默错误。 | 错误 path 不稳定；Schema required 审计漏一个 nullable 字段。 |
| P3 轻微 | 不影响契约判定的消息、命名或证据可读性问题。 | 错误文案不清晰但 code/path 正确。 |

### 13.2 回传格式

| 必填字段 | 填写规则 |
|---|---|
| 缺陷 ID | 使用 `S2-T001-QA-` 加三位递增序号，例如 `S2-T001-QA-001`。 |
| 标题 | 写明失败边界和可观察现象，不写泛化的“测试失败”。 |
| 目标 SHA | 填写发生问题的完整 40 位 commit SHA。 |
| 严重级别 | 只能取 P0、P1、P2、P3，并引用第 13.1 节理由。 |
| 测试 ID/门禁 | 填写本文用例和门禁，例如 `SEM-04 / G01`。 |
| 环境 | Windows 版本、Python/Node 版本、cwd 和关键命令入口。 |
| 前置数据 | 写明正向 Fixture、唯一变异字段及变异值。 |
| 复现命令 | 给出从指定 worktree 可直接执行的完整命令。 |
| 复现步骤 | 按实际操作顺序列出，不合并会影响结果的动作。 |
| 期望 | 引用冻结设计中的精确约束。 |
| 实际 | 原样记录错误、返回对象、状态变化或副作用。 |
| 证据 | 附 stdout/stderr、错误 JSON、Git diff、必要的数据库前后计数和路径。 |
| 基线归因 | 明确标为“既有基线”或“S2-T001 回归”，并说明 node ID/根因依据。 |
| 影响范围 | 从旧入口、新入口、理解提案、下游、前端中列出实际受影响区域。 |

QA 将缺陷回传代码窗口，不提交业务修复。收到修复 SHA 后依次执行：失败用例 → 同类边界矩阵 → 受影响定向套件 → G01～G07 全门禁。修复若改变冻结字段、白名单或基线指纹，先退回分析窗口，不直接放行。

## 14. 需求追溯矩阵

| 委派要求 | 覆盖用例/门禁 | 核心证据 |
|---|---|---|
| SINGLE=1、GROUP=2..3，0/4 拒绝 | TRIP-01～11、G01 | 参数化 pytest、错误 path/code。 |
| 旧入口/旧 Schema 兼容 | LEGACY-01～07、G01/G02、3.3 | 旧 Fixture、旧快照字节 diff、回归输出。 |
| `CreateDayTrip` 新入口 | CREATE-01～08、G01 | 新 Fixture、validator、Schema/快照。 |
| strict/extra、证据、路径、闭环、关怀 | REQ、PROP、SEM、LOOP、CARE 全矩阵 | 定向 pytest、请求/提案 JSON、递归 Schema 审计。 |
| 1/2/3 正向与注入/欺骗/越界负向 | FIX、INJ、TYPE、TRIP/PROP | Fixture diff、参数化负向输出。 |
| planner/PlanReview/执行失败关闭 | CLOSE-01～07、G03、UAT-07 | 明确错误、无计划/事件/DB 副作用。 |
| 前端纯 DTO build/test | 第 9 节、G04 | 类型静态审查、npm test/build 输出。 |
| 181/2 精确基线与不新增失败 | G05/G06、第 12 节 | 完整 pytest 输出、node ID/根因/统计。 |
| 用户可观察验收与缺陷回传 | UAT-01～07、第 13 节 | 请求/提案/错误证据、缺陷单、复验记录。 |

## 15. 最终放行条件与工程风险

只有同时满足以下条件才签发 `QA_PASS`：

- 目标 SHA、祖先关系、分支和工作树已核实；
- 文件白名单通过，旧单人 Schema/快照/Fixture 逐字节兼容；
- G01～G04 全绿且无 skip/xfail；
- UAT-01～07 全部满足契约层可观察结果；
- G05/G06 只保留两个精确指纹化既有失败，无新增 failure/error/collection/module/skip；
- G07 清洁，无测试 SQLite 或其他运行产物进入提交；
- 所有导致强制用例失败的 P0/P1/P2/P3 缺陷均已由代码窗口修复并完成相关回归；不影响任何强门禁的 P3 观察项已明确记录且不伪装为已修复。

代码窗口需提前注意以下工程风险：

1. evidence 的 `sourceText` 来源校验需要请求上下文，不能仅靠 proposal JSON Schema；必须提供确定性、可直接测试的绑定入口。
2. Pydantic validation-mode Schema 必须递归 extra-forbid，nullable 字段仍 required；只看根节点会漏检。
3. 旧 `DraftContractModel` 不能为复用而全局 strict，否则旧 LLM/表单兼容会回归。
4. TypeScript 宽化 `TripMode` 后，`CreateSingleDayTrip` 和 `CandidatePlanningTrip` 必须各自覆盖 `'SINGLE'`；现有测试未必能自动发现类型泄漏。
5. 下游失败关闭必须发生在读取 `participants[0]` 之前；仅依赖 Python 类型注解不构成运行时拒绝。
6. `backend/tests/fixtures/trip_understanding/` 当前尚不存在；只建立该 Fixture 目录，不得建立 `backend/app/domain/` 影子包。
7. 公平性旧测试使用过 `model_copy(update=...)` 绕过重校验；T001 新测试必须从合法 GROUP JSON 走完整验证链。

最终独立验收报告应提交到 `docs/testing/2026-08-26-s2-t001-independent-acceptance-report.md`，记录目标 SHA、实际统计、两条基线失败指纹、用例结论、缺陷与证据路径。QA 不合并 main、不推送、不部署。
