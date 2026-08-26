# 行知旅伴前端

行知旅伴前端是基于 React 19、TypeScript 6 和 Vite 8 的响应式 Web 工作台，覆盖单人单日旅行的需求确认、确定性规划、真实地图、执行记录、Plan V2 决策与旅行总结。

> 当前阶段：Sprint 1 Beta。核心业务默认连接本地 FastAPI；Mock 开关仅用于前端独立开发，不代表线上能力。

## 技术栈

- React 19、React Router
- TypeScript 6、Vite 8
- Lucide React、原生 Fetch API
- 高德 Web 端 JS API 2.0
- Oxlint、Node test
- `prefers-reduced-motion` 动效降级

## 页面路由

| 路由 | 页面 | 作用 |
| --- | --- | --- |
| `/` | 首页 | 项目介绍与规划入口 |
| `/plan` | 行程输入 | 编辑城市、日期、预算、兴趣、起终点和关怀设置 |
| `/generating` | Agent 过程 | 展示地点、路线、预算与约束校验过程 |
| `/workspace` | 行程工作台 | 计划确认、真实地图、执行事件、Plan V2 与总结 |

未知路由会跳转到首页。

## 当前接入范围

已经接入真实后端或 Provider 的能力：

- 自然语言草稿解析、歧义确认、显式起终点和有限表达提取
- 高德城市、POI、地理编码、路线距离、时长与来源事实
- 高德道路底图、地点标记和真实路线 Polyline
- 四类关怀画像及步行、换乘、休息、预算约束
- 服务端校验、签发并确认 Plan V1
- `START / COMPLETE / SKIP / EXPENSE` 执行事件和刷新恢复
- 费用变化触发的服务端重规划评估，以及可行时生成的单候选 Plan V2
- V1/V2 Diff、接受、拒绝与基础旅行总结

Sprint 1 的重规划边界：

- 只接受 `EXPENSE_CHANGE` 事件触发。
- 服务端从 CURRENT V1、可信规划事实和执行事件推导冻结前缀与未完成后缀。
- 浏览器不构造或直接登记 Plan V2，也不提交候选任务、锁定 ID 或自由文本反馈。
- 未完成后缀仍可行时，服务端只生成一个确定性候选；无可行方案时保留 CURRENT V1，且不留下 V2。
- Sprint 1 最多发起一次重规划并完成一次 V2 决策。
- 自主多候选、疲劳/迟到和自由文本重排尚未实现。

## 用户流程

```text
填写自然语言需求与结构化字段
  → 逐项解决歧义并确认关怀画像
  → 获取高德地点与路线事实
  → 服务端确定性校验并签发 Plan V1
  → 用户确认后开始执行
  → 完成 / 跳过 / 记录实际消费
  → 费用变化发起单次重规划评估
  → 可行时查看 Plan V2 Diff 并接受或拒绝
  → 完成全部任务后查看旅行总结
```

## 前端架构

```text
pages/ 页面与交互
   │
   ├─ api/tripApi.ts ─────── FastAPI 业务接口
   ├─ services/ ──────────── 候选请求、风险与时钟等纯前端适配
   ├─ components/RouteOverview.tsx
   │       └─────────────── 高德 Web 端 JS API
   └─ domain/trip.ts ─────── TypeScript 领域契约
```

关键文件：

| 文件 | 职责 |
| --- | --- |
| `src/api/API.md` | 当前 HTTP 接口与 DTO 权威说明 |
| `src/api/client.ts` | API 地址、请求与错误解析 |
| `src/api/tripApi.ts` | Trip、Provider、PlanVersion、事件与总结调用 |
| `src/api/tripContract.ts` | UI 草稿到正式 Trip Schema 的转换 |
| `src/domain/trip.ts` | 前端领域类型 |
| `src/lib/amapJsApi.ts` | 高德 JS API 配置和按需加载 |
| `src/pages/PlannerPage.tsx` | 需求、起终点与规划输入 |
| `src/pages/WorkspacePage.tsx` | Plan V1/V2、执行事件与总结工作台 |

