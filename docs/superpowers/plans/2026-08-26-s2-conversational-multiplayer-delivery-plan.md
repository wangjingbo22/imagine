# Sprint 2：对话式多人旅行与完整执行体验实施计划

**Sprint Goal：** 以单一对话流收集行程与成员需求；每名成员通过独立邀请链接完成自己的需求确认；在真实 Provider 事实和确定性约束边界内生成唯一的多人公平推荐，并完成执行、照片、GPS、迟到/疲劳重规划、回忆和移动端验收。

**范围变更：** 原 S2 仅允许组织者在一个页面代填成员卡；本计划将“成员独立加入链接”提前纳入 S2。它取代原有的“目的地/日期/预算/兴趣/地点限制”并排表单，不新增第二套多人 Trip、计划状态机或数据库。

## 1. 必须守住的系统边界

```text
对话和百炼：提取/解释，绝不生成地点、路线、费用、满意度、PASS 或 Plan 状态
高德/缓存：签发城市、POI、路线、价格和设施事实
服务端确定性模块：校验、冲突、评分、排序、状态迁移与持久化
前端：收集输入、展示确认和事实/解释；不裁决约束或公平结果
```

- 每名成员每轮对话最多调用一次 LLM：全部预设问题答完后，才把“初始描述 + 问答记录”一次性发送给百炼。
- LLM 输出一律经过 Pydantic、日期/时间/预算校验和确认卡；无效、超时、非 JSON 或越界数据走确认/确定性回退。
- Provider 候选使用服务端签发的 `FactRef`；LLM 只可在白名单内提议地点 ID 与顺序，不能虚构事实。
- 所有参与者确认、硬冲突解除、唯一候选校验完成前，不调用 Provider 规划或签发 Plan V1。
- 邀请 token 只能读写目标 `participantId` 的草稿；随机、可撤销、可过期，不能读取或更改其他成员资料。

## 2. 目标用户流程

```text
组织者：自然语言目标 → 6 个固定补充问题 → 一次百炼提取 → 行程确认卡
  → 创建同一 Trip + 自己的成员卡 → 生成成员邀请链接

成员：打开专属链接 → 自然语言偏好 → 固定补充问题 → 一次百炼提取
  → 仅确认自己的成员卡

服务端：全部成员确认 → 硬冲突检测/放宽建议 → 冲突解决
  → Provider FactRef 候选 → LLM 白名单提议（可回退）
  → 确定性公平评分/唯一排序 → 组织者确认 Plan V1

执行：任务/GPS/照片/费用/迟到疲劳事件 → 受控 V2 → 回忆页
```

### 对话收集规则

对话框是唯一的需求输入主界面。固定问题按缺失值显示，不调用 LLM 追问：

1. 出发城市、日期、可用时间与起终点；
2. 总预算与出行人数；
3. 每人的兴趣、必去/避开地点；
4. 每人的预算上限与关怀模式；
5. 是否存在不可妥协的时间、步行、换乘或休息限制；
6. 确认摘要。

用户要纠正结果时，点击确认卡中的“更正”，回到对应对话问题；不恢复多列手工表单。

## 3. 数据与状态设计

### Trip 与协作状态

保留一个 `Trip.participants[]`，将 S1 的单人约束放宽为 1—3 人；不复制 Trip、PlanVersion、ExecutionEvent 或 SQLite 表。

```text
Trip collaborationStatus
  DRAFT_CONVERSATION
  → INVITING
  → COLLECTING_MEMBERS
  → CONFLICT_REVIEW
  → READY_TO_PLAN
  → PLANNING / PLAN_REVIEW / EXECUTING / ...（复用既有状态）

Participant confirmationStatus
  INVITED → DRAFT → CONFIRMED
  INVITED/DRAFT → REVOKED 或 EXPIRED
```

新增持久化表：

- `participant_invitations(token_hash, trip_id, participant_id, expires_at, revoked_at, accepted_at)`；只存 token hash；
- `participant_drafts(trip_id, participant_id, draft_json, status, updated_at, confirmed_at)`；
- `trip_conflicts(trip_id, conflict_id, participant_ids_json, rule_id, resolution_json, status)`；
- `media_assets(media_id, trip_id, task_id, storage_key, content_type, byte_size, status, deleted_at, created_at)`。

### 核心接口

| 接口 | 用途 |
|---|---|
| `POST /trips/conversations` | 组织者提交完整问答，解析并创建/更新协作草稿 |
| `POST /trips/{tripId}/participants/invitations` | 组织者创建或撤销成员邀请 |
| `GET/PUT /participant-invitations/{token}/conversation` | 成员读取/提交自己的问答与确认卡 |
| `POST /participant-invitations/{token}/confirm` | 原子确认一名成员 |
| `GET /trips/{tripId}/collaboration` | 组织者轮询成员确认、冲突和可规划状态 |
| `POST /trips/{tripId}/conflicts/{conflictId}/resolve` | 仅提交明确的放宽决定 |
| `POST /trips/{tripId}/recommendations/generate` | 生成唯一公平推荐 |
| `POST/GET/DELETE /trips/{tripId}/tasks/{taskId}/media` | 媒体生命周期 |

现有 `/trips/drafts/parse` 可保留给 S1 兼容入口，但 S2 页面只使用 conversation 接口。

## 4. 工作分解与实施顺序

### Phase A — 共同基础：对话和多人协作（S2-T001 ~ T006）

1. **S2-T001：多人 Schema 与迁移**
   - 放宽单人验证为 1—3 人；成员 ID 唯一；组织者 ID 必须属于 participants。
   - 新增协作/确认状态、邀请与成员草稿 DTO；1 人旧 Trip 可无损读取。
   - 产出：Schema snapshot、SQLite migration、1/2/3 人 fixture、兼容回归。

