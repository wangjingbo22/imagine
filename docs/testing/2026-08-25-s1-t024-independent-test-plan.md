# S1-T024 最小黄金路径独立测试与验收计划

> 文档日期：2026-08-26
> 适用基线：`b5922986202091b2744b62fe1f3a0233b5fcba56`
> 唯一设计依据：`docs/superpowers/specs/2026-08-26-s1-t024-minimal-golden-path-design.md`
> 实现分析追溯：`01a037c4-3ec9-7c62-afa4-8b4ae8b90c02`
> 本轮活动：只制定计划；不执行测试，不产生 `PASS`/`FAIL` 结论。

## 1. 目标、范围与当前门禁

Sprint Goal（逐字）：**“第一次 Review 就能展示关怀单人完整 Agent”**。

S1-T024 的验收目标是：在桌面端和 375px 手机端，以同一个北京低体力、严格单人案例，在预热后的连续 90 秒内完成约束确认、服务端权威 V1、执行、真实“多花 50 元”事件、服务端最小扰动 V2/Diff、接受 V2、继续执行与服务端基础总结。浏览器只能提交意图、确认、事件和 V2 决策，不能伪造 Provider 结果、金额、硬约束 `PASS`、V2、Summary 或追踪证据。

当前判定分层如下：

| 层次 | 当前判定 | 含义 |
|---|---|---|
| 代码实施入口 | `READY / GO` | 设计已冻结，代码窗口可只实现冻结设计中的最小修复与黄金回归。此判定不等于测试通过。 |
| 本地代码验收 | `NOT_RUN` | 本轮没有执行任何测试。冻结设计记录的后端 `273 passed`、前端 `21 passed`、lint/build exit 0 和 SQLite/ASGI accept 链仅是进入本计划的基线证据，不能替代本轮独立验收。 |
| 公网验收 | `BLOCKED` | 冻结设计记录线上仍是旧包：前端页面 200、同源 health 502、后端直连 health 200。必须重新部署目标 SHA 后再执行 G09～G12。 |
| S1-T024 最终结论 | `BLOCKED` | 公网门禁尚不可执行；不得把现有页面、既有单测数量或实现窗口跑通记录写成 T024 `PASS`。 |

判定术语：

- `READY / GO`：前置设计和依赖足以进入下一阶段，不表示验收通过。
- `BLOCKED`：存在明确外部前置条件，当前不能得到有效结果。
- `NOT_RUN`：尚未真实执行；本计划中的所有门禁初始均为此状态。
- `PASS`：在指定 SHA、环境和证据要求下真实执行且全部预期成立后才可填写。
- `FAIL`：真实执行后至少一个强制预期不成立；必须登记缺陷和原始证据。

## 2. 最小范围与反范围膨胀

本次只验收一个确定性的服务端权威黄金路径。Sprint 1 主路径不得出现或依赖以下能力：GPS 到达辅助、任务照片/视频/对象存储、照片时间线/完整旅行回忆、迟到/疲劳事件、自由文本触发 V2、多成员/公平评分/成员卡、双方案、美团 Skill。

下列技术也不是本次门禁：LangGraph、消息队列、完整 OpenTelemetry、新 Trace 数据库、新 `/ready` 平台、独立 `/version` 平台、把 `trace_summary_numbers` 接入生产 API。构建 SHA 可随现有两个 health 响应暴露，不因此扩建平台。

反范围膨胀验收归入 G06：上述 Sprint 2/Future/P1 UI 在 Sprint 1 主路径不可见、不可操作、不可成为完成路径依赖；发现任一项即 G06 `FAIL`。

## 3. 固定北京严格单人案例

### 3.1 输入与权威边界

