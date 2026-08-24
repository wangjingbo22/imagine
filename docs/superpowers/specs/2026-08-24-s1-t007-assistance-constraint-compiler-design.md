# S1-T007 AssistanceProfile→Constraint 确定性编译器设计

## 1. 任务边界与结论

S1-T007 对应 `PBI-03-A / AC-03-A`。它把已经确认的 `AssistanceProfile` 编译为可计算、可序列化、顺序稳定的 `Constraint` 序列。相同输入必须得到逐字段、逐项顺序和 JSON 字节均一致的输出；非法输入不得产生可进入规划的结果。

本设计选择新增一个纯 Python 服务 `DeterministicAssistanceConstraintCompiler`，结构化实现 T008 已冻结的 `AssistanceConstraintCompiler` Protocol：

```python
class DeterministicAssistanceConstraintCompiler:
    def compile(
        self,
        profile: AssistanceProfile,
    ) -> tuple[Constraint, ...]: ...
```

不修改 T003 的 `AssistanceProfile` 字段，不修改 T008 的 Protocol、Agent 输入/输出和重编译守卫，也不修改 T009 已消费的字段名。编译器无 I/O、网络、LLM、系统时间、随机数、缓存或全局可变状态。

## 2. 权威依据与现状审计

### 2.1 任务与产品依据

Sprint 1 工作簿的 S1-T007 行要求：四类 Profile 编译两次后，步行、换乘、休息、午休、返程和避阶梯 Constraint 均有 `scope/hardness`，结果一致，非法字段停止规划。

产品待办 `AC-03-A` 进一步要求：

- 同一输入可复现；
- 无对应需求时不凭空增加限制；
- 编译失败返回具体字段并停止进入规划；
- LLM 只解释，不直接改写确定性约束。

V2.3 项目规划说明亲子模板应支持午休和最晚返程，低体力模板支持步行、换乘和休息，行动辅助 Beta 排除已知阶梯。

### 2.2 已冻结的上游/下游契约

- T003 在 `backend/app/schemas/trip.py` 定义四种 `AssistanceType` 及 `AssistanceProfile`；`backend/app/schemas/assistance.py` 提供四个新鲜实例工厂。
- Profile 的全部字段都是 required-nullable：JSON 中未采集的字段显式为 `null`，不能省略。现有前后端测试已冻结这一行为。
- T008 在 `backend/app/agents/tools/assistance_constraints.py` 只提供 `AssistanceConstraintCompiler.compile(profile)` Protocol、注入式 Agent adapter、严格输入/输出校验和规划前重编译对比。
- `Constraint` 契约已冻结为 `field/operator/value/scope/hardness`；`hardness` 只能是 `HARD` 或 `SOFT`。
- T009 已固定消费以下字段名：
  - `walkLimits.maxContinuousMeters`
  - `walkLimits.maxDailyMeters`
  - `maxTransfers`
  - `restInterval`
  - `avoidStairs`
- T009 只评估上述已知路线字段。未知硬规则仅在路线 scope 下 fail-closed；日级规则不会被路线风险器误消费。

### 2.3 返程契约缺口

当前 `AssistanceProfile` 没有“最晚返程”字段；返程地点和日结束时间分别位于 `TripDayInput.endLocationText` 与 `TripDayInput.timeWindow.end`。与此同时，T008 的已冻结端口只接收 `AssistanceProfile`，不能接收 Trip 或 Day。

因此编译器不能安全地复制一个不存在于 Profile 的返程时间，也不能从系统时间或人群类型猜测具体时刻。这个缺口必须显式建模，不能用硬编码默认时间掩盖。

## 3. 方案比较

### 方案 A：扩展 AssistanceProfile，新增 `returnBy`

优点是值直接来自输入，语义最直观。缺点是会改变 T003 的 required-nullable Schema、四份 Fixture、公开 JSON Schema、前端类型和转换器；旧前端 payload 会因缺字段失败。这超出 T007 的最小边界并破坏当前兼容性。

### 方案 B：把 T008 端口改为 `compile(profile, day)`

优点是返程值可直接使用 Trip Day。缺点是破坏已冻结的 T008 Protocol、Agent 输入模型和现有契约测试，并扩大 LLM 工具边界。用户要求明确把 T008 视为只提供 Protocol 与 adapter，本方案不采用。

### 方案 C：为亲子 Profile 编译日级返程“引用规则”（采用）

编译器输出一个不含猜测值的返程规则，其 `value` 只保存规范化 Trip 字段路径：

