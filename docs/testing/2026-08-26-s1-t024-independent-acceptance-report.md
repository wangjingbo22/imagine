# S1-T024 独立测试与验收报告

> 验收日期：2026-08-26（Asia/Shanghai）
> 验收角色：独立 QA
> 工作树：`C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.worktrees\czy-S1-T024`
> 功能基线：`b5922986202091b2744b62fe1f3a0233b5fcba56`
> 冻结设计：`docs/superpowers/specs/2026-08-26-s1-t024-minimal-golden-path-design.md`
> 验收计划：`docs/testing/2026-08-25-s1-t024-independent-test-plan.md`

## 1. 独立结论

**QA_FAIL / CHANGES_REQUIRED**

严重度统计：`Critical 0 / Important 4 / Minor 0`。

所有要求的本地命令都已在本窗口 fresh 执行；后端、前端、lint、build、compileall 和 `git diff --check` 的进程结果均为绿色。但是，新增黄金回归使用了错误的亲子 AssistanceProfile，并绕过了它声称覆盖的 Provider/Trip HTTP 链；前端续跑与部署回归还存在会“假绿”的字符串/纯 helper 断言。按验收约定，任一 Important 即阻断，因此不能给出 `QA_PASS` 或 `READY_FOR_FINAL_SPEC_REVIEW`。

公网仍是旧包/同源 health 502 的冻结事实，本轮没有把未部署代码当成公网结果。G09～G12 均保持 `BLOCKED`，本报告不宣称 T024 已公网完成。

## 2. 阻断发现

### Important I-01：黄金回归实际使用亲子画像，不是冻结的北京低体力单自然人案例

位置：

- `backend/tests/test_s1_t024_golden_path.py:21-23,103-107`
- `backend/tests/fixtures/planning/golden_candidate_plan.json:26-45`

预期：固定北京案例必须是恰好一个自然人，`assistanceProfile.type=LOW_STAMINA`，不得采用亲子两人语义；黄金测试还应直接断言服务端持久化后的关怀画像。

实际：测试只断言 `mode == SINGLE` 和 `participants` 数组长度为 1。它复用的 fixture 中，唯一元素的 nickname 是“亲子旅客”，`assistanceProfile.type` 是 `PARENT_CHILD`，并含 `childAge=8` 和午休窗口。数组长度为 1 不能把一个亲子组合变成“一个自然人低体力案例”。

复现命令及实际结果：

```powershell
& ..\..\.venv\Scripts\python.exe -m pytest -q `
  backend/tests/test_s1_t024_golden_path.py::test_beijing_single_accept_path_uses_real_sqlite_asgi_and_server_summary
# 实际：1 passed in 9.55s

rg -n 'nickname|type|childAge|napWindow' `
  backend/tests/fixtures/planning/golden_candidate_plan.json
# 实际：亲子旅客 / PARENT_CHILD / childAge 8 / napWindow
```

影响：测试名和绿色结果会错误证明冻结案例已覆盖，实际没有验证 Sprint Goal 的低体力单自然人路径。

最小修复建议：为 T024 建立专用北京 `LOW_STAMINA` fixture（或从默认 Planner 输入经生产转换生成），移除 `childAge`/亲子语义，并同时断言请求、服务端 Trip 与已确认 AssistanceProfile 都是一个参与者且类型为 `LOW_STAMINA`。修复后先证明旧 fixture/断言为 RED，再跑到 GREEN。

### Important I-02：黄金测试预装候选事实并直接确认 Trip，Provider Stub 未参与，Diff/请求断言不足以防假绿

位置：`backend/tests/test_s1_t024_golden_path.py:26-71,103-127,196-213,221-283`。

预期：测试应使用生产 `create_app`、真实 SQLite/ASGI，仅替换外部 Provider；从公开 HTTP 边界建立/确认 Trip 和 Provider 事实，并验证 `from-events`、实质 Diff、V1/V2/事件 ID 谱系及决策后首个未完成任务。

实际：

