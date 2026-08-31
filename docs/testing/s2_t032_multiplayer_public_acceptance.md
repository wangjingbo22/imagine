# S2-T032 多人公网闭环验收

> 当前状态：`LOCAL_AUTOMATION_PASS / PUBLIC_UAT_NOT_RUN`
>
> 追溯：`PBI-17-A -> AC-17-A -> S2-T032 -> UAT-S2-E2E-001（计划编号）`
>
> 场景：`E2E-S2-新增需求-多人六问到回忆闭环`

## 1. 编号与范围

`UAT-S2-E2E-001` 仅来自需求表 `SprintBacklog模板!O36` 的“待 UAT 编号”，在 `用户功能验收清单`中没有独立行。本文用于执行该计划场景，不代表编号已经由老师登记或验收。

本任务消费 `UAT-S2-001~012` 的分段合同，验收一个组织者和两名成员在同一 Trip 中完成：

1. 组织者固定六问和确认卡；
2. 两个一次性邀请和两个独立成员会话；
3. 未确认与硬冲突门禁、放宽和三人重确认；
4. FactRef 支撑的唯一推荐和共享三人 V1；
5. 执行、到达证据和任务照片；
6. LATE/FATIGUE、PROPOSED V2、结构化 Diff 和组织者决策；
7. 按真实事件时间聚合的回忆；
8. 375px 与 768px 的移动适配和可访问性。

## 2. 自动化边界

本地自动化使用 ASGI、单 SQLite 文件及确定性 Provider/LLM stub 验证三人业务血缘；前端 Vitest 验证 MemoryTimeline 组件合同，本地 Playwright 以 Mock API 在 375px/768px 检查成员字段权限和响应式合同。它们可标记为 `LOCAL_AUTOMATION_PASS`，但不能证明：

- 最新代码已部署到公网；
- 正式 `POST recommendations` 编排；
- 真实高德或百炼请求；
- 真实 GPS、相机或文件权限；
- 三个真实独立浏览器会话；
- 375px/768px 公网连续链；
- 老师或非作者签字。

Mock API、stub、Fixture 或源码检查都只能形成本地合同证据，不能命名为公网闭环证据。

因此本文的公网结论保持 `PUBLIC_UAT_NOT_RUN`，直到第 5 节全部完成并留下合格证据。

## 3. 进入条件

执行前必须记录：

- 前端和后端公网 URL；
- 前后端对应的同一 40 位 build SHA；
- 验收日期、时区、操作者和设备；
- 高德、百炼 Secret 的“已配置/未配置”，不得记录值；
- 定位、相机或文件权限的可用状态；
- 三个全新浏览器上下文：组织者、成员 A、成员 B。

不得预创建 Trip、revision、推荐、PlanVersion、事件、照片或 Timeline。若部署 SHA 不可核验，结果直接记为 `BLOCKED`。

## 4. 门禁矩阵

| 门禁 | 内容 | 当前状态 | 可接受证据 |
|---|---|---|---|
| T032-L01 | 本地三人 ASGI/SQLite/stub 连续链 | LOCAL_AUTOMATION_PASS | 专项 pytest 原始输出 |
| T032-L02 | 来源、权限和证据状态追溯合同 | LOCAL_AUTOMATION_PASS | traceability pytest 原始输出 |
| T032-L03 | MemoryTimeline 本地 Vitest 合同 | LOCAL_AUTOMATION_PASS | Vitest 原始输出 |
| T032-L04 | 375px/768px 本地 Mock Playwright 合同 | LOCAL_AUTOMATION_PASS | 4 项本地 UI 合同；非真实后端连续链 |
| T032-L05 | 前后端全量回归、build、lint | 待根级复验 | 命令、时间、退出码、实际通过数 |
| T032-P01 | 目标 SHA 公网部署 | NOT_RUN | health/build 响应与脱敏环境记录 |
| T032-P02 | 组织者加两成员独立会话 | NOT_RUN | 连续视频、脱敏 Network 与 session 审计 |
| T032-P03 | 未 READY 零 Provider/推荐/规划调用 | NOT_RUN | 前后调用计数与 409 响应 |
| T032-P04 | 真实高德/百炼边界 | NOT_RUN | 脱敏来源、降级状态和服务日志 |
| T032-P05 | GPS/照片真实设备路径 | NOT_RUN | 权限结果、到达状态、照片生命周期 |
| T032-P06 | V2、Diff、决策和回忆血缘 | NOT_RUN | 同一 Trip 的脱敏 lineage |
| T032-P07 | 375px/768px 连续链 | NOT_RUN | 每视口视频、trace 和核心截图 |
| T032-P08 | 非作者与老师签字 | NOT_RUN | `signoff.md` |

任一公网门禁未通过，最终结论只能是 `FAIL` 或 `BLOCKED`，不能用本地 PASS 抵消。

## 5. 公网执行步骤

