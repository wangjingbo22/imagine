# S2-T004 百炼失败降级与固定问题设计

**日期：** 2026-08-27
**基线：** `a43ad37a5c8b97d2b90507fa9966998bfee038b9`
**范围：** S2-T004 实现分析；仅覆盖 T002 对话理解调用的超时、有限重试、严格输出、固定问题降级和观测。
**用户故事：** 作为用户，我希望模型失败时还能用固定问题补全需求，以便不被卡住。

## 1. 结论

采用“**T002 revision 前置幂等 + T004 严格网关 + 固定六问降级**”的最小方案：

1. T002 验证并保存原始输入、六个固定问题答案和 `answerRevision`，在调用 T004 前完成同 revision 的幂等命中判断；
2. T004 复用现有 `BailianTripDraftExtractor` 的同一个 `httpx.AsyncClient`，新增严格 `TripUnderstandingRequest -> raw JSON` 调用，不新建第二个百炼客户端；
3. T004 在 `app/application/llm_gateway.py` 中复用候选选择网关的控制范式：每次传输尝试硬超时默认 **10.0 秒**，最多 **2 次传输尝试**，没有退避或第三次调用；
4. 只有临时传输错误可以再尝试一次。非 JSON、fenced JSON、Schema 错误、证据/语义错误或其他模型内容错误立即降级，不发修复 prompt；
5. 成功只返回严格且非权威的 `TripUnderstandingProposal`；失败返回程序拥有的固定问题降级 DTO，原始输入与六问答案原样保留，`canPlan=false`；
6. 失败不得创建或推进 canonical `TripDraftRevision`，不得写正式 Trip、Constraint、PlanVersion、workflow 或任何确认状态，也不得调用 Provider；T002 只可写其已有的 answer submission/idempotency outcome，以保证保留输入和重放不再调用模型。

旧 `/api/v1/trips/drafts/parse` 与 `/api/v1/trips/drafts/confirm` 仅保留兼容。本任务不把旧单人解析链改造成 T002，也不以旧链的 `DEGRADED_RULES -> canPlan=true` 作为 S2 行为。

## 2. 现状证据矩阵

定向回归使用仓库现有虚拟环境执行：

```powershell
C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q backend/tests/test_bailian_trip_extractor.py backend/tests/test_trip_draft_llm_integration.py backend/tests/test_trip_understanding_schema.py backend/tests/test_s2_t003_revision_port.py backend/tests/test_s2_t003_collaboration_contract.py backend/tests/test_s2_t008_candidate_selection_gateway.py
```

结果：`89 passed in 2.25s`。