1. `_candidate_request()` 直接读取既有 `golden_candidate_plan.json`；`workflow.confirm_trip(...)` 在创建 ASGI client 前直接调用应用服务。
2. `BeijingProviderStub` 被装进 `AmapLocationService`，但测试没有调用任何 Provider HTTP 端点，也没有 Stub 调用计数；即使 Provider 接线完全损坏，该测试仍可绿色。
3. `assert "candidates" not in {"schemaVersion": ..., "reason": ...}` 只检查测试自己刚写出的字面量，是恒真断言；也没有检查 `locked`/客户端 `PASS`。
4. Diff 只断言 `basePlanId` 和 `candidatePlanId`，没有断言变更内容、冻结前缀或最小扰动；谱系只抽查 EXPENSE `eventId` 和所有事件的 `tripId`，没有系统核对 V2 `parentId`、每个事件的 `planVersionId/taskId` 及首个未完成任务只 START 一次。

复现命令：同 I-01；实际仍为 `1 passed`，说明当前绿色结果无法证明上述链路。

影响：G01 的“生产组装/仅 Stub 外部 Provider/真实 Diff 与 ID 谱系”证据不成立，测试可能在关键集成断裂时假绿。

最小修复建议：

- 只给 `create_app` 注入固定外部 Provider seam 和临时 SQLite 路径，让 Plan/Workflow/PlanningBoundary 由工厂正常组装；通过公开 ASGI 端点建立、确认 Trip/约束并取得 Provider 事实。
- 给 Stub 增加调用记录并断言北京 `cityCode=110000` 的必要地点/路线调用真实发生，生产服务使用其返回事实。
- 对实际发送的 replan body 做精确契约断言或补未知字段拒绝测试；删除字面量恒真断言。
- 断言非空且语义正确的 Diff、冻结任务、V2→V1 parent、V1/V2 状态、每个 Event→Task/Plan 谱系和决策后第一个未完成任务恰好一个 START。

### Important I-03：前端测试没有执行 accept/reject 编排，Summary/媒体/+¥50 只做源码字符串扫描

位置：

- `frontend/tests/executionProgress.test.ts:20-43,60-69`
- 被声称覆盖的生产时序位于 `frontend/src/pages/WorkspacePage.tsx:307-342,650-670,813-847,883-947,1520-1527,1624-1650`

预期：回归应能抓住 `applyTripState` 已异步更新索引后又使用旧 closure `currentTaskIndex + 1` 的缺陷；accept 与 reject 都要验证只向恢复后首个未完成任务写一次 START。`+¥50` 应验证点击只改输入值，直到用户完成任务才发真实 EXPENSE/COMPLETE。Summary 应用服务端响应渲染，未来媒体入口应在运行时不可见。

实际：

- 名为“accept/reject resumes...”的测试只直接调用 `firstUnfinishedTaskIndex`，没有调用 `decidePlanV2`、`applyTripState`、`startTask` 或 mock `tripApi`，也没有 accept/reject 两条时序和 START 次数断言。若页面重新写回 `currentTaskIndex + 1`，该测试仍会通过。
- Summary/媒体/+¥50 测试读取 `WorkspacePage.tsx` 文本后匹配正则。只要目标字符串仍存在，它不能证明 UI 使用响应值、入口不可操作，或快捷按钮没有同时发送 API。

复现命令及实际结果：

```powershell
pnpm test
# 实际：24 tests，24 passed；其中上述 3 项通过
```

影响：当前 production diff 经手工审查看起来已使用恢复后的 `currentPlan + events`，稳定 key、服务端 Summary 和只填输入框的按钮；但自动化并不能防止这些核心缺陷回归。按“错误测试本身为 Important”的验收规则，G03/G07 不能放行。

最小修复建议：提取可执行的“决策后续跑动作”纯函数或建立最小组件/服务编排 harness，分别模拟 accept/reject 恢复响应，断言 exact next task、无 `+1`、START API 恰好一次；对 `+¥50` 断言点击前后 API 调用数为 0、完成提交后 EXPENSE/COMPLETE payload 正确；用渲染测试输入服务端 Summary DTO 并查询可见内容/不可见入口，不再以源码字符串存在性作为主断言。

### Important I-04：Nginx 回归没有逐 location 断言 Host/SNI，错误配置可假绿

位置：`tests/test_deployment_config.py:18-27`。

预期：`location /api/` 和 `location /health` 必须分别包含 `proxy_ssl_server_name on`、`proxy_ssl_name $proxy_host` 和 `proxy_set_header Host $proxy_host`。

实际：测试对整个 nginx 文本做字符串存在检查，只对 `proxy_ssl_server_name` 计数至少 2 次；`proxy_ssl_name` 和 Host 只要求全文件出现一次。把两个 SNI 指令放入同一 location、或从 `/health` 删除 Host/proxy_ssl_name，测试仍可能通过。当前 `frontend/nginx.conf:8-27` 经手工审查确实同时配置正确，但回归无法可靠保护它。

