# 林粲涵 Sprint 2 Day 1 代码追溯

本交付对应 `S2-T008 / PBI-08-A / AC-08-A`（Must；修订表当前剩余工时为 0h）。需求口径来自 `doc/行知旅伴_V2.3_Sprint2待办列表_含负责人_新增需求修订版.xlsx` 的 `SprintBacklog模板!A12:V12`、`LLM接入设计!A6:K6` 与 `LLM JSON契约!A5:K5`。

实现提交仍为 `f376574a5c8c5c577d6ed43efd200293023b3b32`，本次兼容性核对基线更新为 `origin/main@90bef1439aee70a3b02675b385bba05f96a65cf6`，统一收口提交为 `1a7fcf7169f3e3656507be878e896bf4db1dd9fd`。机器可读追溯见 `lin_canhan_s2_t008_day1.json`；同一负责人的 S2-T019/T020 追溯见 `lin_canhan_day1.json`。

## PBI → AC → Task → 模块 → 验收证据

| PBI / AC | Task | 生产模块 | 验收证据 | 联动 |
|---|---|---|---|---|
| PBI-08-A / AC-08-A | S2-T008 | `schemas/llm.py`、`llm_gateway.py`、`openai_compatible_llm.py`、`recommendation_service.py` | 6–8 个唯一 FactRef、严格白名单 ID/顺序/理由与 riskNotes、额外字段/非 JSON/越界/重复/超时直接回退、模型最多调用 1 次且无修复重试 | S2-T006 → S2-T008 → S2-T009 →（间接）S2-T010 |

## 真实模块联动

- `S2-T006 → S2-T008`：T006 的 SQLite FactRef registry 已经存在并可恢复签发事实及每个 FactRef 的摘要。T008 的适配器只投影不透明 ID、摘要、展示/分类标签、来源类别和过期风险；价格、路线、评分、`PASS`、坐标及 Provider 原始载荷不进入模型。FactRef 签发与权威恢复仍属于 T006，而不是 T008。
- `S2-T008 → S2-T009`：v2 推荐路由已复用同一个 `RecommendationOrchestrationService` 和注入的 `StrictCandidateSelectionGateway`。有效输出只能包含有序、唯一、属于输入白名单的地点 ID、简短理由与受约束的 riskNotes；非 JSON、Schema 错误、额外字段、重复/越界 ID、超时或服务错误都在首次调用后转 `DETERMINISTIC_ENUMERATION`，不发起修复或传输重试。
- `S2-T009` 外部缺口：正式的 route-backed T009 接口仍需要团队提供生产级 `RouteCandidateBuilderPort` 并完成运行时注入。当前 v2 严格网关已经接通，但不能把这一点写成真实路线构建已经完成。
- `S2-T007 → S2-T009`：main 已提供公平性与确定性平局裁决。T008 不计算分数，也不覆盖 T007 的裁决；T009 必须从恢复后的权威事实集合生成聚合 `providerFactDigest`。
- `S2-T009 → S2-T010`：属于间接下游。只有 T009 完成事实恢复、公平性、真实路线与 HARD 约束校验后，结果才可交给 UI；T008 不直接输出 UI 状态。

## 安全与职责边界

- 发给模型的 payload 不含 `factDigest`、坐标、Provider 原始响应、价格、路线、评分、约束或计划状态。
- 所有模型可见自由文本先经过敏感词与 Prompt Injection 守卫；理由和 riskNotes 必须能在安全投影中找到依据，且仅作为非权威解释。
- 模型输出使用 `extra=forbid`；禁止价格、路线、分数、`PASS`、`planId`、版本状态以及保证性结论。
- 模型最多调用一次。无 Key、超时、鉴权/网络错误、非 JSON、重复或白名单越界均立即使用确定性回退。
- HTTP 与 Provider 错误只映射为稳定错误码，不向业务层泄露 Key、原始错误体或模型内部内容。
- T008 不负责 T006 的签发与恢复、不负责 T007 公平评分，也不负责 T009 的生产 route builder、HARD 校验或 PlanVersion 状态迁移。

## 仍需团队提供

1. T009 生产级 `RouteCandidateBuilderPort` 的实现及正式 route-backed 接口注入。
2. 公网全链证据：T006 签发事实 → T008 单次选择/回退 → T009 真实路线与硬约束校验。
3. 仅用于现场验收的新百炼 Key（环境变量配置，不发聊天、不入 Git）。
4. 非作者 Review、CI、QA 与 PO 验收记录。

## 本地验收结果

- 最新基线 `main@90bef14` 的 T008 追溯专项：`6 passed`。
- T006/T008/T009 与推荐就绪守卫聚焦回归 `87 passed`、后端全量 `528 passed`、前端 `32 passed` 以及 build/lint 结果，均是原实现交付时基于 `a43ad37` 的历史记录，本次追溯刷新没有把它们冒充为最新 main 的重跑结果。
- 本轮修改前基线审计为后端全量 `685 passed`、林粲涵专项 `119 passed`、前端 `52 passed`；完成 T030→T008→签发快照→V1 顺序谱系收口后，最终验证为后端全量 `688 passed`、林粲涵及直接联动专项 `188 passed`、前端 `56 passed`、build/lint PASS、T024 Playwright `14 passed`。
- 公网真实 FactRef、RouteBuilder 和百炼调用仍待外部验收。

精确命令以 JSON 中 `localVerification` 为准；PR、CI、QA、PO、真实模型调用、生产 `RouteCandidateBuilderPort` 和公网 Provider 路线验证未发生时保持为空，不用追溯测试或本地 Mock 结果冒充外部证据。真实百炼验收还需要只配置在部署 Secret 中的已轮换 `BAILIAN_API_KEY`。
