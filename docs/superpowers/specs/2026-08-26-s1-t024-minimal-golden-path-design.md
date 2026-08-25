# S1-T024 最小黄金链冻结设计

> 冻结日期：2026-08-26
> 代码基线：`czy-S1-T024` / `b5922986202091b2744b62fe1f3a0233b5fcba56`，与 `origin/main` 一致
> Sprint Goal：**第一次 Review 就能展示关怀单人完整 Agent**
> 决策：**GO——进入本文定义的最小切片实现；公网发布仍须通过第 13 节门禁。**

## 1. 结论先行

最新 main 已具备服务端 V1、事件驱动 V2、V1/V2 Diff、接受/拒绝和服务端 Summary 的生产链路。T024 不再建设新的 Agent Orchestrator，也不补 LangGraph、队列、OpenTelemetry 或企业级 Trace 平台。

本次只修五件事：

1. 修复 V2 接受/拒绝后错误地跳过首个未完成任务；
2. 删除 Summary 中服务端没有提供的“关怀满足率 100% / 4 项硬约束”自报数字，并让 Sprint 2 媒体区不进入 S1 演示；
3. 固化执行事件的逻辑幂等键，避免“同一任务换一个金额就形成第二笔 EXPENSE”；
4. 增加一条固定北京、严格单人、接受 V2 的真实 SQLite/ASGI 黄金回归；
5. 修复公网 Nginx HTTPS upstream 的 Host/SNI，并让 health/version 暴露构建 SHA。

后端规划、重规划、Diff、决策和 Summary 业务逻辑不是当前阻塞，不得重写。

## 2. 冻结范围

### 2.1 用户可见目标

在暖实例上，用当前页面默认的北京低体力单人案例完成一条少于 90 秒的连续链路：

1. 输入页展示并确认严格单人、低体力关怀约束；
2. 服务端确认 canonical Trip；前端仅调度真实 Provider 事实，服务端 T011 生成并签发唯一 Plan V1；
3. Provider 价格、设施或来源未知时，必须完成服务端登记的逐项事实确认；确认前不能得到可执行 V1；
4. 用户确认 V1 并开始执行，首任务写入 `START`；
5. 用户把首任务实际消费设为“计划金额 + ¥50”，写入 `EXPENSE` 与 `COMPLETE`；
6. 浏览器调用 `POST /api/v1/trips/{tripId}/replans/from-events`，不上传候选 V2、锁定任务或自报 PASS；
7. 服务端读取 CURRENT V1、可信事实和事件，冻结完成前缀，经 T011/T018 签发 PROPOSED V2；
8. 页面读取服务端 Diff，主演示选择 accept；reject 由自动化回归覆盖；
9. 接受后从服务端 `currentPlan + events` 重新求首个未完成任务，完成余项；
10. Trip 进入 `COMPLETED` 后读取服务端 Summary，显示完成数、实际费用、差额和版本历史。

桌面和 375px 均走同一真实 API 链，不存在移动端专用 Mock 路径。

### 2.2 明确非目标

- GPS、到达判断；
- 照片、视频、对象存储、照片时间线、完整旅行回忆页；
- 迟到或疲劳事件、自由文本触发 V2；
- 多成员、成员公平、成员链接；
- 均衡/省钱双方案或多候选产品展示；
- 美团 Skill；
- LangGraph、队列、Saga、OpenTelemetry、独立 Trace 数据库；
- 为 T024 强行把 `trace_summary_numbers` 接进生产 API；
- 重做 T011/T017/T018/T022，或把前端候选拼装重新引入 V2；
- 把 pending V1 review 刷新恢复、reject 后 `v2Attempted` 主动恢复扩大成本次阻塞；二者保留为连续演示之外的后续改进。

## 3. 旧分析中已经失效的结论