2. **S2-T002：对话壳和一次 LLM 解析**
   - 前端替换现有目的地表单为 `ConversationPanel`、问题卡和确认卡。
   - 后端拼接问答 transcript，单次调用百炼，解析后返回字段级 confirmation items。
   - 产出：90 秒录屏、单次调用测试、缺项逐问/未确认阻止测试。

3. **S2-T003：成员确认与硬冲突**
   - 实现邀请 token、独立成员页、成员级确认、协作进度。
   - 确定性检测时间、预算、必去/避开、步行、换乘、休息冲突；返回 participantId/ruleId/建议放宽项。
   - 产出：token 权限测试、冲突矩阵、短路日志和重复运行快照。

4. **S2-T004 ~ T006：复用既有计划/版本链**
   - 将确认后的 1/2/3 人 Trip 接入现有规划入口，阻止未确认/有冲突请求。
   - 不复制执行事件、PlanVersion、Diff 或表；组织者为唯一 V1/V2 决策者。
   - 产出：1/2/3 人 V1→事件→V2→接受/拒绝 E2E。

### Phase B — 公平唯一推荐（S2-T007 ~ T010）

1. **S2-T007：服务端满意度向量**
   - 仅基于已确认偏好、关怀约束和 Provider FactRef 计算 0—100 分、扣分 ruleId 与解释数据。
   - HARD 非 PASS 候选在该层之前淘汰。

2. **S2-T008：确定性唯一排序**
   - 排序键：`min(memberScores)` 降序 → 平均分降序 → 已知费用升序 → 绕路升序 → 稳定候选 ID。
   - 每次仅产生一个 3—4 任务胜者；无可行候选返回冲突/放宽建议，不伪造方案。

3. **S2-T009：Provider/LLM 混合候选**
   - 张琪服务端签发 6—8 个 FactRef；硬过滤后 LLM 仅提议白名单 ID/顺序/简短理由。
   - 越界、重复、超时、非 JSON：直接走确定性枚举，不重试修复。

4. **S2-T010：唯一推荐页**
   - 同一对话壳内展示来源、成员分数、最低分优先、照顾点、妥协、未知事实与一个确认按钮。
   - LLM 理由失败时展示结构化方案；禁止双方案、伪 PASS 或客户端改事实。

### Phase C — 执行现实证据（S2-T011 ~ T016、T019 ~ T022）

- **照片 S2-T011/T012：** 浏览器 Canvas 重编码/去 EXIF，目标 <1.5MB；上传、预览、替换、删除，`taskId` 绑定、每站 1 张/全程 8 张，失败和零照片不阻断任务。
- **GPS S2-T013 ~ T016：** 用户触发一次 `getCurrentPosition`；仅 `accuracy ≤100m && distance ≤ max(150m, 2×accuracy)` 自动判附近；其余四态人工确认；证据进入统一幂等 ExecutionEvent。
- **迟到/疲劳 S2-T019 ~ T022：** 定义事件及幂等键；确定性转换为未完成后缀的时间/步行/休息约束；生成候选 V2，锁定已完成任务，LLM 只能解释 Diff。

### Phase D — 回忆与发布（S2-T017/T018/T023/T024）

- 聚合 `MemoryTimeline`：按实际事件顺序，计算完成率、计划/实际费用、版本、关怀和未删除照片。
- 回忆页覆盖：有/无照片 × 有/无 V2；删除照片绝不出现。
- 统一对话壳在 375px/768px 无横向滚动，主按钮≥44px，支持 reduced-motion 和所有失败态。
- 公网验收串联：多人确认 → 唯一推荐 → 执行 → GPS/照片 → 迟到疲劳 → V2 决策 → 回忆。

## 5. 并行边界

| 可并行 | 必须等待 |
|---|---|
| S2-T011 照片重编码、S2-T013 GPS adapter、S2-T019 事件 Schema | S2-T001 先冻结 Trip/Participant 契约 |
| S2-T010 使用冻结推荐 fixture 开发页面 | S2-T009 的真实 FactRef 接口 |
| S2-T018 使用冻结 Timeline fixture 开发页面 | S2-T012 媒体接口与 S2-T017 聚合真实接通 |
| 移动视觉测试可随页面组件开展 | S2-T024 需等待所有主链完成 |

## 6. 分阶段验收门槛

1. **多人门槛：** 两个独立浏览器会话只能看到各自资料；全部成员确认后才可规划；任一 HARD 冲突零 Provider/规划调用。
2. **公平门槛：** 给定 A=`80/80/80` 与 B=`95/95/50`，必须选择 A；同输入重复运行结果、排序理由、哈希一致。
3. **媒体/GPS 门槛：** EXIF 大图压缩后 <1.5MB；第 9 张被拒绝；GPS 拒绝/超时/低精度不伪装为自动到达。
4. **重规划/回忆门槛：** V2 未接受前 CURRENT 不变；完成任务不改变；删除照片、零照片、无 V2 都有真实完整回忆。
5. **发布门槛：** 1/2/3 人主链通过，375px/768px 截图和 90 秒演示录屏齐全，无 P0/P1。

## 7. 首个实施切片

先完成 S2-T001 + S2-T002 的最小纵切：组织者对话问答 → 一次百炼解析 → 可编辑确认卡 → 创建 1 人/多人协作草稿。它不调用 Provider 或规划器。该切片通过后，再开放邀请链接与多人冲突检测，避免未冻结的成员状态进入公平和计划链。
