# S2-T001 最终产品方案一致性复核报告

- 复核日期：2026-08-27（Asia/Shanghai）
- 工作树：`C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.worktrees\czy-S2-T001`
- 分支：`czy-S2-T001`
- 待复核 HEAD：`5ccbd3a70a4380d7971e433f64ab0cac0c2d3a18`
- 冻结设计：`976b261f9f154b55ddc86d17f552bd690b4dad5b`
- 业务实现：`510cad30b54fb7ce531c89b27cf597092dd21c4a`
- 独立 QA：`5ccbd3a70a4380d7971e433f64ab0cac0c2d3a18`
- 复核结论：`SPEC_PASS / READY_FOR_VERSION_MANAGER`

## 1. 最终结论

业务提交与修订冻结设计一致，没有发现需要退回代码窗口的产品方案偏差。S2-T001 已在冻结范围内交付：统一 Trip 的 1—3 人契约、旧单人窄入口、新 `CreateDayTrip`、严格且非权威的 TripUnderstanding 请求/提案、1/2/3 人 Fixture、发布 Schema/快照、GROUP 下游失败关闭和前端类型窄边界。

本复核是只读产品一致性检查。除本报告外未修改生产代码、测试、Fixture、Schema 或已有文档；未执行 merge、push 或 deploy。

## 2. 复核依据与提交链

已验证以下提交为单线祖先关系：

```text
b88aeee441f1160243acf55521d50e4e1c26d7b9  创建基线
  -> cbcbc6d181fe8c57b6171137ea66700e45eacc56  初版设计
  -> 976b261f9f154b55ddc86d17f552bd690b4dad5b  修订冻结设计
  -> c5357e7d1ef78754a5aff25a114bd67ad1eb005b  独立测试计划
  -> 510cad30b54fb7ce531c89b27cf597092dd21c4a  业务实现
  -> 5ccbd3a70a4380d7971e433f64ab0cac0c2d3a18  独立 QA 报告
```

复核材料包括修订冻结设计、独立测试计划、业务提交完整 diff、两份新发布 Schema、两份新快照、五份新 Fixture、相关生产/测试文件及独立 QA 报告。

## 3. 14 文件白名单

业务提交恰好修改或新增 14 个文件，全部在冻结设计白名单内：

```text
app/domain/trip_draft.py
backend/app/schemas/trip.py
backend/schemas/create-day-trip.schema.json
backend/schemas/trip-understanding.schema.json
backend/tests/fixtures/trip_understanding/one_participant.json
backend/tests/fixtures/trip_understanding/three_participants.json
backend/tests/fixtures/trip_understanding/two_participants.json
backend/tests/fixtures/trips/group_three_participants.json
backend/tests/fixtures/trips/group_two_participants.json
backend/tests/snapshots/create_day_trip.schema.json
backend/tests/snapshots/trip_understanding.schema.json
backend/tests/test_trip_schema.py
backend/tests/test_trip_understanding_schema.py
frontend/src/domain/trip.ts
```

未创建不可达的 `backend/app/domain/trip_draft.py`，未修改百炼运行时、Provider、TripDraft 服务/路由、Constraint、planning、PlanVersion、ExecutionEvent、Diff、workflow/store、推荐、页面或 `WorkspacePage.tsx`。

## 4. 设计条款逐项映射

| 冻结条款 | 实现证据 | 复核 |
|---|---|---|
| 单一 Trip 模型支持 1—3 人 | `TripMode` 增加 `GROUP`；`Trip.participants` 为 `1..3`；基础模型校验模式/人数不变量 | PASS |
| SINGLE 只允许 1 人 | 基础不变量与旧 `CreateSingleDayTrip` 的 literal/exact-one 双重限制 | PASS |
| GROUP 只允许 2—3 人 | `GROUP+2/3` Fixture 正向；`GROUP+0/1/4` 由长度和模式校验拒绝 | PASS |
| 新统一入口 | `CreateDayTrip` 固定 DRAFT、一天、1—3 人；`validate_create_day_trip_json()` 执行 strict 解析和原有单日策略 | PASS |
| 旧单人兼容 | `validate_trip_json()` 仍返回 `CreateSingleDayTrip` 并拒绝 GROUP；旧发布 Schema、旧快照、北京/上海/成都 Fixture 相对冻结设计无 diff | PASS |
| 不复制多人业务模型 | GROUP 继续使用既有 `Trip`、`Participant`、Preference 和 AssistanceProfile | PASS |
| 理解提案不是权威 Trip | DTO 不含 mode、tripId、participantId、状态、Constraint、Provider、计划、评分或版本字段；各层 extra-forbid | PASS |
| 严格 JSON 契约 | 新 `UnderstandingContractModel` 独立启用 strict/camelCase/extra-forbid；旧 `DraftContractModel` 未被全局收紧 | PASS |
| 成员与关怀草稿 | 1/2/3 人连续 memberKey、独立预算/偏好/关怀；空壳 careDraft、边界数值和非法枚举被拒绝 | PASS |
| 字段证据与请求上下文 | proposal 语义验证覆盖路径、索引、成员归属和非空值证据；`validate_trip_understanding*` 绑定 USER_TEXT/EXPLICIT_FIELD 来源上下文 | PASS |
| missing/ambiguity/question 闭环 | 重复、交叉、缺失问题、孤儿问题和候选/选项不一致均由确定性验证器拒绝 | PASS |
| 发布物与快照 | 两对新 Schema/快照分别逐字节一致；所有 object schema 均为 `additionalProperties=false` | PASS |
| GROUP 下游失败关闭 | CandidatePlanRequest 在读取首成员前拒绝非 SINGLE；PlanReview/旧创建/公开确认路径保持单人窄边界，不产生 CandidatePlan、PlanVersion 或事件 | PASS |
| 前端纯 DTO 窄边界 | `TripMode='SINGLE'|'GROUP'`；`CreateDayTrip` 为 1/2/3 tuple union；旧创建和 CandidatePlanningTrip 均保持 literal `SINGLE` | PASS |