| 旧结论 | 最新事实 | 修订 |
| --- | --- | --- |
| 没有服务端权威 V1 生成入口，浏览器直接登记 V1 | 已有 `POST /api/v1/trips/{tripId}/plan-versions/generate`；T011 重算、未知事实 review、可信签发均在服务端 | 失效；T011 为可复用生产能力 |
| T008/T009/T010 未进入 V1 门禁 | T011 重新编译关怀约束、适配路线风险并处理设施/价格 UNKNOWN；请求还必须匹配 T002/T004 的已确认 Trip/画像 | 失效；不再判依赖阻塞 |
| T017/T018 缺失，前端拼 V2 | `3b70101` 已交付 `/replans/from-events`；前端只发 `{schemaVersion, reason=EXPENSE_CHANGE}`；服务端生成后缀并经 T011/T018 选择 | 失效；不得恢复旧客户端 V2 代码 |
| V2 决策后可以重放为选中 | `b592298` 已在相同 planId 已终态时返回 `REPLAN_S1_VERSION_LIMIT`/409，数据库无副作用 | 失效；当前为 fail-closed |
| T011/T018/T022 没有生产实现和测试 | 对应生产模块、HTTP/SQLite 测试、三条 Summary 路径均已存在 | 失效；T024 只补跨模块 accept 黄金回归 |
| 前端没有真实 Summary 接线 | `WorkspacePage` 在 summary 视图调用 `GET /api/v1/trips/{tripId}/summary` | 失效；但 UI 仍有一项硬编码假数字，必须修 |
| 必须新建 `traceId`/Trace 平台才能开始 | 需求已收敛为现成 `tripId/taskId/eventId/planVersionId` 加构建 SHA、HTTP/应用日志 | 失效；不新增企业级 Trace |
| 193 个后端测试且前端无可用回归 | 主窗口新鲜基线为后端 `273 passed`、前端 `21 tests passed`、lint/build 均 exit 0 | 失效；结果是基线证据，不等于 T024 公网验收 |
| T023 只需把文档 PASS 当完成 | 公网同源 API 仍为 502，仓库 Nginx 的 Host/SNI 仍有明确缺口 | 这一部分仍有效，但只作为发布门禁，不否定本地实现 GO |

README、`frontend/README.md`、`frontend/src/api/API.md` 中仍有“T017 未完成”“前端使用 Mock”“V2 走 `/replans`”等陈旧文字。它们是文档债，不是生产能力缺失；最小切片不得因修全文档而扩张。

## 4. 依赖门禁矩阵

“完成”表示当前 main 存在生产实现和对应测试，不冒充 PO/QA 最终验收。

| 依赖 | 当前状态 | 运行时事实 | 验收证据/剩余门禁 |
| --- | --- | --- | --- |
| T002 Trip 解析/确认 | 完成 | `/trips/drafts/parse` 与 `/confirm` 固化 canonical Trip | 草稿解析、确认测试；黄金回归断言 1 participant/1 day |
| T004 关怀确认 | 完成 | DRAFT→`CONSTRAINT_CONFIRMED`，变更后回退，确认幂等 | `tests/test_workflow_execution.py` 与 V1 HTTP 边界测试 |
| T008 约束工具 | 完成 | T011 在服务端从已确认 AssistanceProfile 重新编译约束 | T011 生产调用与 Day1/Day2 集成测试 |
| T010 设施证据 | 完成 | UNKNOWN 形成服务端 pending review；不允许客户端自报 PASS | `test_planning_http_boundaries.py` 中 unknown/review/confirm 测试 |
| T011 唯一 V1 | 完成 | 服务端生成、验证、可信签发 V1；公开直登被拒绝 | V1 HTTP、规划器、可信摘要与重复登记测试 |
| T012 前后端 V1 接线 | 完成 | 前端 `generatePlanVersion`→确认→开始执行；刷新可恢复已签发计划 | 当前生产代码；T024 补完整 UI 黄金路径证据 |
| T016 执行费用 | 完成 | 事件落 SQLite，整数分，幂等键冲突 fail-closed，实际预算重算 | `tests/test_execution_expenses.py` |
| T017 事件驱动 V2 | 完成 | `/replans/from-events` 只接收 `EXPENSE_CHANGE`，服务端推导冻结前缀/后缀 | `backend/tests/test_s1_t017_event_replan.py`；决策后重放 409 |
| T018 最小扰动选择 | 完成 | 候选经 T011 重验，T018 选择并只登记 SELECTED V2 | selector 与 replanning integration 测试 |
| T020 Diff/决策页 | 完成但有前端连续性缺陷 | 服务端 Diff、accept/reject 原子且幂等；页面已接线 | 必修“决策后跳过任务”缺陷后退出 |
| T022 Summary | 完成但有前端真实性缺陷 | 服务端返回事件、任务、费用和版本历史；三路径测试存在 | 删除硬编码 100%，补 from-events→accept→summary 黄金回归 |
| T023 公网 | 部分/发布阻塞 | 前后端直连健康，但同源代理 502；无构建 SHA；持久盘依赖 Render 配置 | 修代理后做第 13 节人工门禁；不阻塞本地代码开工 |
| 375px 与 <90 秒 | 未验收 | 有响应式 CSS，不等于真实通过 | 仅部署后真实设备/浏览器秒表可放行 |

