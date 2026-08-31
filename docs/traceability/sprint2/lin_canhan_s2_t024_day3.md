# 林粲涵 Sprint 2 Day 3：S2-T024 追溯

## 交付范围

- PBI / AC：`PBI-13-A` / `AC-13-A`
- Task / UAT / 证据：`S2-T024` / `UAT-S2-012` / `RESP-S2-001`
- 负责人：林粲涵；全员参与
- 前置依赖：`S2-T001~S2-T023`
- 需求源：`SprintBacklog模板!A28:V28`、`PBI追溯!A13:J13`、`用户功能验收清单!A15:J15`
- 验证基线：`main@90bef1439aee70a3b02675b385bba05f96a65cf6`
- 本地关闭提交：`1a7fcf7169f3e3656507be878e896bf4db1dd9fd`

T024 是验收任务，不拥有上游业务真值。它把六问、唯一推荐、执行/GPS、照片、LATE/FATIGUE V2、组织者接受或拒绝、回忆串成可重复的公网黄金路径，并在 375px 和 768px 下验证布局、触控、状态、键盘和 reduced-motion。

## 与 T032 的边界

`S2-T032 / PBI-17-A / AC-17-A / UAT-S2-E2E-001` 是新增多人完整闭环：组织者加两名成员、邀请隔离、冲突处理再进入推荐和后续旅程。它是单独任务，不计入本交付，也不能用 T024 的响应式截图宣称 T032 完成。

T024 可以消费陈梓元已经交付的 1/2/3 人兼容状态机作为依赖回归，但本轮的追溯目标始终固定为 `PBI-13-A -> AC-13-A -> S2-T024 -> UAT-S2-012 -> RESP-S2-001`。

## 模块联动

```text
S2-T001~T005 Trip/协作/执行兼容
  -> S2-T006~T010 FactRef 唯一推荐
  -> S2-T011~T016 GPS 与任务照片
  -> S2-T019~T023 LATE/FATIGUE、PROPOSED V2、Diff 与决策
  -> S2-T017~T018 MemoryTimeline/回忆
  -> S2-T024 375px/768px 与公网验收证据
```

前端只收集、展示、确认和触发用户动作；高德或缓存提供地点、路线、价格和设施事实；千问只提取和解释；冲突、排序、PASS、PlanVersion 与状态迁移继续由后端确定性模块负责。验收 helper 只能观察和断言，不能预创建成功状态或伪造 PASS。

## 已实施文件

- `frontend/playwright.config.ts`：375px、768px 项目和 video/trace 策略。
- `frontend/e2e/s2-t024-responsive.spec.ts`：两视口本地 Mock UI 串接与响应式断言；不替代公网黄金路径证据。
- `frontend/tests/s2T024ResponsiveContract.test.ts`：快速响应式和可访问性合同。
- `frontend/src/services/s2T024Acceptance.ts`：无业务写权限的验收 helper。

以上文件均已落盘并通过本地验收。单人可信桥 `app/application/collaboration_planning_bridge.py` 把 READY revision 接入 canonical Trip；新的 `backend/tests/test_s2_t024_full_golden_path.py` 在同一个真实 ASGI app 和 SQLite 文件内串起六问、READY、Provider/FactRef 推荐、V1、GPS 到达、照片替换/删除、LATE/FATIGUE、PROPOSED V2、组织者接受和 MemoryTimeline，并核对这些表始终属于同一个 `tripId`。关闭提交还把 `app/application/planning_boundary_service.py` 的 V2 恢复父版本引用从不存在的 `plan.parent_plan_id` 修正为真实字段 `plan.parent_id`，全链测试覆盖了该路径。

T023 的迟到/疲劳解析、确认事件、结构化 Diff 与组织者专用决策已在本地前端接线；公网连续浏览器证据仍待部署。T005 的 1/2/3 人 PlanVersion 共享状态机已在最新 `main` 可用，但本轮只刷新 T024 基线追溯，不把尚未执行的公网全链或 T032 扩展验收写成新闭环。

## 验收合同

- 375px 与 768px 均无横向滚动或内容遮挡。
- 主操作区域至少 44px，键盘焦点可见且顺序正确。
- 状态、权限、Provider/模型降级和失败信息可见。
- 金额、时间、Diff 和版本状态可读。
- reduced-motion 模式不执行非必要动画。
- V2 被接受前 CURRENT 不变；解释失败仍显示结构化 Diff，并能完成确定性接受或拒绝。
- 回忆只展示真实事件、费用、版本变化和未删除照片。

## 当前结论

本轮修改前基线审计为后端全量 `685 passed`、林粲涵专项 `119 passed`、前端 `52 passed`。最终收口验证为后端全量 `688 passed`、林粲涵及直接联动专项 `188 passed`、前端 `56 passed`、build/lint PASS、375px 与 768px Playwright `14 passed in 28.9s`。真实 ASGI/SQLite 测试已经覆盖单人六问 revision、READY、Provider/FactRef 唯一推荐、不可变签发地点快照、推荐顺序进入 canonical V1、执行/GPS、任务照片、LATE/FATIGUE、V2 Diff/接受和回忆；浏览器自动化仍使用明确的 Mock API，覆盖推荐确认到工作台以及执行、V2 Diff、回忆分阶段的响应式、44px、无横向滚动与 reduced-motion，不宣称真实后端连续公网全链。

公网验收仍保持 `NOT_RUN / BLOCKED`。当前公网 build 是 `32bb112a5eb7ec1e0e3d052ec060defe9f3627c1`，不是本地关闭提交 `1a7fcf7169f3e3656507be878e896bf4db1dd9fd`，且 Render 尚未配置 `BAILIAN_API_KEY`。没有目标 SHA 的公网 URL、真实高德/百炼配置证明、连续录屏和验收签字前，不得把 `RESP-S2-001` 写成公网 PASS。

仍需要：目标提交对应的前后端公网 URL；部署端确认高德和百炼秘密已配置但不暴露值；真实浏览器定位和文件/相机权限；非作者验收人与老师签字。
