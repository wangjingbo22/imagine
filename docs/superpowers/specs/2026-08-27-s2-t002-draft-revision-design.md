# S2-T002 不可变草稿版本与一次解析设计

- 日期：2026-08-27
- 分支：`czy-S2-T002-analysis`
- 基线：`a43ad37a5c8b97d2b90507fa9966998bfee038b9`
- 阶段：实现分析；本分支只提交设计与实施计划
- 决策：在 T003 已冻结的 `TripDraftRevisionPort` 后补生产 revision service/store，并接通现有 `/api/v2/trips/conversations`；确认、冲突、成员隔离和 READY 继续由 T003 唯一负责

## 1. 任务边界与结论

S2-T002 只解决一件事：一次固定六问答案形成一个不可变、可恢复的 `TripDraftRevision`，后续确认读取这份 revision，不再次解析。用户修改固定问题时，以当前 revision 为 `baseRevision` 创建 `revision + 1`；T003 已有的 revision/source/shared/member digest 比较会自动让受影响的旧确认失效，并阻止旧结果进入 `READY_TO_PLAN`。

`answerRevision` 在最小实现中不是新增客户端字段，而是一次 answer command 的服务端身份：`actor scope + actor id + operation + Idempotency-Key + requestDigest`。同 key、同 digest 是同一 answer revision；重放只能复用已保存结果。同 key、不同 digest 返回冲突。修改答案必须使用新 key，并以当前 `baseRevision` 申请下一个 draft revision。这样不改 T003 已发布 DTO，也能冻结“一次 answerRevision 至多一次 gateway 调用”。

actor 映射固定为：初始创建使用 `SYSTEM/INITIAL_CONVERSATION`，成员更正使用 `PARTICIPANT/<participant UUID>`，T003 已鉴权并生成的 relaxation 使用 `SYSTEM/<trip UUID>`。`operation` 仍属于命令主键，因此同一个外部 key 可依次用于 T002 初始创建和 T003 bootstrap，而不会共享幂等记录。

模型边界保持严格：T004 gateway 只能返回 T001 的 `TripUnderstandingProposal` 及解析元数据；T002 只保存草稿 revision；T003 只写协作确认；正式 `Trip`、`Constraint`、`PlanVersion` 和 READY 状态均不由模型或 T002 写入。

## 2. 现状证据矩阵

