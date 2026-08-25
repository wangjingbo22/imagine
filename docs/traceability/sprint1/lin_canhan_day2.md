# 林粲涵 Sprint 1 Day 2 代码追溯

本页只覆盖 `S1-T011`、`S1-T018`、`S1-T022`。实现以团队最新 `origin/main` 提交 `b5b6d9fc0f19c01ef56f5b6db2aa8f13bf82cbdf` 为兼容基线，代码提交为 `1837e288686aa30c215eb01ea97e21682fba0360`。逐文件机器可读证据见 `lin_canhan_day2.json`。

## PBI → AC → Task → 模块 → 测试

| PBI / AC | Task | 生产模块 | 验收证据 | 上游 → 下游 |
|---|---|---|---|---|
| PBI-04-A / AC-04-A | S1-T011 | `services/planning` | 3–4 个任务的黄金 CandidatePlan；T007 重编译、T006 路线/价格事实、T009 风险、分单位预算、时间与端点连续性均服务端重算；unknown 独立为待确认 | T006 + T007 + T009 → T011 → T012 / T018 / T024 |
| PBI-05-B / AC-05-B | S1-T018 | `services/replanning` 与 T011 重算适配器 | 冻结已完成/跳过/锁定前缀；先最少改动数、再满意度损失、最后稳定摘要；预算含实际消费与剩余计划；无解输出 ruleId 和可操作放宽项；选中 V2 可由真实 SQLite 服务登记 | T011 + T017 输入端口 → T018 → T019 / T024 |
| PBI-06-A / AC-06-A | S1-T022 | `services/summary_trace` | 无 V2、接受 V2、拒绝 V2 三条真实 HTTP/SQLite 路径；每个公开整数都有 PlanVersion 谱系，并在适用时带 Task/Event 谱系；错误的 planVersion→task 归属会 fail-closed；不依赖照片 | T021 → T022 → T024 |

## 关键联动

- T011 不接受客户端或模型自报的 PASS。它重新编译 T007 关怀约束，校验路线首尾坐标、段间连续性和通勤耗时，调用 T006→T009 适配链重算路线风险，并从 Place/Route 原始价格事实按整数分重算预算。
- T018 通过 `TrustedCandidateFactSource` 取回不可变事实，再调用 `T011ReplanCandidateValidator` 重算预算、时间、路线、关怀四个 HARD 域。实际 `EXPENSE` 与候选剩余成本共同参与预算，已发生费用不会与同一任务计划成本重复计算。
- T011 的 V1 已通过真实 `PlanVersionService` 登记、确认并进入执行；T018 选出的 V2 随后由同一个 SQLite 服务登记为 `PROPOSED`，Trip 进入 `REPLAN_REVIEW`，供既有 T019 接口接受或拒绝。
- T022 读取既有 T021 Summary 与完整 PlanVersion 快照，只生成只读数字追溯；它不改 Summary，不虚构任务、事件、版本或图片证据。

## T017 边界声明

最新 main 仍没有 S1-T017 的真实候选生成器。本次只定义并验证 `ReplanCandidateSource` 输入端口，未代替其他负责人实现 T017，也不声明 T017→T018 已完成线上组装。当前可验收的是 T018 选择器、真实 T011 重算适配器以及 Selected V2→既有 T019/SQLite 的登记闭环。

## 本地验收

在仓库根目录执行：

```powershell
python -B -m pytest -p no:cacheprovider -q
cd frontend
npm ci --no-audit --no-fund
npm run build
npm run lint
```

最终结果：后端 `215 passed`；Day2 聚焦回归 `33 passed`；前端 build 与 lint 均通过。远端 main 在验收前再次 fetch，仍为上述兼容基线。PR、CI Build、QA 和 PO 属于外部证据，当前没有时保持为空。