| 项目 | 固定规则 |
|---|---|
| 城市 | 北京；Provider 请求和返回的 `cityCode` 必须一致。 |
| 参与者 | 恰好 1 个自然人；使用产品默认的低体力关怀资料及其服务端 schema，不添加儿童、陪同人或第二成员。 |
| 约束 | 用户必须先确认 AssistanceProfile/关怀约束；未知设施、未知价格等事实保持 `UNKNOWN` 并由服务端要求复核，不能由前端改写为 `PASS`。 |
| 地点和 V1 金额 | 使用代码窗口为 T024 固定的北京 Provider Stub 响应及服务端生成结果。设计未冻结具体 POI 名称和绝对金额，QA 不另造数字；黄金测试提交时必须把固定 fixture 与 V1 JSON 一并留证。 |
| V1 | 只能由 `POST /api/v1/trips/{tripId}/plan-versions/generate` 对服务端规范 Trip、Provider 事实和确认记录生成；全程唯一 `CURRENT`。 |
| 执行 | 用户确认 V1 后启动首任务；每个 START/COMPLETE/EXPENSE 都是服务端事件。 |
| 真实变更 | 当前任务实际金额 = 该任务 V1 计划金额 + `5000` 分，即多花 50 元；不得在 UI 或 fixture 中直接写一个与 V1 无关的总额。 |
| V2 | 前端仅发送 `schemaVersion` 与 `reason=EXPENSE_CHANGE` 到 `POST /api/v1/trips/{tripId}/replans/from-events`；V2、硬约束复验、最小扰动和 Diff 都由服务端产生。 |
| 决策 | 主演示接受 V2：V2=`CURRENT`、V1=`SUPERSEDED`；随后启动当前计划中第一个未完成任务，不得 `currentTaskIndex + 1` 跳过任务。 |
| Summary | Trip 最终为 `COMPLETED`，所有任务完成，服务端数字反映 `+5000` 分及真实事件；UI 不得硬编码“100%”或“4 项硬约束”。 |

### 3.2 三条路径

| 路径 | 执行方式 | 必须结果 |
|---|---|---|
| 无 V2 | 自动化，复用 T022 三路径 Summary 回归 | V1 始终 `CURRENT`，完成后 Summary 可追溯且不伪造数字。 |
| V2 后接受 | 新增 G01 真实 SQLite/ASGI 黄金回归；桌面和 375px 主现场也走此路径 | V2 `CURRENT`、V1 `SUPERSEDED`，不跳任务，最终完成并显示服务端 Summary。 |
| V2 后拒绝 | 自动化，复用 T017/T018/T022 专项回归 | V1 保持 `CURRENT`，V2 `REJECTED`，事件和执行状态不丢失；同一决策幂等，决策后再次 replan 返回 409 且无副作用。 |

## 4. 十二个最少充分门禁

本计划只有 G01～G12 共 12 个门禁，不再拆成旧版 61 项。每项在真实执行前均为 `NOT_RUN`；被公网前置阻塞的项目记 `BLOCKED`，不能预填 `FAIL`。