| 证据 | 已有能力 | 真正缺口 / T002 动作 |
| --- | --- | --- |
| `app/domain/trip_draft.py:243-247,418-428,430-578,723-778` | T001 已实现 strict `TripUnderstandingRequest/Proposal`、成员键、证据、缺项、歧义和上下文校验 | 缺 server-owned `TripDraftRevision` envelope；新增模型但原样复用 proposal，不复制理解 DTO |
| `app/application/trip_draft_service.py:59-77,177-206,255-297` | S1 兼容 parser 能解析单人输入；无确认项时还会解析城市并构造正式 `CreateSingleDayTrip` | 这是 legacy 流，不可作为 S2 revision store；S2 不调用 city resolver、不构造正式 Trip |
| `app/api/trip_draft_routes.py:20-44` | `/api/v1/trips/drafts/parse` 与 `/confirm` 已发布 | `confirm` 当前重新执行 `parse()`，所以 S2 不复用它；保持兼容、不在 T002 改写 S1 路由 |
| `app/application/collaboration_ports.py:20-61` | T003 已冻结 `TripDraftRevisionView` 以及 `get_current`、`submit_participant_conversation`、`apply_relaxation` | 缺生产实现；不得重命名、扩成第二套 collaboration 接口或让 T003读 T002 内表 |
| `app/application/collaboration_ports.py:64-94` | `UnavailableTripDraftRevisionPort` 使所有 revision 命令失败关闭 | T002 上线后只把默认 wiring 换成生产 service；保留 unavailable adapter 给故障/边界测试 |
| `app/domain/collaboration.py:37-65,153-181` | T003 已有协作/成员状态机、`currentRevision`、`confirmedRevision`、`canPlan` | T002 不新增确认状态或 READY 布尔值 |
| `app/application/collaboration_service.py:205-295` | 确认有效性绑定 current revision、source/shared/member digest；变更后自动 `NEEDS_RECONFIRMATION`；READY 要求全员当前确认、无 issue 且 stored/current revision 相等 | 无需重做失效逻辑；T002 只需保证新 revision/sourceDigest 不可变、连续 |
| `app/application/collaboration_service.py:349-381` | 成员提交会调用 revision port 并在随后推进 collaboration revision | 当前在 T002 调用前未校验 `expectedVersion`；stale 请求可能先解析。需先做 version/base/lease preflight，并补幂等恢复分支 |
| `app/application/collaboration_service.py:388-472` | confirm 只读取 current revision、计算 issue/digest 并保存确认 | 已满足“确认不调模型”；T002 不新增 confirm API |
| `app/application/collaboration_service.py:485-634` | relaxation 已校验 current item、权限、base/version，并要求 port 返回连续新 revision；跨步骤重试有审计恢复 | T002 实现确定性 canonical patch；该路径调用模型次数必须为 0 |
| `app/infrastructure/collaboration_store.py:105-239,363-478` | T003 已有 WAL、`BEGIN IMMEDIATE`、capability hash、bootstrap 幂等、flow 注册 | T002 使用同一 SQLite 文件和事务风格，但另建 draft revision 表；不写确认表 |
| `app/infrastructure/collaboration_store.py:1065-1164` | participant confirmation 已按 idempotency key + digest 原子复用 | 确认复用已实现；只补“确认期间不会重新解析”的计数验收 |
| `app/infrastructure/collaboration_store.py:1166-1259` | collaboration revision 用 expected version/base revision CAS 前进；旧 confirmation 数据保留但不再匹配 | T002 的 draft head 也必须 CAS；两步之间失败时依赖 mismatch 失败关闭并允许同 key 恢复 |
| `app/application/collaboration_readiness.py:61-83` | Provider/规划前取得 digest-bound lease，结束后释放 | 为关闭“首次 READY 检查后、lease 写入前 revision 已变化”的窗口，lease 成功后、执行下游前再校验一次 readiness digest |
| `app/api/collaboration_routes.py:54-61` | T003 已预留 `POST /api/v2/trips/conversations` | 当前固定 503；这是唯一需要接通的创建入口 |
| `app/api/collaboration_routes.py:106-129,149-194` | 成员提交、成员/组织者确认、issue resolve、协作读取均已发布且有 capability/idempotency 边界 | T002 不增加页面路由，不复制这些 mutation |
| `app/main.py:175-176,264-275,415-418` | 支持注入 revision port，但默认仍是 unavailable；legacy 百炼 extractor 只服务 S1 parser | 缺生产 revision service/store 默认 wiring；T004 新 gateway 不得复用 legacy `LlmTripDraftFields` extractor 冒充多人 proposal |
| `backend/tests/test_s2_t003_revision_port.py:24-49` | unavailable port 的全部命令已锁定失败关闭 | 新生产 port 测试与该回归并存 |
| `backend/tests/test_s2_t003_collaboration_service.py:126-157,188-212` | 已证明 T002 unavailable 零协作写、member/shared digest 失效范围正确 | 补真实 port 的调用计数、重放与 preflight 验收 |
| `backend/tests/test_s2_t003_readiness_guard.py:107-150` | 已证明 active lease 阻止 mutation、sourceDigest 改变阻断下游 | 补 lease 后二次校验的竞争窗口测试 |
| `backend/tests/test_s2_t003_http_boundaries.py:23-40` | v2 路由表、token 不入路径已冻结 | 实现现有 conversations stub，不新增 token 路径或前端接口 |
| 提交 `835c286`、`2610c6c`、`5adf96e`、`9f26929`、`8fd3bed`、`06f27bb` | T003 依次冻结契约、fail-closed wiring、前置校验、恢复、返回最新状态、actor 复用与 no-store | T002 必须沿用这些恢复/安全语义，不回退到 legacy collaboration baseline |

最新修订表 `doc/行知旅伴_V2.3_Sprint2待办列表_含负责人_新增需求修订版.xlsx` 的 S2-T002 行与上述缺口一致：`draftId/revision` 保存、确认复用、关键字段修改后旧确认失效；一次确认流程只解析一次，修改对应问题后重新解析。

现有相关基线测试已在指定 worktree 以项目 `.venv` 定向执行：`57 passed in 7.23s`。

## 3. 方案比较

### 方案 A：给 S1 `/drafts/confirm` 加内存缓存

改动最少，但只缓存单进程单人 `ParsedTripFields`，仍会构造正式 Trip、调用城市 Provider，无法满足重启恢复、多人 bindings、T003 port 和并发 CAS。拒绝。

### 方案 B：T002 自建确认/READY 聚合

