# 行知旅伴前端

行知旅伴是一个面向国内城市的预算约束与关怀出行 AI Agent。

当前目录包含项目的 React Web 前端，实现从行程输入、Agent 生成候选方案、用户反馈、旅行执行、拍摄指导、素材保存到旅行总结导出的完整演示流程。

## 1. 技术栈

- React 19
- TypeScript 6
- Vite 8
- React Router
- Lucide React
- Oxlint
- 原生 Fetch API
- 原生 IntersectionObserver 动效

## 2. 当前实现状态

### 已实现

- 白色桌面 Web 页面
- 首页与产品介绍
- 可编辑行程表单
- Agent 生成过程展示
- 候选路线、预算和关怀约束展示
- 用户反馈后重新推荐
- 行程执行状态推进
- 完成和跳过任务
- 途中持续反馈并更新后续计划
- 实际消费记录
- 地点拍照指导
- 地点视频分镜指导
- 按任务保存照片和视频
- 旅行素材预览与删除
- 旅行总结
- HTML 总结导出
- Mock API 与真实 API 切换机制
- S1-T001 Trip Schema TypeScript 契约
- Trip Schema 字段级错误解析
- 苹果官网风格的淡入、景深和滚动动效
- `prefers-reduced-motion` 无动画模式

### 仍使用 Mock 的能力

- 自然语言需求解析
- 城市和 CityContext 查询
- Agent 规划算法
- 地点和路线 Provider
- 预算与关怀约束校验
- 途中反馈后的计划更新
- 执行事件持久化
- 照片和视频对象存储
- 旅行总结后端聚合

这些接口尚未由后端登记正式 URL 和 DTO。前端目前使用 Mock 数据保证页面流程可演示。

## 3. 页面路由

| 路由 | 页面 | 说明 |
| --- | --- | --- |
| `/` | 首页 | 产品介绍、单人/多人入口及功能价值 |
| `/plan` | 行程输入 | 编辑城市、日期、时间、预算、兴趣、地点限制和关怀设置 |
| `/generating` | Agent 过程 | 展示需求理解、地点检索、路线分析、预算计算和确定性校验 |
| `/workspace` | 行程工作台 | 推荐方案、执行流程、拍摄指导、素材和旅行总结 |

未知路由会自动跳转到首页。

## 4. 核心用户流程

```text
首页
  -> 填写行程
  -> Agent 生成过程
  -> 候选推荐方案
  -> 接受推荐或提交反馈重新推荐
  -> 确认当前计划
  -> 执行任务
  -> 完成 / 跳过 / 记录消费 / 提交途中反馈
  -> 查看地点拍摄指导并保存素材
  -> 完成全部任务
  -> 旅行总结
  -> 导出 HTML
```

### 推荐阶段

候选方案在用户确认前使用：

```text
RECOMMENDATION #1
RECOMMENDATION #2
...
```

用户可以：

- 直接接受推荐
- 选择“想少走路”
- 选择“预算再低一些”
- 选择“减少换乘”
- 选择“增加文化景点”
- 选择“调整用餐安排”
- 输入最多 200 字的具体反馈

重新推荐只更新候选事实。前端必须复用 `/trips/drafts/confirm` 返回的完整 Trip，保留已确认的参与者、预算、时间窗和起终点；最后一个任务是真实返回固定终点的路线。前端把 `CandidatePlanRequest` 交给服务端 T011；只有服务端核对 T004 与权威 Trip、重编译关怀约束、重算路线/时间/预算并签发的 V1 才能确认和进入执行。未知价格、设施或来源会保留为待确认，前端不会自行填写 `PASS`。

### 执行阶段

执行阶段出现费用变化或用户反馈时，前端只提交新的 Provider 候选事实；服务端 T011 重新校验，并由 T018 结合真实执行事件选择最小扰动的不可变 Plan V2，再进入中文 V1/V2 Diff 审核页。候选方案在用户接受前不会覆盖当前 V1。刷新后只从服务端签发记录恢复原始规划事实；当前 S1 迭代最多执行一次 V2 调整。

用户可以持续反馈：

- 有点累了
- 希望提前吃饭
- 希望减少后续步行
- 实际消费发生变化
- 其他自然语言反馈

Agent 只提出尚未执行任务的候选调整，已经完成或跳过的内容保持不变。用户接受后，旧 `CURRENT` 原子变为 `SUPERSEDED`，V2 成为唯一 `CURRENT`；用户拒绝后，V2 标记为 `REJECTED`，原版本和执行状态保持不变。

### 总结阶段

只有所有任务均已完成或跳过后，旅行总结入口才可用。

总结包含：

- 完成任务数量
- 跳过任务数量
- 计划和实际消费
- Agent 调整次数
- 实际任务时间线
- 已保存照片
- 已保存视频