| ID | 类别 | RED（修复前或失败条件） | GREEN（验收条件） | 主要证据 |
|---|---|---|---|---|
| G01 | 后端黄金链 | 没有固定北京单人、真实 SQLite/ASGI、生产组装入口的 accept 全链测试；或测试向 replan 注入 candidates/locked/PASS。 | 新增一个测试，从约束确认和服务端 V1 一直跑到 `COMPLETED`；调用 `from-events`，V2 `CURRENT`、V1 `SUPERSEDED`、Summary 与事件均为 `+5000` 分；仅 Stub 外部 Provider。 | pytest 原始输出、V1/V2/Diff/Event/Summary JSON、SQLite 查询摘录。 |
| G02 | 三路径与一致性 | reject、重复决策、决策后 replan、UNKNOWN/无可行解或事件冲突可覆盖服务端状态。 | 复用既有 T017/T018/T022/执行专项：无 V2、accept、reject 均可总结；同请求幂等；冲突返回 409 且无新增 Plan/Event；未知事实 fail-closed，Provider 超时/cityCode/schema 非法及无可行解不生成伪 V2。 | 定向 pytest 输出；失败响应与前后数据库计数。 |
| G03 | 决策后续跑 | accept/reject 回调使用旧索引 `+1`，会跳过首个未完成任务。 | V2 决策响应后按 `currentPlan + events` 重新计算第一个未完成任务；有任务时只 START 该任务，无任务时进入 Summary。 | 前端 RED/GREEN 单测、Network 事件顺序。 |
| G04 | EXPENSE 幂等 | key 包含金额；改金额会产生第二个逻辑 EXPENSE。 | 逻辑 key 稳定为 `planId:taskId:EXPENSE`；同 key 同 payload 返回同 `eventId`，同 key 不同金额返回冲突且不重复扣款。 | 前后端定向测试、事件 JSON/DB 计数。 |
| G05 | Summary 真值 | UI 显示硬编码 100%/4 项，或客户端重算覆盖服务端数字。 | UI 只渲染 `GET /api/v1/trips/{tripId}/summary` 的字段；未完成状态不得显示完成率 100%；accepted 主链显示服务端任务数、金额与 `+5000` 分。 | 前端单测、Summary JSON、最终截图。 |
| G06 | S1 反膨胀 | 主路径可见媒体上传、GPS、成员/公平、双方案等 Sprint 2/Future 能力。 | S1 主路径隐藏第 2 节列出的全部能力，桌面和 375px 均无入口且完成链不依赖它们。 | 前端单测、两端截图/录屏。 |
| G07 | 前端质量 | T024 RED 用例失败，或 test/lint/build 任一非 0。 | 前端新增/更新的 G03～G06 测试先 RED 后 GREEN；全量 test、lint、build 均 exit 0，既有 21 项不得回退。 | RED/GREEN 输出与三条全量命令输出。 |
| G08 | 后端质量 | G01 尚未实现或定向/全量回归失败。 | G01 新测试及 T017/T018/T022/执行专项全绿；后端全量 exit 0，既有 273 项不得回退，记录新增后的实际总数。 | RED/GREEN 输出、定向与全量 pytest 输出。 |
| G09 | 桌面 90 秒 | 公网未部署目标 SHA、链中断、需刷新/剪辑、超时或出现客户端伪造数据。 | 预热后一次不间断 accept 主链 `<90s`，Summary 可见，所有数据来自同源 API。 | 桌面录屏、秒表、HAR/Network、最终截图。 |
| G10 | 375px 90 秒 | 375px 有横向滚动、按钮不可触控、反馈不可见、超时或调用不同 API。 | 375px 一次不间断同案例 accept `<90s`；无横滚，主要按钮可触控，加载/错误/成功状态可见，与桌面使用相同 API。 | 375px 录屏、秒表、视口截图、HAR。 |
| G11 | 公网部署 | 任一页面/同源 health 非 200，SHA 不符，OpenAPI 无 `from-events`，或仍回退旧包/localhost/mock/CORS 旁路。 | `/`、`/workspace`、同源 `/health`、`/api/v1/health` 均 200；两个 health 均含目标 SHA；后端 OpenAPI 含 `from-events`；SPA 刷新恢复；Nginx Host/SNI 正确。Persistent Disk 若无法代码声明，则部署后人工确认挂载和进程重启持久化。 | HTTP 输出、health JSON、OpenAPI 摘录、部署 URL/版本、刷新和重启记录。 |
| G12 | 追踪与保密 | UI/API/日志无法串联，或证据含 token、Cookie、API key、完整敏感资料。 | 以 `tripId`、`taskId`、`eventId`、V1/V2 `planVersionId` 和构建 SHA 串联 UI、Network、服务端日志及必要 DB 摘录；ID 一致且证据脱敏。无需新增 `traceId`。 | 脱敏 HAR、日志、DB 摘录和 ID 对照表。 |

## 5. 代码窗口 RED/GREEN 清单

代码窗口应先保存能证明问题存在的 RED 输出，再完成最小修改并保存 GREEN 输出。建议测试名是验收契约；如因项目命名规范调整，必须保持断言语义并在证据中给出映射。

### 5.1 必须新增的后端黄金测试

目标文件与测试：

```text
backend/tests/test_s1_t024_golden_path.py
test_beijing_single_accept_path_uses_real_sqlite_asgi_and_server_summary
```

测试必须使用默认生产应用组装、真实 SQLite 和 ASGI HTTP 边界，只替换外部 Provider 为确定性北京 Stub。至少断言：单参与者；约束先确认；V1 唯一 `CURRENT`；EXPENSE `+5000` 分；`from-events` 请求没有 candidates/locked/PASS；V2/Diff 为服务端产物；accept 后 V2/V1 状态正确；第一个未完成任务未被跳过；最终 `COMPLETED`；Summary 数字来自服务端事件。

RED/GREEN 命令（从工作树根执行）：

```powershell
& ..\..\.venv\Scripts\python.exe -m pytest -q backend/tests/test_s1_t024_golden_path.py::test_beijing_single_accept_path_uses_real_sqlite_asgi_and_server_summary
```

### 5.2 前端三个最小 RED/GREEN 契约

在既有 `frontend/tests/eventReplan.test.ts`、`replanPolicy.test.ts` 中扩展，或增加一个被 `npm test` 明确包含的测试文件，覆盖：

1. `accept/reject resumes the first unfinished task without skipping`：决策后从服务端返回的 currentPlan/events 重算，不能在已重算索引上再 `+1`。
2. `expense logical idempotency key is stable when amount changes`：相同 plan/task 的 EXPENSE key 不随金额变化。
3. `Sprint 1 summary renders server numbers and hides future media`：不得出现硬编码 100%/4 项；媒体及其他排除能力在 S1 主路径不可见。

RED/GREEN 与全量命令：

```powershell
Set-Location frontend
npm test
npm run lint
npm run build
Set-Location ..
```