复现命令及实际结果：

```powershell
& ..\..\.venv\Scripts\python.exe -m pytest -q tests/test_deployment_config.py
# 实际：7 passed in 0.91s
```

影响：T023 的本地配置测试可能在同源 health 再次 502 时仍为绿色；公网 G11 本来就 BLOCKED，此测试质量问题还阻止代码阶段放行。

最小修复建议：按花括号层级提取 `/api/` 与 `/health` 两个 location block，分别断言三条完整指令和正确 `proxy_pass`；或用可解析的 nginx 模板结构测试。不要只统计全文件字符串。

## 3. 生产 diff 手工审查结果

以下结论来自本窗口逐文件 diff 与当前源码审查，不来自代码窗口自报：

| 检查点 | 手工结果 | 证据 |
|---|---|---|
| accept/reject 首个未完成任务 | 实现方向正确 | `WorkspacePage.tsx:825-846` 在决策后 GET Trip，基于返回的 `currentPlan/events` 调用 helper，并仅 START 该 index；不再复用 state index 或 `+1`。 |
| 跳过/完成/失败回退续跑 | 实现方向正确 | `WorkspacePage.tsx:855-947` 均从事件后的服务端状态重算 next index。 |
| EXPENSE 逻辑 key | 正确 | `executionReplan.ts:24-30` 返回 `planId:taskId:eventType`，不含金额；后端同 key 同 payload 幂等、异金额 409 的 fresh 专项通过。 |
| Summary 真值 | 当前代码正确 | `WorkspacePage.tsx:1624-1650` 只在 `summary` 存在时显示 completed/total、金额、事件数与历史；未发现硬编码关怀 100%/4 项。 |
| Sprint 1 媒体入口 | 当前代码已移除 | `frontend/src` 未检出旅行影像、拍摄指导、上传照片/视频或导出总结入口。 |
| +¥50 | 当前代码正确 | `WorkspacePage.tsx:1520-1527` onClick 仅 `setActualCost`；真实 EXPENSE/COMPLETE 仍在 `handleCompleteTask`。 |
| build SHA | 当前代码正确 | `Settings.build_sha` 只接受 `BUILD_SHA`/`RENDER_GIT_COMMIT`；两个 health 共用该设置，未配置返回 `unavailable`，没有 git HEAD fallback。额外手工探针得到 `qa-render-sha`、同时设置时得到 `qa-build-sha`。 |
| Nginx/CORS/磁盘范围 | 当前配置正确 | 两个 location 均有 Host/SNI；CORS 为 `https://imagine-1-31o2.onrender.com`；`render.yaml` 没有新增付费 disk 声明。 |

上述生产实现正向审查不抵消 I-01～I-04 的测试有效性缺陷。

## 4. Fresh 命令证据

统一测试临时根目录（保留，未删除）：

```text
C:\Users\lenovo\AppData\Local\Temp\codex-s1-t024-independent-20260826-033731-bdb33806
```

Python 命令使用该目录下独立 `basetemp`、pytest cache 与 `PYTHONPYCACHEPREFIX`。前端 runner 使用 Codex bundled Node/pnpm；当前沙箱 PATH 没有 `npm`，首次 `npm test` 和首次未注入 Node PATH 的 pnpm 尝试均未进入测试断言，不计为产品失败。注入 bundled Node bin 后 fresh 结果如下：

| 命令/范围 | 结果 | 判读 |
|---|---:|---|
| G01 黄金单测 | `1 passed in 9.55s` | 进程 GREEN；因 I-01/I-02，验收语义 FAIL。 |
| G01～G08 后端定向：T024/T017/T022/Diff/expenses/planning | `45 passed in 11.65s` | GREEN。 |
| deployment tests | `7 passed in 0.91s` | 进程 GREEN；因 I-04，配置回归质量 FAIL。 |
| 后端全量 | `276 passed in 17.61s` | GREEN；高于 273 基线。 |
| 前端全量 | `24 passed`，`0 fail` | 进程 GREEN；高于 21 基线，但因 I-03 不放行。 |
| 前端 lint | exit `0` | GREEN。 |
| 前端 build | exit `0`，1834 modules transformed | GREEN；Vite 仍给出既有 `runtime-config.js` 非 module 警告，不是本次阻断。 |
| `python -m compileall -q app backend tests` | exit `0` | GREEN。 |
| `git diff --check` | exit `0` | GREEN，仅有 Git for Windows 的 LF→CRLF 提示，无 whitespace error。 |

