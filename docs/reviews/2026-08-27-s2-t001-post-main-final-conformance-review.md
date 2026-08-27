# S2-T001 主线合并后最终产品一致性复核

> 复核日期：2026-08-27
> 复核结论：`SPEC_PASS_POST_MERGE`
> 分支：`czy-S2-T001`
> 复核目标 HEAD：`39446b6ba8f569f0f8040df6ca6cfcbd488c3b5b`
> 待验 merge commit：`7f130242209f34ab6219cb43ffac554a9300b25d`
> merge parents：`05a5520d65296ad2ce5c402a32c1a468740fd1ef`、`b0cf25e279deb3626d55d077b6122ff82cd96a6c`
> 第二轮 QA：`docs/testing/2026-08-27-s2-t001-post-main-integration-acceptance-report.md`

## 1. 最终结论

经提交对象、双亲差分、控制流、测试迁移、发布资产和新鲜自动化复跑交叉核对，merge tree 完整保留最新 main 与 S2-T001 两侧语义，并严格落实最新 `INTEGRATION_DECISION`：仅开放 `CandidatePlanRequest → DeterministicCandidatePlanner → CandidatePlan → fairness` 的 GROUP 2—3 人候选能力，正式 PlanVersion 与执行状态链仍失败关闭。

未发现需退回工程窗口的产品、契约、范围或证据缺陷。当前分支可交回版本管理器；最终测试口径为后端全量 **419 passed、exit 0**，不再沿用旧 main 的四个 collection errors 基线。

## 2. 六项委派要求复核

### 2.1 `trip_draft` 语义合并

`app/domain/trip_draft.py` 相对 T001 父提交只增加 main 已有的：

- `recognitionSource`；
- `recognitionModel`；
- `degradedReason`。

相对 main 父提交则完整增加 T001 的 `UnderstandingContractModel`、请求/提案 DTO、成员级 evidence/missing/ambiguity/question/careDraft 语义校验和上下文绑定 validator。两侧没有字段删除或隐式替换：旧 `DraftContractModel` 仍保持原兼容行为，TripUnderstanding 单独使用 strict、camelCase、extra-forbid，且 `validate_trip_understanding_json()` 同时严格解析 request/proposal 并核验来源上下文。

`frontend/src/domain/trip.ts` 同样同时保留 main 的三项识别元数据和 T001 的 `TripMode`、`CreateDayTrip`、旧单人窄入口。该合并没有丢失百炼运行时可观察字段，也没有放宽 T001 strict 契约。

结论：PASS。

### 2.2 GROUP 候选层与正式状态链

`backend/app/services/planning/models.py` 明确接受：

- `SINGLE + 1`；
- `GROUP + 2`；
- `GROUP + 3`。

其余模式/人数冻结组合均拒绝，并保留规划状态、单日、3—4 任务、时间窗、任务顺序和事实形状校验。planner 入口继续执行 JSON round-trip strict 重验证，因此伪造的 `model_copy()` 对象不能绕过门禁。

`backend/app/services/planning/planner.py` 对所有成员取最低预算上限，逐成员编译关怀约束，保留精确重复去重、LTE 取严格值、不可合并冲突 fail-close、完整请求摘要和既有路线/费用/来源校验。T007 fairness 按 participants 原顺序逐成员执行 HARD 预算、MUST_VISIT、AVOID_PLACE 和满意度评分。

候选转 V1/V2 的两个 bridge 在持久化前均显式拒绝 GROUP，稳定错误码为 `GROUP_PLAN_VERSION_UNSUPPORTED`。同时：

- `PlanReviewTripSnapshot` 仍是 `mode=SINGLE`、exact-one；
- `WorkflowService.confirm_trip()` 与 workflow store 仍接收 `CreateSingleDayTrip`；
- 前端 `CandidatePlanningTrip.mode` 仍是 literal `SINGLE`；
- PlanVersion、ExecutionEvent、Diff Schema 与状态机未被本补丁放宽。

结论：候选层扩展符合裁决，正式版本/执行状态链未开放，PASS。

### 2.3 手工合并与白名单

`git diff-tree -c` 识别到七个双方均有变化的手工合并/补丁路径：

1. `app/domain/trip_draft.py`；
2. `backend/app/services/planning/models.py`；
3. `backend/app/services/planning/planner.py`；
4. `backend/tests/test_candidate_planner.py`；
5. `backend/tests/test_s2_t007_fairness.py`；
6. `backend/tests/test_s2_t009_recommendation_orchestration.py`；
7. `frontend/src/domain/trip.ts`。

其中 `trip_draft.py` 与前端 DTO 属于冻结 T001 白名单；两个 planner 文件和三份测试属于 `INTEGRATION_DECISION` 批准的最小生产/测试白名单。相对 main 父提交共有 23 个差异路径，其余均为冻结 T001 Schema、发布物、Fixture、快照、测试及证据文档。没有白名单外生产扩张。

结论：PASS。

### 2.4 单人兼容、发布 Schema 与 golden