```json
{
  "field": "return",
  "operator": "ARRIVE_BY",
  "value": {
    "endLocationPath": "days[0].endLocationText",
    "deadlinePath": "days[0].timeWindow.end"
  },
  "scope": "DAY",
  "hardness": "HARD"
}
```

这保留 T003/T008/T009 契约，且不会虚构返程地点或时间。亲子 Profile 类型是当前已存在、且 V2.3 项目规划明确关联“最晚返程”的唯一信号，因此只有 `PARENT_CHILD` 产生该规则。后续确定性计划校验器必须在规划前从已确认 Trip 快照解析这两个路径；路径缺失或类型错误时 fail-closed。自定义具体返程时间不在 T007 中新增，需以后由 Profile Schema 的独立版本化任务处理。

## 4. 文件与模块边界

新增：

- `backend/app/services/assistance_constraints/compiler.py`
  - 定义所有规范字段、scope、operator 和固定规则顺序；
  - 重新校验传入 Profile；
  - 实现纯函数式编译；
  - 定义字段级编译错误。
- `backend/app/services/assistance_constraints/__init__.py`
  - 只导出稳定的编译器、错误类型和需要共享的字段常量。
- `backend/tests/test_assistance_constraint_compiler.py`
  - 单元测试、四 Profile 快照、确定性与非法输入测试。
- `backend/tests/snapshots/assistance_constraints.json`
  - 四种正式 Profile 的完整 canonical 输出。
- `backend/tests/test_assistance_constraint_integration.py`
  - 用真实编译器验证 T008 Protocol/adapter 与 T009 路线风险兼容。
- `docs/traceability/sprint1/chen_ziyuan_s1_t007.json` 与同名 `.md`
  - 单独记录陈梓元负责的 S1-T007，不篡改林粲涵个人 Day 1 追溯范围。
- `backend/tests/test_s1_t007_traceability.py`
  - 校验追溯条目与引用文件存在。

不修改：

- `backend/app/schemas/trip.py`
- `backend/app/schemas/assistance.py`
- `backend/app/schemas/constraint.py`
- `backend/app/agents/tools/assistance_constraints.py`
- `backend/app/services/route_risk/evaluator.py`

这些文件是审计和兼容目标，而不是 T007 的业务实现位置。只有测试证明不兼容时，才允许在代码实现窗口提出最小契约修订；不能先改冻结契约再让测试追随。

## 5. Canonical 规则表

所有当前 Profile 字段都代表用户已确认的限制，因此生成的规则均为 `HARD`。现阶段不从人群标签推导软偏好。

| 固定顺序 | Profile 来源/条件 | `Constraint.field` | `operator` | `value` | `scope` | `hardness` |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `walkLimits.maxContinuousMeters != null` | `walkLimits.maxContinuousMeters` | `LTE` | 原整数值 | `ROUTE_SEGMENT` | `HARD` |
| 2 | `walkLimits.maxDailyMeters != null` | `walkLimits.maxDailyMeters` | `LTE` | 原整数值 | `DAY` | `HARD` |
| 3 | `maxTransfers != null` | `maxTransfers` | `LTE` | 原整数值 | `ROUTE` | `HARD` |
| 4 | `restInterval != null` | `restInterval` | `LTE` | 原整数分钟 | `ROUTE` | `HARD` |
| 5 | `napWindow != null` | `napWindow` | `BLOCK` | `{"start":"HH:mm:ss","end":"HH:mm:ss"}` | `DAY` | `HARD` |
| 6 | `type == PARENT_CHILD` | `return` | `ARRIVE_BY` | 两个规范 Trip 字段路径 | `DAY` | `HARD` |
| 7 | `avoidStairs is true` | `avoidStairs` | `EQ` | `true` | `ROUTE_SEGMENT` | `HARD` |

顺序是编译器常量，不依赖字典遍历、Pydantic 序列化顺序或调用方输入顺序。未来新增规则只能追加版本化决策；不能在不更新快照与消费者审计的情况下插入或重排。

## 6. 四类 Profile 的预期输出

| Profile | Canonical 输出（依次） | 规则数 |
| --- | --- | --- |
| `ORDINARY` | 空序列 | 0 |
| `PARENT_CHILD` | `napWindow/BLOCK`、`return/ARRIVE_BY` | 2 |
| `LOW_STAMINA` | `walkLimits.maxContinuousMeters/LTE`、`maxTransfers/LTE`、`restInterval/LTE` | 3 |
| `MOBILITY_ASSISTANCE_BETA` | `avoidStairs/EQ true` | 1 |