### 5.3 既有专项和后端全量

定向回归：

```powershell
& ..\..\.venv\Scripts\python.exe -m pytest -q `
  backend/tests/test_s1_t024_golden_path.py `
  backend/tests/test_s1_t017_event_replan.py `
  backend/tests/test_s1_t022_summary_paths.py `
  tests/test_plan_v2_diff.py `
  tests/test_execution_expenses.py `
  backend/tests/test_planning_http_boundaries.py
```

其中必须保留并核对这些既有契约：

```text
test_same_event_replan_is_idempotent
test_rejected_v2_cannot_be_replayed_as_selected
test_accept_v2_atomically_switches_unique_current_and_is_idempotent
test_reject_v2_preserves_current_and_execution_state
test_reused_idempotency_key_with_different_expense_is_rejected
test_expense_replay_remains_idempotent_after_current_switches_to_v2
test_s1_t022_real_summary_path_is_complete_and_traceable[no_v2]
test_s1_t022_real_summary_path_is_complete_and_traceable[accepted_v2]
test_s1_t022_real_summary_path_is_complete_and_traceable[rejected_v2]
```

后端全量：

```powershell
& ..\..\.venv\Scripts\python.exe -m pytest -q
```

本轮不执行以上命令，也不记录预期总数为实际结果。验收时应确认基线 273 项无回退，并记录加入 T024 测试后的真实收集数、通过数和耗时。

## 6. 90 秒连续烟测

计时采用冻结的 warm-run 口径：只允许预先访问 health 使 Render 服务苏醒；不得预创建 Trip、V1、Event 或 V2，不得用 `VERIFIED_CACHE`、浏览器 Mock、剪辑或暂停替代真实链路。若产品决定把 Render 冷启动纳入 Review，则这是发布口径变更，应另记录冷启动结果，不能覆盖本门禁的 warm-run 结果。

计时起点：已加载 `/plan`，点击第一次“确认/继续”提交固定案例。
计时终点：服务端 Summary 在 UI 完整可见。

| 时间预算 | 检查点 |
|---|---|
| 0～10s | 提交北京单人 AssistanceProfile/约束。 |
| 10～35s | Provider 事实、V1 和 UNKNOWN 人工复核；未知不能自动变 PASS。 |
| 35～45s | 确认 V1 并 START 首任务。 |
| 45～55s | 提交计划额 `+5000` 分的 EXPENSE，并完成当前任务。 |
| 55～68s | 调用 `from-events`，显示服务端 V2 和 V1/V2 Diff。 |
| 68～75s | 接受 V2。 |
| 75～87s | 从首个未完成任务继续，完成剩余任务。 |
| 87～90s | 显示服务端 Summary。 |

同一个执行人对桌面 G09 和 375px G10 各录制一条从起点到终点的连续视频。375px 额外检查：`document.documentElement.scrollWidth <= document.documentElement.clientWidth`、主要按钮触控区域可用、文本和 Diff 不被裁切、加载/错误/成功状态不靠 hover 才能发现。

## 7. 公网部署与同源验收命令

以下命令只能在目标 SHA 已重新部署、G07/G08 已 GREEN 后执行。它们是计划，不是本轮结果。

```powershell
$web = 'https://imagine-1-31o2.onrender.com'
$api = 'https://imagine-mp7v.onrender.com'
$expectedSha = (git rev-parse HEAD).Trim()

foreach ($url in @(
  "$web/",
  "$web/workspace",
  "$web/health",
  "$web/api/v1/health",
  "$api/health",
  "$api/api/v1/health"
)) {
  $response = Invoke-WebRequest -UseBasicParsing -Uri $url
  if ($response.StatusCode -ne 200) { throw "HTTP gate failed: $url" }
  "{0} {1}" -f $response.StatusCode, $url
}

foreach ($url in @("$web/health", "$web/api/v1/health")) {
  $body = (Invoke-WebRequest -UseBasicParsing -Uri $url).Content
  if ($body -notmatch [regex]::Escape($expectedSha)) {
    throw "Build SHA mismatch: $url expected $expectedSha"
  }
}

$openApi = (Invoke-WebRequest -UseBasicParsing -Uri "$api/openapi.json").Content
if ($openApi -notmatch [regex]::Escape('/api/v1/trips/{trip_id}/replans/from-events')) {
  throw 'OpenAPI does not expose from-events'
}
```

随后人工执行：

