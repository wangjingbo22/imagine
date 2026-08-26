# S2-T007 成员满意度向量与扣分追溯

**Owner:** 王敬博
**Traceability:** PBI-08-A / AC-08-A / S2-T007
**Dependencies:** S2-T001

## 实现

`TrustedRecommendationService` 对每个已确认成员、每个 3—4 任务候选组合计算 0—100 的确定性分数。分数仅使用成员已确认的兴趣、必去地点和高德 `FactRef` 地点事实；前端和 LLM 均不能提交或改写分数。

`MemberScore` 返回 `participantId`、`score`、`penaltyRuleIds` 与原因。必去地点未进入候选组合时记录 `MUST_VISIT_NOT_SELECTED` 并扣分；硬冲突在推荐前的协作门禁中已被阻断。

## 代码证据

- `app/domain/recommendation.py`：`MemberScore`、`TrustedPlan` DTO。
- `app/application/recommendation_service.py`：`_score_members()`。
- `backend/tests/test_s2_recommendation_boundary.py`：成员分数、未知事实和确定性边界测试。

## 验收状态

实现与定向测试完成；真实 2/3 人页面截图、录屏属于最终人工验收证据，尚待采集。