## 5. 当前真实链路、Mock 与部署边界

### 5.1 真实后端

- V1：`PlanningBoundaryService.generate_v1()` 校验已确认 Trip/画像，执行 T011，必要时持久化 `CandidatePlanReview`，完整 PASS 后签发 PlanVersion。
- 执行：`WorkflowService`/SQLite 持久化 `START/EXPENSE/COMPLETE/SKIP`，事件响应包含 `eventId`。
- V2：`generate_v2_from_events()` 读取 CURRENT V1、可信 `CandidatePlanRequest` 和事件，调用 suffix planner 后经 T011/T018 签发 V2。
- Diff/决策：服务端从不可变 V1/V2 快照算 Diff；accept/reject 原子且语义幂等。
- Summary：`GET /summary` 从当前计划、所有版本和真实事件计算费用、完成任务与版本历史。

主窗口已用默认生产组装（仅替换外部 Provider 为固定 Stub）跑通 20 步真实 SQLite/ASGI 链：最终 `COMPLETED`、V2 `CURRENT`、V1 `SUPERSEDED`、4/4 完成、费用差额 `+5000`。本分析窗口交叉核对了相同生产入口、状态转换和对应测试；因此没有后端业务代码级阻断。

### 5.2 前端调度

- V1 前，前端调用后端 Provider API 收集地点/路线事实并构造 `CandidatePlanRequest`；权威校验、planId、PASS 和签发仍由服务端负责。
- V2 已不再调用 `buildAmapReplanCandidate`，而是直接调用 `/replans/from-events`。
- 页面已接 Diff、accept/reject 和 Summary。
- 当前真实 P0 缺陷：完成首任务后 `applyTripState` 已把 `currentTaskIndex` 移到首个未完成任务；`decidePlanV2` 又使用 `currentTaskIndex + 1`，会在 accept 和 reject 后跳过一个任务并错误写入下一条 START。
- 当前真实 P0 缺陷：Summary 显示硬编码“关怀满足率 100% / 4 项硬约束”，但 `TripSummary` 无此字段。
- 当前事件幂等键把金额拼进 key；同一逻辑 EXPENSE 改金额后会形成另一个 key。服务端虽支持冲突保护，前端没有使用好该语义。

### 5.3 Mock/测试替身

- 公网和正常生产路径没有固定地点/路线 Mock 回退；Provider 失败时页面明确失败。
- 自动化可以用固定 Provider Stub 隔离第三方波动，但必须继续走真实 FastAPI、生产 service/repository、SQLite 和 HTTP 契约。
- 测试替身不能进入公网主演示，也不能生成浏览器自报 Plan/Summary。

### 5.4 部署事实

2026-08-26 最新只读实测：

- `https://imagine-1-31o2.onrender.com/`：200；
- `https://imagine-1-31o2.onrender.com/workspace`：200；
- 前端同源 `/api/v1/health` 与 `/health`：502；
- `https://imagine-mp7v.onrender.com/health`：200；
- 后端 `/api/v1/health`：200。

仓库 `frontend/nginx.conf` 仍使用 `proxy_set_header Host $host`，且未启用 `proxy_ssl_server_name`；`API_UPSTREAM` 却是 HTTPS Render 域名。`render.yaml` 的 CORS 前端域名仍是旧 `xingzhi-travel-web`，health 也没有构建 SHA。由此可判定 502 是前端反代/旧部署问题，不是后端能力缺失。