可以局部闭环，却会复制 T003 的确认状态、摘要、冲突和门禁，形成双写与两套真相。拒绝。

### 方案 C：实现冻结 port 后的不可变 revision（采用）

新增一个 focused revision service 和一个 SQLite store；现有 v2 conversations stub 只负责编排“创建初始 revision → T003 bootstrap”。成员修订和 relaxation 继续从 T003 进入冻结 port；确认继续读取 current revision。该方案修改范围小，跨步骤失败天然因 revision mismatch 失败关闭，也为 T004 留出单一 gateway 接口。

## 4. 最小模块与数据流

```text
POST /api/v2/trips/conversations
  -> validate six fixed answers + Idempotency-Key
  -> TripDraftRevisionService.create_initial()
       -> reserve answer command (BEGIN IMMEDIATE, no model in txn)
       -> T004 TripUnderstandingGateway.extract() exactly once
       -> strict T001 context validation
       -> allocate tripId/draftId/memberBindings server-side
       -> persist immutable revision 1 + sourceDigest
  -> existing CollaborationService.bootstrap(revision)
  -> return revision + one-time organizer capability metadata

PUT /api/v2/member-session/conversation
  -> existing participant capability check
  -> collaboration version/base revision/lease preflight
  -> frozen submit_participant_conversation()
       -> reserve target revision = baseRevision + 1
       -> gateway once, outside transaction
       -> enforce participant scope and immutable bindings
       -> persist immutable next revision with CAS
  -> existing collaboration advance_revision()
  -> existing digest derivation marks affected confirmations stale

POST confirm
  -> existing get_current() + deterministic issue/digest check
  -> existing confirmation store
  -> zero gateway/model calls

POST confirmation-items/.../resolve
  -> existing permission/current-item validation
  -> frozen apply_relaxation()
       -> deterministic allowlisted patch, zero model calls
       -> persist immutable next revision with CAS
  -> existing collaboration advance/audit/readiness
```

### 4.1 文件职责

- `app/domain/trip_draft.py`：新增严格、server-owned `TripDraftRevision`，不改 T001 proposal 或 S1 DTO。
- `app/domain/collaboration.py`：新增初始 conversations 请求/响应 DTO，复用 `ConversationSubmission` 和 `OrganizerBootstrapResult`。
- `app/application/trip_draft_revision_service.py`：实现冻结 port、一次 gateway 编排、scope merge、source digest 和 canonical patch。
- `app/infrastructure/trip_draft_revision_store.py`：只负责 command claim、不可变 revision、CAS 与恢复读取；不依赖 FastAPI。
- `app/application/collaboration_service.py`：只补提交前置检查和同 key 两步恢复；不迁移状态机。
- `app/api/collaboration_routes.py`：替换既有 503 stub；不增加新路径。
- `app/main.py`：把同一生产 revision service 同时注入创建入口和 T003。
- `app/application/collaboration_readiness.py`：lease 后再次比较 readiness digest，关闭 mutation/plan 竞争窗口。

## 5. 数据模型与持久化

### 5.1 公共 envelope

```text
TripDraftRevision
  schemaVersion: "1.0"
  draftId: UUID4
  revision: integer >= 1
  tripId: UUID4
  understanding: TripUnderstandingProposal
  memberBindings: map<member-[1-3], UUID4>
  sourceDigest: lowercase sha256[64]
  createdAt: RFC3339 datetime
```

不把 `confirmationStatus`、`canPlan`、`Constraint`、正式 `Trip` 或 `PlanVersion` 放入该 envelope。validator 要求 binding keys 与 proposal 的有序 member keys 完全一致，UUID 唯一，`member-1` 在后续 revision 中保持原 participantId。最小实现冻结 bootstrap 后参与人数和全部 binding；改变 party size 返回 `DRAFT_BINDINGS_IMMUTABLE`，因为当前 T003 participant rows/invitations 没有成员增删迁移协议。

`sourceDigest` 为以下 canonical JSON 的 SHA-256：`draftId + revision + tripId + exact understanding + ordered memberBindings + source request digest`。它由程序计算，客户端和模型不能提供。

### 5.2 SQLite 表

