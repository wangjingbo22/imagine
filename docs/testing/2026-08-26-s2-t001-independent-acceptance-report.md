# S2-T001 多成员 Trip 与 TripUnderstanding 独立验收报告

> 验收日期：2026-08-26（Asia/Shanghai）
>
> 验收结论：`QA_PASS`（契约范围通过；后端全量仍受四个既有 collection errors 限制，不是全量绿色）
>
> 创建基线：`origin/main@b88aeee441f1160243acf55521d50e4e1c26d7b9`
>
> 修订设计：`976b261f9f154b55ddc86d17f552bd690b4dad5b`
>
> 独立测试计划：`c5357e7d1ef78754a5aff25a114bd67ad1eb005b`
>
> 待验业务提交：`510cad30b54fb7ce531c89b27cf597092dd21c4a`
>
> 分支/工作树：`czy-S2-T001` / `C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.worktrees\czy-S2-T001`

## 1. 独立结论

S2-T001 在冻结契约范围内通过独立测试与验收：权威 Trip 的 SINGLE/GROUP 人数边界、旧单人窄入口、新 `CreateDayTrip`、严格 `TripUnderstanding` 请求/提案、证据与问题闭环、关怀草稿、GROUP 下游失败关闭，以及前端纯 DTO 镜像均满足设计要求。

本轮没有修改生产代码，没有替工程师修缺陷，没有 merge、push 或 deploy。验收未发现 S2-T001 新增缺陷。

后端全量命令不能标记为绿色：在 `b88aeee` 基线和业务提交上，仓库根与 `backend/` 两种 cwd 均精确复现同四个 `ModuleNotFoundError` collection errors、exit 2。该限制已通过 Git 树和同命令复跑独立确认，未计入 S2-T001 新缺陷。

## 2. 提交、白名单与兼容门禁

### 2.1 提交关系

- HEAD 与待验 SHA 一致：`510cad30b54fb7ce531c89b27cf597092dd21c4a`。
- 修订设计与独立测试计划均为待验业务提交祖先。
- 当前确认为 linked worktree，分支为 `czy-S2-T001`。

### 2.2 业务提交文件

业务提交只修改/新增以下 14 个冻结白名单路径：

```text
app/domain/trip_draft.py
backend/app/schemas/trip.py
backend/schemas/create-day-trip.schema.json
backend/schemas/trip-understanding.schema.json
backend/tests/fixtures/trip_understanding/one_participant.json
backend/tests/fixtures/trip_understanding/three_participants.json
backend/tests/fixtures/trip_understanding/two_participants.json
backend/tests/fixtures/trips/group_three_participants.json
backend/tests/fixtures/trips/group_two_participants.json
backend/tests/snapshots/create_day_trip.schema.json
backend/tests/snapshots/trip_understanding.schema.json
backend/tests/test_trip_schema.py
backend/tests/test_trip_understanding_schema.py
frontend/src/domain/trip.ts
```

`backend/app/domain/trip_draft.py` 不存在，没有创建不可达影子模块。

### 2.3 旧资产逐字节兼容

以下旧资产相对修订设计提交执行 `git diff --exit-code`，结果为 0：

```text
backend/schemas/trip.schema.json
backend/tests/snapshots/create_single_day_trip.schema.json
backend/tests/fixtures/trips/beijing.json
backend/tests/fixtures/trips/shanghai.json
backend/tests/fixtures/trips/chengdu.json
```

## 3. G01—G07 实际结果

| 门禁 | 实际执行与统计 | 结论 |
|---|---|---|
| G01 T001 定向契约 | `test_trip_schema.py` + `test_trip_understanding_schema.py`：`64 passed in 0.24s` | PASS |
| G02 兼容回归 | AssistanceProfile、TripDraft LLM、公平性：`29 passed in 0.34s` | PASS |
| G03 可运行旧链 | planner/replanning `37 passed`；约束、百炼 extractor、route risk、T024 黄金链等 `52 passed`；Day1 traceability `2 passed`；合计 `91 passed` | PASS |
| G03 GROUP 失败关闭探针 | CandidatePlanRequest、PlanReviewTripSnapshot、旧 CreateSingleDayTrip、TripDraft/workflow 窄类型边界均拒绝；未调用 planner/store/event | PASS |
| G04 前端 | `npm.cmd test`：`31 passed, 0 failed, 0 skipped, 0 todo`；`npm.cmd run build` exit 0，Vite 转换 1834 modules | PASS |
| G05 根目录全量 | 当前提交：4 collection errors、exit 2；与 `b88aeee` 根目录同命令结果完全相同 | BASELINE_MATCH |
| G06 backend 目录全量 | 当前提交：4 collection errors、exit 2；与 `b88aeee` backend 目录同命令结果完全相同 | BASELINE_MATCH |
| G07 清洁度 | 无 tracked/staged diff；旧资产无漂移；仅保留验收前已存在的两份未跟踪 SQLite | PASS |

