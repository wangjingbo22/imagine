# S2-T001 主线语义合并后独立验收报告

> 验收日期：2026-08-27
> QA 结论：`QA_PASS_POST_MERGE`
> 目标分支：`czy-S2-T001`
> 待验 merge commit：`7f130242209f34ab6219cb43ffac554a9300b25d`
> 双亲：`05a5520d65296ad2ce5c402a32c1a468740fd1ef`、`b0cf25e279deb3626d55d077b6122ff82cd96a6c`
> 冻结设计：`976b261f9f154b55ddc86d17f552bd690b4dad5b`
> 独立测试计划：`c5357e7d1ef78754a5aff25a114bd67ad1eb005b`

## 1. 独立结论

本轮未沿用首轮结论，而是在新 merge commit 上从头执行静态审计、G01—G07、T009 专项、契约 UAT 与零副作用探针。结果满足最新 `INTEGRATION_DECISION`：

- 主线百炼草稿识别元数据与 T001 严格 TripUnderstanding 契约同时保留；
- 候选规划层接受 `SINGLE+1`、`GROUP+2/3`，拒绝其余冻结组合，且 `model_copy()` 不能绕过重校验；
- GROUP 2/3 人可生成确定性 CandidatePlan，并保留全体成员预算、HARD 关怀、事实与公平评分；
- GROUP 候选不能进入 V1/V2 ProposedPlanVersion，PlanReview、Workflow、Store、ExecutionEvent、Diff 继续失败关闭；
- 旧单人 golden、candidateId 断言、发布 Schema、快照与 Fixture 无变化；
- 后端全量、前端测试与构建全部绿色，无任何基线例外或新增失败。

本轮没有发现需退回代码窗口的 P0—P3 缺陷。

## 2. 冻结裁决与范围审计

正式 `INTEGRATION_DECISION` 来自实现分析任务 `01a03d27-0df7-7a31-97fb-d062a7a182f5` 的最新一轮。QA 采用其最新裁决：只扩展 `CandidatePlanRequest → DeterministicCandidatePlanner → CandidatePlan → fairness` 的 GROUP 2—3 人能力，不扩展正式版本与执行状态链。

相对最新 main 父提交 `b0cf25e...`，merge tree 有 23 个差异路径，均属于冻结的 T001 契约/发布物/Fixture/测试/文档、语义冲突文件 `app/domain/trip_draft.py`，以及裁决批准的 planner/fairness/T009 集成补丁。未发现白名单外生产扩张。

`git ls-tree`、双亲差分和工作树扫描均未发现被提交的 `.sqlite`、`.sqlite3`、`.pytest_cache`、`__pycache__`、`.pyc`、tmp 或 temp 产物。

## 3. 关键语义验收

| 冻结要求 | 独立证据 | 结果 |
|---|---|---|
| 百炼元数据与 T001 严格契约并存 | `TripDraftParseResult` 保留 `recognitionSource`、`recognitionModel`、`degradedReason`；独立 `UnderstandingContractModel` 使用 strict、camelCase、extra-forbid；`validate_trip_understanding_json()` 同时解析 request/proposal 并校验 `sourceText` 上下文 | PASS |
| CandidatePlanRequest 模式矩阵 | 接受 SINGLE+1、GROUP+2/3；拒绝 SINGLE+0/2/3、GROUP+0/1/4；planner 在入口重新 JSON 序列化并 strict 校验，绕过探针得到 `CANDIDATE_PLAN_INPUT_INVALID` | PASS |
| GROUP 确定性候选 | 2 人 candidateId 为 `candidate-5b0ebb32b6232b287df7ebbc`；3 人为 `candidate-f4380cd0f5612299fca116eb`；同输入重复结果逐对象相等 | PASS |
| 预算、关怀与事实不丢 | 预算上限取 Trip 总预算、日预算和所有成员预算上限最小值；逐成员编译关怀，精确重复去重、LTE 取严格值、不可合并冲突失败关闭；FactRef/起终点/Trip/confirmedConstraints 一致性检查保持 | PASS |
| 三人公平评分 | 三人 GROUP 返回按 participants 原顺序排列的 3 份 `participantScores`；HARD 预算、MUST_VISIT、AVOID_PLACE 逐成员执行 | PASS |
| T009 完整链 | `16 passed, 0 failed, 0 xfail`；生产控制流中每个可用 route candidate 先调用 planner，成功 CandidatePlan 才进入 fairness；GROUP 未改写为 SINGLE | PASS |
| GROUP→版本/执行失败关闭 | V1/V2 bridge 均返回 `GROUP_PLAN_VERSION_UNSUPPORTED`；PlanReview 拒绝 GROUP；隔离数据库中的 Workflow/Store/Event/Diff 操作均失败，四张状态表行数保持 0 | PASS |
| 旧单人兼容 | 相对两个父提交，旧 `trip.schema.json`、`create_single_day_trip` 快照、北京/上海/成都 Fixture 与 planning golden 均无 diff；旧 golden candidateId 断言通过 | PASS |

## 4. 自动化执行记录