```text
trip_draft_heads(
  draft_id PK, trip_id UNIQUE,
  current_revision, pending_revision NULL,
  created_at, updated_at
)

trip_draft_revisions(
  draft_id, revision, trip_id,
  understanding_json, member_bindings_json,
  source_request_digest, source_digest,
  recognition_source, recognition_model, degraded_reason,
  llm_call_count CHECK 0..1, created_at,
  PK(draft_id, revision), UNIQUE(trip_id, revision)
)

trip_draft_commands(
  actor_scope, actor_id, operation, idempotency_key,
  request_digest, draft_id, base_revision, target_revision,
  status CHECK(CLAIMED|COMPLETED|FAILED),
  failure_code, claimed_at, completed_at,
  PK(actor_scope, actor_id, operation, idempotency_key)
)
```

revision JSON 只插入，不更新。`trip_draft_heads` 是唯一可变 head/CAS 行。command 表是 at-most-once 证据，不能被确认或 READY 当作业务状态。

## 6. 状态、幂等与并发规则

### 6.1 一次解析

1. 在 `BEGIN IMMEDIATE` 中计算 request digest、检查同 key 记录、检查 `baseRevision == currentRevision`、没有 pending revision且 T003 现有 lease 表没有 active planning lease，然后写 `CLAIMED` 和 `pendingRevision = base + 1`。lease 检查与 claim 共用同一个 SQLite 写事务，避免 read-only preflight 后才取得 lease 的竞态。
2. 提交事务后才调用 T004 gateway；数据库事务不得跨越网络等待。
3. 同 key、同 digest：`COMPLETED` 返回已保存 revision；`CLAIMED` 返回 `DRAFT_PARSE_IN_PROGRESS`；`FAILED` 返回保存的 failure。三种情况都不再调用 gateway。
4. 同 key、不同 digest：`IDEMPOTENCY_KEY_REUSED`，零 gateway 调用。
5. gateway 成功后 strict 校验并以 `pendingRevision` CAS 插入 immutable revision、推进 current、清 pending、完成 command。
6. gateway/进程在完成前失败时保留 pending/failed，`get_current()` 失败关闭，旧 READY 不会复活。同 answer command 永不自动二次调用模型；T004 应把超时/非 JSON/schema 失败收敛为 strict degraded proposal。无法收敛时重新创建草稿是最小降级，不在 T002 做运维接管 UI。

### 6.2 两阶段 revision/collaboration 收敛

T002 revision 先成功，T003 `advance_revision` 后成功。若第二步失败，T002 current 已前进而 T003 stored revision 仍旧，`canPlan` 必为 false。相同 key 重试时 T002 返回已保存 revision，T003 完成自己的 idempotent advance，不再次解析。

`submit_member()` 的安全顺序固定为：

1. authenticate participant；
2. 若已有同 key 的 `ADVANCE_REVISION` 记录，走安全重放；
3. 否则读取 stored collaboration，先校验 `expectedVersion`、`baseRevision` 和 active lease；
4. 再调用 T002；
5. 校验 `tripId`、`revision == base + 1` 和 binding；
6. 调用现有 `advance_revision` CAS。

因此 stale collaboration request 在模型调用前失败；跨步骤恢复仍可完成。

### 6.3 planning/mutation 互斥

T003 service 在 revision command 前先做现有 active lease preflight；T002 claim 在同一 SQLite 的 `BEGIN IMMEDIATE` 中再次读取 T003 lease 表并原子预留 pending revision。READY guard 在取得 lease 后、进入 Provider/推荐/planner body 前再次调用 `require_ready()` 并比较 digest：

- planning 先取得 lease：revision mutation 返回 `COLLABORATION_OPERATION_IN_PROGRESS`；
- revision 先写 pending/current：首次或二次 readiness 校验失败；
- 任一路径都不能同时带旧 digest执行下游。

## 7. API 与 DTO

### 7.1 创建初始草稿

`POST /api/v2/trips/conversations`

Headers：`Idempotency-Key` 必填，沿用现有 16—128 printable ASCII 校验。

```json
{
  "schemaVersion": "1.0",
  "referenceDate": "2026-08-27",
  "naturalLanguageRequest": "两个人去上海一日游",
  "answers": [
    {"questionId": "trip", "answer": "上海，9月5日，09:00-20:00"},
    {"questionId": "party", "answer": "两人，我是组织者"},
    {"questionId": "endpoints_budget", "answer": "虹桥站往返，总预算800元"},
    {"questionId": "preferences", "answer": "分别喜欢建筑和美食"},
    {"questionId": "assistance", "answer": "均为普通模式"},
    {"questionId": "confirm", "answer": "以上信息确认"}
  ]
}
```

