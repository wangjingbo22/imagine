# S3-T003 质量门禁与 T002 接入说明

## 唯一执行入口

在仓库根目录运行：

```powershell
python tools/s3_t003_quality_gate.py
```

门禁固定执行后端全量 pytest，并生成：

- `.quality-reports/s3-t003/quality-gate.json`：总判定、各检查结果和 Git 提交；
- `.quality-reports/s3-t003/coverage.json`：coverage.py 明细；
- `.quality-reports/s3-t003/junit.xml`：后端测试结果。

CI 使用同一命令，并在成功或失败时上传 `s3-t003-quality-reports`。报告目录属于本地/CI 运行产物，不提交仓库。

## 强制检查

| 检查 | 通过条件 |
| --- | --- |
| 后端测试 | `backend/tests` 全量退出码为 0 |
| 固定硬约束 | `fixed_hard_constraint_cases.json` 中所有修复后用例的违规总数为 0 |
| 核心覆盖率 | 规划、关怀、校验、预算、重规划五个域分别不低于 75% |
| 缺陷 | `docs/quality/s3_defects.json` 中没有状态非 `CLOSED` 的 P0/P1 |

覆盖率按域聚合，统计范围固定在 `tools/s3_t003_quality_gate.py` 的 `COVERAGE_GROUPS`。缺少任何声明范围也会失败，不能通过删除未覆盖文件缩小分母。

后端测试只允许西安、杭州两条真实高德在线烟测在未设置 `RUN_AMAP_LIVE_SMOKE=1` 时跳过；任何新增 skip/xfail 都会失败并出现在 `unexpectedSkippedTests`。

缺陷状态允许 `OPEN`、`IN_PROGRESS`、`BLOCKED`、`RESOLVED`、`CLOSED`。`RESOLVED` 表示代码可能已经修复但尚未完成独立复验，仍会阻断 P0/P1；只有带非空验证证据的 `CLOSED` 才算关闭。登记格式由 `s3_defects.schema.json` 冻结。

## S3-T002 如何接入

T002 不需要修改门禁脚本：

1. 将降级/恢复回归放在现有 `backend/tests/test_*.py` 下，门禁会自动执行。当前媒体存储恢复测试和权威 Trip 百炼降级测试已经由全量入口覆盖。
2. 发现缺陷时向 `docs/quality/s3_defects.json` 增加唯一 `S3-DEF-NNN` 项；修复后先标为 `RESOLVED`，独立复验通过并填写测试节点或证据路径后改为 `CLOSED`。
3. 如果新增的是“修复后必须永远保持零硬冲突”的确定性用例，先放入 `backend/tests/fixtures/s2_t003/cases.json`，再把名称加入 `backend/tests/fixtures/s3_t003/fixed_hard_constraint_cases.json`。

门禁会执行完整测试集，因此 T002 新用例失败会直接阻断 CI。T002 不应降低 75% 阈值、删除覆盖率统计范围，或把失败用例改成 skip/xfail 来换取 PASS。

## 验收边界

本门禁证明本地确定性代码、测试、覆盖率和已登记缺陷状态满足 AC-15-A。它不替代真实高德/百炼、公网多浏览器、GPS、照片权限、真实设备或老师签字；这些结果必须在各自验收记录中保持 `NOT_RUN`、`BLOCKED` 或实际结果。
