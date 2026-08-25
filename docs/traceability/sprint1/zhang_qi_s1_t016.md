# 张琪 S1-T016 实际消费与预算复算追溯

实际消费以 `EXPENSE` ExecutionEvent 写入 SQLite，金额只接受整数分。每条事件
绑定 `eventId`、`taskId`、当前 `planVersionId`、`idempotencyKey` 和带时区的
`occurredAt`。同一幂等键和相同负载返回原事件，不重复扣减；同键不同负载
返回 `EVENT_IDEMPOTENCY_CONFLICT`。

剩余预算不依赖 React 内存，而是每次从 Trip 的全部 `EXPENSE` 事件重新求和：
`remainingBudgetCents = plannedBudgetCents - actualSpentCents`。刷新恢复接口同时
返回事件流和复算结果。

自动化证据为 `tests/test_execution_expenses.py`，固定预算复算和幂等日志位于
`docs/testing/evidence/s1_t016_expense_event_stream.json`，刷新恢复页面截图为
`docs/testing/evidence/s1_t016_expense_refresh_desktop.png`。为兼容前置 T015，事件
模型同时允许 `START/COMPLETE/SKIP`，但本任务不修改王敬博的页面设计。本次
提交推送 `zq` 分支；PR、同伴 Review 和远端 CI 由团队合并流程补充。
