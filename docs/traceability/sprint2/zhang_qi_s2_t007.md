# S2-T007 服务端满意度与公平裁决验收说明

## 实现边界

- 负责人：张琪
- 仅实现服务端契约、规则与确定性裁决，不包含前端页面或组件。
- 输入候选必须是服务端已校验的 `CandidatePlan`，并带同一份 Provider 事实摘要。
- 候选输入契约没有 `satisfactionLoss`、模型推荐语或其他客户端评分字段；额外字段由严格契约直接拒绝。

## 评分规则

每位成员从 100 分开始。已确认的 `INTEREST` 未被候选覆盖时，服务端按以下规则扣分：

| ruleId | 扣分 | 说明 |
| --- | ---: | --- |
| `FAIR.INTEREST.UNMET` | `weight × 4` | 候选未覆盖该成员的一项兴趣 |

最终分数为 `max(0, 100 - 所有可追溯扣分)`，因此每位成员的结果始终处于 0—100 分。每笔扣分同时返回成员、偏好值、`ruleId`、分值和原因。

## HARD 排除规则

命中下列任一规则的候选不参加排序：

| ruleId | 条件 |
| --- | --- |
| `FAIR.HARD.CONSTRAINT_NOT_PASS` | 候选含未通过的 HARD 约束 |
| `FAIR.HARD.MUST_VISIT_MISSING` | 缺少成员必去地点 |
| `FAIR.HARD.AVOID_PLACE_PRESENT` | 包含成员明确避开的地点 |
| `FAIR.HARD.BUDGET_CAP_EXCEEDED` | 方案确定总费用超过任一成员预算上限 |

若所有候选均被排除，服务返回 `NO_FAIR_CANDIDATE`，不会强行推荐。

## 唯一裁决顺序

服务端只返回一个胜出方案，固定依次比较：

1. 最低成员分更高；
2. 平均分更高；
3. 费用更低（费用未知排在确定费用之后）；
4. 绕路米数更少；
5. 稳定候选 ID 字典序更小。

同一 Trip、同一 Provider 事实和同一组候选重复计算，或改变候选输入顺序，结果均保持一致。

## 代码与验收证据

- 契约：`backend/app/services/fairness/models.py`
- 裁决服务：`backend/app/services/fairness/service.py`
- 自动化验收：`backend/tests/test_s2_t007_fairness.py`
- 专项测试命令：`.venv\\Scripts\\python.exe -m pytest backend\\tests\\test_s2_t007_fairness.py -q`

专项测试覆盖最低分、平均分、费用、绕路、稳定 ID 的全部优先级；HARD 排除；0 分边界；逐项 `ruleId`；相同输入复算；倒序输入；Provider 摘要不一致；伪造 `satisfactionLoss` 和模型措辞字段被拒绝。
