# 林粲涵 Sprint 1 Day 2 代码追溯

本页的核心任务归属为 `S1-T011`、`S1-T018`、`S1-T022`，并记录它们与其他负责人模块的真实运行时联动。历史兼容基线是团队 `origin/main` 提交 `3b9321c39e794a3e1bcc782cb947219bff197c3d`；历史融合提交是 `9a7c290a3af2fe7a4afc9627090366fdc0150299`，核心融合代码提交是 `d43442c8ada3c741ed43b629aec5b20a291cae07`。本次验收已在更新后的远端 main `3e60435fcfde0705149dbc5f340d60e1aa63103c` 上复跑。逐文件机器可读证据见 `lin_canhan_day2.json`。

## PBI → AC → Task → 模块 → 测试

| PBI / AC | Task | 生产模块 | 验收证据 | 上游 → 下游 |
|---|---|---|---|---|
| PBI-04-A / AC-04-A | S1-T011 | `services/planning`、后端可信规划边界及前端候选构造器 | 只接受 T002 已确认并持久化的 canonical Trip 与 T004 已确认画像；校验 3–4 个任务、固定起终点、独立 `RETURN` 任务和路线连续性；T007 关怀约束、T006 路线/价格事实、T009 风险、预算与时间均由服务端重算；T010 设施/价格 `UNKNOWN` 会 fail-closed | T002 + T004 + T006 + T007 + T009 + T010 → T011 → T012 / T018 / T024 |
| PBI-05-B / AC-05-B | S1-T018 | `services/replanning`、可信事实存储及 `/replans` 运行时边界 | 冻结已完成/跳过/锁定前缀；每个候选先经过 T011 重算，再按最少改动数、满意度损失和稳定摘要选优；预算包含 T016 实际消费；只有被选中的 V2 可由服务端登记并签发，且必须继承一个已签发、摘要匹配的当前 V1 | T011 + T013 + T016 + T017 输入边界 → T018 → T019 / T024 |
| PBI-06-A / AC-06-A | S1-T022 | `services/summary_trace` 与真实 HTTP/SQLite 流程 | 无 V2、接受 V2、拒绝 V2 三条路径均改用服务端签发的 V1/V2（`ISSUED` + canonical digest）；每个公开整数都有 PlanVersion 谱系，并在适用时带 Task/Event 谱系；错误的 planVersion→task 归属会 fail-closed；不依赖照片 | T021 → T022 → T024 |

## 关键运行时联动

- `S1-T002 → S1-T011`：`POST /api/v1/trips/drafts/confirm` 持久化完整 canonical `CreateSingleDayTrip`。规划请求必须与这份已确认 Trip 精确一致，仅允许状态从 `DRAFT` 进入 `PLANNING`；不存在时返回 `TRIP_NOT_CONFIRMED`，内容冲突时返回 `CONFIRMED_TRIP_MISMATCH`。语义相同的重试复用首次确认结果，不能用客户端新造数据替换可信输入。
- `S1-T004 → S1-T011`：V1 生成必须读取已确认的出行者画像。未确认画像不能越过后端边界进入候选计划验收，因此 T007 关怀约束始终基于已确认画像重新编译。
- `POST /api/v1/trips/{tripId}/plan-versions/generate` 是 V1 的可信入口。服务端验证 canonical Trip、已确认画像和候选事实，执行 T011 后登记并把 V1 标记为 `ISSUED`；客户端不能自报 `PASS`、`planId` 或可信摘要。
- `POST /api/v1/trips/{tripId}/replans` 是 V2 的可信入口。每个候选先执行 T011，T018 只从通过验证的候选中选择一个；只有选中 V2 会被登记和签发。签发前还会验证当前父 V1 已是 `ISSUED` 且 canonical digest 匹配，防止未签发或被篡改的旧 V1 被用来建立 V2 谱系。
- 原始 `POST /api/v1/trips/{tripId}/plan-versions` 始终返回 `403 PLAN_VERSION_DIRECT_REGISTRATION_FORBIDDEN`。确认 V1、接受 V2 也要求目标版本已由服务端签发且摘要一致，不能绕过可信边界直接写入 PlanVersion。
- `GET /api/v1/trips/{tripId}/planning-facts` 返回当前已签发版本对应的原始可信事实。前端刷新后通过该接口恢复事实和版本上下文，而不是从浏览器缓存重建或伪造验证结果。
- 前端候选构造器使用确认页传入的 canonical Trip，地理编码固定起点和终点，生成 3 个游玩 POI，并额外生成独立 `RETURN` 任务返回固定终点。正反测试覆盖 3–4 个任务、路线链连续、固定端点和缺失/篡改返回段。
- T011 不接受模型或客户端自报的 PASS。它重新编译 T007 关怀约束，校验路线首尾坐标、段间连续性和通勤耗时，调用 T006→T009 适配链重算路线风险，并从 Place/Route 原始价格事实按整数分重算预算。
- `S1-T010 → S1-T011`：`Route.facilityEvidence` 提供电梯、坡道、母婴室和无障碍入口事实；四类设施或价格事实缺失、重复、`NEEDS_CONFIRMATION` 或 `UNKNOWN` 都会阻止计划确认。已确认的 `FAIL` 保留为 SOFT 快照供审核。
- `S1-T016 → S1-T018`：带时区的 `ExecutionEvent.EXPENSE` 与整数分 `amountCents` 作为不可变实际消费参与“已发生费用 + 剩余计划费用”重算，同一任务不会重复计入计划成本。
- `S1-T013 → S1-T018`：PlanVersion 唯一性守卫覆盖选中 V2 的真实 SQLite 登记；首次登记成功，重复登记返回 `PLAN_VERSION_ALREADY_EXISTS`/409，数据库状态保持不变。
- `S1-T022` 的无 V2、接受 V2、拒绝 V2 测试均走上述服务端签发路径；Summary 只读取 T021 结果、完整 PlanVersion 快照及真实任务/事件谱系，不改 Summary，也不虚构任务、事件、版本或图片证据。

## T017 边界声明

最新版 main 仍没有 `S1-T017` 的自主多候选生成器。当前运行时由前端 `amapPlan` 流程向 `POST /api/v1/trips/{tripId}/replans` 提交 **1 个 provider candidate**，后端负责 T011 重算、T018 选择及选中 V2 的签发闭环。这里不把该单候选供应方式记作 T017 已完成，也不声明自主生成、并行多候选或线上供应器组装已经交付；如果验收要求 T017 自主生成多个候选，仍需对应负责人补齐。

## 本地验收

在仓库根目录执行：

```powershell
python -B -m pytest -p no:cacheprovider -q
python -B -m pytest -p no:cacheprovider -q backend/tests/test_candidate_planner.py backend/tests/test_minimum_disruption_replanning.py backend/tests/test_planning_replanning_integration.py backend/tests/test_planning_http_boundaries.py backend/tests/test_s1_t022_summary_paths.py backend/tests/test_trip_draft_llm_integration.py backend/tests/test_s1_t017_event_replan.py
cd frontend
npm test
npm run build
npm run lint
```

本次远端 main 测试支持迁移验收结果：排除尚未纳入 Sprint1 的 S2-T008 新测试后，后端 `167 passed`；Day2/runtime 聚焦回归 `68 passed`；前端测试 `31/31 passed`；前端 build 与 lint 均通过。PR、CI Build、QA 和 PO 属于外部证据，当前没有时保持为空，不以本地结果冒充。
