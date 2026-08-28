# S2-T031 白名单 LLM 排序 JSON 边界

**Owner:** 张琪
**Traceability:** PBI-16-A / AC-16-B / S2-T031

## 交付边界

- 模型输入只包含服务端签发的 6--8 个 FactRef 投影；模型输出仅能选择其中的地点 ID 并提供短理由。
- `extra="forbid"` 拒绝任何额外 JSON 字段；重复或白名单外 ID 不会被修正，而是进入确定性回退。
- 价格、费用、路线、满意度、`PASS`、计划状态、`PlanVersion` 及其同义表述不得出现在模型理由中；路线、评分和状态均由服务端事实、规划和公平裁决模块决定。
- 非 JSON、Schema 错误、超时和模型错误均在一次调用后回退到确定性枚举，不会发起修复重试。

## 证据

- `backend/tests/test_s2_recommendation_boundary.py` 覆盖旧 JSON 兼容入口的额外字段、非 JSON、六类禁止主张、重复 ID 和白名单外 ID 回退。
- `backend/tests/test_s2_t008_candidate_selection_gateway.py` 覆盖严格网关的单次传输、超时、格式错误及白名单外 ID 的零修复重试。
- `backend/tests/test_s2_t009_recommendation_orchestration.py` 覆盖推荐编排对禁止模型主张的确定性回退。
