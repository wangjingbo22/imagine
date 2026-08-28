# 林粲涵 Sprint 2 Day 2：S2-T029 追溯

## 交付范围

- PBI / AC：`PBI-15-A` / `AC-15-B`
- 依赖：`S2-T003`
- 需求源：`SprintBacklog模板!A33:V33`、`PBI追溯!A15:J15`、`用户功能验收清单!A6:J6` 与 `A8:J8`
- 最新集成验证基线：`main@012fa364894ffc7dd36a6dd91cdd21641550da06`
- 实现提交：`00f7ef692b5b3a5ef1b5d711af68456eeff41a66`

本任务不重写 T003 冲突算法，而是把既有确定性结果冻结成可验收合同：每个确认项对外提供 `participantId`、`relatedParticipantIds`、`ruleId`、`reason` 和 `allowedRelaxations`，组织者页面逐项展示责任成员、规则和权限范围。

## 状态与权限

硬冲突存在时，服务端固定返回 `CONFLICT_REVIEW / canPlan=false / readinessDigest=null`。组织者只能提交 `actorScope=ORGANIZER` 的放宽项；成员字段放宽仍须对应成员本人完成，页面只提示“需对应成员本人处理”，不会替成员改资料。

一次合法放宽会通过生产默认的 `TripDraftRevisionService` 在共享 SQLite 中创建新的 T002 revision，因此旧确认变为 `NEEDS_RECONFIRMATION`，协作状态先进入 `COLLECTING_MEMBERS`。只有新 revision 全员重新确认且确认项为零，状态才进入 `READY_TO_PLAN`。这条链由 `backend/tests/test_s2_t029_conflict_acceptance.py` 通过真实 ASGI 路由完整验证，不再依赖假 revision port。

## 模块联动

`S2-T003 冲突检测 / 权限 / revision patch` → `S2-T029 结构化冲突与组织者处理` → `S2-T028 readiness 门禁` → `S2-T030 唯一推荐`。

前端通过 `frontend/src/api/collaborationApi.ts` 携带组织者凭证、当前 revision、协作版本和幂等键，调用冻结的 `/confirmation-items/{itemId}/resolve`；不再使用旧 `/conflicts/...` 路径。T027 的 `MemberConversationPage` 也已经迁移到 `/api/v2/member-session` 独立成员会话，不再列为 T029 的上游代码阻塞。`ConflictReviewPanel` 在 375px 和 768px 下保持单列、UUID 可换行、按钮不少于 44px，并使用 `aria-live` 展示状态。

## 验收证据

- `backend/tests/fixtures/collaboration/s2_t029_conflict_case.json`：两人“必去 A / 避开全角 Ａ”冲突快照。
- `backend/tests/test_s2_t029_conflict_acceptance.py`：公开字段、NFKC 归一化、READY 门禁，以及真实 `TripDraftRevisionService + SQLite + ASGI` 的创建、冲突、放宽、新 revision、全员重新确认、`READY_TO_PLAN` 状态链。
- 真实链同时断言：放宽不触发第二次 LLM 调用；revision 1 与 revision 2 均持久化；`collaboration_resolution_audit` 记录 `1 → 2`。
- `frontend/tests/collaborationConflictReview.test.ts`：组织者权限、真实 API 路径、版本和幂等参数、推荐入口门禁。
- `backend/schemas/s2-t003-collaboration.schema.json`：发布合同使用 `allowedRelaxations`，并给成员视图补充 `collaborationVersion`。

本次收口重跑 T029 及 T002/T003 直接相邻回归，共 `80 passed`；统一收口提交为 `1a7fcf7169f3e3656507be878e896bf4db1dd9fd`。最新后端全量 `633 passed in 78.57s`，前端 `52 passed`，build 通过，lint 通过并保留 2 条既有 warning，`git diff --check` 通过。

## 诚实边界与仍需输入

T002 生产默认 revision port 现已接通：`create_app` 会构建 `TripDraftRevisionService` 与 `SqliteTripDraftRevisionRepository`，本地 `/api/v2/trips/conversations` 可以进入真实创建链；T027 成员邀请/会话页面也已完成本地接线。原追溯中的“T002 返回 503”和“T027 成员页待迁移”均已过时，本次予以移除。

当前仍不声称公网完成：需要在最新公网部署中配置所需密钥，使用两个独立浏览器会话执行同一条冲突放宽与重确认链，并补非作者评审、QA、PO 验收记录。共享 SQLite 的正常链已经覆盖，但“revision 已写入、collaboration advance 失败”等故障窗口恢复不属于本次 happy-path 验收，仍明确标记为未声明。