不重复计数时，本轮实际通过：

- 后端 pytest 定向及所有可运行相关旧链：`184 passed`；
- 前端 Node tests：`31 passed`；
- 独立契约 UAT：`7/7 passed`；
- 前端 build：`1/1 passed`；
- GROUP 失败关闭：1 个独立脚本，覆盖 4 组边界断言。

后端全量因 collection 中断，没有可诚实报告的“全量 passed 数”；本报告不以定向 184 passed 冒充全量结果。

## 4. 后端既有 collection 基线差分

### 4.1 Git 树证据

- `git ls-tree -r --name-only b88aeee... -- tests` 无输出；基线根级 `tests/` 没有文件。
- 业务提交的根级 `tests/` 同样无文件。
- `pyproject.toml` 在基线与业务提交均为：`pythonpath=[".", "backend"]`、`testpaths=["backend/tests", "tests"]`、`--import-mode=importlib`。
- 四个出错测试文件及其缺失模块导入在基线与业务提交之间无 diff。

### 4.2 两个 cwd、两个提交的相同指纹

四次执行均 exit 2，均在收集阶段中止，错误集合完全相同：

| 出错测试 | 缺失模块 |
|---|---|
| `backend/tests/test_day2_duplicate_plan_registration.py` | `tests.test_plan_v2_diff`；同时依赖 `tests.test_plan_versions` |
| `backend/tests/test_planning_http_boundaries.py` | `tests.test_plan_versions` |
| `backend/tests/test_s1_t017_event_replan.py` | `tests.test_plan_versions` |
| `backend/tests/test_s1_t022_summary_paths.py` | `tests.test_plan_versions` |

对比组合：

```text
b88aeee / repository root / python -m pytest -q -> 4 collection errors, exit 2
b88aeee / backend cwd    / python -m pytest -q -> 4 collection errors, exit 2
510cad3 / repository root / python -m pytest -q -> 4 collection errors, exit 2
510cad3 / backend cwd    / python -m pytest -q -> 4 collection errors, exit 2
```

因此先前设计文档记录的 `181 passed, 2 failed` 来自不同文件状态，不适用于本次冻结 Git 树。四个错误属于既有基线，未出现第五个 collection error、不同缺失模块或 S2-T001 新失败。

## 5. 关键契约矩阵结果

### 5.1 Trip 与创建入口

- SINGLE 仅接受 1 人；0、2、3、4 人拒绝。
- GROUP 接受 2、3 人；0、1、4 人拒绝。
- 2/3 人 GROUP Fixture 使用不同 UUID、昵称、预算和成员资料并可严格往返。
- `validate_trip_json()` 仍拒绝 GROUP，继续返回旧 `CreateSingleDayTrip`。
- `validate_create_day_trip_json()` 接受合法 SINGLE 1 人和 GROUP 2/3 人。
- 新 CreateDayTrip Schema、快照和发布物一致；旧 Schema/快照未改变。

### 5.2 TripUnderstanding

- request/proposal 采用 strict JSON、camelCase、`schemaVersion=1.0` 和各层 extra-forbid。
- 字符串金额、浮点整数、数字布尔、未知枚举、非法日期/时间和注入字段被拒绝。
- 1/2/3 人 Fixture、memberKey 连续性、CanonicalFieldPath、成员键/索引和列表索引均通过正负验证。
- 每个非空标量/列表项需要证据；USER_TEXT 与 rawConversation、EXPLICIT_FIELD 与规范显示值通过请求上下文绑定。
- missing/ambiguity/question 三元组闭环、candidates/choices 一致、孤儿问题和重复项均有负向覆盖。
- 空壳 careDraft 被拒绝；儿童年龄、步行阈值、关怀证据和成员归属通过验证。
- `participantId`、Constraint、Provider、plan、score、确认状态和运行时元数据均不能进入提案。

### 5.3 下游失败关闭