前端 build 的额外参数被 package script 作为字面 `--` 传给 Vite，产物仍生成到已忽略的 `frontend/dist/`；本窗口没有删除或修改该生成目录。

## 5. G01～G12 判定

| Gate | 结论 | 独立 QA 依据 |
|---|---|---|
| G01 后端黄金链 | `FAIL` | 命令通过，但案例为 PARENT_CHILD，且 Provider/Trip HTTP 链被绕过；见 I-01/I-02。 |
| G02 三路径与一致性 | `PASS` | T017/T022/Diff/expenses/planning 定向 fresh 45 项全部通过，未发现相反生产 diff。 |
| G03 决策后续跑 | `FAIL` | 手工实现审查正向，但自动化没有执行 accept/reject/applyTripState/START 时序；见 I-03。 |
| G04 EXPENSE 幂等 | `PASS` | 前端 key 不含金额；后端同 payload 同 eventId、异金额 409 专项及黄金路径实际执行通过。 |
| G05 Summary 真值 | `PASS` | 当前渲染只用服务端 Summary 字段，后端三路径/黄金 Summary 均 fresh 通过；测试质量缺口统一计入 G07/I-03。 |
| G06 S1 反膨胀 | `PASS`（代码级） | 手工 diff 和 `frontend/src` 扫描未发现媒体/拍摄/影像/导出入口；不替代部署后视觉门禁。 |
| G07 前端质量 | `FAIL` | test/lint/build 进程均绿，但关键新增测试会假绿；见 I-03。 |
| G08 后端质量 | `FAIL` | 全量 276 进程全绿，但必需 G01 黄金契约无效；见 I-01/I-02。 |
| G09 桌面 `<90s` | `BLOCKED` | 目标 SHA 未部署；未执行，不能写 PASS。 |
| G10 375px `<90s`/无横滚 | `BLOCKED` | 目标 SHA 未部署；仅检查到响应式 CSS/本地 build，不能替代连续烟测。 |
| G11 公网/同源/版本 | `BLOCKED` | 冻结事实仍为旧包及同源 health 502；本轮未联网重验未部署版本。 |
| G12 Network/日志/ID 串联 | `BLOCKED` | 需要部署后真实运行的脱敏 Network、日志和目标 SHA。 |

代码阶段也尚未达到 `READY_FOR_FINAL_SPEC_REVIEW`；先修复四个 Important 并由独立 QA fresh 重跑 G01～G08。

## 6. Git 与写入边界

- 工作树确认是 linked worktree，分支 `czy-S1-T024`，HEAD=`b5922986202091b2744b62fe1f3a0233b5fcba56`。
- `origin/main=966913a48931ce03ff2190cf342da5c0bbea8645`，本分支 behind 1、ahead 0。唯一上游提交 `966913a docs: align README with latest Sprint 1 state` 只修改 `README.md` 与 `frontend/README.md`；这是 Git 集成事项，不是功能失败。
- 本窗口没有 sync、切支、stash、commit、push 或 merge。
- 验收前已有 9 个 tracked 修改：`app/api/routes.py`、`app/core/config.py`、`app/main.py`、`frontend/nginx.conf`、`frontend/package.json`、`frontend/src/pages/WorkspacePage.tsx`、`frontend/src/services/executionReplan.ts`、`render.yaml`、`tests/test_deployment_config.py`。
- 验收前已有源文件级 untracked：黄金测试、冻结设计、验收计划、前端新增测试；另有 `.qa-t024-final-*` SQLite 目录。本窗口没有删除或改写这些目录/用户文件。
- 本窗口唯一允许的仓库写入是本报告。测试生成物位于上列系统临时根目录；前端 build 还刷新了被 Git 忽略的 `frontend/dist/`/依赖缓存，未做清理。

## 7. 复验放行条件

下一轮独立 QA 至少需要看到：

1. 专用北京 `LOW_STAMINA` 单自然人 fixture 与服务端持久化断言；
2. 黄金测试真实经过公开 Trip/约束/Provider/规划 HTTP 边界，Provider Stub 有调用证据；
3. 非恒真的 Diff、request、首个未完成 START 和完整 ID 谱系断言；
4. accept/reject 编排、+¥50 行为、Summary/媒体运行时测试；
5. Nginx 两个 location 的分块断言；
6. 重新 fresh 执行本报告第 4 节全部命令并重新手工审查 diff。

