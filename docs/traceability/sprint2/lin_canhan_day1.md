# 林粲涵 Sprint 2 Day 1 代码追溯

本交付只实现 `S2-T008 / PBI-08-A / AC-08-A` 的候选地点提议 Gateway，基于已核验的远端 `origin/main@3e60435fcfde0705149dbc5f340d60e1aa63103c`。机器可读追溯见 `lin_canhan_day1.json`。

## PBI → AC → Task → 模块 → 验收证据

| PBI / AC | Task | 生产模块 | 验收证据 | 联动 |
|---|---|---|---|---|
| PBI-08-A / AC-08-A | S2-T008 | `schemas/llm.py`、`llm_gateway.py`、`openai_compatible_llm.py` | 固定 JSON Schema、6–8 个唯一 FactRef、2–3 个白名单地点、10 秒超时、最多 2 次传输调用、格式/Schema/越权输出不发修复调用、失败转确定性枚举 | S2-T006 → S2-T008 → S2-T009 →（间接）S2-T010 |

## 真实模块联动

- `S2-T006 → S2-T008`：输入契约只接受 `placeFactId`、`sha256:<64 lowercase hex>` 摘要及安全属性。T008 不生成 FactRef，也不接触坐标、Provider 原文、价格或路线。最新版 main 还没有 T006 的正式 registry/fixture，因此追溯明确标为 `UPSTREAM_FIXTURE_CONTRACT_PENDING`。
- `S2-T008 → S2-T009`：运行时暴露可注入的 `CandidateSelectionGateway`。成功只返回有序、唯一且属于请求白名单的地点 Fact ID；超时、鉴权、网络、非 JSON、Schema 错误或越权 ID 都返回 `DETERMINISTIC_ENUMERATION`，由 T009 继续确定性枚举，不进行第三次“修复”模型调用。
- `S2-T007 → S2-T009`：公平性与确定性平局裁决是 T009 的另一条独立输入。T008 不计算分数，也不覆盖 T007 的裁决证据。
- `S2-T009 → S2-T010`：属于间接下游。T009 必须恢复 T006 权威事实、执行公平性/路线/硬约束校验后才能交给 UI；本交付不虚报 T009 或 T010 已完成。

## 安全与职责边界

- 发给模型的 payload 不含 `factDigest`、坐标、Provider 原始响应、价格、路线、评分、约束或计划状态。
- 所有模型可见自由文本先经过敏感词与 Prompt Injection 守卫；输出理由必须为每个入选地点命中至少一项输入标签/属性，风险提示必须能追溯到入选地点已有的 `riskFlags`。这些文本仍是非权威解释，程序不能据此改变 Provider 事实。
- 模型输出使用 `extra=forbid`；禁止价格、路线、分数、`PASS`、`planId`、版本状态及“保证/确保可达”等断言。
- 风险提示只能表达未知、未确认、待核实或缺失事实。
- HTTP 错误与 Provider 响应会转换成稳定错误码，不把 Key、原始错误体或模型内部内容带到业务层。
- 无 Key 时记录 `0` 次调用并直接进入确定性枚举；真实 Key 只应由本地或部署环境配置，不能提交到仓库。

## 仍需团队提供

1. S2-T006 最终 FactRef Fixture、摘要生成规则或实现提交。
2. S2-T009 消费接口确认，以及“模型失败后由 T009 枚举”的联调入口。
3. 6–8 个同城、已脱敏、由服务端签发的真实候选事实。
4. 仅用于现场验收的新百炼 Key（环境变量配置，不发聊天、不入 Git）。
5. 非作者 Review、CI、QA 与 PO 验收记录。

## 本地验收结果

- S2-T008 与既有百炼解析聚焦回归：`64 passed`。
- 后端全量：`228 passed`。
- 前端兼容回归：`31 passed`，build 与 lint 均通过。

精确命令与耗时以 JSON 中 `localVerification` 为准；PR、CI、QA、PO 与真实模型调用未发生时保持为空，不用本地 Mock 结果冒充外部证据。
