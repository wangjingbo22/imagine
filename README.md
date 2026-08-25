# 2026 林大实训 12 组

| 账号 | 姓名 | 职责 |
| ---- | ---- | ---- |
| wangjingbo | 王敬博 | Scrum Master |
| fangfangxiao | 张琪 | QA |
| rasz12345 | 林粲涵 | QA |
| c_z_yy | 陈梓元 | PO |

## 张琪：PBI-02-A 城市地点、路线与可信来源

当前本地实现 FastAPI 高德 Web 服务适配及前端真实 Provider 证据面板，范围包含城市解析、地点检索、路线规划、可信来源和按城市隔离的 SQLite 缓存。页面动态展示 `cityCode`、来源时间和未知价格；Provider 未知价格不会以 0 元进入预算，计划费用会明确标为前端估算。

### 本地启动

要求 Python 3.11 或更高版本：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

在 `.env` 中填写高德开放平台申请的 Web 服务 Key：

```env
AMAP_WEB_SERVICE_KEY=你的Web服务Key
```

不要把 `.env` 或真实 Key 提交到 Git。启动服务：

```powershell
uvicorn app.main:app --reload
```

接口文档：`http://127.0.0.1:8000/docs`

### 测试

```powershell
pytest
```

测试默认使用模拟高德响应，不需要真实 Key，也不会消耗高德调用额度。

## 张琪：PBI-04-B Plan V1 确认与状态守卫

本地实现使用 SQLite 保存不可变的 Plan V1、约束快照和来源快照，并保证同一个 Trip 只有一个 `CURRENT`。未确认方案不能开始执行，前端刷新后可通过地址栏中的 `tripId` 恢复。

默认数据库：`data/plan_versions.sqlite3`。如需修改位置，在 `.env` 设置：

```env
PLAN_VERSION_DB_PATH=data/plan_versions.sqlite3
```

前端 `.env` 使用：

```env
VITE_API_BASE_URL=http://localhost:8000
VITE_USE_MOCK_API=true
VITE_USE_PLAN_VERSION_API=true
```

其中 Trip 草稿和方案生成仍可使用 Mock，Plan V1 保存、确认、执行守卫与刷新恢复使用真实本地接口。

## 张琪：PBI-05-C V1/V2 Diff 与接受拒绝

执行中的费用变化或用户反馈会登记不可变的候选 Plan V2。服务端确定性计算地点、时间、路线、费用和关怀指标的保留、删除、新增与变更，前端用中文 Diff 页面展示。

- 接受：旧 `CURRENT` 变为 `SUPERSEDED`，V2 原子切换为唯一 `CURRENT`，Trip 回到 `EXECUTING`。
- 拒绝：V2 变为 `REJECTED`，原 `CURRENT` 和执行状态保持不变。
- 同一决策可安全重试；终态后反向决策返回 `409`。
- LLM/前端不得直接写业务状态，V2 在接受前不得覆盖 V1。

## 王敬博：Sprint 1 前端、约束状态与执行闭环

- T004：AssistanceProfile 使用真实 `DRAFT / CONSTRAINT_CONFIRMED` 状态，修改回退、重复确认幂等，未确认不能登记 Plan V1。
- T015：`START / COMPLETE / SKIP / EXPENSE` 事件保存到 SQLite，绑定 task、CURRENT PlanVersion 和幂等键，刷新后可恢复。
- T020：前端展示服务端 V1/V2 Diff，并通过原子接口接受或拒绝。
- T021：基础总结由服务端事件流复算实际金额、完成/跳过任务和版本历史。
- T023：仓库提供 Docker、Nginx SPA 回退、Render HTTPS Blueprint 和 CI；公网 URL 需平台账号创建服务后补录。

详细文档：

```text
docs/superpowers/plans/2026-08-25-wang-jingbo-sprint1-completion.md
docs/testing/2026-08-25-wang-jingbo-sprint1-acceptance.md
docs/traceability/sprint1/wang_jingbo_sprint1.md
docs/reviews/2026-08-25-wang-jingbo-sprint1-review.md
```