## 6. 方案比较与推荐

| 方案 | 内容 | 优点 | 代价/风险 | 决策 |
| --- | --- | --- | --- | --- |
| A. 现有链路薄接线 | 修 Workspace 两个 P0、幂等键、黄金回归、Nginx/版本；复用全部现有端点 | 改动最少、风险最低、与已通过后端事实一致 | 仍需部署后人工验证第三方和 375px | **推荐** |
| B. 新增“一键演示/Agent Orchestrator”端点 | 一个端点内部完成 V1、事件、V2、Summary | 表面操作少 | 重复状态机、掩盖用户决策、扩大幂等/事务面，不是真实用户链 | 不采用 |
| C. 浏览器 Fixture/Mock 演示 | 前端直接加载 V1/V2/Summary | 最快展示 | 不验证真实后端、Provider、事件或部署；违背验收目标 | 禁止 |

采用方案 A。若 90 秒实测失败，先删除重复 GET、缩短纯展示动画或优化页面操作；不得用方案 B/C 绕过真实链。

## 7. 推荐架构与端到端数据流

```mermaid
sequenceDiagram
    participant U as 用户
    participant F as React 前端
    participant A as FastAPI 现有边界
    participant P as Provider/VERIFIED_CACHE
    participant D as SQLite

    U->>F: 北京单人输入 + 关怀确认
    F->>A: draft/constraints confirm
    A->>D: canonical Trip + AssistanceProfile
    F->>A: 城市/地点/路线请求
    A->>P: 高德或同 cityCode 可信缓存
    P-->>A: Provider facts/provenance
    A-->>F: facts（UNKNOWN 原样保留）
    F->>A: plan-versions/generate
    alt 存在 UNKNOWN
        A->>D: pending review
        A-->>F: 422 + reviewId/items
        U->>F: 逐项确认
        F->>A: plan-reviews/{reviewId}/confirm
    end
    A->>D: ISSUED PROPOSED V1
    U->>F: confirm/start
    F->>A: confirm V1 + execution/start + START
    U->>F: 首任务计划价 + ¥50，完成
    F->>A: EXPENSE + COMPLETE
    A->>D: eventId/taskId/planVersionId
    F->>A: replans/from-events
    A->>D: T011/T018 签发 PROPOSED V2
    F->>A: GET Diff
    U->>F: accept
    F->>A: accept V2
    A->>D: V1 SUPERSEDED; V2 CURRENT
    F->>A: GET currentPlan + events
    F->>A: 完成首个未完成任务及余项
    F->>A: GET summary
    A-->>F: 服务端 Summary
```

关键边界：浏览器负责意图和展示；Provider 负责外部事实；FastAPI 负责校验、生成、版本与决策；SQLite 负责权威状态。T024 不增加第五个编排层。

## 8. 状态机与恢复原则

```text
DRAFT
  -> CONSTRAINT_CONFIRMED
  -> [UNKNOWN: PENDING REVIEW，未签发 V1]
  -> PLAN_REVIEW + V1 PROPOSED
  -> CONFIRMED + V1 CURRENT
  -> EXECUTING
  -> REPLAN_REVIEW + V1 CURRENT + V2 PROPOSED
       -> accept:  EXECUTING + V1 SUPERSEDED + V2 CURRENT
       -> reject:  EXECUTING + V1 CURRENT + V2 REJECTED
  -> COMPLETED
```

恢复规则：

- 已有 CURRENT/PROPOSED V2 时，刷新从 `GET /trips/{tripId}` 恢复，并重新获取 Diff；不从 React state 猜测。
- 决策后必须用响应后的 `currentPlan.days[0].tasks` 与 `events` 求 `firstUnfinishedIndex`，不能复用旧 closure 中的 `currentTaskIndex`，更不能再 `+1`。
- 如果没有未完成任务，进入 Summary；否则只为该首个未完成任务写 START。
- pending V1 review 刷新缺少可发现 reviewId、reject 后刷新不能预先展示 `v2Attempted`，均不阻塞本次连续主演示；服务端仍 fail-closed。后续再扩展恢复 DTO。
- 任一 POST 响应丢失时，先用同一逻辑幂等键重试或 GET 权威状态，不用本地成功提示覆盖服务端结果。