## 5. 可编辑字段

行程输入页支持编辑：

- 自然语言需求
- 目标城市
- 出行日期
- 开始时间
- 结束时间
- 总预算
- 兴趣标签
- 必去地点
- 希望避开的地点
- 关怀出行模式
- 单段步行上限
- 最大换乘次数
- 休息间隔

当前关怀模式：

| 值 | 页面名称 |
| --- | --- |
| `standard` | 普通出行 |
| `family` | 亲子同行 |
| `low-mobility` | 低体力 |
| `assisted` | 行动辅助 |

## 6. 地点拍摄与素材功能

每个行程任务都可以打开地点体验面板。

### Agent 拍照指导

- 环境全景
- 地点标志
- 人物三分线构图
- 光线方向
- 建筑、餐食或票据细节

### Agent 视频指导

- 3 秒地点开场
- 5 至 8 秒过程镜头
- 3 秒离场或感受镜头

### 素材限制

| 类型 | 当前前端限制 |
| --- | --- |
| 图片 | 最大 5MB |
| 视频 | 最大 30MB |

Mock 模式下使用 FileReader 将素材保存为 Data URL，仅在当前页面会话中存在。刷新页面后素材不会保留。

真实环境应接入对象存储或媒体服务。

## 7. 总结导出

总结页提供“导出旅行总结”按钮。

当前前端会生成一个 HTML 文件，包含：

- 城市
- 任务列表
- 完成/跳过状态
- 实际消费
- 已保存照片
- 已保存视频

导出逻辑位于：

```text
src/pages/WorkspacePage.tsx
```

## 8. 目录结构

```text
frontend/
├── src/
│   ├── api/
│   │   ├── API.md
│   │   ├── client.ts
│   │   ├── tripApi.ts
│   │   └── tripContract.ts
│   ├── components/
│   │   ├── AppShell.tsx
│   │   └── BrandMark.tsx
│   ├── domain/
│   │   └── trip.ts
│   ├── mocks/
│   │   └── trip.ts
│   ├── pages/
│   │   ├── AgentProcessPage.tsx
│   │   ├── HomePage.tsx
│   │   ├── PlannerPage.tsx
│   │   └── WorkspacePage.tsx
│   ├── styles/
│   │   ├── motion.css
│   │   ├── premium.css
│   │   └── white-web.css
│   ├── App.tsx
│   ├── index.css
│   └── main.tsx
├── .env.example
├── index.html
├── package.json
└── vite.config.ts
```

## 9. 分层说明

### 页面层

```text
src/pages/
```

负责：

- 页面布局
- 用户交互
- 页面状态
- Mock 演示流程

### 组件层

```text
src/components/
```

负责：

- 全局导航
- 品牌组件
- 通用页面外壳

### 领域类型

```text
src/domain/trip.ts
```

包括：

- UI 表单模型
- 正式 Trip Schema 类型
- 计划任务类型
- 执行事件类型
- 总结类型
- Schema 错误类型

### API 层

```text
src/api/
```

负责：

- 请求封装
- Mock/真实请求切换
- 统一错误处理
- Trip Schema 转换
- API 文档

### Mock 层

```text
src/mocks/
```

仅用于页面演示。不得把 Mock 数据当成后端真实响应契约。

## 10. 环境变量

复制配置：

```bash
cp .env.example .env.local
```

### Mock 模式

```env
VITE_API_BASE_URL=http://localhost:8000
VITE_USE_MOCK_API=true
```

### 真实 API 模式

```env
VITE_API_BASE_URL=http://localhost:8000
VITE_USE_MOCK_API=false
```

自然语言草稿已接入真实接口：

```text
POST /api/v1/trips/drafts/parse
POST /api/v1/trips/drafts/confirm
```

缺失或歧义字段会显示逐项确认清单；清单未解决时不能进入规划。确认成功后，服务端持久化完整 `CreateSingleDayTrip`；同一 `tripId` 的相同语义重试返回首次快照，预算、时间窗、参与者、偏好或起终点变化会以冲突拒绝。

## 11. 权威 Trip Schema

当前后端已经确认的契约是 S1-T001 `CreateSingleDayTrip` 与 S1-T003
`AssistanceProfile`。

权威来源：

```text
backend/app/schemas/trip.py
backend/schemas/trip.schema.json
backend/app/schemas/validation_error.py
docs/superpowers/specs/2026-08-24-s1-t001-trip-schema-design.md
```

前端对应文件：

```text
src/domain/trip.ts
src/api/tripContract.ts
src/api/API.md
```

### 正式 Trip 结构

