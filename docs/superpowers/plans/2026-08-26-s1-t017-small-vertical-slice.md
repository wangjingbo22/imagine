# S1-T017 小闭环实施计划

**Goal:** 在最新 main 上实现可部署的事件驱动后缀重规划，并用真实 SQLite/ASGI 与前端契约证明闭环。

**Architecture:** 新增服务端事件重规划请求与后缀规划端口。PlanningBoundaryService 从持久化 V1/可信事实/事件推导冻结边界，只向默认后缀规划器暴露未完成任务，再复用现有 T011 + T018 + PlanVersion/T019 边界签发 V2。前端从客户端高德候选切换到该接口。

**Tech Stack:** FastAPI, Pydantic v2, SQLite, pytest/httpx ASGI, React/TypeScript, node:test.

---

### Task 1: 锁定服务端红测

**Files:**
- Create: `backend/tests/test_s1_t017_event_replan.py`

1. 写默认 `create_app` 黄金路径测试，断言第一项多花 5000 cents 后生成 V2。
2. 用捕获型 planner 断言只收到未完成后缀，冻结前缀 PlanTask 全字段相等。
3. 写超预算、消费不完整、无剩余后缀与重复请求测试，断言无解零 V2/幂等。
4. 运行定向测试并确认因接口/装配尚不存在而 RED。

### Task 2: 实现后缀规划契约与事件投影

**Files:**
- Create: `backend/app/services/replanning/suffix_planner.py`
- Modify: `backend/app/services/replanning/__init__.py`
- Modify: `backend/app/schemas/planning.py`

1. 定义 `EventDrivenReplanRequest`、`SuffixPlanningInput`、`SuffixPlanner`。
2. 实现生产默认 `DeterministicRetainedSuffixPlanner`。
3. 实现事件校验、连续冻结边界和严格后缀输出验证。
4. 跑领域/契约定向测试至 GREEN。

### Task 3: 接入应用边界与 HTTP

**Files:**
- Modify: `app/application/planning_boundary_service.py`
- Modify: `app/api/planning_routes.py`
- Modify: `app/main.py`

1. 注入默认 suffix planner。
2. 新增 `generate_v2_from_events`，读取签发 V1、可信 facts 与执行事件。
3. 组装全量 request 后复用现有 `generate_v2`。
4. 新增 `/replans/from-events` 路由。
5. 运行黄金、负路径、现有 planning/PlanVersion/T019 回归至 GREEN。

### Task 4: 前端切换到服务端事件重规划

**Files:**
- Modify: `frontend/src/domain/trip.ts`
- Modify: `frontend/src/api/tripApi.ts`
- Modify: `frontend/src/pages/WorkspacePage.tsx`
- Create: `frontend/tests/eventDrivenReplan.test.ts`
- Modify: `frontend/package.json`

1. 先写请求路径/载荷契约红测。
2. 增加类型与 API 方法。
3. 删除 Workspace 的客户端 `buildAmapReplanCandidate` V2 路径，改调事件重规划接口。
4. 保留 V1 AMap/证据确认、Diff、接受/拒绝流程。
5. 跑前端 test/lint/build 至 GREEN。

### Task 5: 追溯、独立验收和全量回归

**Files:**
- Create: `docs/testing/evidence/s1_t017/clean-slice-acceptance.md`
- Create: `docs/handoffs/s1-t017-and-ui-followups.md`

1. 真实 SQLite/ASGI 运行 V1→执行事件→V2→Diff→接受/拒绝黄金链。
2. 检查 plan_versions、execution_events、trusted_plan_issuances 的行数和状态。
3. 运行后端全量、前端 test/lint/build、compileall、`git diff --check`。
4. 独立审查 T017/T018 边界、默认生产装配和 UNKNOWN fail-closed。
5. 输出队友必须/建议/不要做清单。
