# 陈梓元 S1-T007 关怀约束编译追溯

## 任务

`S1-T007 / PBI-03-A / AC-03-A` 在基线
`67206f2c55dcb011c61304de94f95b8b83a72ba0` 上实现确定性的
`AssistanceProfile→Constraint` 编译器。上游是 T003；T008、T009 和
T011 消费本任务结果。

## 固定规则

Canonical 顺序为连续步行、全天步行、换乘、休息、午休、返程、
避阶梯。Null 来源和 `avoidStairs=false` 不产生规则；四个正式 Profile
输出数量依次为 0、2、3、1。当前规则均为 HARD。

亲子午休表示为 `napWindow/BLOCK/DAY`。返程表示为
`return/ARRIVE_BY/DAY`，value 引用 `days[0].endLocationText` 与
`days[0].timeWindow.end`，不猜测地点或时间。

## 兼容边界

T003 Profile Schema、T008 Protocol/Agent adapter 和 T009 路线风险器
均未修改。真实编译器通过 T008 注入与防篡改测试；T009 直接消费五个
冻结路线字段，并忽略 DAY-scoped 午休/返程规则。返程引用的解析和
候选计划总校验属于 T011。

## 自动化证据

- `test_assistance_constraint_compiler.py`：四 Profile 快照、重复编译、
  Null 省略、固定顺序和字段级非法输入。
- `test_assistance_constraint_integration.py`：T008/T009 真实集成与篡改
  拒绝。
- `snapshots/assistance_constraints.json`：四 Profile canonical JSON。
- `test_s1_t007_traceability.py`：任务、依赖、消费者及证据文件完整性。