```json
{
  "schemaVersion": "1.0",
  "tripId": "00000000-0000-4000-8000-000000000001",
  "mode": "SINGLE",
  "status": "DRAFT",
  "cityContext": {
    "countryCode": "CN",
    "cityCode": "110000",
    "cityName": "北京市",
    "center": {
      "longitude": 116.407387,
      "latitude": 39.904179
    },
    "providerConfig": {
      "provider": "AMAP",
      "coordinateSystem": "GCJ02"
    }
  },
  "startDate": "2026-09-05",
  "endDate": "2026-09-05",
  "currency": "CNY",
  "totalBudgetCents": 35000,
  "participants": [
    {
      "participantId": "10000000-0000-4000-8000-000000000001",
      "nickname": "单人旅客",
      "budgetCapCents": 35000,
      "preferences": [
        {
          "type": "INTEREST",
          "value": "历史",
          "weight": 4,
          "isHard": false
        }
      ],
      "assistanceProfile": {
        "type": "LOW_STAMINA",
        "childAge": null,
        "walkLimits": {
          "maxContinuousMeters": 500,
          "maxDailyMeters": null
        },
        "maxTransfers": 2,
        "restInterval": 90,
        "napWindow": null,
        "avoidStairs": false
      }
    }
  ],
  "days": [
    {
      "dayIndex": 0,
      "date": "2026-09-05",
      "dailyBudgetCents": 32000,
      "startLocationText": "北京林业大学",
      "endLocationText": "北京林业大学",
      "timeWindow": {
        "start": "09:00:00",
        "end": "20:00:00"
      }
    }
  ]
}
```

## 12. Trip Schema 规则

### 固定字段

| 字段 | 固定值 |
| --- | --- |
| `schemaVersion` | `"1.0"` |
| `mode` | `"SINGLE"` |
| `status` | `"DRAFT"` |
| `currency` | `"CNY"` |
| `countryCode` | `"CN"` |
| `provider` | `"AMAP"` |
| `coordinateSystem` | `"GCJ02"` |

### 时间

- 使用 `HH:mm:ss`
- 不接受毫秒
- 不接受时区后缀
- 结束时间必须晚于开始时间
- 当前不支持跨午夜

### 日期

```text
startDate == endDate == days[0].date
```

### 数组

- `participants` 必须且只能有一个元素
- `days` 必须且只能有一个元素
- `days[0].dayIndex` 必须为 `0`

### 金额

- 使用人民币分
- 必须为非负整数
- `dailyBudgetCents` 不得超过 `totalBudgetCents`

### 偏好

| 类型 | 是否硬约束 |
| --- | --- |
| `INTEREST` | 否 |
| `MUST_VISIT` | 是 |
| `AVOID_PLACE` | 是 |

同一地点不能同时是 `MUST_VISIT` 和 `AVOID_PLACE`。

### AssistanceProfile

S1-T003 已将四种页面模式接入正式 Trip：

| 页面模式 | 正式类型 | 行为 |
| --- | --- | --- |
| `standard` | `ORDINARY` | 不附加人群约束 |
| `family` | `PARENT_CHILD` | 预设 13:00–14:00 午休 |
| `low-mobility` | `LOW_STAMINA` | 写入页面配置的步行、换乘和休息阈值 |
| `assisted` | `MOBILITY_ASSISTANCE_BETA` | 避开已知阶梯 |

未采集的 required-nullable 字段显式写入 `null`；旧的
`assistanceProfile: null` payload 仍可通过后端验证。

## 13. UI 草稿转正式 Trip

前端页面使用 `TripDraftInput` 保存用户填写内容。

它不是后端正式请求。

转换器：

```text
src/api/tripContract.ts
```

使用示例：

```ts
const trip = buildCreateSingleDayTrip(formInput, {
  tripId,
  participantId,
  cityContext,
  nickname: '单人旅客',
  startLocationText: '北京林业大学',
  endLocationText: '北京林业大学',
})
```

转换器负责：

- `HH:mm` 转 `HH:mm:ss`
- 兴趣转 `INTEREST`
- 必去地点转 `MUST_VISIT`
- 避开地点转 `AVOID_PLACE`
- 设置偏好权重和硬约束
- 填充单人、单日和 CNY 固定字段
- 将四种关怀模式转换为完整的 S1-T003 AssistanceProfile

## 14. 错误处理

### 通用 API 响应

未来普通 REST 接口如采用统一包装：

```json
{
  "code": 200,
  "message": "success",
  "data": {}
}
```

### Trip Schema 错误

Trip Schema 使用独立错误格式：

```json
{
  "code": "TRIP_SCHEMA_INVALID",
  "schemaVersion": "1.0",
  "errors": [
    {
      "path": "days[0].timeWindow.end",
      "code": "missing",
      "message": "Field required"
    }
  ]
}
```