即使上述全部修复并使 G01～G08 GREEN，G09～G12 仍须在目标 SHA 重新部署后由桌面/375px 连续烟测、公网 health/OpenAPI、Network/日志证据独立放行。

## 8. QA 签字

```text
结论：QA_FAIL / CHANGES_REQUIRED
代码门禁：未放行
公网门禁：G09-G12 BLOCKED
Critical：0
Important：4
Minor：0
独立验收基线：b5922986202091b2744b62fe1f3a0233b5fcba56
验收日期：2026-08-26 Asia/Shanghai
验收人：Codex 独立 QA 窗口
```

## 9. FIX1 独立复验（当前最新结论）

本节追加于第一轮报告之后；第 1～8 节的 `QA_FAIL / CHANGES_REQUIRED`、四个 Important 和首次命令输出均作为历史原样保留，不以代码任务的自报结果覆盖。以下结论仅来自本独立 QA 窗口对 FIX1 当前工作树的重新审查、缺陷注入和 fresh 执行。

**QA_PASS / READY_FOR_FINAL_SPEC_REVIEW（仅代码阶段）**

FIX1 当前严重度统计为 `Critical 0 / Important 0 / Minor 0`；第一轮 `I-01`～`I-04` 均已独立复验关闭。G01～G08 已达到代码阶段放行条件。G09～G12 仍因目标 SHA 未重新部署而为 `BLOCKED`，因此本结论不表示 S1-T024 已完成公网验收，也不表示 Sprint Goal 已最终 PASS。

### 9.1 第一轮四个 Important 的关闭证据

| 缺陷 | FIX1 独立复验 | 判定 |
|---|---|---|
| I-01 严格单人画像错误 | 专用 fixture `backend/tests/fixtures/s1_t024/beijing_low_stamina_single.json:2-32` 的请求是北京、`SINGLE`、唯一昵称“单人旅客”、`LOW_STAMINA`，请求中没有 `PARENT_CHILD`、`childAge` 或亲子语义。黄金测试在 `backend/tests/test_s1_t024_golden_path.py:124-140,283-337` 对确认 Trip、确认约束和规划请求重复断言同一低体力画像，并在 `536-549` 直接读取真实 SQLite 的 `confirmed_trip_inputs`，断言持久 Trip 与 HTTP 确认结果完全相等。通用响应 schema 会把不适用的 `childAge` 规范化为 `null`，但输入未携带该字段，类型始终为 `LOW_STAMINA`，不存在亲子语义。 | `CLOSED` |
| I-02 黄金链假绿 | `backend/tests/test_s1_t024_golden_path.py:106-121` 只在外部 Provider client seam 注入 `BeijingProviderStub`，其余由 production `create_app` 组装服务、repo 和 SQLite；`292-375` 经公开 ASGI HTTP 完成城市解析、Trip/约束确认、Provider 事实、V1 review 与执行启动。`422-472` 用 request hook 断言 `from-events` 精确 body，并分别验证 `candidates`、`lockedTaskIds`、客户端 `validationReport/PASS` 为 422；同段断言服务端非空 Diff、冻结前缀及最小扰动语义。`474-598` 验证 V2 parent、V1/V2 状态、Provider 实际调用、`COMPLETED`、`+5000` 分、所有 Event 的 Trip→Plan→Task 谱系以及决策后首个未完成任务只有一次 V2 `START`。 | `CLOSED` |
| I-03 前端测试只测孤立 helper/字符串 | `frontend/tests/executionProgress.test.ts:47-237` 直接导入并执行生产 `decideAndContinueExecution`、`continueExecutionFromRestoredState`、`submitTaskCompletionEvents`、`plannedPlusFiftyYuan` 和 `sprint1SummaryView`：accept/reject 都核对 `decide→restore→apply→START` 顺序和仅一次 START；+¥50 在提交前不调用 API，提交时真实产生 EXPENSE→COMPLETE；Summary 使用服务端 DTO 数字且无媒体 action。手工接线审查确认 `WorkspacePage.tsx:55-62,311-345,655-686,818-847,883-958,1529-1533,1638-1644` 实际调用这些生产函数；TS/TSX 扫描未发现照片、视频、拍摄指导、影像、导出或上传入口，也未发现“关怀满足率/4 项硬约束”硬编码。 | `CLOSED` |
| I-04 Nginx 跨块假绿 | `tests/test_deployment_config.py:18-46` 用括号深度分别提取 `/api/` 与 `/health` location，并在每个块内独立断言对应 `proxy_pass`、SNI、`proxy_ssl_name`、Host 和转发协议；`frontend/nginx.conf:8-27` 两块配置匹配。独立 mutation probe 在系统临时副本中仅删除 `/api/` 的 Host 时得到 `EXPECTED_RED`，仅删除 `/health` 的 `proxy_ssl_name` 时也得到 `EXPECTED_RED`，最终输出 `MUTATION_PROBE_PASS both single-location deletions were detected`。 | `CLOSED` |