## 9. Trace 链（最小充分）

不新增 `traceId`。一次验收用以下现成字段关联：

| 阶段 | 主键/证据 |
| --- | --- |
| Trip/关怀 | `tripId`、已确认 AssistanceProfile |
| V1 | `planVersionId`、version=1、可信签发摘要 |
| 执行 | `taskId`、服务端 `eventId`、`planVersionId`、idempotencyKey |
| V2 | V2 `planVersionId`、`parentId=V1`、frozenTaskIds、validationReport |
| Diff/决策 | basePlanId、candidatePlanId、CURRENT/SUPERSEDED/REJECTED |
| Summary | tripId、completedTaskIds、events、planHistory |
| 部署 | health/version 的 build SHA、浏览器 Network、Render/Uvicorn access log |

验收附件只需保存一份脱敏 Network JSON/截图和日志时间窗。不得为 T024 新建 Trace 表、消息队列或日志平台。

## 10. 90 秒黄金演示

计时从已加载的 `/plan` 点击第一次确认开始，到服务端 Summary 数字可见结束。允许计时前访问 health 预热前后端；不得预创建本次 Trip、V1、事件或 V2。

| 累计时间 | 操作 | 可见/服务端检查点 |
| ---: | --- | --- |
| 0–10s | 使用预填北京、严格单人、低体力案例；确认关怀并生成 | `participants.length=1`，Trip/画像已确认 |
| 10–35s | Provider/V1；如出现 UNKNOWN，完成真实事实确认 | V1 由服务端签发；UNKNOWN 未按 0/PASS 绕过 |
| 35–45s | 确认 V1、开始执行 | V1 CURRENT；首任务 START 有 eventId |
| 45–55s | 点击“按计划 + ¥50”并完成首任务 | EXPENSE/COMPLETE 均落库，差额 5000 分 |
| 55–68s | `/replans/from-events` + Diff | V2 PROPOSED；完成前缀逐字段保留 |
| 68–75s | 接受 V2 | V2 CURRENT；V1 SUPERSEDED |
| 75–87s | 完成服务端求出的首个未完成任务及余项 | 不跳任务；所有终态事件属于正确 current plan |
| 87–90s | 读取 Summary | COMPLETED、完成数、+¥50、版本历史均来自服务端 |

`+¥50` 快捷动作只负责把输入框设置为 `currentTask.costCents + 5000`，最终金额仍由用户提交、服务端记录。若 Provider 的真实未知事实数量导致总时长超过 90 秒，应如实判发布门禁失败并优化交互，不能自动填 0、自动 PASS 或换 Mock。

## 11. 失败关闭、幂等与 Provider 不可信处理

| 场景 | 必须行为 |
| --- | --- |
| Provider 超时/失败 | 不返回固定 POI/路线；保留未生成状态，显示可重试错误 |
| cityCode/起终点不一致 | 服务端/前端停止规划，不跨城借缓存 |
| 价格、设施、来源 UNKNOWN | 返回 pending review；用户逐项确认后服务端重新计算；未知价格不能按 0 |
| V1 非 PASS 或未签发 | confirm/start 失败；浏览器不能直接登记 PlanVersion |
| EXPENSE 重试 | 同一 `planId:taskId:EXPENSE` 使用同一 key；相同 payload 返回同一 eventId，不同金额返回 `EVENT_IDEMPOTENCY_CONFLICT` |
| COMPLETE/START 重试 | 每个 plan/task/type 使用稳定 key；禁用按钮只防 UI 双击，服务端幂等才是最终保护 |
| EXPENSE 已成功、COMPLETE 失败 | 重试同一 EXPENSE 不重复扣款，再补 COMPLETE；不回滚已持久化事实 |
| V2 无可行解 | 不留下 V2/可信草稿；V1 保持 CURRENT，已记录事件不回滚，可继续 V1 |
| 同一事件重复请求 V2 | 决策前恢复相同 PROPOSED V2；不生成第二个 V2 |
| V2 已 accept/reject 后重放 | 409 `REPLAN_S1_VERSION_LIMIT`，数据库无变化 |
| accept/reject 响应丢失 | 重试决策或 GET Trip；以服务端 CURRENT 为准 |
| Summary 未完成 | 不显示伪造完成率；完成后只渲染服务端字段 |

