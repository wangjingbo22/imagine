# S2-T009 推荐编排接口与白名单验证

## 职责边界

T009 只负责推荐编排，不重新实现依赖任务：

- T006：签发和恢复服务端 `FactRef`、事实摘要及真实 Provider 数据。
- T007：服务端计算成员满意度，执行最低分→平均分→费用→绕路→稳定 ID 的唯一裁决。
- T008：调用千问并返回未经信任的严格 JSON 候选提议。
- T009：连接以上接口、执行双重白名单/digest 校验、构建路线候选并处理降级。

T009 通过 `ProviderFactRegistryPort`、`CandidateProposalGatewayPort` 和 `RouteCandidateBuilderPort` 消费其他任务的实现。当前仓库未包含 T006/T008 的正式实现，因此应用允许在组装时注入端口，不使用 Mock 作为生产默认值。

## HTTP 接口

`POST /api/v1/trips/{tripId}/recommendations`

公开请求只包含：

```json
{
  "schemaVersion": "1.0",
  "factSetId": "server-issued-id",
  "providerFactDigest": "64位小写十六进制摘要"
}
```

客户端不能提交地点事实、路线、费用、分数、`PASS` 或 `satisfactionLoss`。请求与响应 DTO 已进入 OpenAPI；响应只包含一个 3—4 任务胜出计划、成员评分/扣分、所用白名单 ID、策略和降级原因，不返回多个方案供客户端自行裁决。

## 编排流程

1. 按 `tripId + factSetId` 从 T006 端口恢复权威事实。
2. 比较请求摘要、恢复摘要和 Trip 归属；不一致时在调用模型和路线服务前终止。
3. 只把 6—8 个只读 FactRef 视图和确认摘要传给 T008。
4. 严格解析千问 JSON；拒绝 extra、重复 ID、白名单外 ID 和响应摘要不匹配。
5. 由 Provider 路线构建端口生成真实 `CandidatePlanRequest`，再次验证 Trip、起终点、确认约束以及所有任务地点均来自白名单。
6. 确定性规划器重新计算时间、路线、费用、来源和 HARD 约束。
7. T007 公平服务执行唯一裁决；模型理由和风险措辞不参与排序。

## 确定性降级

以下情况自动切换到覆盖全部 6—8 个 FactRef 的有界稳定轮转枚举：

- `LLM_UNAVAILABLE`
- `LLM_TIMEOUT`
- `LLM_FORMAT_INVALID`
- `LLM_DIGEST_MISMATCH`
- `LLM_ALLOWLIST_VIOLATION`
- `LLM_PROPOSAL_UNUSABLE`

枚举结果仍需经过真实路线构建、HARD 校验和 T007 公平排序。若白名单中没有任何合格候选，返回 `NO_RECOMMENDATION`，不会把失败候选签发为计划。

## 交付证据

- DTO：`backend/app/services/recommendation/contracts.py`
- 编排服务：`app/application/recommendation_service.py`
- HTTP/OpenAPI：`app/api/recommendation_routes.py`
- 自动化验收：`backend/tests/test_s2_t009_recommendation_orchestration.py`

专项测试覆盖：有效千问提议、超时、响应摘要不一致、越界/重复 ID、extra/价格字段、模型措辞不影响排序、提议路线不可用、确定性复算、客户端摘要篡改、UNKNOWN 事实拦截、客户端 `satisfactionLoss` 拒绝、OpenAPI DTO 和唯一 3—4 任务输出。
