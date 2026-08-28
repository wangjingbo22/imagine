# S2-T024 公网黄金路径与响应式验收

> 当前状态：`LOCAL PASS / PUBLIC NOT_RUN-BLOCKED`
>
> 负责人：林粲涵
> 追溯链：`PBI-13-A -> AC-13-A -> S2-T024 -> UAT-S2-012 -> RESP-S2-001`

## 1. 本任务边界

S2-T024 只验收 Sprint 2 既有主链在公网和移动视口中的可用性：固定六问、唯一推荐、执行、照片、LATE/FATIGUE V2、接受或拒绝、回忆。它依赖 `S2-T001~T023`，不重写这些任务的业务规则。

`S2-T032 / PBI-17-A / AC-17-A / UAT-S2-E2E-001` 是新增的“组织者加两名成员、邀请隔离、冲突处理到回忆”完整多人验收，明确不计入本任务。本任务可以复用多人兼容数据，但不得据此宣称 T032 完成。

需求源：

- `doc/行知旅伴_V2.3_Sprint2待办列表_含负责人_新增需求修订版.xlsx`
- `SprintBacklog模板!A28:V28`
- `PBI追溯!A13:J13`
- `用户功能验收清单!A15:J15`
- `版权说明!A10:B14`
- `LLM接入设计!A10:K10`

## 2. 必须通过的验收合同

### 2.1 两个视口

同一条黄金路径必须分别在 `375x812` 和 `768x1024` 运行，并满足：

1. `document.documentElement.scrollWidth <= document.documentElement.clientWidth`；
2. 页面正文、Diff、金额、时间和状态不被裁切或互相遮挡；
3. 当前可用的可见链接、按钮和 `role=button` 控件的可点击宽高均不少于 44px；
4. 等待、权限不足、Provider/模型降级和操作失败通过可见文字或 `aria-live` 呈现，不只依赖颜色或 hover；
5. 键盘可以到达主流程控件，焦点顺序与页面顺序一致；
6. `prefers-reduced-motion: reduce` 下取消非必要动画和滚动效果。

### 2.2 公网黄金路径（当前 `NOT_RUN`）

每个视口按相同顺序验证：

1. 固定六问完成后才提交解析，出现确认结果；
2. 进入唯一推荐并显示服务端事实、金额和成员说明；
3. 启动 CURRENT 计划，执行至少一个任务并显示 GPS/人工确认状态；
4. 上传、替换或删除任务照片，失败不能阻断任务执行；
5. 提交一次 LATE 或 FATIGUE 事件并预览 PROPOSED V2；
6. 在接受前确认 CURRENT 未改变，结构化 Diff 始终存在；
7. 模拟解释不可用，仍能接受或拒绝 V2；
8. 进入回忆区域，按真实事件顺序显示完成率、费用、版本变化、关怀结果和未删除照片。

这八步必须连接同一公网后端和真实服务端状态，才属于黄金路径证据。浏览器路由拦截、Fixture 页面和单独打开某个阶段，只用于本地 UI 合同检查，不能替代本节，也不能据此宣称真实执行、V2 或回忆全链已通过。

### 2.3 本地浏览器自动化边界

当前 Playwright 自动化使用明确的 Mock API/Fixture，覆盖：

1. 单人固定六问、确认组织者资料、进入唯一推荐；
2. 实际点击“确认唯一方案”和“生成完整路线”，验证浏览器进入后续行程工作台，而非只检查推荐页标题；
3. 分别渲染 Mock 的执行、V2 Diff、回忆阶段，检查 375px/768px 无横向溢出；
4. 检查所有当前可用的可见链接/按钮触控区域，以及全页面可见元素和伪元素的 reduced-motion 计算样式。

第 3 项只是“Mock 阶段响应式 Fixture”，不代表这些阶段通过真实后端串成同一个行程。真实串链仍由第 2.2 节公网验收提供证据。

后端另有 `backend/tests/test_s2_t024_full_golden_path.py`，在一个真实 ASGI app 和 SQLite 文件中验证同一单人 Trip 从六问、READY、Provider/FactRef 推荐、V1、GPS/照片、LATE/FATIGUE、V2 接受到 MemoryTimeline 的连续状态与持久化血缘。该测试同时回归 `planning_boundary_service.py` 使用 `plan.parent_id` 恢复被确认的调整事件。T023 前端已完成本地契约与页面接线；这些本地证据仍不替代真实浏览器和公网服务证据。

自动化由下列文件承载：

- `frontend/playwright.config.ts`
- `frontend/e2e/s2-t024-responsive.spec.ts`
- `frontend/tests/s2T024ResponsiveContract.test.ts`
- `frontend/src/services/s2T024Acceptance.ts`