## 12. 文件级最小切片与阶段安排

### 阶段 A：前端连续性和真实性（T024 前端负责人）

建议影响文件：

- `frontend/src/pages/WorkspacePage.tsx`
  - 决策后从恢复后的 `currentPlan + events` 求首个未完成 index，删除 `currentTaskIndex + 1`；
  - Summary 删除硬编码 100%/4 项，替换为 `summary.events.length`、`completedTaskIds/totalTasks` 或 `planHistory.length` 等已有服务端数字；
  - S1 演示隐藏照片/视频/完整回忆与导出入口；
  - 增加“按计划 + ¥50”输入快捷动作；
  - 事件 key 不再包含金额，使用稳定逻辑 key。
- `frontend/src/services/executionReplan.ts`（或一个同等大小的纯 helper）
  - 提供 `firstUnfinishedTaskIndex(plan, events)` 和稳定事件 key 生成函数，避免页面 closure 逻辑再次漂移。
- `frontend/tests/eventReplan.test.ts` 或新增 `frontend/tests/executionProgress.test.ts`
  - accept/reject 后均启动第一个未完成任务；无未完成任务进入 Summary；
  - EXPENSE 同一逻辑 key 不随金额变化；
  - 不再出现硬编码“关怀满足率 100% / 4 项”。
- `frontend/package.json`
  - 仅当新增独立测试文件时把它加入现有 `node --test` 列表；不引入新测试框架。

退出条件：前端 21 项既有测试继续通过，新回归通过，lint/build exit 0；源码不再包含两个已知 P0 表现；手工执行不跳任务。

### 阶段 B：一条黄金链自动化（T024 后端/集成负责人）

建议新增：

- `backend/tests/test_s1_t024_golden_path.py`
  - 使用生产 `create_app`/service/repository、真实 SQLite/ASGI，仅 Stub 外部 Provider；
  - 严格单人→关怀确认→V1→confirm/start→首任务 EXPENSE(+5000) 幂等重放→COMPLETE→`from-events`→Diff→accept→完成余项→Summary；
  - 断言 `COMPLETED`、V2 CURRENT、V1 SUPERSEDED、全部任务完成、差额 +5000、事件/任务/版本谱系一致；
  - reject 不复制整条链，复用既有 reject/重放回归。

不修改 `PlanningBoundaryService`、T011、suffix planner、T018 selector、Diff、Plan store 或 Summary store，除非新增测试揭示与当前 20 步运行证据相冲突的生产缺陷。

退出条件：新黄金测试通过；T017/T022/Diff 定向回归继续通过；后端全量不回退。

### 阶段 C：部署可证实性（T023/部署负责人）

建议影响文件：

- `frontend/nginx.conf`
  - HTTPS upstream 开启 `proxy_ssl_server_name on`；
  - upstream 请求 Host 使用 upstream host，而不是前端 `$host`；
  - `/api/` 与代理 `/health` 使用一致的代理头/SNI 规则。
- `app/core/config.py`、`app/main.py`、`app/api/routes.py`
  - health/version 返回应用版本与 `BUILD_SHA`/`RENDER_GIT_COMMIT`；未知 SHA 不得伪装成当前提交。
- `render.yaml`
  - 将 CORS/服务地址与实际 `imagine-1-31o2`、`imagine-mp7v` 配置对齐；主演示首选同源 `/api`；
  - Persistent Disk 是跨重部署恢复要求，若 Blueprint 不声明则必须在 Render 控制台门禁中核验。
- `tests/test_deployment_config.py` 及 health 定向测试
  - 静态断言 Host/SNI；运行断言两个 health 返回同一非空构建 SHA。

