# 林粲涵 Sprint 2 Day 3：S2-T032 追溯

## 交付范围

- PBI / AC：`PBI-17-A` / `AC-17-A`
- Task / 计划 UAT：`S2-T032` / `UAT-S2-E2E-001`
- 场景名：`E2E-S2-新增需求-多人六问到回忆闭环`
- 负责人：林粲涵；全员配合
- 依赖：`S2-T025~T031,T012,T023`
- 验证基线：`main@e248e9ad88db9b4f40b2ed087844df7fcdeae10b`
- 当前结论：`LOCAL_AUTOMATION_PASS / PUBLIC_UAT_NOT_RUN`

需求源为 `SprintBacklog模板!A36:V36` 和 `PBI追溯!A17:J17`。源表仍把 T032 标记为“未开始”、剩余 3 小时；本地实现和自动化不会擅自改写这份计划状态。

`UAT-S2-E2E-001` 只出现在 `SprintBacklog模板!O36` 的“待 UAT 编号”中，`用户功能验收清单`没有该编号的独立行。`UAT-S2-001~012` 是本任务使用的分段验收依据，不得伪造成 `UAT-S2-E2E-001` 已登记或已签字。

## 联动范围

```text
T025~T027 六问、两份邀请、两名成员独立会话
  -> T028~T029 未确认/冲突零调用门禁、放宽、新 revision、三人重确认
  -> T030~T031 FactRef 与白名单推荐边界
  -> GROUP canonical Trip / V1
  -> T012~T018 执行、到达、任务照片、MemoryTimeline
  -> T019~T023 LATE/FATIGUE、PROPOSED V2、Diff、组织者决策
  -> T032 公网三会话与 375px/768px 证据包
```

待办表没有在依赖列显式列出 `T013~T018`，但验收条件写了“执行”和“回忆”，因此追溯 JSON 将 GPS/执行与 MemoryTimeline 记录为需求隐含依赖，避免闭环证据断链。

本地三人测试通过真实 ASGI app、单一 SQLite 文件和确定性 Provider/LLM stub 串接业务状态，检查组织者加两名成员、独立 token、冲突前零下游调用、放宽后全员重确认、GROUP Trip、FactRef 到 V1、GPS/照片、LATE/FATIGUE、V2 与 Timeline。它证明本地确定性集成合同，不证明公网网络、真实高德或百炼。

前端新增 MemoryTimeline 展示合同，验证真实事件顺序、版本变化、费用、逐成员关怀结果以及未删除照片的展示边界。多人 DTO 保留每名成员各自的 AssistanceProfile，不把不同长期档案伪造成一个合并档案。Vitest 覆盖源码/UI 合同；`frontend/e2e/s2-t032-multiplayer.spec.ts` 另以明确的 Mock API 在 375px/768px 检查成员字段权限、无横向滚动、44px 操作区、reduced-motion 和邀请过期提示。它不是三个公网浏览器连接真实后端的连续 E2E，不能代替 T032 公网多人验收。

## 权限与真值边界

- 前端只收集、展示、确认和触发操作，不改写事实、金额、评分或状态。
- 每个完整六问 transcript 最多触发一次解析；更正后才针对新 transcript 重解析。模型只提取和解释。
- 高德或缓存拥有地点、路线、价格和设施事实。
- 后端确定性模块拥有冲突、评分、排序、PASS、PlanVersion 和状态迁移。
- 两名成员会话分别只能读取和修改绑定的 `participantId`；组织者才可确认或拒绝 V1/V2。
- 验收代码只能观察和断言，不得预创建成功状态或伪造公网 PASS。

## 本地自动化结论

`LOCAL_AUTOMATION_PASS` 仅覆盖：

1. `backend/tests/test_s2_t032_multiplayer_e2e.py` 的本地 ASGI、SQLite 与 stub 连续链；
2. `backend/tests/test_s2_lin_canhan_s2_t032_traceability.py` 的来源、边界和证据状态合同；
3. `frontend/tests/s2T032MemoryTimeline.test.ts` 的本地 Vitest 组件合同；
4. `frontend/e2e/s2-t032-multiplayer.spec.ts` 在 375px/768px 的 4 项本地 Mock UI 合同；
5. T024、T029、T030 等既有依赖测试提供的分段回归。

不声称正式 `POST recommendations` 编排已通过，不声称真实高德、百炼、GPS、相机、文件权限、三浏览器或 375px/768px 公网连续链已执行。专项和全量命令的实际通过数应由本轮根级验证记录，追溯文件不预填会随代码变化的总数。

## 公网验收状态

`PUBLIC_UAT_NOT_RUN`。正式 PASS 必须在包含本次实现的同一公网 build 上，每个验收运行使用一个新的 Trip 和三个独立浏览器会话，从组织者六问开始连续完成两份邀请、成员独立确认、冲突处理、唯一推荐、执行/到达、任务照片、V2 决策和回忆。

375px 与 768px 均需验证无横向滚动、无文字/控件遮挡、主按钮不小于 44px、状态/权限/失败可见、关键数字和 Diff 可读、键盘焦点可见以及 reduced-motion。任何 Mock、源码截图、预创建 Trip 或分阶段 Fixture 都不能替代这条公网链。

## 仍需输入

- 含本次实现且可核验 40 位 build SHA 的公网前后端 URL；
- 部署端确认高德和百炼 Secret 已配置，只确认状态，不提供值；
- 组织者与两名成员的三个独立浏览器会话；
- 可使用定位及相机或文件上传权限的真实设备或受控浏览器；
- 非作者验收人、老师验收时间和签字。

公网证据规范见 `docs/testing/s2_t032_multiplayer_public_acceptance.md` 和 `docs/testing/evidence/s2_t032/README.md`。一次性邀请 token、组织者凭证、成员 session、API Key、精确位置和照片 EXIF 不得进入仓库证据。