四种正式预设的并集恰好覆盖 AC 点名的步行、换乘、休息、午休、返程和避阶梯六类规则。`maxDailyMeters` 当前四个预设均为 `null`，通过自定义有效 Profile 单独测试，不因此从实现中删除。

`ORDINARY` 不输出 `avoidStairs EQ false`，避免把“没有避阶梯需求”误写成路线必须包含或允许阶梯的规则。任何为 `null` 的来源字段都不生成 Constraint，输出中不出现 `value: null`。

## 7. 午休与返程表达

### 7.1 午休

`napWindow` 使用一个原子规则，不拆成两个不完整的边界：

```json
{
  "field": "napWindow",
  "operator": "BLOCK",
  "value": {"start": "13:00:00", "end": "14:00:00"},
  "scope": "DAY",
  "hardness": "HARD"
}
```

`BLOCK` 表示计划器不得在半开时间区间 `[start, end)` 安排任务或交通；`start/end` 保持 T003 已校验的无时区、秒精度 `HH:mm:ss`。编译器不重新解释时区或跨午夜，因为 T003 已禁止这些输入。

### 7.2 返程

返程使用一个原子引用规则：

```json
{
  "field": "return",
  "operator": "ARRIVE_BY",
  "value": {
    "endLocationPath": "days[0].endLocationText",
    "deadlinePath": "days[0].timeWindow.end"
  },
  "scope": "DAY",
  "hardness": "HARD"
}
```

`ARRIVE_BY` 表示候选计划最后必须在 `deadlinePath` 指向的时刻前抵达 `endLocationPath` 指向的地点。路径是契约引用，不是字面地点或时间。T007 只生成引用；T011 的规划/校验组装层负责用同一已确认 Trip 快照解析。T009 看到 `scope=DAY` 时不会把它当成未知硬路线规则。

## 8. Null、序列化与确定性

- Profile 输入继续保留 T003 的 required-nullable 规则；不得改为 `exclude_none=True`，也不得允许省略已冻结字段。
- Constraint 输出采用“无需求即无规则”：`null` 来源和 `avoidStairs=false` 均省略整条 Constraint。
- `compile()` 返回 `tuple[Constraint, ...]`，与 T008 的 `Sequence[Constraint]` Protocol 协变兼容。
- `napWindow.value` 和 `return.value` 使用按字面量声明的固定键顺序。
- 测试同时比较对象相等、字段序列和 compact JSON 字节；重复调用不得共享可变列表或 Constraint 实例。
- 编译器不读取 Profile 之外的可变环境，因此在进程、时区和执行日期变化下结果不变。

## 9. 校验与错误模型

虽然正常入口由 T008 先校验，具体编译器仍在边界重新把 `AssistanceProfile` 做 JSON round-trip 和严格校验，以防调用方传入创建后被修改的 Pydantic 实例。

新增错误：

```python
class AssistanceConstraintCompileError(ValueError):
    code: str
    issues: tuple[ValidationIssue, ...]

    def as_dict(self) -> dict[str, object]: ...
```

固定顶层 code 为 `ASSISTANCE_PROFILE_INVALID`。Pydantic 错误通过现有 `issues_from_pydantic()` 转换，路径使用 camelCase，例如：

```json
{
  "code": "ASSISTANCE_PROFILE_INVALID",
  "errors": [
    {
      "path": "maxTransfers",
      "code": "int_type",
      "message": "Input should be a valid integer"
    }
  ]
}
```

直接编译失败时不返回部分 Constraint。经 T008 Agent 工具调用时，原始 mapping 或被修改的模型会在其 `_validate_input()` 阶段变为 `CONSTRAINT_TOOL_INPUT_INVALID`，编译器不会获得非法 Profile；两条路径都保证没有规划可用返回值。

错误对象不包含原始输入值，避免把昵称或关怀细节写入日志。错误顺序沿用 Pydantic 的稳定字段顺序。

## 10. T008 注入与 T009 兼容

### T008

具体编译器通过现有构造器注入，不新增服务定位器或全局单例：

```python
compiler = DeterministicAssistanceConstraintCompiler()
tool = AssistanceConstraintAgentTool(compiler)
```

运行时 `isinstance(compiler, AssistanceConstraintCompiler)` 必须为真。T008 的 `validate_for_planning()` 仍通过重新编译比较 scope、hardness、value、顺序和数量；T007 不复制该守卫。

仓库目前没有 backend Agent composition root。实际 registry 注册由 T011/T024 的组装层负责；T007 不为了“接入”而创建未被调用的全局对象。

### T009

