# 林粲涵 Sprint 2 Day 2：S2-T021 / S2-T022 追溯

## 交付范围

- 负责人：林粲涵
- PBI / AC：`PBI-11-B` / `AC-11-B`
- 验证基线：远端 `main` 的 `a43ad37a5c8b97d2b90507fa9966998bfee038b9`
- 实现提交：`f376574a5c8c5c577d6ed43efd200293023b3b32`
- Day 2：`S2-T021` 与 `S2-T022`（均为 Must；修订表当前剩余工时均为 0h）
- 需求文件：`doc/行知旅伴_V2.3_Sprint2待办列表_含负责人_新增需求修订版.xlsx`
- 需求范围：`SprintBacklog模板!A25:V26`、`PBI追溯!A11:J11`、`LLM接入设计!A7:K7`、`用户功能验收清单!A12:J13`
- 机器可读追溯：`docs/traceability/sprint2/lin_canhan_s2_t021_t022_day2.json`

验收核心是：模型只解析事件草稿和解释差异；后端从服务端确认事件和可信规划事实生成事件感知候选，冻结已完成/锁定前缀，重验全部 HARD。候选签发绑定协作 readiness，且只有组织者通过专用决策接口接受后才可替换 `CURRENT`。

## 模块联动

`S2-T019 adjustmentEventId` → `S2-T020 EventConstraintSet` → `S2-T021 事件感知 PROPOSED V2 + readiness 绑定 + HARD 重验` → `S2-T022 专用接受/拒绝 + Diff` → `S2-T018` 版本回忆与待接入的 `S2-T023` 页面。

### S2-T021

T021 通过可选 `adjustmentEventId` 从 `WorkflowService` 恢复不可变的服务端确认 LATE/FATIGUE 事件，校验事件属于当前 `CURRENT`，并要求随请求携带的兼容 inline 内容与持久事件完全一致。新流程应传事件 ID；无 ID 的 inline 仅保留旧接口兼容。

生产默认使用确定性事件感知后缀规划器：

- LATE 只压缩可信 Provider 路线耗时之外的既有日程空隙；
- FATIGUE 只收紧派生休息计数；
- 地点、路线、价格和设施事实原样复用，不伪造 Provider 事实；
- 若可信路线或活动本身无法满足收紧后的 HARD 条件，则返回无可行候选并保持零 V2 写入；
- 旧 S1 `EXPENSE_CHANGE` 没有事件约束时继续保留原可信后缀，兼容既有链路。

候选身份和签发证据同时绑定 `adjustmentEventId`（存在时）、事件约束摘要、`readinessDigest` 与 `currentRevision`。冻结前缀、预算、时间、路线、关怀以及 T020 临时规则仍在同一份服务端 HARD 报告内重验。

主要代码证据：

- `backend/app/schemas/execution_replan.py`
- `backend/app/services/execution_replanning/context.py`
- `backend/app/services/execution_replanning/validator.py`
- `backend/app/services/replanning/suffix_planner.py`
- `app/application/planning_boundary_service.py`
- `app/application/collaboration_ports.py`
- `app/application/collaboration_readiness.py`
- `app/application/execution_replan_service.py`
- `app/api/execution_replan_routes.py`

### S2-T022

预览响应返回候选 `PlanVersion`、结构化 `Diff`、临时约束、冻结任务、候选评估和完整校验报告，候选始终保持 `PROPOSED`。专用决策接口在同一 readiness lease 中完成证据复验和 PlanVersion 状态迁移：若预览后协作摘要或修订号发生变化，则拒绝决策，原 `CURRENT` 与候选状态均不变。

DELAY/FATIGUE 候选不能经通用 `/accept` 或 `/reject` 绕过专用证据检查。接受仍复用 PlanVersion 的唯一 `CURRENT` 原子切换；拒绝继续使用原 `CURRENT`。多人模式下只有 readiness guard 验证过的组织者能力可进入规划和决策边界。

千问只读取冻结后的 Diff 生成短解释，不能新增/删除任务、修改金额、状态或计划标识。模型未配置、超时、失败或返回非法结构时，解释降级为 `UNAVAILABLE`，结构化候选、Diff 和状态转换仍正常工作。

主要代码证据：

- `backend/app/schemas/replan_explanation.py`
- `app/infrastructure/bailian_replan_explanation.py`
- `app/application/planning_boundary_service.py`
- `app/application/execution_replan_service.py`
- `app/api/execution_replan_routes.py`
- `app/api/plan_routes.py`

## 验收证据

- `backend/tests/fixtures/execution_replanning/s2_t021_t022_cases.json`：冻结前缀、可行重规划和无解零写入场景。
- `backend/tests/snapshots/s2_t022_adjustment_diff.json`：候选与变化对比快照。
- `backend/tests/test_s2_t021_t022_execution_replan.py`：默认运行时、Provider 事实保持、持久事件防篡改、readiness 漂移、通用接口绕过、接受/拒绝与解释降级验收。
- `backend/tests/test_s2_t003_readiness_guard.py`：ready revision 与 lease 竞态防护。
- `backend/tests/test_bailian_replan_explanation.py`：模型严格输入/输出和失败降级。
- `backend/tests/test_s2_lin_canhan_t021_t022_traceability.py`：PBI、依赖、边界和证据路径机器校验。

本次记录的聚焦回归分别为 `42 passed` 和 `43 passed`；全量后端为 `528 passed`；前端测试 `32 passed`，生产构建与 lint 均通过。本文不声称公网在线 E2E 已完成。

## 仍需要的外部输入

1. `S2-T006` 的具体 FactRef 注册表已经存在，但正式在线 Provider 路线构建器和公网事实验证仍是外部缺口；当前 planner 不会用推测路线冒充高德事实。
2. `S2-T005` 的 2 人和 3 人 PlanVersion 共享链仍受上游单人快照契约阻塞，本交付没有擅自扩大该契约。
3. `S2-T023` 仍需在前端消费预览、Diff 和专用接受/拒绝接口。
4. PO 仍需冻结 `MILD / MODERATE / SEVERE` 疲劳阈值，以及迟到超过剩余窗口时的最终产品口径。
5. 如需真实千问或公网 E2E，请只通过部署 secrets 提供已轮换密钥，不要把明文 Key 写入聊天、代码或日志。