上述文件只承载本地合同和公网执行入口；即使本地测试通过，也不得把公网状态从 `NOT_RUN` 改成 `PASS`。

## 3. 自动化与公网门禁

| 门禁 | 内容 | 当前状态 | 主要证据 |
|---|---|---|---|
| T024-L01 | 响应式合同单测：无横向滚动、44px、状态可见、reduced-motion | PASS | 4 项 T024 合同测试；前端共 52 passed |
| T024-L02 | 375px 本地 Mock 浏览器合同 | PASS | 六问 → 推荐确认 → 生成路线 → 进入工作台；Mock 执行/V2/回忆仅作分阶段 UI 检查；公网视频仍待录制 |
| T024-L03 | 768px 本地 Mock 浏览器合同 | PASS | 六问 → 推荐确认 → 生成路线 → 进入工作台；Mock 执行/V2/回忆仅作分阶段 UI 检查；公网视频仍待录制 |
| T024-L04 | 前端全量 test/lint/build | PASS | 52 passed；build PASS；lint PASS（2 个既有 warning） |
| T024-L05 | 后端可信单人全链与门禁回归 | PASS | 新增真实 ASGI/SQLite full golden path；全量 633 passed in 78.57s；含 `parent_id` 修复回归 |
| T024-P01 | 公网页面和同源 API 使用目标提交 | BLOCKED | 当前 build `32bb112`，不是关闭提交 `1a7fcf7` |
| T024-P02 | 375/768 真实浏览器连续验收 | NOT_RUN | `RESP-S2-001` 录屏和截图 |
| T024-P03 | 真实高德/缓存事实和百炼降级边界 | BLOCKED | 当前公网未配置 `BAILIAN_API_KEY`；脱敏 Network/服务日志待补 |
| T024-P04 | 验收签字 | NOT_RUN | 验收人、时间、结论 |

只有所有本地门禁通过、目标提交已部署且公网门禁有真实证据时，才能把 S2-T024 标记为 `PASS`。旧部署、Mock 页面、源码截图或历史测试数字不能替代本轮证据。

本轮本地记录：backend `633 passed in 78.57s`；frontend `52 passed`；lint 通过并保留 2 条既有 warning；build PASS；Playwright `14 passed in 31.4s`。T023 前端本地闭环；T032 明确排除。

## 4. 建议执行命令

```powershell
python -m pytest -q backend/tests/test_s2_lin_canhan_s2_t024_traceability.py

Set-Location frontend
npm test
npm run lint
npm run build
npm run test:e2e
Set-Location ..
```

验收时必须记录命令、开始和结束时间、退出码、目标提交 SHA 以及实际通过数。本文不预填预计总数。

## 5. 公网执行步骤

1. 记录前端 URL、后端 URL、部署环境、构建 SHA 和验收时区。
2. 仅确认 `AMAP_*`、`BAILIAN_*` 等秘密变量“已配置”，绝不读取或记录值。
3. 预热 health 后分别启动 375px、768px 的独立浏览器上下文。
4. 从 `/plan` 开始完整执行第 2.2 节，不预创建 Trip、PlanVersion、Event 或照片。
5. 用 `tripId -> currentPlanVersionId -> taskId -> eventId -> proposedV2Id -> decision -> memoryTimeline` 串联 UI、Network 和服务日志。
6. 证据脱敏后放入 `docs/testing/evidence/s2_t024/` 对应目录，并在 README 登记。
7. 任一步失败时记录 `FAIL` 或 `BLOCKED` 和原始错误；不得跳步后继续声明完整通过。

## 6. 需要的外部输入

- 已部署目标提交的公网前端、后端 URL；
- 部署平台中已安全配置的高德和百炼凭据，仅提供“是否已配置”，不提供明文；
- 可使用定位、相机/文件上传的真实浏览器或等价受控测试设备；
- 验收人、时间和签字；
- 若要执行 T032，必须另开 `UAT-S2-E2E-001`，不能混入本记录。

## 7. 签字模板

```text
任务：S2-T024
追溯：PBI-13-A / AC-13-A / UAT-S2-012 / RESP-S2-001
目标提交 SHA：
前端 URL：
后端 URL：
验收日期与时区：
验收人：

375px：PASS / FAIL / BLOCKED（证据：）
768px：PASS / FAIL / BLOCKED（证据：）
黄金路径：PASS / FAIL / BLOCKED（证据：）
自动化：backend __ passed；frontend __ passed；lint __；build __；playwright __
阻断缺陷：
非阻断缺陷：

最终结论：PASS / FAIL / BLOCKED
签字：
```