| 关注点 | current main 证据 | 已完成 | S2-T004 缺口/决策 |
|---|---|---|---|
| 百炼配置 | `app/core/config.py` 的 `bailian_request_timeout_seconds=45.0`，允许 `(0, 60]`；`.env.example` 同为 `45` | API Key 使用 `SecretStr`；base URL/model 已配置 | 改为默认 `10.0`，范围 `[8, 12]`，作为 trip understanding 每次传输尝试的硬上限 |
| 现有客户端 | `app/infrastructure/bailian.py::BailianTripDraftExtractor` 已持有唯一 `httpx.AsyncClient`、Authorization header 和关闭生命周期 | 无需新增供应商 SDK 或重复 client | 在同一类增加严格 understanding 原始响应方法；旧 `extract()` 保留兼容 |
| 现有错误处理 | `BailianTripDraftExtractor.extract()` 无受控重试；`HTTPError`、响应 envelope、JSON 和 Pydantic 错误大多折叠为 `BAILIAN_INVALID_RESPONSE` | 超时、鉴权、不可用已有粗粒度错误码 | 新 understanding 路径分离 retryable transport 与 non-retryable content；网关最多一次传输重试 |
| fenced JSON | `app/infrastructure/bailian.py::_strip_json_fence()` 主动接受 fenced JSON；`test_bailian_extractor_accepts_json_code_fence` 固化旧行为 | 旧 S1 兼容有测试 | 新严格路径不调用 fence stripping；fenced JSON 归 `LLM_INVALID_JSON`，一次调用后降级；不回改旧测试语义 |
| 严格理解契约 | `app/domain/trip_draft.py` 已有 strict/extra-forbid 的 `TripUnderstandingRequest`、`TripUnderstandingProposal`、canonical field paths、证据绑定和问题闭环 | T001 已完成 1/2/3 人 strict Schema 与语义校验 | T004 必须直接调用 `model_validate_json(raw, strict=True)` 和 `validate_trip_understanding()`，不另造类似 proposal |
| 固定问题 | `app/domain/collaboration.py` 已冻结 `QUESTION_IDS=(trip, party, endpoints_budget, preferences, assistance, confirm)`；`ConversationSubmission` 保留原始描述、六问顺序和 transcript | 固定六问、长度与顺序验证已完成 | 失败直接复用 `ConversationSubmission` 生成 review items；不得让模型动态追问或改写答案 |
| 旧 TripDraft 编排 | `TripDraftParserService.parse()` 在模型失败后用规则字段；字段齐全时仍可 `can_plan=True` 并构造 `CreateSingleDayTrip(status=DRAFT)` | S1 单人兼容链可运行 | 这不是 S2-T004 降级语义；新对话失败必须 `understanding=null`、`canPlan=false`、canonical revision 零推进 |
| 旧 confirm | `app/api/trip_draft_routes.py::confirm_trip_draft()` 每次先 `service.parse(payload)`，随后可能 `workflow.confirm_trip()` | 旧接口已上线 | T002 的 confirm/replay 不得调用旧接口；T004 不大改旧路由，只用测试证明 S2 route 未串入旧链 |
| T002 接缝 | `app/api/collaboration_routes.py::create_organizer()` 仍返回 `TRIP_DRAFT_REVISION_UNAVAILABLE`；`app/main.py` 默认注入 `UnavailableTripDraftRevisionPort` | 接缝和失败关闭存在 | T002 先实现 answer revision/store/route；T004 不接管其存储，只注入 understanding gateway |
| T003 接缝 | `app/application/collaboration_ports.py::TripDraftRevisionPort` 消费 `TripUnderstandingProposal`；`CollaborationService.submit_member()` 要求连续 canonical revision | T003 的确认、冲突、readiness 已隔离于 T002 | 只有 T004 成功 proposal 才允许 T002 创建下一 canonical revision；失败不得调用 T003 advance/confirm |
| 可复用网关范式 | `app/application/llm_gateway.py::StrictCandidateSelectionGateway` 最多两次传输尝试；格式/Schema/语义错误直接 fallback | 调用计数、失败码、无 Key 的零调用、有限重试已有测试范式 | 在同一模块增加 trip understanding 专用 Protocol/Result/Gateway；不复用候选业务 DTO |
| 可复用传输分类 | `app/infrastructure/openai_compatible_llm.py` 使用默认 10 秒、范围 8–12；timeout/transport/429/5xx 可重试，401/403 与其他 4xx 不重试 | 项目已有稳定策略和测试 | T004 原样采用同一政策，并增加硬 wall-clock timeout；不增加指数退避 |
| 运行时/安全 | `app/main.py` 从 `SecretStr` 取 Key，只在有 Key 时装配 client；health 不回显 Key | 生命周期关闭和 Key 基础保护已完成 | 日志仅记录固定事件名、错误码、调用数和 model；禁止记录 prompt、原始输入、答案、模型原文、Authorization 或 provider body |

## 3. 方案比较

### 方案 A：直接修补旧 `/api/v1` parse/confirm

优点是表面文件最少。缺点是旧模型 DTO 只支持单人字段，confirm 会二次 parse，规则降级仍可能构造 Trip，无法自然表达 T002 的 `answerRevision` 和多人 `TripUnderstandingProposal`。这会把 T004 扩成 T001/T002 迁移工程，拒绝采用。