附加部署静态审查：`app/core/config.py:22-25` 的 build SHA 只接受 `BUILD_SHA`/`RENDER_GIT_COMMIT`；`app/main.py:213-218` 与 `app/api/routes.py:24-31` 使用同一配置值，未配置时明确返回 `unavailable`。对应 ASGI 测试见 `tests/test_deployment_config.py:87-130`。`render.yaml:6,10-13,22-25` 使用两个 `/health`、正确公网 CORS origin 和 HTTPS upstream，没有扩大为付费 Persistent Disk 声明。

### 9.2 I-04 mutation probe

本轮新建并保留的系统临时根目录：

```text
C:\Users\lenovo\AppData\Local\Temp\codex-s1-t024-independent-fix1-e7c22af33f214b9c8594e077ae9e33bd
```

实际调用当前 `tests.test_deployment_config.test_nginx_has_spa_fallback_and_api_proxy`，只把该测试模块的 `ROOT` 指向以下临时副本，没有修改工作树：

| 临时变异 | 单一改动 | 实际 |
|---|---|---|
| `nginx-mutations/api-host-removed/frontend/nginx.conf` | 只从 `/api/` 删除 `proxy_set_header Host $proxy_host;` | `EXPECTED_RED` |
| `nginx-mutations/health-sni-name-removed/frontend/nginx.conf` | 只从 `/health` 删除 `proxy_ssl_name $proxy_host;` | `EXPECTED_RED` |

两种变异若未被断言捕获，探针自身会 exit 1；本次探针 exit 0，说明两处单块缺失均被当前生产测试检测。准备探针时发生的 PowerShell 引号/字面指令错误都在测试函数执行前退出，不涉及产品代码，也没有计作 RED 证据；表中只记录最终实际调用测试函数的变异结果。

### 9.3 G01～G08 fresh 命令结果

Python 命令使用上列唯一临时根目录中的独立 runtime、pytest basetemp/cache 和 pycache；为规避 Windows 长路径，仅 `compileall` 的 pycache 使用另一个已保留的短系统临时目录 `C:\Users\lenovo\AppData\Local\Temp\c24f1-e7c22af3`。前端使用 Codex bundled Node/pnpm。

| 命令/范围 | fresh 实际结果 | 判读 |
|---|---:|---|
| G01 黄金单测 `test_beijing_single_accept_path_uses_real_sqlite_asgi_and_server_summary` | `1 passed in 2.08s` | `PASS`；结合 9.1 的实现与断言审查，不再是假绿。 |
| T024/T017/T022/Diff/expenses/planning 定向 | `45 passed in 11.66s` | `PASS`。 |
| `tests/test_deployment_config.py` | `7 passed in 1.11s` | `PASS`；另有 9.2 的两项 mutation RED 证据。 |
| 后端全量 | `276 passed in 17.62s` | `PASS`，无回退。 |
| 前端全量 | `28 tests / 28 pass / 0 fail` | `PASS`；本轮新增行为契约实际执行。 |
| 前端 lint | exit `0` | `PASS`。 |
| 前端 build | exit `0`，1834 modules transformed | `PASS`；仍有 `runtime-config.js` 非 module 的既有 Vite 警告，不阻断。 |
| `python -m compileall -q app backend tests` | exit `0` | `PASS`。 |
| `git diff --check` | exit `0` | `PASS`；只有 Git for Windows 的 LF→CRLF 提示，无 whitespace error。 |

