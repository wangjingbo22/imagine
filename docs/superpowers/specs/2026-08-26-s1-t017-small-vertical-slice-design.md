# S1-T017 事件驱动后缀重规划小闭环设计

## 目标

完成 Sprint Backlog 的 S1-T017，而不把 T018 的多候选排序和放宽算法混入本任务：

- 服务端从 CURRENT Plan V1 与 T016 `ExecutionEvent` 推导冻结前缀和剩余预算；
- 已完成、跳过或已开始的任务形成连续冻结前缀，Plan V2 中这些任务字段 100% 保留；
- 规划器只接收未完成后缀，不接收冻结前缀；
- 默认生产装配必须可用，不能依赖测试 Fake；
- 额外消费后仍可行时生成并登记唯一 PROPOSED V2；不可行时返回 typed error，`plan_versions` 不新增 V2；
- 继续复用 T011 可信校验、T018 选择器和 T019 Diff/接受/拒绝，不复制这些规则。

## 非目标

- T018 的多候选排序、满意度损失比较与约束放宽；
- 新 POI 或新高德路线搜索；
- 将 UNKNOWN 价格、设施或来源自动标成 PASS；
- Sprint 2 的 GPS 到达、照片、疲劳/迟到事件与完整回忆页。

## 接口

新增 `POST /api/v1/trips/{tripId}/replans/from-events`。

请求只包含：

- `schemaVersion: "1.0"`
- `reason`: 非 `INITIAL_PLAN` 的 PlanVersionReason
- `feedback`: 可选的简短用户反馈

客户端不再提交候选、冻结任务 ID 或事实快照。服务端从持久化状态推导这些内容，避免浏览器伪造 V2。

响应复用 `RegisteredReplan`，包含 PROPOSED V2、`frozenTaskIds`、扰动分数、校验报告与候选评估。

## 服务端流程

1. 读取 Trip 的 CURRENT V1，要求它是服务端已签发的 V1 且 Trip 正在执行。
2. 读取 T016 事件流与 V1 的可信 `CandidatePlanRequest`。
3. 校验：
   - 至少存在一个执行事件；
   - `EXPENSE_CHANGE` 至少存在一条 EXPENSE；
   - 每个 COMPLETE 任务必须有对应 EXPENSE（0 元也要显式记录）；
   - 事件必须属于当前 Trip、当前 Plan 和已知 taskId；
   - 仍存在未完成后缀。
4. 将出现 START/COMPLETE/SKIP 的最末任务及其之前任务作为冻结前缀。
5. 仅把原 V1 的可信后缀事实、实际消费投影、原因和反馈交给 `SuffixPlanner`。
6. 默认 `DeterministicRetainedSuffixPlanner` 返回已确认的原后缀事实。这是安全的最小扰动基线：它不会制造新的 Provider 事实；T011 会在实际支出上下文中重新计算预算、时间、路线和关怀约束。
7. 把规划器后缀与原冻结前缀重新组装成完整 `CandidatePlanRequest`。冻结前缀不可改变；旧 suffix taskId 不得跨 order 复用。
8. 调用现有 `generate_v2` 边界，让 T011 重新生成/校验候选、T018 验证冻结前缀并选择、PlanVersionService 登记 V2、TrustedPlanningStore 标记签发。
9. 若 T011/T018 判定无可行解，返回 `REPLAN_NO_FEASIBLE_CANDIDATE`，不新增 PlanVersion V2。

## 前端流程

- 完成任务时先写 EXPENSE，再写 COMPLETE；
- 有消费差异时调用 `/replans/from-events`，不再在浏览器调用高德重新拼候选；
- 用户反馈时当前任务已有 START，服务端据此冻结当前及之前任务；
- 成功后继续使用现有 Diff、接受与拒绝页面；
- 原 `/replans` 保留给 T018 的显式多候选接口和现有回归，不破坏兼容性。

## 安全与失败策略

- 默认规划器只复用已经通过 V1 证据确认的事实，因此不会绕过 `CANDIDATE_CONFIRMATION_REQUIRED`；
- 规划器异常和非法输出统一转换为稳定、脱敏的 `REPLAN_SUFFIX_PLANNER_*` 错误；
- 不完整实际消费、无事件、无未完成任务、非 CURRENT V1 都 fail closed；
- V2 ID 继续由可信请求、父计划和原因确定，重复同请求可恢复相同提案；
- 本切片不宣称解决并发水位/as-of replay；S1 采用当前 T016 持久化事件顺序与单用户执行边界。

## 验收

核心黄金路径：CURRENT V1 第一项计划消费后实际多花 5000 cents，写 EXPENSE + COMPLETE，再请求事件驱动重规划；服务端冻结第一项，规划器只看到第 2—4 项，生成 PROPOSED V2，冻结任务所有 PlanTask 字段完全相同，T011 四域 HARD 全 PASS，T019 Diff 可查询，V2 可接受/拒绝。

负路径：超预算、缺少 COMPLETE 对应金额、无事件、全部任务已结束、非法规划器输出，均不得新增 V2。
