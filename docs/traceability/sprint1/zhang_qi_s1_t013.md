# 张琪 S1-T013 Plan V1 持久化追溯

PlanVersion 以不可变 JSON 快照写入 SQLite，`(trip_id, version)` 唯一，且
部分唯一索引保证同一 Trip 只能存在一个 `CURRENT`。确认操作把 V1 从
`PROPOSED` 原子迁移为 `CURRENT`；刷新后恢复 cityCode、days[0]、任务和金额。

同一 `planId` 的重复登记现在严格返回 `PLAN_VERSION_ALREADY_EXISTS`；尝试用
同一 `planId` 改写快照返回 `PLAN_VERSION_IMMUTABLE`。重复点击“确认”仍保持
幂等，不重复迁移状态。

自动化证据为 `tests/test_plan_versions.py` 与
`tests/test_s1_t013_evidence.py`，固定快照为
`docs/testing/evidence/s1_t013_plan_v1_snapshot.json`。本次提交推送 `zq` 分支；
PR、同伴 Review 和远端 CI 由团队合并流程补充。