以下命令均在目标 linked worktree 上使用仓库 `.venv` 独立执行。定向门禁是后端 419 项全量中的子集，不重复计入唯一测试总数。

| 门禁 | 实际结果 | 退出码 |
|---|---:|---:|
| G01：`test_trip_schema.py` + `test_trip_understanding_schema.py` | `64 passed` | 0 |
| G02：关怀 Schema + TripDraft LLM + fairness | `31 passed` | 0 |
| G03：planner、PlanReview、workflow、重规划与执行回归 | `82 passed` | 0 |
| T009 独立专项 | `16 passed` | 0 |
| G04：`npm.cmd test` | `32 passed, 0 failed, 0 skipped` | 0 |
| G04：`npm.cmd run build` | TypeScript + Vite 成功，1836 modules transformed | 0 |
| G05：工作树根 `python -m pytest -q` | `419 passed` | 0 |
| G06：`backend/` 目录 `python -m pytest -q` | `419 passed` | 0 |
| G07：`git diff --check` | 无输出 | 0 |

准确的唯一全量计数为：后端 **419 passed**、前端 **32 passed**；前端 build exit 0。没有 failure、error、collection error、skip 或 xfail。

pytest 仅报告无法创建工作树 `.pytest_cache` 的 `PytestCacheWarning`；测试退出码与断言不受影响，且工作树中没有生成该目录或其他 pytest 产物。

## 5. 用户可观察 UAT

| 场景 | 用户可观察结果 | 结果 |
|---|---|---|
| UAT-01 单人旧入口 | 单人请求继续生成 `member-1` 与旧 CreateSingleDayTrip；解析/确认与识别来源状态兼容 | PASS |
| UAT-02 两人理解 | 两张连续成员卡、预算/兴趣/少走路证据绑定正确 memberKey/path | PASS |
| UAT-03 三人关怀 | 三张成员卡；儿童年龄与老人步行上限保留在各自 careDraft，证据不串人 | PASS |
| UAT-04 人数未知 | 不猜 2/3 人，返回 PARTY_SIZE missing/question 闭环 | PASS |
| UAT-05 冲突输入 | mustVisit/avoidPlaces 与各自证据均保留，不伪造 HARD 裁决字段 | PASS |
| UAT-06 注入与类型欺骗 | participantId、权威状态、计划/评分/Provider 字段、字符串预算、第 4 人与越界路径均 strict 拒绝 | PASS |
| UAT-07 多人候选与公平性 | 2/3 人 GROUP 生成确定性 CandidatePlan；三人显示三份公平分数；T009 返回唯一推荐 | PASS |
| UAT-08 版本与执行边界 | 用户不能把 GROUP 候选确认为 V1/V2；后续确认、执行事件和 Diff 均无状态副作用 | PASS |

UAT 是公开 DTO/Fixture、确定性 planner/fairness 与隔离状态库边界验收；没有把 T001 范围外的真实 LLM 文案稳定性或多人 UI 页面冒充为本任务能力。

## 6. 零副作用与工作树清洁度

隔离库探针实际返回：

```json
{
  "bridgeCodes": [
    "GROUP_PLAN_VERSION_UNSUPPORTED",
    "GROUP_PLAN_VERSION_UNSUPPORTED"
  ],
  "downstreamErrors": {
    "workflow": "TRIP_NOT_CONFIRMED",
    "store_confirm": "PLAN_VERSION_NOT_FOUND",
    "store_start": "TRIP_NOT_FOUND",
    "execution_event": "TRIP_NOT_FOUND",
    "diff": "PLAN_VERSION_NOT_FOUND"
  },
  "sideEffectCounts": {
    "confirmed_trip_inputs": 0,
    "trips": 0,
    "plan_versions": 0,
    "execution_events": 0
  }
}
```

验收前后工作树始终只有两份既有未跟踪数据文件，内容哈希与时间戳未变化：

- `backend/data/amap_cache.sqlite3`：16384 bytes，SHA-256 `84E262DC234FC544BF1A10DDBCFAA68FAA870616EA8D23509ABE3BE8AEB3FAE5`
- `backend/data/plan_versions.sqlite3`：151552 bytes，SHA-256 `07945745B12629A80290127FC6FFC79A30FF03E35B65F79E147B140433FC3892`

两份文件未暂存、未提交，也未作为业务变更处理。

## 7. 最终产品分析复核入口

最终产品分析应从以下证据复核：

1. merge commit `7f130242209f34ab6219cb43ffac554a9300b25d` 及其两个父提交；
2. 正式 `INTEGRATION_DECISION`；
3. 本报告第 3 节的裁决映射、第 4 节的准确测试结果、第 5 节 UAT 与第 6 节零副作用证据；
4. 冻结设计 `docs/superpowers/specs/2026-08-26-s2-t001-multi-participant-contract-design.md` 与独立测试计划 `docs/testing/2026-08-26-s2-t001-independent-test-plan.md`。

本 QA 不合并 main、不推送、不部署；分支和 linked worktree 保持原位，交由版本管理器继续处理。