### 方案 B：T002 前置幂等，T004 提供严格网关与固定六问降级（推荐）

优点是直接复用 T001 strict contract、现有 Bailian client 和 LLM gateway 模式；T002 继续拥有 answer revision 与 canonical revision；T003 继续只消费成功 proposal。失败结果天然零权威写入，范围最小且可独立测试。采用此方案。

### 方案 C：把重试、fallback 和幂等全部塞进 `BailianTripDraftExtractor`

优点是上层调用简单。缺点是基础设施层不知道 `answerRevision`，无法保证同 revision 重放；同时会混合 HTTP、Schema、固定问题和持久化语义，未来其他模型调用也难以复用。拒绝采用。

## 4. 架构与调用时机

```text
T002 conversation service
  1. validate six fixed answers and answerRevision
  2. atomically claim/read idempotency outcome for this answer revision
  3a. completed -> return stored outcome, zero LLM call
  3b. same revision + different digest -> 409, zero LLM call
  3c. new owner -> build one TripUnderstandingRequest
          |
          v
StrictTripUnderstandingGateway (application)
  - at most two transport attempts
  - strict JSON + Schema + context/semantic validation exactly once
          |
          v
BailianTripDraftExtractor.propose_trip_understanding (infrastructure)
  - reuse existing AsyncClient / credentials / base URL / model
  - 10.0 s hard timeout per attempt
          |
          +--> MODEL_PROPOSAL -> T002 may append canonical TripDraftRevision
          |
          +--> FIXED_QUESTIONS -> T002 persists only answer/idempotency outcome;
                                 canonical TripDraftRevision unchanged
```

### 4.1 唯一调用时机

每个新的 `answerRevision` 只有在以下条件全部满足后才允许调用网关：

- `ConversationSubmission` 已通过固定六问顺序、数量、非空和长度验证；
- T002 已生成唯一 `TripUnderstandingRequest`，其中 `rawConversation` 是初始描述与六问 transcript，`explicitFields` 由程序拥有；
- T002 已在原子幂等检查中取得该 revision 的调用所有权；
- 同 revision 没有已完成的成功或降级 outcome。

确认、查询、T003 冲突解析、重复 HTTP 请求和同 revision 重放均不得调用模型。用户编辑任一原始输入或答案时，T002 创建新 `answerRevision`；只有新 revision 才可开始新的最多两次传输尝试。

并发重放时，T002 的唯一键必须先于网络调用生效。已完成记录返回已存 outcome；正在处理的同 revision 返回稳定的 `ANSWER_REVISION_IN_PROGRESS`，不得启动第二个调用。该并发控制属于 T002，不在 T004 内另建缓存或表。

### 4.2 超时预算

- 配置名继续复用 `BAILIAN_REQUEST_TIMEOUT_SECONDS` / `Settings.bailian_request_timeout_seconds`；
- 默认值：`10.0` 秒；允许值：`8.0 <= value <= 12.0`；
- 每个 transport attempt 同时使用 `httpx` timeout 和 `asyncio.timeout(10.0)` 硬 wall-clock 截止；
- 第一次临时传输失败后立即执行唯一一次重试，不 sleep、不 backoff；
- 最坏模型等待预算为 `2 * 10.0 = 20.0` 秒，外加本地序列化/校验时间；不存在第三次调用或内容修复调用。

这里的“单次调用”指一次 transport attempt，而不是整个 HTTP endpoint。这样与 current main 的候选选择链一致，也能精确观测 `callCount=0|1|2`。

## 5. 一次重试与错误分类