以下 Git blob 在两个父提交、merge commit 与第二轮 QA HEAD 上完全相同：

| 资产 | Git blob |
|---|---|
| `backend/schemas/trip.schema.json` | `ec7511385ea4cf60b94dfda07169734665609dd7` |
| `backend/tests/snapshots/create_single_day_trip.schema.json` | `ec7511385ea4cf60b94dfda07169734665609dd7` |
| `backend/tests/fixtures/trips/beijing.json` | `d3b60b48eaf07fa157d89a86ff5d87052bf1d352` |
| `backend/tests/fixtures/trips/shanghai.json` | `a6ab053a49ea1869a41c7387c8278ef099571337` |
| `backend/tests/fixtures/trips/chengdu.json` | `fc32f2dd68f36f5aeb98e217d8e16a96310ab887` |
| `backend/tests/fixtures/planning/golden_candidate_plan.json` | `2c2b275bae000b73d12a901a0e673771e481e825` |

旧 `validate_trip_json()`、`CreateSingleDayTrip`、单人 candidate golden 与 candidateId 断言继续通过。新增统一 Schema/Fixture 没有覆盖旧发布物。

结论：PASS。

### 2.5 QA 数字与控制流

第二轮 QA 报告的数字与本次新鲜复跑一致：

| 门禁 | 本次结果 | 退出码 |
|---|---:|---:|
| G01：Trip + TripUnderstanding | `64 passed` | 0 |
| G02：关怀 + TripDraft LLM + fairness | `31 passed` | 0 |
| G03：planner/PlanReview/workflow/replan/execution | `82 passed` | 0 |
| T009 专项 | `16 passed` | 0 |
| 仓库根后端全量 | `419 passed` | 0 |
| `backend/` cwd 后端全量 | `419 passed` | 0 |
| 前端测试 | `32 passed, 0 failed, 0 skipped` | 0 |
| 前端 build | `1836 modules transformed` | 0 |

首次后端复跑因当前沙箱拒绝 pytest 写入用户 Temp，出现 `tmp_path` setup PermissionError；将 TEMP/TMP 明确指向目标 worktree 外的专用可写验证目录并关闭 cacheprovider 后，两种 cwd 均完整收集并通过 419 项。该环境重跑没有代码变更，也没有被计入产品失败。

生产控制流核对确认：T009 route candidate 必须先经 `DeterministicCandidatePlanner.generate()`，成功 CandidatePlan 才进入 fairness；没有把 GROUP 改写为 SINGLE，也没有通过异常捕获将失败候选伪装为成功。QA 的八项 UAT 与隔离库证据同实现控制流和自动化断言一致。

结论：QA 数字与提交/控制流一致，PASS。

### 2.6 清洁度与交回条件

`git ls-tree` 未发现提交的 `.sqlite`、`.sqlite3`、`.pytest_cache`、`__pycache__`、`.pyc`、tmp 或 temp 产物。复核前后工作树仅有两份既有未跟踪 SQLite：

- `backend/data/amap_cache.sqlite3`：16384 bytes，SHA-256 `84E262DC234FC544BF1A10DDBCFAA68FAA870616EA8D23509ABE3BE8AEB3FAE5`；
- `backend/data/plan_versions.sqlite3`：151552 bytes，SHA-256 `07945745B12629A80290127FC6FFC79A30FF03E35B65F79E147B140433FC3892`。

两份文件未暂存、未提交，哈希未变化。除本报告外无 tracked/staged 变更。

结论：可交回版本管理器，PASS。

## 3. 最终提交链

版本管理器应接收以下完整 S2-T001 证据链，并保留 merge commit 的 main 第二父历史：

1. `cbcbc6d181fe8c57b6171137ea66700e45eacc56` — 初版冻结设计；
2. `976b261f9f154b55ddc86d17f552bd690b4dad5b` — 路径修订设计；
3. `c5357e7d1ef78754a5aff25a114bd67ad1eb005b` — 独立测试计划；
4. `510cad30b54fb7ce531c89b27cf597092dd21c4a` — T001 业务实现；
5. `5ccbd3a70a4380d7971e433f64ab0cac0c2d3a18` — 首轮独立 QA；
6. `05a5520d65296ad2ce5c402a32c1a468740fd1ef` — 首轮最终一致性复核；
7. `b0cf25e279deb3626d55d077b6122ff82cd96a6c` — 最新 main 第二父；
8. `7f130242209f34ab6219cb43ffac554a9300b25d` — 主线语义合并与 GROUP 候选边界修复；
9. `39446b6ba8f569f0f8040df6ca6cfcbd488c3b5b` — 第二轮独立 QA 报告；
10. 本最终复核报告提交。

## 4. 版本管理器结论

`SPEC_PASS_POST_MERGE / READY_FOR_VERSION_MANAGER`

版本管理器可以接收本提交链。后端最终口径为 419 passed、exit 0；前端为 32 passed、build exit 0；不得再引用旧 main 的四个 collection errors 作为当前限制。
