# 张琪 S1-T019 V1/V2 Diff 与原子决策追溯

服务端从不可变 V1/V2 快照计算地点、时间、路线、费用和关怀变化，并区分
`RETAINED`、`REMOVED`、`ADDED`、`CHANGED`。接受 V2 在同一 SQLite 事务中
把 V1 迁移为 `SUPERSEDED`、V2 迁移为唯一 `CURRENT`；拒绝 V2 时 V1 和
执行状态保持不变。重复同一决策幂等，反向决策会被状态守卫拒绝。

固定 Diff JSON 与接受/拒绝状态快照位于
`docs/testing/evidence/s1_t019_diff_and_decisions.json`。自动化会重新运行真实
仓储事务并逐项比对该证据，见 `tests/test_s1_t019_evidence.py` 和
`tests/test_plan_v2_diff.py`。本次提交推送 `zq` 分支；PR、同伴 Review 和远端
CI 由团队合并流程补充。
