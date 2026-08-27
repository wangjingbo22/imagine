# 林粲涵 Sprint 2 Day 2：S2-T021 / S2-T022 追溯

## 交付范围

- 负责人：林粲涵
- PBI / AC：`PBI-11-B` / `AC-11-B`
- 实现基线：远端 `main` 的 `5b846f35eafc51a3834701e9c0b729f22ae21223`
- 最终兼容验证：远端 `main` 的 `5e71d03b98cd80fd92ffbc442d369ec4aa29330a`（合并提交 `3c1daa638363a531f43d07c6bdcdc52a31dd1694`）
- 实现提交：`d738b0a2ecde37f4fb9d76f420b73b645d7ed150`
- Day 2：`S2-T021`（3h，Must）和 `S2-T022`（3h，Must）
- 机器可读追溯：`docs/traceability/sprint2/lin_canhan_s2_t021_t022_day2.json`

需求表中的验收核心是：模型只解析事件草稿和解释差异；程序负责恢复可信事实、转换临时约束、冻结已完成/锁定任务、生成候选 V2、重验全部 HARD，并且在接受前不覆盖 `CURRENT`。

## 模块联动

`S2-T019 ConfirmedExecutionAdjustment` → `S2-T020 EventConstraintSet` → `S2-T021 PROPOSED V2 + HARD 重验报告` → `S2-T022 Diff + 接受/拒绝` → `S2-T018` 版本回忆与 `S2-T023` 调整页面。

### S2-T021

依赖 `S2-T005`、`S2-T006`、`S2-T019`、`S2-T020`。服务端从 `CURRENT`、执行事件和已签发规划事实推导剩余时间、步行与休息基线；客户端不能提交 FactRef 或编译后的约束。系统重新编译 T020 临时约束，冻结已完成、已开始、当前和显式锁定任务，只允许修改未完成后缀，并把预算、时间、路线、关怀以及 T020 临时 HARD 检查放进同一份报告。

若没有可行候选，只返回冲突、受影响规则和可放宽项；候选在完整校验通过之前不得写入，因此不能留下半成品版本。

主要代码证据：

- `backend/app/schemas/execution_replan.py`
- `backend/app/services/execution_replanning/context.py`
- `backend/app/services/execution_replanning/validator.py`
- `backend/app/services/replanning/suffix_planner.py`
- `app/application/planning_boundary_service.py`
- `app/application/execution_replan_service.py`
- `app/api/execution_replan_routes.py`

### S2-T022

依赖 `S2-T005` 和 `S2-T021`。预览响应同时返回候选 `PlanVersion`、结构化 `Diff`、临时约束、冻结任务、候选评估和完整校验报告。候选保持 `PROPOSED`，接受操作复用 PlanVersion 原子切换，拒绝则继续使用原 `CURRENT`。

千问只读取已经冻结的 Diff 生成短解释，解释不会成为计划输入，也不能新增/删除任务、修改金额、状态或计划标识。未配置模型、超时、上游失败或返回非法结构时，接口把解释标记为 `UNAVAILABLE`，但仍返回完整的候选和 Diff。

主要代码证据：

- `backend/app/schemas/replan_explanation.py`
- `app/infrastructure/bailian_replan_explanation.py`
- `app/application/execution_replan_service.py`
- `app/api/execution_replan_routes.py`

## 验收证据

- `backend/tests/fixtures/execution_replanning/s2_t021_t022_cases.json`：冻结前缀、可行重规划、无解零写入、接受/拒绝和解释降级场景。
- `backend/tests/snapshots/s2_t022_adjustment_diff.json`：候选与变化对比 JSON 快照。
- `backend/tests/test_s2_t021_t022_execution_replan.py`：HTTP 与 SQLite 状态验收。
- `backend/tests/test_bailian_replan_explanation.py`：模型严格输入/输出和失败降级。
- `backend/tests/test_s2_lin_canhan_t021_t022_traceability.py`：PBI、依赖、边界和证据路径的机器校验。

收口时全部后端测试为 `366 passed`；前端 Node 测试 `32 passed`，生产构建通过，lint 通过（2 条上游既有 warning）。本文不声称在线 E2E 已完成。

## 仍需要的外部输入

1. `S2-T006` 的具体 FactRef 注册表、持久化 Provider bundle 和事件感知后缀候选源。当前最新 main 只有合同接缝；默认保留后缀规划器会明确返回不可用，不能签发伪调整。测试通过可注入端口证明 T021/T022 编排与守卫，但不能宣称已完成真实在线备选地点/路线 E2E。
2. `S2-T005` 的 2 人和 3 人 PlanVersion 链交付及验收证据；该链仍由上游任务负责。
3. `S2-T023` 前端消费候选、Diff 和接受/拒绝接口；本交付不实现页面。
4. PO 冻结 `MILD / MODERATE / SEVERE` 疲劳阈值，以及迟到超过剩余窗口时“直接冲突”还是“编译为零”的口径。
5. 如需做真实千问冒烟测试，请通过部署密钥提供已轮换的 `BAILIAN_API_KEY`，不要把明文 Key 写入聊天、代码或日志。