请求复用 T003 `QUESTION_IDS` 与 `ConversationSubmission` 的固定顺序校验。沿用项目现有 `ApiResponse` envelope，其 `data` 为：

```text
OrganizerConversationCreated
  revision: TripDraftRevision
  organizerAccess: OrganizerBootstrapResult
```

首次成功 `organizerAccess.organizerTokenAvailable=true` 并只返回一次 raw token；重放复用相同 draft/revision，但遵循 T003 现有安全规则，不重放 raw token。响应统一 `Cache-Control: no-store`。

### 7.2 成员修订与确认

不新增路径或 DTO：

- `PUT /api/v2/member-session/conversation`：现有 `ParticipantConversationRequest`，`baseRevision` 是被替代 revision；新 answer command 成功时只产生 `base + 1`。
- `POST /api/v2/member-session/confirm` 与组织者 confirm：只读取 current revision，gateway/LLM 调用数为 0。
- confirmation item resolve：沿用现有 `ResolveConfirmationItemRequest`；确定性 patch 产生新 revision，gateway/LLM 调用数为 0。

## 8. Canonical patch 与成员隔离

`apply_relaxation()` 只接受 T003 已验证、服务器生成的 `CanonicalRevisionPatch`。最小 allowlist 与当前 evaluator 产生的 action 一致：

- `SELECT_CANDIDATE`：设置当前 ambiguity 的 candidate，并移除同 path 的 ambiguity/question；
- `SET_SHARED_FIELD`、`LOWER_SHARED_BUDGET`、`EXTEND_SHARED_TIME`：只允许 `trip.*` canonical path；
- `SET_MEMBER_FIELD`、`RAISE_MEMBER_BUDGET_CAP`、`CHANGE_NAP_WINDOW`：participantId 必须解析到对应 member path；
- `REMOVE_MUST_VISIT`、`REMOVE_AVOID_PLACE`：只删除 path 指向的当前列表项。

patch 后必须重新 strict validate `TripUnderstandingProposal`。任意未知 action/path、owner/path 不匹配、越界索引或 binding 变化均失败且不写 revision。

成员重新解析只能改变绑定到本人 participantId 的成员字段；共享字段变化只能由 organizer-owned canonical patch 进入。其他成员卡、成员顺序、bindings 和 shared trip 被模型改变时返回 `PARTICIPANT_SCOPE_VIOLATION`，不静默接受。

## 9. 可观察验收条件

| AC | 可观察结果 |
| --- | --- |
| AC1 初始一次解析 | 一次 conversations 请求得到 `draftId`、`revision=1`、`sourceDigest` 和 exact proposal；gateway spy 为 1，Provider/workflow/PlanVersion spy 均为 0 |
| AC2 创建重放 | 同 key、同 body 重放得到同 `draftId/revision/sourceDigest`；gateway 仍为 1；organizer raw token 不重放 |
| AC3 幂等冲突 | 同 key、不同 body 返回 `IDEMPOTENCY_KEY_REUSED/409`；gateway 和全部表行数不增加 |
| AC4 并发一次调用 | 两个并发同 key 请求最多一个进入 gateway；另一个得到 in-progress 或已保存结果；最终只有一个 revision 行 |
| AC5 confirm 复用 | 成员/组织者确认与相同确认重放都读取 current revision；gateway 计数不变 |
| AC6 stale 前置短路 | stale `expectedVersion` 或 `baseRevision` 在调用 T002/gateway 前返回 409，command/revision/confirmation 均不写 |
| AC7 更正产生新 revision | 修改固定问题并使用新 key 后只产生 `base+1`，gateway 增加 1；原 revision JSON 逐字节不变 |
| AC8 旧确认失效 | member-only 更正只使本人 `NEEDS_RECONFIRMATION`；shared patch 使全员如此；`canPlan=false` 且 readinessDigest 为空 |
| AC9 relaxation 不调模型 | 选择当前 server relaxation 后产生连续新 revision，gateway 计数不变，issue 由 T003 重新计算 |
| AC10 重启恢复 | 新 repository 实例从同一 SQLite 读取相同 current revision/sourceDigest；重放仍不调 gateway |
| AC11 失败关闭 | pending/failed revision、T004 unavailable 或二次 readiness digest 不同均在下游 body 前失败，Provider/推荐/planner/PlanVersion 写入为 0 |
| AC12 legacy 回归 | `/api/v1/trips/drafts/*` 与既有 S1 单人测试保持原行为；不把 legacy row 合成 S2 revision |