每个视口分别创建新的 Trip，并保持该次运行的所有阶段属于同一 Trip。成员会话必须与组织者会话相互独立。

### 5.1 组织者六问与邀请

1. 从公网 `/plan` 选择三人创建，按固定顺序完成六问。
2. 六问完成前确认解析调用为 0；最终提交后每个完整 transcript 只解析一次并出现确认卡。
3. 确认组织者资料，创建成员 A、B 的两份邀请。
4. 只在对应浏览器中打开邀请，不在视频、截图、HAR、trace 或日志中暴露一次性邀请 token。
5. 验证每份邀请只绑定一个 `participantId`，A/B 不能读取或修改对方资料。
6. A/B 独立完成会话和确认；确认后原邀请不能再次使用。

### 5.2 门禁、冲突与重确认

1. 在至少一名成员未确认时调用推荐和规划入口，验证等待或 409。
2. 记录此时 Provider、推荐和 planner 调用次数均为 0。
3. 构造一名成员必去 A、另一名成员避开 A 的硬冲突。
4. 验证组织者看到 `participantId`、`ruleId`、原因和 `allowedRelaxations`，状态为 `CONFLICT_REVIEW` 且不能规划。
5. 按权限选择合法放宽项，验证创建新 revision，三人均需重新确认。
6. 三人确认当前 revision 后，验证 `READY_TO_PLAN`、`canPlan=true`、确认数 3、开放问题 0 和非空 readiness digest。

### 5.3 推荐与共享 V1

1. READY 后进入唯一推荐，验证 6-8 个候选均可追溯到服务端 FactRef 和高德/缓存来源。
2. 验证唯一方案只使用签发白名单 ID，没有重复/越界 ID；成员得分、妥协和未知事实可见。
3. 记录所选 `factSetId`、digest 和脱敏 FactRef 血缘。
4. 由组织者生成并确认 V1；成员会话尝试相同行为必须被拒绝。
5. 验证 V1 与协作态使用同一个 Trip，且快照中保留三个 canonical `participantId`。

正式公网 `POST recommendations` 编排不在本地通过声明中；若公网产品使用该接口，必须在本节另行记录实际响应与血缘后才能计入公网结果。

### 5.4 执行、到达与照片

1. 启动 CURRENT V1，执行至少一个任务。
2. 主动触发一次定位并记录成功或明确的拒绝、超时、低精度、过远结果；失败时人工确认入口和原因必须可见。
3. 为同一任务上传照片，再执行替换和删除或在另一任务保留一张照片。
4. 验证失败不阻断执行、每站和全程上限生效、照片严格绑定任务。
5. 不提交原始精确位置、真实个人照片或 EXIF；仓库证据只保留脱敏结果。

### 5.5 V2 与回忆

1. 提交一次 LATE 或 FATIGUE 并确认事件，生成 PROPOSED V2。
2. 在接受前验证 CURRENT 仍为 V1，已完成/锁定任务未改变。
3. 验证结构化 Diff 始终可读；解释不可用时仍能按确定性流程继续。
4. 由组织者执行 ACCEPT 或 REJECT，并验证唯一 CURRENT 状态；成员执行必须被拒绝。
5. 进入回忆，验证按真实事件时间稳定排序，展示完成率、计划/实际费用、版本变化、关怀结果和未删除照片。
6. 验证已删除照片不出现，替换后只显示当前照片，所有记录仍属于同一 Trip。

### 5.6 响应式与可访问性

375x812 和 768x1024 均需检查：

- `scrollWidth <= clientWidth`；
- 文本、状态、金额、时间、Diff、UUID 和控件无裁切或遮挡；
- 当前可用主操作触控区至少 44x44px；
- 等待、权限不足、Provider/模型降级和失败信息可见，不只依赖颜色；
- 键盘能按页面顺序到达主流程控件，焦点样式可见；
- `prefers-reduced-motion: reduce` 下取消非必要动画和滚动。

## 6. 结果判定

- `PASS`：所有本地门禁和公网门禁均通过，证据同一 build、同一运行内血缘连续，并完成非作者与老师签字。
- `FAIL`：功能或安全合同不满足，保留原始脱敏失败证据。
- `BLOCKED`：目标 build、Secret 配置、网络、设备权限或验收人缺失，无法执行完整步骤。
- `NOT_RUN`：尚未尝试。当前公网状态即为此值。

失败或阻断后新建新的时间戳证据目录复验，不覆盖历史记录，不跳过失败步骤继续宣称完整 PASS。

## 7. 建议本地命令

```powershell
python -m pytest -q backend/tests/test_s2_t032_multiplayer_e2e.py
python -m pytest -q backend/tests/test_s2_lin_canhan_s2_t032_traceability.py

Set-Location frontend
npm test
npm run build
npm run lint
npx playwright test e2e/s2-t032-multiplayer.spec.ts
Set-Location ..
```

实际执行时记录命令、开始/结束时间、退出码和真实通过数；本文不预填会随仓库变化的全量数字。