环境重试说明：第一次启动前端测试时 bundled Node bin 尚未加入当前 PATH，命令在执行任何测试断言前以“node not recognized”退出；注入固定 bundled Node 路径后的完整 fresh 结果为 28/28。`compileall` 第一次因长 `PYTHONPYCACHEPREFIX` 生成超过 Windows 路径限制的临时 `.pyc` 路径而退出；把前缀改为上述短系统临时目录后，同一源码范围 exit 0。这两次均为 runner 环境问题，不计作产品失败，原始临时目录均保留。

### 9.4 当前门禁

| Gate | FIX1 最新结论 | 独立 QA 依据 |
|---|---|---|
| G01 后端黄金链 | `PASS` | 严格北京单自然人、公开 ASGI、生产组装、真实 SQLite、仅 Stub 外部 Provider，全链及谱系断言 fresh 通过。 |
| G02 三路径与一致性 | `PASS` | 定向 45 项覆盖 reject、决策幂等、决策后 replan 409、Summary 三路径等契约。 |
| G03 决策后续跑 | `PASS` | 生产编排行为测试覆盖 accept/reject/all-terminal，页面接线时序审查无重复或跳过 START。 |
| G04 EXPENSE 幂等 | `PASS` | key 不含金额；同 key 同 payload 幂等、不同金额冲突；+¥50 最终走真实 EXPENSE/COMPLETE 编排。 |
| G05 Summary 真值 | `PASS` | presenter 和页面仅显示服务端 DTO 数字，无 100%/4 项硬编码。 |
| G06 S1 反膨胀 | `PASS`（代码级） | TS/TSX 主路径无媒体及 Sprint2/Future 入口；仍须由部署后两视口烟测补充视觉证据。 |
| G07 前端质量 | `PASS` | 行为测试 28/28、lint/build exit 0，测试不再依靠源码字符串假绿。 |
| G08 后端质量 | `PASS` | 黄金、定向、deployment、全量与 compileall 全绿，黄金测试质量已通过手工审查。 |
| G09 桌面 `<90s` | `BLOCKED` | 未部署目标 SHA；本轮按要求未执行最终公网验收。 |
| G10 375px `<90s`/无横滚 | `BLOCKED` | 未部署目标 SHA；本地 build 不能替代连续手机视口烟测。 |
| G11 公网/同源/版本 | `BLOCKED` | 冻结外部事实仍是线上旧包/同源 health 502，须重新部署后核对页面、两个同源 health、SHA 和 OpenAPI。 |
| G12 Network/日志/ID 串联 | `BLOCKED` | 须在目标部署上以 tripId/taskId/eventId/V1/V2 id 和 SHA 提交脱敏证据。 |

因此代码窗口可进入最终规格审查/部署步骤，但 S1-T024 仍不能写最终公网 `PASS`。pending V1 review 刷新恢复和 reject 后主动恢复继续作为冻结设计中的非阻断后续改进；Persistent Disk 仍保留为部署后人工核验，不在本轮扩大代码范围。

### 9.5 Git 与写入边界复核

- 工作树仍为 `czy-S1-T024`，HEAD=`b5922986202091b2744b62fe1f3a0233b5fcba56`。
- 复验结束前 `origin/main=4c05be26d2e913f50c94b5e29f25d9c905083831`，本分支 `ahead 0 / behind 2`；上游两个提交只涉及 `README.md`、`frontend/README.md`。这是后续 Git 集成事项，不是功能失败；本窗口未同步。
- 源码 tracked diff 仍是验收前的 10 个文件，共 `378 insertions / 294 deletions`；源文件级 untracked 仍包括专用 fixture/黄金测试、冻结设计、验收计划、本文档和前端行为测试。既有 `.qa-t024-final-*` 目录未删除、未改写。
- 本独立 QA 窗口唯一仓库写入是追加本报告；测试产物只写入上述系统临时目录，前端 build 写入 Git 忽略的 `frontend/dist`。未执行 sync、切支、stash、commit、push 或 merge。

### 9.6 FIX1 独立 QA 签字

```text
最新结论：QA_PASS / READY_FOR_FINAL_SPEC_REVIEW（仅代码阶段）
代码门禁：G01-G08 PASS
公网门禁：G09-G12 BLOCKED
Critical：0
Important：0（第一轮 4 项均 CLOSED）
Minor：0
独立验收基线：b5922986202091b2744b62fe1f3a0233b5fcba56
验收日期：2026-08-26 Asia/Shanghai
验收人：Codex 独立 QA 窗口
公网最终结论：BLOCKED / NOT_RUN（等待目标 SHA 部署）
```