## 10. 错误与降级

| code | HTTP | retryable | 语义与副作用 |
| --- | ---: | --- | --- |
| `IDEMPOTENCY_KEY_REQUIRED` | 400 | false | 沿用现有 header 校验，零 command |
| `IDEMPOTENCY_KEY_REUSED` | 409 | false | 同 key 不同 digest，零 gateway/写入 |
| `DRAFT_PARSE_IN_PROGRESS` | 409 | true | 相同 answer command 已 claimed，绝不并发二次调用 |
| `DRAFT_REVISION_STALE` | 409 | false | base 不是 current，零 gateway/写入 |
| `COLLABORATION_VERSION_STALE` | 409 | false | 在调用 T002 前失败 |
| `COLLABORATION_OPERATION_IN_PROGRESS` | 409 | true | planning lease 已存在，revision 不开始 |
| `DRAFT_BINDINGS_IMMUTABLE` | 409 | false | bootstrap 后 participant count/key/UUID 变化被拒绝 |
| `PARTICIPANT_SCOPE_VIOLATION` | 403 | false | 成员 proposal 越权改变 shared/他人字段，零 revision |
| `TRIP_DRAFT_REVISION_UNAVAILABLE` | 503 | true | current pending/failed/损坏或 store 不可用；T003/READY 失败关闭 |
| `TRIP_UNDERSTANDING_UNAVAILABLE` | 503 | true | T004 gateway 未装配；初始/更正不产生完成 revision |
| `TRIP_UNDERSTANDING_INVALID` | 502 | false | gateway 未返回 T001-valid proposal；同 answer command 不自动重调模型 |

T004 的正常降级结果仍必须是 strict `TripUnderstandingProposal`，并保存 `recognitionSource/degradedReason/llmCallCount`。T002 不提供“再试一次模型”按钮；修改固定问题产生新 answer command，或者重新创建草稿。

## 11. 明确不做

- 不修改 `frontend/**`，不新增页面、卡片、跳转、轮询或 token 存储。
- 不改写 S1 `/api/v1/trips/drafts/parse|confirm`，不迁移旧确认输入。
- 不创建第二套 Trip、Participant、Constraint、confirmation、conflict 或 READY 模型。
- 不调用城市/POI/路线 Provider，不写 workflow、正式 Trip、Constraint、PlanVersion、ExecutionEvent 或 plan 状态。
- 不让 LLM 生成 participantId、draftId、revision、sourceDigest、ruleId、relaxation、确认或 READY。
- 不支持 bootstrap 后增删/重排成员；需先由 T003/T005 冻结 participant-row 迁移协议。
- 不实现账号找回、跨设备恢复、WebSocket、通知、后台 job 或通用 JSON Patch。

## 12. 对 T003/T004 的依赖与任务顺序

### T003（已完成，直接复用）

依赖其冻结 port、capability/member isolation、confirmation digest、hard-conflict evaluator、collaboration CAS、resolution recovery 和 READY guard。T002 只需补 `submit_member` 的 preflight/replay 集成和 guard 二次校验；不重做状态机。

### T004（实现时可后接）

T004 提供 `TripUnderstandingGateway.extract(request) -> TripUnderstandingExtraction`：单次 invocation 内 `llmCallCount` 只能为 0 或 1；超时、非 JSON、schema invalid 的降级必须返回 T001-valid proposal，不能写任何 T003 或正式状态。T004 未接入时，T002 store/get_current/apply_relaxation 仍可测试，创建/重新解析返回稳定 503。

### 推荐顺序

1. T002 domain + store（不可变 revision、command claim、CAS）；
2. T002 service（一次 gateway、scope、patch）；
3. T003 submit preflight/replay 与 READY 二次校验；
4. conversations stub/main wiring；
5. T004 接入真实 gateway；
6. 王敬博前端任务消费现有 v2 DTO；
7. T005 才把 READY GROUP 转换为正式 `CreateDayTrip`/PlanVersion。

## 13. 自查结果

- 完整性：不存在占位内容或未定义接口。
- 一致性：revision 内容由 T002 唯一拥有；确认/READY 由 T003 唯一拥有；正式状态仍由下游拥有。
- 幂等：同 answer command 不二次调用；跨 T002/T003 两步可重放收敛。
- 并发：stale version 在模型前拒绝；pending revision 与 planning lease 互斥并二次校验。
- 范围：只有后端和测试；不含前端、Provider、正式 Trip/PlanVersion 扩展。