| 来源 | 对外失败码 | 是否允许唯一一次重试 | 最终行为 |
|---|---|---:|---|
| 未配置 API Key | `LLM_NOT_CONFIGURED` | 否，`callCount=0` | 固定六问降级 |
| `asyncio` 硬截止或 `httpx.TimeoutException` | `LLM_TIMEOUT` | 是 | 第二次仍失败则降级 |
| `httpx.TransportError`（连接、读写、协议等） | `LLM_UNAVAILABLE` | 是 | 第二次仍失败则降级 |
| HTTP 429 或 500–599 | `LLM_UNAVAILABLE` | 是 | 第二次仍失败则降级 |
| HTTP 401/403 | `LLM_AUTH_FAILED` | 否 | 立即降级 |
| 其他 HTTP 4xx（含 400/404/408/409/422） | `LLM_UNAVAILABLE` | 否 | 立即降级 |
| provider envelope 缺字段、`content` 非字符串 | `LLM_INVALID_RESPONSE` | 否 | 立即降级 |
| content 不是一个裸 JSON 对象，包括 Markdown fence | `LLM_INVALID_JSON` | 否 | 立即降级 |
| strict Pydantic/extra-forbid/类型/字段闭环失败 | `LLM_SCHEMA_INVALID` | 否 | 立即降级 |
| 证据不在 request、显式字段不匹配、其他上下文内容错误 | `LLM_CONTENT_INVALID` | 否 | 立即降级 |
| 未分类异常 | `LLM_UNAVAILABLE` | 否 | 记录异常类名后立即降级 |

若第一次是临时传输错误、第二次返回非 JSON/Schema/内容错误，则 `callCount=2` 并立即降级；不得出现第三次“修复”调用。HTTP 408 按项目现有策略归其他 4xx，不自行扩大临时错误集合。

## 6. 成功与降级 DTO

### 6.1 T004 网关结果

网关返回程序拥有的判别联合，不抛出 provider 细节到 route：

```text
TripUnderstandingGatewayResult
  decision: MODEL_PROPOSAL | FIXED_QUESTIONS
  proposal: TripUnderstandingProposal | null
  failureCode: null
    | LLM_NOT_CONFIGURED | LLM_TIMEOUT | LLM_AUTH_FAILED | LLM_UNAVAILABLE
    | LLM_INVALID_RESPONSE | LLM_INVALID_JSON | LLM_SCHEMA_INVALID
    | LLM_CONTENT_INVALID
  callCount: 0 | 1 | 2
  model: string | null

invariant:
  MODEL_PROPOSAL -> proposal != null, failureCode == null, callCount in 1..2
  FIXED_QUESTIONS -> proposal == null, failureCode != null, callCount in 0..2
```

成功 proposal 必须是 current main 的 `TripUnderstandingProposal`，并已通过 `validate_trip_understanding(request, proposal)`。它仍是非权威理解提案，不含 UUID、状态、Constraint、Provider、计划或版本字段。

### 6.2 T002 对话响应中的失败投影

T002 在其既有 answer revision response 中嵌入以下形状；T004 不另造平行 revision envelope：

```json
{
  "answerRevision": 3,
  "naturalLanguageRequest": "原始输入原样保留",
  "answers": [
    {"questionId": "trip", "answer": "原答案"},
    {"questionId": "party", "answer": "原答案"},
    {"questionId": "endpoints_budget", "answer": "原答案"},
    {"questionId": "preferences", "answer": "原答案"},
    {"questionId": "assistance", "answer": "原答案"},
    {"questionId": "confirm", "answer": "原答案"}
  ],
  "recognition": {
    "source": "FIXED_QUESTIONS",
    "model": "qwen3.7-plus",
    "failureCode": "LLM_TIMEOUT",
    "callCount": 2
  },
  "understanding": null,
  "fallback": {
    "mode": "FIXED_QUESTIONS",
    "items": [
      {
        "questionId": "trip",
        "answer": "原答案",
        "code": "REVIEW_REQUIRED",
        "message": "模型未能生成可校验提案，请核对或修改此答案"
      }
    ]
  },
  "canPlan": false
}
```