五个路线字段名和 operator 保持现状：数值上限用 `LTE`，避阶梯用 `EQ true`。scope 与现有测试一致。T009 自己按固定 `_RULE_ORDER` 输出风险结果，因此 T007 的 canonical 编译顺序不会改变风险报告顺序。

`napWindow` 与 `return` 均为 `DAY` scope。T009 会忽略它们，未来由 T011 的日程校验器消费；不会触发 `UNSUPPORTED_HARD_ROUTE_CONSTRAINT`。

## 11. 测试矩阵

| 维度 | 输入 | 断言 |
| --- | --- | --- |
| 四预设快照 | 四个 `create_assistance_profile()` 结果 | 与完整 JSON 快照相等；规则数为 0/2/3/1 |
| 重复编译 | 每个 Profile 连续编译两次 | 对象、顺序和 compact JSON 字节完全一致；实例不共享 |
| Null 省略 | `ORDINARY` 与各 null 字段 | 无 `value:null`；无凭空步行/换乘/休息/午休/阶梯规则 |
| 普通档案 | `ORDINARY` | 空序列，不产生 `avoidStairs=false` 假规则 |
| 亲子 | `PARENT_CHILD` | 先 `napWindow/BLOCK`，后 `return/ARRIVE_BY`；均为 DAY/HARD |
| 低体力 | `LOW_STAMINA` | 500 米、2 次换乘、90 分钟原值保留；scope/operator 精确 |
| 行动辅助 | `MOBILITY_ASSISTANCE_BETA` | 仅 `avoidStairs EQ true / ROUTE_SEGMENT / HARD` |
| 全天步行 | 有效自定义 `maxDailyMeters` | 位于连续步行之后、换乘之前；`DAY/HARD` |
| 组合顺序 | 所有可选字段均有值 | 严格遵循七项 canonical 顺序 |
| 非法直接输入 | 创建后把 `maxTransfers` 改成字符串、步行值改为 0 | `AssistanceConstraintCompileError` 含 camelCase 字段路径；无部分结果 |
| 非法 Agent 输入 | mapping 缺字段、错类型、未知字段 | T008 抛 `CONSTRAINT_TOOL_INPUT_INVALID`，没有规划返回值 |
| T008 端口 | 真实编译器注入 Agent tool | Protocol 检查通过；adapter 输出与直接编译相等 |
| T008 防篡改 | 改 scope/hardness/value/顺序/数量 | `CONSTRAINT_TOOL_OUTPUT_MISMATCH` |
| T009 路线消费 | 真实低体力/行动辅助编译结果 + 路线 Fixture | 既有步行/换乘/休息/阶梯规则命中不变 |
| T009 日级隔离 | 亲子编译结果 + 路线 Fixture | nap/return 不被误判为未知硬路线规则 |
| 追溯 | S1-T007 追溯 JSON | PBI/AC、依赖、消费者、代码、测试、快照路径完整且存在 |

## 12. 明确非目标

- 不修改或版本化 `AssistanceProfile`，不新增具体 `returnBy` 字段。
- 不实现 T004 的关怀确认 UI、状态机或 HTTP 路由。
- 不实现 T006 的 Provider/RouteSnapshot 适配。
- 不修改 T008 的 Agent Protocol、输入/输出 DTO、注册器或防篡改策略。
- 不修改 T009 的路线风险算法、字段别名或风险状态。
- 不实现 T011 的候选规划、日程冲突、返程路径解析或硬约束总校验。
- 不从 `childAge`、Profile 类型或人口特征推导未确认的数值阈值。
- 不生成软偏好、设施可用性声明、母婴室/电梯/坡道保证或全国无障碍结论。
- 不接入数据库、缓存、网络、LLM、LangGraph、系统时间或随机数。
- 不实现多人约束合并、冲突放宽、Sprint 2 事件转约束或 Plan V2。

## 13. 完成判定

S1-T007 只有在以下条件同时满足时才能声明实现完成：

1. 四 Profile 快照、重复编译和 canonical 顺序测试通过。
2. 六类 AC 规则在四 Profile 并集中均出现，且每条都含精确 scope/hardness。
3. Null 来源不产生 Constraint；`ORDINARY` 不产生人口特征假限制。
4. 非法直接输入与非法 Agent 输入均返回字段级错误且没有规划可用值。
5. 真实编译器通过 T008 Protocol/adapter 集成测试，T008 防篡改回归不变。
6. 真实编译结果通过 T009 现有路线 Fixture；DAY 规则不被路线风险器误消费。
7. 新增追溯文件完整，现有 T003/T008/T009 追溯与测试仍通过。
8. 相关测试、完整 pytest、`git diff --check` 和生产范围扫描全部通过。