合法 GROUP Trip 在 `CandidatePlanRequest` 上得到明确 `T011 only supports SINGLE trips` 拒绝；PlanReviewTripSnapshot 和旧 CreateSingleDayTrip 同样在单人边界拒绝。TripDraft ParseResult、require-planning-ready 和 Workflow confirm 的类型仍收窄为 `CreateSingleDayTrip`。独立探针没有调用 planner、store 或 event，因此没有只读取 `participants[0]` 后继续执行的副作用。

### 5.4 前端 DTO

- `TripMode = 'SINGLE' | 'GROUP'`。
- `CreateDayTrip` participants 为 1/2/3 人 tuple union。
- `CreateSingleDayTrip.mode` 和 `CandidatePlanningTrip.mode` 均显式为 `'SINGLE'`。
- `TripDraftParseResult.trip` 仍为 `CreateSingleDayTrip | null`。
- 业务提交未修改前端页面、API 行为或 WorkspacePage。

## 6. 用户可观察契约 UAT

UAT 采用冻结计划约定的 DTO/Fixture 边界，不调用真实 LLM，不宣称 T001 已提供多人 UI。

| UAT | 实际结果 | 结论 |
|---|---|---|
| UAT-01 “我一个人，北京一天，预算 500 元” | 1 张 member-1 卡；北京与 50000 分有原文证据；旧单人链回归通过 | PASS |
| UAT-02 两人不同预算/兴趣/少走路 | 两卡预算 50000/30000，博物馆与 LOW_STAMINA 分别绑定 member-1/member-2 | PASS |
| UAT-03 三人、6 岁孩子与老人 500 米 | childAge=6 位于 member-2；maxContinuousMeters=500 位于 member-3 | PASS |
| UAT-04 “我们几个人去上海” | 保留一个组织者；产生 participants + PARTY_SIZE missing/question 闭环，不猜人数 | PASS |
| UAT-05 同成员想去且避开外滩 | mustVisit/avoidPlaces 均保留且有证据；无 HARD/Constraint 裁决 | PASS |
| UAT-06 注入/字符串预算/第 4 人 | participantId、字符串金额和第 4 人全部严格拒绝 | PASS |
| UAT-07 GROUP 送入旧 planner | 在 CandidatePlanRequest 显式拒绝，无候选计划 | PASS |

## 7. 工作树与 SQLite 产物

验收前后 `git status --short --untracked-files=all` 均只显示：

```text
?? backend/data/amap_cache.sqlite3
?? backend/data/plan_versions.sqlite3
```

两份文件在验收前后大小、修改时间和 SHA-256 完全一致：

| 文件 | 大小 | SHA-256 |
|---|---:|---|
| `backend/data/amap_cache.sqlite3` | 16384 bytes | `84E262DC234FC544BF1A10DDBCFAA68FAA870616EA8D23509ABE3BE8AEB3FAE5` |
| `backend/data/plan_versions.sqlite3` | 102400 bytes | `029A2BA0CF019C675B60DD62C6EA7FF4C0CA91A6FADC9C0BB36E342753D8F5A4` |

它们不在业务 commit，也不进入本报告 commit；按委派要求未删除。基线差分使用的 `.qa-baseline-b88aeee/` 临时目录已限定清理，不残留工作树状态。

## 8. 缺陷与限制

- S2-T001 新缺陷：0。
- P0/P1/P2/P3 缺陷单：无。
- 已知限制：四个既有 collection errors 阻止后端全量收集和全绿声明；修复归属不在 S2-T001。
- 既有 `test_day2_traceability.py` 没有作为 S2-T001 放行门禁；全量收集在其执行前已被上述四个错误中止。本轮没有改动该文件或其依赖。

## 9. 最终产品分析复核入口

最终产品分析应按以下顺序复核：

1. 设计契约：`docs/superpowers/specs/2026-08-26-s2-t001-multi-participant-contract-design.md` @ `976b261f...`；
2. 独立测试计划：`docs/testing/2026-08-26-s2-t001-independent-test-plan.md` @ `c5357e7d...`；
3. 业务实现：`510cad30b54fb7ce531c89b27cf597092dd21c4a`；
4. 本独立验收报告：`docs/testing/2026-08-26-s2-t001-independent-acceptance-report.md`；
5. 特别核对本报告第 4 节：全量基线是四个既有 collection errors，不能写成“后端全量通过”。

最终签字：`QA_PASS`。分支保持原状，不合并 main、不推送、不部署。