- 在 `/workspace` 中途刷新，确认同一 `tripId` 的服务端状态可恢复，且没有 localhost、浏览器 Stub 或跨域旁路请求。
- 记录 Render 前后端服务的部署版本、目标 SHA、区域、环境变量来源；证据只能显示变量名和“已配置”，不得显示值。
- 若 Persistent Disk 没有在代码配置中声明，人工确认 SQLite 实际挂载路径；在保留数据的前提下重启进程，验证 Trip、Event、V1/V2 与 Summary 仍可恢复。
- 核对前端 Nginx 到 HTTPS upstream 的 Host/SNI 生效；同源两个 health 的 200 和 SHA 一致是最终外部事实。

## 8. 证据、追溯和需求矩阵

建议验收证据根目录（后续执行时创建，不属于本轮写入）：

```text
artifacts/s1-t024/<YYYYMMDD-HHMM>-<shortSHA>/
  G01-G08-commands/
  G01-api-and-db/
  G09-desktop/
  G10-375px/
  G11-deploy/
  G12-trace/
  defects/
```

文件名统一为 `Gxx-<kind>-<step>-<timestamp>.<ext>`，例如 `G09-video-accept-20260826T143000+0800.mp4`。命令需保留命令行、stdout/stderr、exit code、开始/结束时间和 SHA；JSON 保留 HTTP 状态与脱敏 body；视频必须含完整地址栏、视口/设备、连续秒表和最终 Summary。自动化证据覆盖 G01～G08；G09～G12 需要部署后的人工/半自动证据。

G12 建立以下单行对照，不要求新 `traceId`：

```text
buildSha -> tripId -> V1 planVersionId -> taskId -> EXPENSE eventId -> V2 planVersionId -> decision -> Summary
```

| 需求来源 | 验收意图 | 门禁 | 前置 | 证据 |
|---|---|---|---|---|
| Sprint Goal | 第一次 Review 展示关怀单人完整 Agent | G01、G09～G12 | 目标 SHA 部署 | 全链视频、秒表、API/日志/ID 对照 |
| S1-T024 | 北京单人 V1→执行→+50 元→V2/Diff→accept→Summary | G01、G03～G05、G09、G10 | G07/G08 GREEN | 黄金 pytest、两端录屏、Summary JSON |
| T017 | 服务端事件驱动重规划生产入口 | G01、G02、G04 | `from-events` 可用 | 请求/响应、专项 pytest、409 无副作用 |
| T018 | 最小扰动 V2、Diff、接受/拒绝 | G01～G03 | V1 和事件存在 | V1/V2 状态、Diff、决策回归 |
| T022 | 无 V2/accept/reject 服务端 Summary | G02、G05 | 三路径可完成 | 参数化回归和 Summary JSON |
| T023 | 公网 HTTPS、同源 API 与目标版本 | G09～G12 | 重新部署 | HTTP/health/OpenAPI/部署证据 |
| Sprint 1 范围 | 严格单人、无媒体及未来能力 | G06、G09、G10 | S1 UI 构建 | 前端测试、两端录屏 |

依赖放行顺序：G01～G08 全部 GREEN 后才允许发布目标 SHA；G11 GREEN 后才允许执行 G09/G10/G12；G09～G12 全部 GREEN 且无阻断缺陷后，S1-T024 才可从 `BLOCKED` 转为最终 `PASS`。任一环节不能用旧包、旧日志或单测总数代替。

## 9. 已知非阻断项与签字模板

以下是冻结设计确认的后续改进，不作为本次阻断：pending V1 review 的刷新恢复、reject 后主动恢复 `v2Attempted`。这不豁免 G11 的一般 SPA 刷新/服务端状态恢复，也不允许为绕过它们伪造状态。

当前无待 PO/实现分析继续冻结的产品设计选择。仍需部署执行阶段给出事实证据的只有：目标 SHA 是否上线、Persistent Disk 是否实际挂载、warm-run 与可选 cold-start 的发布口径记录；它们是执行门禁，不是新增设计。

最终独立验收签字（真实执行后填写）：

```text
任务：S1-T024
提交 SHA：
前端部署版本 / URL：
后端部署版本 / URL：
环境与区域：
Persistent Disk：已确认 / 不适用 / FAIL（证据：）
验收日期与时区：
验收人：

G01～G12：
自动化统计：backend __ passed；frontend __ passed；lint exit __；build exit __
桌面用时：__ 秒
375px 用时：__ 秒
阻断缺陷：
非阻断缺陷：
证据根目录：

最终结论：PASS / FAIL / BLOCKED
签字：
```

未填写完整证据、使用非目标 SHA、任一门禁仍为 `NOT_RUN/BLOCKED`，或只引用冻结设计中的历史通过数时，最终结论不得写 `PASS`。
