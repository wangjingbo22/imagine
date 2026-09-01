# 林粲涵 Sprint 3：S3-T003 自动化质量门禁

**Owner：** 林粲涵

**Traceability：** PBI-15-A / AC-15-A / S3-T003

**交付基线：** `main@72011508a668b585d59c0e41d63985ca10efc15d`
**状态：** `LOCAL_QUALITY_GATE_PASS`

## 需求来源

任务来自 `doc/行知旅伴_V2.3_Sprint3收尾待办列表_12小时Alpha扩展版.xlsx` 的 `Sprint3收尾待办!A10:M10`：固定硬约束用例违规为 0；核心规划、关怀、校验、预算、重规划覆盖率分别不低于 75%；无未关闭 P0/P1。

## 交付合同

- `python tools/s3_t003_quality_gate.py` 是本地与 CI 共用的唯一后端门禁入口。
- `backend/tests/fixtures/s3_t003/fixed_hard_constraint_cases.json` 冻结修复后必须保持零违规的命名用例。
- `docs/quality/s3_defects.json` 是缺陷登记事实源；P0/P1 只有在带复验证据的 `CLOSED` 状态才不阻断。
- `.quality-reports/s3-t003/quality-gate.json`、`coverage.json` 和 `junit.xml` 是每次运行生成的机器证据，CI 保留 14 天。
- 覆盖率缺少声明模块时 fail closed，不能以移除文件或只跑聚焦测试缩小门禁范围。
- 仅两条显式真实高德在线烟测允许在未启用在线开关时 skip；任何新增 skip/xfail 都阻断门禁。

## AC 映射

| AC-15-A 条件 | 自动化证据 |
| --- | --- |
| 固定硬约束用例违规为 0 | 门禁直接执行 `one-person-ready` 与 `three-person-ready`，汇总实际 `CollaborationIssue` 数量 |
| 五个核心域覆盖率均不低于 75% | pytest-cov 全量采集后按声明源文件聚合并逐域判定 |
| 无未关闭 P0/P1 | 缺陷登记解析器校验 ID、严重级别、状态、唯一性和关闭证据 |
| T002 可接入 | 所有标准 `backend/tests/test_*.py` 自动纳入；缺陷登记和固定用例扩展方式已冻结 |

## 依赖与边界

S3-T001 已有本地响应式验收记录。S3-T002 当前提交包含媒体 SQLite 恢复验收，其他模型、地图、定位和真实设备范围仍应按各自证据独立陈述；T003 接口会自动接收 T002 后续测试，但不提前宣称这些外部范围已经完成。

本记录只覆盖本地自动化门禁。真实 Provider、模型、公网、设备和验收签字不由覆盖率或本地 pytest 替代。

## 本地验证

基于上述交付基线及本次变更执行 `python tools/s3_t003_quality_gate.py`：后端 `782 passed, 2 skipped`，两条 skip 均为未设置 `RUN_AMAP_LIVE_SMOKE=1` 时的西安/杭州真实高德烟测，且 `unexpectedSkippedTests` 为空；门禁总状态为 `PASS`。

| 域 | 覆盖率 | 门槛 | 结果 |
| --- | ---: | ---: | --- |
| 规划 | 86.25% | 75% | PASS |
| 关怀 | 93.75% | 75% | PASS |
| 校验 | 91.91% | 75% | PASS |
| 预算 | 100.00% | 75% | PASS |
| 重规划 | 85.75% | 75% | PASS |

固定硬约束共 2 例、实际违规 0；缺陷登记共 0 项、未关闭 P0/P1 为 0。运行产物位于 `.quality-reports/s3-t003/`，该目录不提交仓库；合并后的 CI 将针对实际提交重新生成并上传报告。
