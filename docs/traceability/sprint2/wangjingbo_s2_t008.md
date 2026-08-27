# S2-T008 公平唯一排序

**Owner:** 王敬博
**Traceability:** PBI-08-A / AC-08-A / S2-T008
**Dependencies:** S2-T007

## 实现

服务端枚举最多 8 个可信候选中的全部 3—4 任务组合，使用以下稳定排序键选出唯一方案：

1. 最低成员满意度降序；
2. 平均满意度降序；
3. 已知 Provider 费用升序；
4. 稳定的地点 ID 字典序。

结果只返回一个 `TrustedPlan`，其任务、成员分数、最低分、未知事实与解释均来自程序和 Provider 事实，不允许 LLM 生成费用、路线或状态。

## 代码证据

- `app/application/recommendation_service.py`：`choose_single_plan()`、`_fairness_sort_key()`。
- `backend/tests/test_s2_recommendation_boundary.py`：`80/80/80` 优先于 `95/95/50` 的回归测试。
- 提交：`17f02da fix: rank trusted plans by member fairness floor`。

## 验收状态

确定性规则和测试通过；绕路事实尚由后续真实路线核验阶段补充，不由前端或 LLM 伪造。