`fallback.items` 必须按 `QUESTION_IDS` 生成恰好六项，每项原样复制对应答案；示例只展开第一项。该 DTO 是“保留并继续编辑”的确认资料，不是 T003 `CollaborationIssue`，因此没有 `ruleId`、`relaxations` 或确认状态，也不能被误当作 canonical field 已解析。

无 Key 时 `recognition.model=null`、`failureCode=LLM_NOT_CONFIGURED`、`callCount=0`。已调用但失败时 model 名可以返回；API Key、provider body 和模型原文永不返回。

## 7. 状态与写入边界

| 结果 | T002 answer submission/idempotency outcome | canonical `TripDraftRevision` | Trip/Constraint/PlanVersion/workflow | T003 确认状态 | Provider |
|---|---:|---:|---:|---:|---:|
| strict proposal 成功 | 保存 | 可由 T002 创建下一连续 revision | 不写 | 不写 | 不调用 |
| 固定六问降级 | 保存，供保留答案和幂等重放 | **不创建、不推进** | **不写** | **不写** | **不调用** |
| 同 revision 重放 | 只读已存 outcome | 不推进 | 不写 | 不写 | 不调用 |
| 同 revision 不同 payload | 返回 409 | 不推进 | 不写 | 不写 | 不调用 |

`canPlan` 在 T002/T004 边界始终为 `false`。即使 strict proposal 没有 missing/ambiguity，也必须经过 T003 程序校验、成员确认和 readiness guard；T004 不拥有确认或规划状态。

## 8. 日志、凭据与 prompt 安全

- 继续只通过 `Settings.bailian_api_key: SecretStr` 和进程环境 Secret 取 Key；Key 不进入 DTO、异常消息、health、测试快照或 Git；
- `BailianTripDraftExtractor` 不记录 Authorization header、request JSON、system prompt、raw conversation、六问答案、模型原文或 provider response body；
- 网关日志只允许固定事件名、`failureCode`、`callCount`、model 和异常类名；不得记录 `str(ValidationError)` 或 `.errors()`，因为其中可能包含模型输入；
- 对外只返回上述稳定失败码，不透传 HTTP body、URL query、SDK message 或 stack trace；
- 用户自己的原始输入与答案仅在已授权的 T002 response/store 中原样保留，不视为日志；route 必须继续使用 `Cache-Control: no-store`；
- prompt 只包含 T001 allowlist 所需的 `TripUnderstandingRequest` JSON，不加入 API Key、内部 token、确认状态、Provider 事实、Constraint 或 Plan 数据。

## 9. 可观察验收标准

| AC | 可观察结果 |
|---|---|
| AC-T004-01 | `Settings()` 与 `.env.example` 的 trip understanding 默认 timeout 均为 10 秒；7.99 和 12.01 被拒绝 |
| AC-T004-02 | 一个合法裸 JSON proposal 经 strict Schema 和 request context 校验后返回 `MODEL_PROPOSAL`；第一次成功时 client 调用恰好 1 次 |
| AC-T004-03 | timeout、`TransportError`、429、5xx 最多再尝试一次；可在第二次成功；连续失败时 `callCount=2` 并固定问题降级 |
| AC-T004-04 | 401/403、其他 4xx、provider envelope 错误、非 JSON、fenced JSON、Schema 错误、证据/内容错误都不重试；client 调用恰好 1 次 |
| AC-T004-05 | 未配置 Key 返回 `FIXED_QUESTIONS + LLM_NOT_CONFIGURED + callCount=0`，不会构造临时 client |
| AC-T004-06 | 降级响应保留相同 `answerRevision`、原始描述和按冻结顺序排列的六个原答案；有六个 `REVIEW_REQUIRED` item；`understanding=null`、`canPlan=false` |
| AC-T004-07 | 同一 `answerRevision + sourceDigest` 的顺序重放返回同一 outcome，client 总调用数不增加；不同 payload 使用同 revision 返回 409 且零新增调用 |
| AC-T004-08 | 降级前后 canonical revision、Trip、Constraint、PlanVersion、workflow、T003 confirmation 表计数不变，Provider fake 调用数为 0 |
| AC-T004-09 | 捕获日志和 HTTP body 均不含测试 API Key、原始输入、六问全文、system prompt、模型原文和 provider secret body |
| AC-T004-10 | 旧 `/api/v1` extractor 的代码 fence 兼容测试继续通过；S2 understanding 路径的 fence 测试必须降级，证明两条路径未串线 |
| AC-T004-11 | T001 strict understanding、T002 revision、T003 collaboration/readiness、既有 Bailian 及 candidate gateway 定向回归全部通过 |

