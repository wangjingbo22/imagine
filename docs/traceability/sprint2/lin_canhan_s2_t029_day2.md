# 林粲涵 Sprint 2 Day 2：S2-T029 追溯

## 交付范围

- PBI / AC：`PBI-15-A` / `AC-15-B`
- 依赖：`S2-T003`
- 需求源：`SprintBacklog模板!A33:V33`、`PBI追溯!A15:J15`、`用户功能验收清单!A6:J6` 与 `A8:J8`
- 验证基线：`main@10d1742885675694ea0b13c5d20d2e498ef67608`
- 实现提交：`00f7ef692b5b3a5ef1b5d711af68456eeff41a66`

本任务不重写 T003 冲突算法，而是把既有确定性结果冻结成可验收合同：每个确认项对外提供 `participantId`、`relatedParticipantIds`、`ruleId`、`reason` 和 `allowedRelaxations`，组织者页面逐项展示责任成员、规则和权限范围。

## 状态与权限

硬冲突存在时，服务端固定返回 `CONFLICT_REVIEW / canPlan=false / readinessDigest=null`。组织者只能提交 `actorScope=ORGANIZER` 的放宽项；成员字段放宽仍须对应成员本人完成，页面只提示“需对应成员本人处理”，不会替成员改资料。

一次合法放宽会创建新的 T002 revision，因此旧确认变为 `NEEDS_RECONFIRMATION`，协作状态先进入 `COLLECTING_MEMBERS`。只有新 revision 全员重新确认且确认项为零，状态才进入 `READY_TO_PLAN`。这条链由 `backend/tests/test_s2_t029_conflict_acceptance.py` 验证。

## 模块联动

`S2-T003 冲突检测 / 权限 / revision patch` → `S2-T029 结构化冲突与组织者处理` → `S2-T028 readiness 门禁` → `S2-T030 唯一推荐`。

前端通过 `frontend/src/api/collaborationApi.ts` 携带组织者凭证、当前 revision、协作版本和幂等键，调用冻结的 `/confirmation-items/{itemId}/resolve`；不再使用旧 `/conflicts/...` 路径。`ConflictReviewPanel` 在 375px 和 768px 下保持单列、UUID 可换行、按钮不少于 44px，并使用 `aria-live` 展示状态。

## 验收证据

- `backend/tests/fixtures/collaboration/s2_t029_conflict_case.json`：两人“必去 A / 避开全角 Ａ”冲突快照。
- `backend/tests/test_s2_t029_conflict_acceptance.py`：公开字段、NFKC 归一化、READY 门禁、放宽与重新确认状态链。
- `frontend/tests/collaborationConflictReview.test.ts`：组织者权限、真实 API 路径、版本和幂等参数、推荐入口门禁。
- `backend/schemas/s2-t003-collaboration.schema.json`：发布合同使用 `allowedRelaxations`，并给成员视图补充 `collaborationVersion`。

本地最终结果：T029/T003/门禁/追溯聚焦回归 `67 passed`，全量后端 `537 passed`，前端 `37 passed`，生产构建通过，lint 通过并保留 2 条既有 warning，`git diff --check` 通过。

## 诚实边界与仍需输入

生产默认仍缺 T002 `TripDraftRevisionPort`，所以 `/api/v2/trips/conversations` 继续返回 503；本交付只能通过注入 revision port 的 HTTP/SQLite 与服务测试证明 T029，不声称公网完整创建链已经完成。成员会话页面迁移属于上游 T027，S2-T029 没有越权代做。

仍需要：陈梓元交付真实 T002 revision/applyRelaxation 持久化实现；T027 负责人迁移成员页面；随后补非作者评审、QA、PO 与公网验收记录。
