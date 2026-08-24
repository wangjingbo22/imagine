# S1-T007 最终评审记录

## 结论

**FINAL REVIEW PASS**

被审业务提交 `11fae535a70f67cf3a3aa63cfce4f6d9296e6d30` 与独立 QA 提交
`71e3d4a8ba3a1ea2733c28b8be16bb4243decf41` 满足
`S1-T007 / PBI-03-A / AC-03-A` 的设计、实现、测试、追溯与范围门禁。
本次终审未发现 P0、P1、P2 或 P3 缺陷。

评审开始时，分支为 `czy-S1-T007`，本地 HEAD、fetch 后的
`origin/czy-S1-T007` 均精确为 QA 提交；冻结基线
`67206f2c55dcb011c61304de94f95b8b83a72ba0` 是其祖先。

## 验收核对矩阵

| 验收项 | 证据 | 结论 |
| --- | --- | --- |
| 七项 canonical 顺序 | 编译器显式按连续步行、全天步行、换乘、休息、午休、返程、避阶梯构造；全字段测试与独立探针逐项比较 | PASS |
| 四预设 `0/2/3/1` | JSON 快照、12 项编译器测试、独立完整输出预言机一致 | PASS |
| null/false 整项省略 | 数值和窗口仅在非 null 时生成；`avoidStairs` 仅 true 时生成；输出无 `value:null` | PASS |
| 午休与返程 | `napWindow/BLOCK/DAY/HARD`；`return/ARRIVE_BY/DAY/HARD`，均为单条原子规则 | PASS |
| 返程不猜测 | value 只引用已确认 Trip/Plan V1 输入快照的 `days[0].endLocationText` 与 `days[0].timeWindow.end`，不生成字面地点或时间 | PASS |
| 非法 Profile fail-closed | 编译前 strict JSON round-trip 重验证；错误为 `ASSISTANCE_PROFILE_INVALID`，路径为 camelCase，且无部分返回值 | PASS |
| 新鲜对象与确定性 | 同实例重复、跨编译器、JSON round-trip 后的值、顺序和 compact UTF-8 字节一致；Constraint 与嵌套 dict 不共享 | PASS |
| T008 注入和防篡改 | runtime Protocol、Agent canonical 输出与直接编译一致；scope、hardness、value、顺序、数量篡改均被拒绝 | PASS |
| T009 消费边界 | 五个冻结路线字段直接消费；亲子 `DAY` 规则被隔离；未知 HARD 路线规则仍 fail-closed | PASS |
| PBI→AC→Task→证据 | 机器 JSON、Markdown 与追溯测试闭合 `PBI-03-A → AC-03-A → S1-T007 → 代码/测试/快照/消费者` | PASS |
| 后续任务边界 | T011 只被标记为消费者；DAY 求值、返程引用解析、候选规划和后续 Sprint 均未声明完成 | PASS |

## 新鲜运行证据

终审使用仓库现有 `.venv`：Python `3.12.13`、pytest `8.4.2`，项目依赖探针打印
`project-deps-ok`。

```powershell
python -m pytest -p no:cacheprovider -ra -q `
  backend/tests/test_assistance_profile_schema.py `
  backend/tests/test_assistance_constraint_compiler.py `
  backend/tests/test_assistance_constraint_integration.py `
  backend/tests/test_assistance_constraint_tool.py `
  backend/tests/test_route_risk.py `
  backend/tests/test_s1_t007_traceability.py `
  backend/tests/test_day1_traceability.py
```

结果：`63 passed in 0.24s`，无 skip、xfail 或 deselect。

两个独立黑盒探针均以 exit code 0 结束，并分别打印：

```text
s1-t007-compiler-black-box-ok
s1-t007-t008-t009-boundaries-ok
```

独立 QA 文档同时记录了业务提交上的完整新鲜回归：backend `89 passed`、全仓
`101 passed`，均无 skip、xfail 或 deselect。

## 范围与静态门禁

- 相对 `67206f2c...` 的业务/QA diff 在最终评审文档加入前共 11 个路径，均为新增文件并精确落入设计、实现、测试、快照、追溯与 QA 白名单。
- 五个冻结生产契约、三个 T003/T008/T009 既有测试、原 Day 1 追溯 JSON/Markdown 与测试均为零 diff。
- `git diff --check 67206f2c...HEAD` 通过；新增编译服务的网络、LLM、环境、时钟、随机数、休眠和缓存禁止依赖扫描为零命中。
- 编译服务只依赖 schema/validation contract，不反向 import T008 Agent adapter 或 T009 路线风险器，也没有 I/O 或模块级可变状态。
- 工作树在写入本记录前只有既存未跟踪 Excel 锁文件
  `doc/~$行知旅伴_V2.3_Sprint1待办列表_含负责人.xlsx`；终审未读取、修改、暂存或提交该文件。
- 本记录是用户授权的最终评审产物；不修改任何生产代码、测试代码、快照、追溯或独立 QA 结论。

## 范围声明

本 PASS 只证明 S1-T007 的确定性 `AssistanceProfile→Constraint` 编译器及其与
T003/T008/T009 冻结契约的兼容性。它不证明 T011 已解析 DAY 引用，不证明候选计划
已执行返程/午休硬约束，也不代表后续 Sprint 或端到端规划已完成。