在线百炼 smoke 不是自动化门禁；若验收需要，只能通过部署 Secret 提供已轮换 Key，且不得把 Key 或完整 prompt 放入聊天、日志或仓库。

## 10. 与 T002/T003 的接口关系

### 10.1 T002 拥有

- `answerRevision` 的生成、递增、source digest、原始输入/六问保存和并发幂等 claim；
- organizer/member conversation HTTP route 与授权；
- 成功 proposal 到 canonical `TripDraftRevision` 的连续版本写入、`memberBindings` 和 `sourceDigest`；
- 成功/降级 outcome 的重放；确认时只读已有 revision，绝不重新调用 T004。

T004 只提供 `TripUnderstandingGateway` 和程序拥有的 recognition/fallback projection。代码窗口必须在 T002 落地后接入其实际 service/store，不得为绕过依赖新建第二套 revision repository。

### 10.2 T003 拥有

- 消费成功的 `TripDraftRevisionView.understanding`；
- 将 proposal 的 missing/ambiguity 转换为带稳定 ID/rule 的 `CollaborationIssue`；
- HARD conflict、relaxation、成员确认、readiness digest 与 planning guard。

T003 不消费 `FixedQuestionFallback`，也不把模型失败伪造成业务冲突。T004 降级时 T003 的 `current_revision` 和所有 confirmation 状态保持不变。

## 11. 明确不做

- 不做 UI、`ConversationPanel`、固定问题文案视觉呈现或前端类型；由王敬博后续任务统一完成；
- 不实现或复制 T002 revision store、idempotency table、organizer/member route、邀请或协作会话；
- 不修改 T003 冲突规则、确认状态机、readiness guard 或 `CollaborationIssue`；
- 不写正式 Trip、Constraint、PlanVersion、workflow、ExecutionEvent 或 Provider FactRef；
- 不让模型生成 UUID、participantId、状态、ruleId、Constraint、PASS、费用事实、路线、评分或计划；
- 不做 prompt 修复、JSON fence 剥离、Schema 修复、内容自纠、第三次调用、退避队列、后台补偿或跨进程重试；
- 不替换模型 SDK、不新增第二个 Bailian/OpenAI client、不引入新依赖；
- 不重构旧单人 `/api/v1/trips/drafts/*` 为 S2 主流程，不取消其既有 fence 兼容；
- 不在本任务添加在线 Key、在线 smoke fixture 或完整敏感 prompt 快照。

## 12. 实施顺序

建议集成顺序为：

1. **T002** 先落地 answer revision、原子幂等和 conversation response/store；
2. **T004** 在该边界注入严格网关、10 秒硬超时、一次临时传输重试及固定六问降级；
3. **T003 接线回归** 验证只有成功 canonical revision 才进入 confirmation/conflict/readiness；不改 T003 业务规则；
4. **王敬博前端任务** 消费 T002 response 中的 `recognition`、`fallback.items` 和 `canPlan=false`。

若 T002 尚未合入，T004 可以先实现和测试纯 gateway/adapter，但不得自行提交替代 revision store；最终 HTTP/idempotency/零写入验收必须在 T002 基线上完成。