### 需要确认的歧义

```json
{
  "code": "TRIP_CONFIRMATION_REQUIRED",
  "schemaVersion": "1.0",
  "errors": [
    {
      "path": "days[0].date",
      "code": "ambiguous_value",
      "message": "“下周六”需确认具体日期",
      "context": {
        "referenceDate": "2026-08-24"
      },
      "candidates": ["2026-08-29", "2026-09-05"]
    }
  ]
}
```

`src/api/client.ts` 会将错误转换成 `ApiError`：

```ts
error.code
error.message
error.issues
```

## 15. 当前 API 方法

文件：

```text
src/api/tripApi.ts
```

| 方法 | 当前状态 |
| --- | --- |
| `createDraft()` | 真实解析接口 |
| `confirmDraft()` | 真实确认接口 |
| `submitNormalizedTrip()` | 后端确认 URL 后可提交正式 Trip |
| `generatePlan()` | Mock 可用，真实 URL 待确认 |
| `confirmConstraints()` | Mock 可用，真实 URL 待确认 |
| `resolveCity()` / 地点 / 地理编码 / 路线方法 | 本地真实接口已接入 |
| `confirmPlan()` | 本地真实接口已接入 |
| `getTrip()` | 本地真实接口已接入 |
| `getPlanDiff()` / `acceptPlanV2()` / `rejectPlanV2()` | 本地真实接口已接入 |
| `createExecutionEvent()` | Mock 可用，真实 URL 待确认 |
| `updatePlan()` | Mock 可用，真实 URL 待确认 |
| `getSummary()` | Mock 可用，真实 URL 待确认 |

当前 Sprint 1 已新增真实工作流接口：

```text
PUT  /api/v1/trips/{tripId}/constraints
POST /api/v1/trips/{tripId}/constraints/confirm
GET  /api/v1/trips/{tripId}/constraints
POST /api/v1/trips/{tripId}/events
GET  /api/v1/trips/{tripId}/events
GET  /api/v1/trips/{tripId}/summary
```

启用：

```env
VITE_USE_PLAN_VERSION_API=true
VITE_USE_WORKFLOW_API=true
```

执行页面的完成、跳过和消费操作会写入真实事件；刷新后从事件流恢复。

接口详细说明见：

```text
src/api/API.md
```

## 16. 接入真实后端的步骤

1. 后端负责人确定自然语言解析接口。
2. 后端负责人确定城市查询和 CityContext 返回结构。
3. 获取 `tripId`、`participantId` 和 CityContext。
4. 调用 `buildCreateSingleDayTrip()`。
5. 使用后端确认的 URL 提交正式 Trip。
6. 根据字段级 `errors[]` 将错误显示到对应表单字段。
7. 后端逐步登记计划、执行、媒体和总结接口。
8. 每完成一个正式接口，再替换对应 Mock 方法。
9. 设置：

   ```env
   VITE_USE_MOCK_API=false
   ```

10. 运行完整端到端回归。

## 17. 本地运行

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

默认地址：

```text
http://localhost:5173
```

## 18. 构建与检查

```bash
npm run build
npm run lint
```

后端 Schema 测试：

```bash
cd ..
python3 -m pytest backend/tests/test_trip_schema.py
```

当前验证结果：

- 前端 TypeScript 构建通过
- Oxlint 通过
- 26 个后端 Trip Schema 测试通过

## 19. 动效与可访问性

动效包括：

- 页面淡入
- 模糊消散
- 滚动进入
- 卡片悬浮
- 地图定位点呼吸
- Agent 状态切换

用户启用系统“减少动态效果”后：

```css
@media (prefers-reduced-motion: reduce)
```

所有主要动画会被关闭。

## 20. 已知限制

- 当前只实现单人单日页面流程
- 多人入口尚未开放
- 媒体对象存储等 Sprint 2 URL 尚未登记
- T007 编译器与正式计划/执行 HTTP 接口尚未接入前端
- 页面刷新后 Mock 执行状态会重置
- Mock 素材刷新后会丢失
- 导出为 HTML，不是 PDF
- 地图为视觉 Mock，不是真实地图 SDK
- 计划生成与计划费用仍为演示估算；城市、同城地点候选、路线证据和来源时间已接入真实 Provider

## 21. 协作要求

新增或修改接口时必须同步更新：

```text
backend/app/schemas/
backend/schemas/
frontend/src/domain/trip.ts
frontend/src/api/API.md
frontend/src/api/tripContract.ts
frontend/README.md
```

不得：

- 在页面组件中直接拼接 API URL
- 私自新增未登记字段
- 将未知价格当作 0 元
- 将未知设施标记为已通过
- 在源码中写入地图密钥或 Token
- 让 Mock 数据冒充真实后端结果