## 环境配置

从 `frontend` 目录复制示例配置：

```powershell
Copy-Item .env.example .env
```

本地真实 API 模式：

```env
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_AMAP_JS_API_KEY=你的Web端（JS API）Key
VITE_AMAP_SECURITY_JS_CODE=你的安全密钥
VITE_USE_MOCK_API=false
VITE_USE_PLAN_VERSION_API=true
VITE_USE_WORKFLOW_API=true
```

- `VITE_AMAP_JS_API_KEY` 必须使用高德控制台的“Web 端（JS API）”Key，不能复用后端 Web Service Key。
- 本地 Vite 从 `.env` 读取地图配置；容器部署可通过 `runtime-config.js.template` 和 `40-runtime-config.sh` 在启动时注入。
- `.env`、真实 Key 和安全密钥不得提交到 Git，也不得出现在截图中。

如需独立调试纯前端页面，可临时设置 `VITE_USE_MOCK_API=true`；评审真实业务闭环时应保持 `false`。

## 本地运行

先按根目录 [README](../README.md#快速开始) 启动 FastAPI，然后在 `frontend` 目录执行：

```powershell
npm ci
npm run dev
```

默认地址：<http://localhost:5173>

## 接口状态

前端已使用的主要真实方法：

| 方法 | 能力 |
| --- | --- |
| `createDraft()` / `confirmDraft()` | 自然语言草稿、歧义确认和权威 Trip |
| 城市、地点、地理编码与路线方法 | 高德 Provider 事实 |
| `generatePlanVersion()` | 服务端校验并签发 Plan V1 |
| `getTrip()` / 规划事实与审核方法 | 状态和可信事实恢复 |
| `createExecutionEvent()` | 开始、完成、跳过和消费事件 |
| `replanFromEvents()` | `EXPENSE_CHANGE` 事件驱动重规划 |
| `getPlanDiff()` / `acceptPlanV2()` / `rejectPlanV2()` | Plan V2 决策 |
| `getSummary()` | 服务端旅行总结 |

完整 URL、请求 DTO、响应 DTO 和错误码见 [前端 API 契约](src/api/API.md)。

## 测试与构建

```powershell
npm test
npm run lint
npm run build
```

测试脚本覆盖关怀约束、休息时钟、路线风险、候选请求、规划事实恢复、重规划策略和 S1-T017 事件驱动契约。构建产物位于 `dist/`。

## 安全与数据边界

- 高德 Web Service Key 只属于后端，前端只使用 Web 端 JS API Key 和安全密钥。
- 未知价格不会按 0 元计入预算，未知设施和来源不会自动标记为 `PASS`。
- PlanVersion、约束结论、执行事件和 Plan V2 决策均以服务端状态为准。
- 照片和视频目前只保存在浏览器本地，不宣称已经上传到对象存储。
- Mock 数据不得作为真实接口证据或回退数据混入正式流程。

## 已知限制

- 当前只支持单人单日流程；2—3 人公平推荐属于 Sprint 2。
- 起终点支持显式输入和有限自然语言模板，复杂自由表达仍需确认。
- Sprint 1 仅支持费用变化发起一次重规划评估，不支持自主多候选和连续重规划。
- 疲劳、迟到、偏好调整等自由文本事件尚未进入真实重规划契约。
- 照片/视频对象存储、跨设备素材恢复和完整旅行回忆页尚未实现。
- 当前没有已验证的公网 HTTPS 演示地址。

## 相关文档

- [项目首页](../README.md)
- [前端 API 契约](src/api/API.md)
- [部署说明](../deploy/README.md)
- [S1-T017 事件驱动重规划验收](../docs/testing/evidence/s1_t017/clean-slice-acceptance.md)
- [Sprint 1 验收记录](../docs/testing/2026-08-25-wang-jingbo-sprint1-acceptance.md)