退出条件：本地配置测试通过；部署后的同源 health 200 且 SHA 精确等于发布提交。静态测试不能替代公网门禁。

### 阶段 D：QA/Review（QA + PO/主持人）

- 独立执行 accept 主链；reject 只看自动化证据和必要的短烟测；
- 桌面与 375px 各跑一遍，记录未剪辑秒表；
- 保存 Network/日志/最终 Summary；
- 确认主演示没有 GPS、照片、迟到/疲劳、多人、双方案或美团。

退出条件：第 13 节全部通过，才可称为“公网 Review Ready”；任何文档自报 PASS 都不能替代实测。

### 协作边界

- 前端负责人不改 T011/T017/T018 选择算法，不构造 V2。
- 后端负责人只补黄金回归和最小 health 元数据，不重写已通过链路。
- 部署负责人不改业务状态机，只处理代理、环境、版本与持久盘。
- QA 不修代码，不把旧部署或测试 Fixture 当成产品验收。
- 现有 `docs/testing/2026-08-25-s1-t024-independent-test-plan.md` 属于 QA 输入，本切片不修改；其旧 NO-GO 事实应以本文和最新运行证据解释，而不是删除历史记录。

## 13. 验收条件与部署后人工门禁

### 13.1 代码/自动化验收

- HEAD 基于 `b592298` 或其后续 main，无旧客户端 V2 拼装回归；
- 后端全量至少保持当前 `273 passed` 基线；
- 前端至少保持当前 `21 tests passed`，lint/build exit 0；
- 新的 T024 accept 黄金回归通过；
- reject、决策幂等、决策后 V2 重放 409 的既有回归通过；
- accept/reject 后不会跳过首个未完成任务；
- Summary 没有服务端不存在的关怀百分比/硬约束数量；
- 事件金额 key 不随金额变化，冲突由服务端拒绝；
- Sprint 1 主路径不展示或调用媒体能力。

### 13.2 公网发布门禁

以下是真正依赖外部部署的门禁，不反向把已实现依赖判成阻塞：

1. 后端 `/health` 与 `/api/v1/health` 均为 200，build SHA 等于发布提交；
2. 前端 `/`、`/workspace`、同源 `/health`、同源 `/api/v1/health` 均为 200，不再出现 502；
3. 同源 API 实际到达 `imagine-mp7v` 对应版本，浏览器无 localhost、Mock 或跨域回退；
4. Render 前后端均已预热；AMap Web/JS Key 只存在于部署环境；
5. 如要求重部署后恢复，`/app/data` Persistent Disk 已挂载并做一次重启恢复烟测；
6. 桌面和 375px 的同一 accept 链均完成，关键按钮可见、无横向溢出、Diff 可读；
7. 未剪辑计时少于 90 秒；若超时则门禁失败；
8. 最终 Network/日志能用 tripId、taskId、eventId、V1/V2 planVersionId 和 build SHA 串联；
9. 最终 Summary 为服务端响应，显示 `COMPLETED`、全部任务完成、费用差额 +5000 和 V1→V2 历史。

## 14. 已冻结的设计决定与 GO/NO-GO

用户已批准且本文冻结，不再等待 PO 选择：

- 固定北京、严格一名参与者、低体力关怀、单日案例；
- 暖实例计时，计时前只允许 health 预热；
- accept 为 90 秒主演示，reject 为自动化回归；
- 使用现有同步服务与 SQLite，不引入 LangGraph/队列/OTel；
- Trace 只用现有业务 ID、构建 SHA 和日志；
- pending V1 review 刷新发现与 reject 后主动恢复不进入本次 P0；
- Provider UNKNOWN 必须人工确认或失败关闭，不使用 Mock/0/PASS 绕过；
- 推荐方案 A，先修薄接线，再发布验证。

没有尚待用户批准的实现设计点。Render 密钥、Persistent Disk 和实际部署动作属于发布执行门禁，不是重新讨论产品方案的理由。

**最终结论：GO（可以立即进入上述最小代码切片）。**
**当前公网状态：尚未 Review Ready；修复并部署代理/版本后，必须通过 13.2 才可宣称 T024 完成。**