## 5. Schema、快照与 Fixture 复核

### 5.1 发布物

- `backend/schemas/create-day-trip.schema.json` 与 `backend/tests/snapshots/create_day_trip.schema.json` 逐字节一致；
- `backend/schemas/trip-understanding.schema.json` 与 `backend/tests/snapshots/trip_understanding.schema.json` 逐字节一致；
- CreateDayTrip Schema 固定 `status=DRAFT`、participants `1..3`、days `1..1`，TripMode 枚举为 SINGLE/GROUP；
- TripUnderstanding Schema 的 10 个 object schema 全部 `additionalProperties=false`，可空提案字段仍是 required；
- 请求上下文、memberKey 连续性、路径索引、证据闭环等跨对象语义由 Pydantic 验证器承担，不虚称 JSON Schema 能独立完成。

### 5.2 Fixture

- GROUP 两人和三人 Fixture 均使用不同 UUID、昵称、预算、偏好与关怀资料；
- TripUnderstanding 的一人、两人、三人 Fixture 均提供完整字段证据；
- 两人 Fixture 含成员级关怀缺失问题；三人 Fixture 分别表达低体力和亲子关怀并保持 memberKey/path 归属；
- 五个旧单人资产相对修订设计提交逐字节未变。

## 6. 独立 QA 与基线事实

独立 QA 结论为 `QA_PASS`，证据统计为：

- 后端定向契约与所有可运行相关旧链：`184 passed`；
- 前端：`31 passed`，build exit 0；
- 独立契约 UAT：`7/7 passed`；
- S2-T001 新增缺陷：0。

上述 `184 passed` 不是后端全量通过数。后端全量在收集阶段被四个既有 `ModuleNotFoundError` 中止，仓库根和 `backend/` cwd 均 exit 2。静态差分确认：

- `b88aeee` 和业务提交都没有根级 `tests/` 文件；
- `pyproject.toml` 及四个出错测试在基线与业务提交之间无差异；
- 缺失模块均为既有的 `tests.test_plan_versions` / `tests.test_plan_v2_diff` 依赖；
- 没有证据把四个 collection errors 归因于 S2-T001，也不能宣称后端全量绿色。

## 7. 工作树与 SQLite

复核开始时仅有两份未跟踪测试产物：

| 文件 | 大小 | SHA-256 |
|---|---:|---|
| `backend/data/amap_cache.sqlite3` | 16384 bytes | `84E262DC234FC544BF1A10DDBCFAA68FAA870616EA8D23509ABE3BE8AEB3FAE5` |
| `backend/data/plan_versions.sqlite3` | 102400 bytes | `029A2BA0CF019C675B60DD62C6EA7FF4C0CA91A6FADC9C0BB36E342753D8F5A4` |

它们与独立 QA 报告记录一致，不在业务提交或 QA 报告提交中。本复核未修改、删除或暂存它们；最终报告提交也不得包含它们。

## 8. 已知限制

1. 后端全量不是绿色；四个既有 collection errors 仍需由其所属任务修复。
2. T001 只交付契约和 DTO，不包含多人 UI、真实 LLM 多人调用编排、草稿版本/确认状态机、邀请协作或成员独立确认。
3. 当前 planner、PlanVersion 和执行链仍只支持单人；GROUP 会失败关闭，扩展归 T003/T005 及后续任务。
4. TripUnderstanding 的证据来源上下文必须通过 `validate_trip_understanding()` 或 `validate_trip_understanding_json()` 校验，不能只运行孤立的发布 JSON Schema。
5. 两份 SQLite 是未跟踪既有测试产物；版本管理器接收提交链时必须继续排除。

## 9. 版本管理器接收范围

版本管理器应接收以下完整提交链，连同本最终复核报告提交：

```text
cbcbc6d181fe8c57b6171137ea66700e45eacc56  初版设计
976b261f9f154b55ddc86d17f552bd690b4dad5b  修订冻结设计
c5357e7d1ef78754a5aff25a114bd67ad1eb005b  独立测试计划
510cad30b54fb7ce531c89b27cf597092dd21c4a  业务实现
5ccbd3a70a4380d7971e433f64ab0cac0c2d3a18  独立 QA 报告
```

接收时应确认最终新增提交只包含 `docs/reviews/2026-08-26-s2-t001-final-conformance-review.md`，并继续排除 `backend/data/*.sqlite3`。本分支已达到 `READY_FOR_VERSION_MANAGER`，但本报告不授权自动 merge、push 或 deploy。
