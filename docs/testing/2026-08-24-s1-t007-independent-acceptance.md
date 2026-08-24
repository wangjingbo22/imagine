# S1-T007 独立测试与验收规程

## 1. 文档状态与使用边界

本规程是 `S1-T007 / PBI-03-A / AC-03-A` 的独立 QA 预言机，先于业务实现冻结。QA 不需要阅读编译器内部实现即可执行黑盒部分；完成黑盒验收后，再按本规程做最小白盒静态审查。

- 目标分支：`czy-S1-T007`
- 冻结生产契约基线：`67206f2c55dcb011c61304de94f95b8b83a72ba0`
- 设计/计划基线：`8b5c73322a8c736986f02e563c6586716815c608`
- 权威需求：
  - `docs/superpowers/specs/2026-08-24-s1-t007-assistance-constraint-compiler-design.md`
  - `docs/superpowers/plans/2026-08-24-s1-t007-assistance-constraint-compiler.md`
  - T003、T008、T009 在冻结基线上的生产契约与既有测试
- 当前状态：`PENDING_IMPLEMENTATION`。本规程建立测试与判定标准，不代表业务代码已验收。

实现窗口的测试日志、自报结果、截图、提交说明或追溯文件声明均不能单独作为 PASS 证据。所有强制命令必须由独立 QA 在交接的目标 commit 上重新执行；预期输出必须由本规程、冻结契约或独立黑盒预言机证明。

## 2. 验收对象、允许范围与非目标

实现完成后，设计/计划基线之后只允许出现以下路径：

```text
backend/app/services/assistance_constraints/__init__.py
backend/app/services/assistance_constraints/compiler.py
backend/tests/snapshots/assistance_constraints.json
backend/tests/test_assistance_constraint_compiler.py
backend/tests/test_assistance_constraint_integration.py
backend/tests/test_s1_t007_traceability.py
docs/traceability/sprint1/chen_ziyuan_s1_t007.json
docs/traceability/sprint1/chen_ziyuan_s1_t007.md
docs/testing/2026-08-24-s1-t007-independent-acceptance.md
```

以下内容不属于 S1-T007 的完成范围：修改 `AssistanceProfile` 或增加 `returnBy`；修改 T008 Protocol/DTO/adapter/registry/重编译守卫；修改 T009 路线风险算法或字段别名；实现 T011 的 DAY 规则求值、返程引用解析或候选规划；接入前端、HTTP、Provider、数据库、网络、LLM、系统时钟、随机数、缓存或全局单例。

返程规则只生成对 Trip 快照字段的引用。即使本规程全部通过，也只能声明 S1-T007 编译器通过，不能声明 T011 或端到端规划完成。

## 3. 目标 commit 与环境引导

### 3.1 交接预检

主协调窗口交接时，先把其提供的 40 位目标 commit 写入环境变量，再执行以下命令。若本地 HEAD、远端分支或交接 commit 任一不一致，立即停止；不得自行切换到其他分支、猜测目标 commit 或验收中间提交。

```powershell
$targetCommit = $env:S1_T007_TARGET_COMMIT
if ($targetCommit -notmatch '^[0-9a-f]{40}$') {
    throw 'S1_T007_TARGET_COMMIT must be the 40-character handoff commit'
}

git fetch origin czy-S1-T007
$branch = git branch --show-current
$localHead = git rev-parse HEAD
$remoteHead = git rev-parse origin/czy-S1-T007
$mergeBase = git merge-base 67206f2c55dcb011c61304de94f95b8b83a72ba0 HEAD

if ($branch -ne 'czy-S1-T007') { throw "wrong branch: $branch" }
if ($localHead -ne $targetCommit) { throw "local HEAD $localHead != handoff $targetCommit" }
if ($remoteHead -ne $targetCommit) { throw "remote HEAD $remoteHead != handoff $targetCommit" }
if ($mergeBase -ne '67206f2c55dcb011c61304de94f95b8b83a72ba0') {
    throw "unexpected contract ancestry: $mergeBase"
}

git status --short --untracked-files=all
```

允许的无关工作树条目只有既存 Excel 锁文件：

```text
?? doc/~$行知旅伴_V2.3_Sprint1待办列表_含负责人.xlsx
```

出现其他未提交、未跟踪或暂存内容时，本轮结果为 FAIL，须先由对应所有者处理并重新确认目标 commit。

### 3.2 Python 环境

在仓库根目录执行。`.venv/` 已被忽略，不得加入提交。

```powershell
$bootstrapPython = 'C:\Users\lenovo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    & $bootstrapPython -m venv .venv
}
$python = (Resolve-Path -LiteralPath '.venv\Scripts\python.exe').Path
& $python -m pip install -e '.[test]'
$env:PYTHONPATH = (Join-Path (Get-Location) 'backend')
& $python --version
& $python -m pytest --version
& $python -c "import fastapi, httpx, pydantic, pydantic_settings, uvicorn; print('project-deps-ok')"
```

门槛：Python `>=3.11`，pytest 可用，依赖探针打印 `project-deps-ok`。安装失败、使用了错误解释器或测试依赖缺失均不得继续给出 PASS。

## 4. 固定 canonical 预言机

### 4.1 全字段映射与顺序

所有生成规则当前均为 `HARD`。表中顺序是输出序列顺序，不得由字典遍历、输入键顺序或序列化器偶然决定。

| 顺序 | Profile 输入/条件 | `field` | `operator` | `value` | `scope` | 输出条件 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `walkLimits.maxContinuousMeters` | `walkLimits.maxContinuousMeters` | `LTE` | 原整数值 | `ROUTE_SEGMENT` | 非 `null` |
| 2 | `walkLimits.maxDailyMeters` | `walkLimits.maxDailyMeters` | `LTE` | 原整数值 | `DAY` | 非 `null` |
| 3 | `maxTransfers` | `maxTransfers` | `LTE` | 原整数值 | `ROUTE` | 非 `null`；`0` 仍须输出 |
| 4 | `restInterval` | `restInterval` | `LTE` | 原整数分钟 | `ROUTE` | 非 `null` |
| 5 | `napWindow` | `napWindow` | `BLOCK` | `{"start":"HH:mm:ss","end":"HH:mm:ss"}` | `DAY` | 非 `null` |
| 6 | `type == PARENT_CHILD` | `return` | `ARRIVE_BY` | 固定 Trip 字段引用 | `DAY` | 仅亲子预设 |
| 7 | `avoidStairs is true` | `avoidStairs` | `EQ` | `true` | `ROUTE_SEGMENT` | 仅 `true` |

其余输入语义固定如下：

- `childAge` 不产生 Constraint，不得据此推导阈值或偏好。
- T003 输入 JSON 的 `childAge`、两个步行字段、`maxTransfers`、`restInterval`、`napWindow` 仍是 required-nullable；“省略 null”仅指编译后的整条 Constraint，不是从输入 Schema 删除字段。
- `avoidStairs=false` 表示没有避阶梯约束，必须省略整条 Constraint；不得输出 `EQ false`。
- 任何输出都不得包含 `value: null`。
- `napWindow` 是单条、半开区间 `[start,end)` 的 DAY/HARD 原子规则；不得拆成两个边界。
- `return` 是单条 DAY/HARD 引用规则，value 的固定键顺序和值为：

```json
{
  "endLocationPath": "days[0].endLocationText",
  "deadlinePath": "days[0].timeWindow.end"
}
```

### 4.2 四个正式预设的完整输出

规则数必须依次为 `0/2/3/1`，完整 JSON 预言机如下：

```json
{
  "ORDINARY": [],
  "PARENT_CHILD": [
    {
      "field": "napWindow",
      "operator": "BLOCK",
      "value": {"start": "13:00:00", "end": "14:00:00"},
      "scope": "DAY",
      "hardness": "HARD"
    },
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
  ],
  "LOW_STAMINA": [
    {
      "field": "walkLimits.maxContinuousMeters",
      "operator": "LTE",
      "value": 500,
      "scope": "ROUTE_SEGMENT",
      "hardness": "HARD"
    },
    {
      "field": "maxTransfers",
      "operator": "LTE",
      "value": 2,
      "scope": "ROUTE",
      "hardness": "HARD"
    },
    {
      "field": "restInterval",
      "operator": "LTE",
      "value": 90,
      "scope": "ROUTE",
      "hardness": "HARD"
    }
  ],
  "MOBILITY_ASSISTANCE_BETA": [
    {
      "field": "avoidStairs",
      "operator": "EQ",
      "value": true,
      "scope": "ROUTE_SEGMENT",
      "hardness": "HARD"
    }
  ]
}
```

`maxDailyMeters` 当前四预设均为 `null`，但它是受支持字段，必须通过全字段自定义 Profile 证明其位于第 2 位并输出 `LTE / DAY / HARD`。

## 5. 独立测试矩阵

| ID | 维度 | 独立输入/动作 | 必须证据 |
| --- | --- | --- | --- |
| QA-001 | 分支与提交 | 比较交接 commit、本地 HEAD、远端 HEAD、基线祖先 | 四者满足第 3.1 节；无额外脏文件 |
| QA-002 | 四预设 | 逐一调用公开工厂与真实编译器 | 完整输出等于第 4.2 节，数量 `0/2/3/1` |
| QA-003 | 全字段映射 | 在有效亲子 Profile 上赋齐全部可选值 | 严格七项顺序；每项 field/operator/value/scope/hardness 精确 |
| QA-004 | null/false | 普通预设及四预设中的 null、`avoidStairs=false` | 不生成对应规则；无 `value:null`；普通输出为空 |
| QA-005 | 午休/返程 | 亲子预设 | 仅 `napWindow/BLOCK/DAY/HARD` 后接 `return/ARRIVE_BY/DAY/HARD`；路径值精确 |
| QA-006 | 边界值 | `maxTransfers=0`，步行/休息合法最小值，精确路线阈值 | 零值不被 truthiness 丢弃；LTE 等于阈值通过、超过 1 失败 |
| QA-007 | 字节级确定性 | 同一实例重复编译、不同编译器实例编译、Profile JSON round-trip 后编译 | 对象值、字段顺序、compact UTF-8 JSON 字节完全一致；Constraint 实例不共享；输入未被修改 |
| QA-008 | 非法直接 mutation | 构造后把 `maxTransfers` 改为字符串、连续步行改为 `0`、传入非 Profile | 抛 `ASSISTANCE_PROFILE_INVALID`；camelCase 字段路径与错误 code 精确；无部分结果 |
| QA-009 | 非法 Agent 输入 | 缺字段、错类型、未知字段、被 mutation 的模型 | `CONSTRAINT_TOOL_INPUT_INVALID`；编译结果不能进入规划 |
| QA-010 | T008 注入 | 真实编译器注入 `AssistanceConstraintAgentTool` | runtime Protocol 为真；invoke 输出等于直接编译；canonical 输出可进入规划 |
| QA-011 | T008 防篡改 | 分别改 scope、hardness、value、顺序、数量 | 每项均为 `CONSTRAINT_TOOL_OUTPUT_MISMATCH`；结构缺失则为 `CONSTRAINT_TOOL_OUTPUT_INVALID` |
| QA-012 | T009 真编译器 | 低体力 + 行动辅助真实输出送入风险器 | 阶梯、连续步行、换乘、休息四规则按 T009 固定顺序 FAIL，无字段翻译 |
| QA-013 | T009 DAY 隔离 | 亲子真实输出送入路线风险器 | nap/return 被忽略，报告 PASS 且 results 为空；未知硬路线规则仍 fail-closed |
| QA-014 | 全天步行消费 | 真实编译器输出自定义 `maxDailyMeters` | T009 识别 `walkLimits.maxDailyMeters` 并计算累计步行 |
| QA-015 | 冻结契约 | 对五个生产契约和三个既有测试做基线 diff | 字节级无差异 |
| QA-016 | 追溯 | 检查 S1-T007 JSON/Markdown 与路径存在性 | PBI→AC→Task→代码/测试/快照/消费者闭环；不篡改原 Day 1 账本 |
| QA-017 | 全量回归 | 定向、backend 全量、仓库全量 | 零失败、零错误；T007 用例无 skip/xfail/deselect |
| QA-018 | 静态范围 | 审查新增服务与变更清单 | 无 I/O/时钟/随机/缓存/全局可变状态；无越界文件 |

## 6. 强制自动化执行

### 6.1 定向测试与全量测试

按顺序执行并保存完整 stdout、exit code 与目标 commit：

```powershell
& $python -m pytest -p no:cacheprovider backend/tests/test_assistance_constraint_compiler.py -q
& $python -m pytest -p no:cacheprovider backend/tests/test_assistance_constraint_integration.py -q
& $python -m pytest -p no:cacheprovider backend/tests/test_assistance_profile_schema.py backend/tests/test_assistance_constraint_tool.py backend/tests/test_route_risk.py -q
& $python -m pytest -p no:cacheprovider backend/tests/test_s1_t007_traceability.py backend/tests/test_day1_traceability.py -q
& $python -m pytest -p no:cacheprovider backend/tests/test_assistance_profile_schema.py backend/tests/test_assistance_constraint_compiler.py backend/tests/test_assistance_constraint_integration.py backend/tests/test_assistance_constraint_tool.py backend/tests/test_route_risk.py backend/tests/test_s1_t007_traceability.py backend/tests/test_day1_traceability.py -q
& $python -m pytest -p no:cacheprovider backend/tests -q
& $python -m pytest -p no:cacheprovider -q
```

计划冻结时的预期计数分别为：编译器 `12 passed`、集成 `9 passed`、T003/T008/T009 既有回归 `38 passed`、追溯组合 `4 passed`、S1 关怀回归 `63 passed`、仓库全量 `101 passed`。backend 全量须记录实际收集数并全部通过。

低于上述定向计数、缺失测试、skip/xfail/deselect 均为 FAIL。因已审计的新提交而增加计数，只可在确认新增测试身份、变更路径和全部通过后接受；不得用“计数变化”解释测试减少。

### 6.2 独立编译器黑盒预言机

以下脚本不读取实现内部常量，也不使用实现窗口的 EXPECTED 数据。它独立验证完整四预设、七项顺序、null/false 省略、合法零值、输入不变、实例隔离和 compact UTF-8 JSON 字节确定性。

```powershell
@'
from __future__ import annotations

import json

from app.schemas.assistance import (
    create_assistance_profile,
    low_stamina_profile,
    parent_child_profile,
)
from app.schemas.trip import AssistanceType
from app.services.assistance_constraints import (
    AssistanceConstraintCompileError,
    DeterministicAssistanceConstraintCompiler,
)

EXPECTED = {
    AssistanceType.ORDINARY: [],
    AssistanceType.PARENT_CHILD: [
        {"field": "napWindow", "operator": "BLOCK", "value": {"start": "13:00:00", "end": "14:00:00"}, "scope": "DAY", "hardness": "HARD"},
        {"field": "return", "operator": "ARRIVE_BY", "value": {"endLocationPath": "days[0].endLocationText", "deadlinePath": "days[0].timeWindow.end"}, "scope": "DAY", "hardness": "HARD"},
    ],
    AssistanceType.LOW_STAMINA: [
        {"field": "walkLimits.maxContinuousMeters", "operator": "LTE", "value": 500, "scope": "ROUTE_SEGMENT", "hardness": "HARD"},
        {"field": "maxTransfers", "operator": "LTE", "value": 2, "scope": "ROUTE", "hardness": "HARD"},
        {"field": "restInterval", "operator": "LTE", "value": 90, "scope": "ROUTE", "hardness": "HARD"},
    ],
    AssistanceType.MOBILITY_ASSISTANCE_BETA: [
        {"field": "avoidStairs", "operator": "EQ", "value": True, "scope": "ROUTE_SEGMENT", "hardness": "HARD"},
    ],
}
COUNTS = {
    AssistanceType.ORDINARY: 0,
    AssistanceType.PARENT_CHILD: 2,
    AssistanceType.LOW_STAMINA: 3,
    AssistanceType.MOBILITY_ASSISTANCE_BETA: 1,
}

def dump(items):
    return [item.model_dump(mode="json", by_alias=True) for item in items]

def compact_bytes(items):
    return json.dumps(dump(items), ensure_ascii=False, separators=(",", ":")).encode("utf-8")

compiler = DeterministicAssistanceConstraintCompiler()
for profile_type in AssistanceType:
    profile = create_assistance_profile(profile_type)
    before = profile.model_dump_json(by_alias=True)
    first = compiler.compile(profile)
    second = compiler.compile(profile)
    third = DeterministicAssistanceConstraintCompiler().compile(
        type(profile).model_validate_json(before, strict=True)
    )
    assert isinstance(first, tuple)
    assert len(first) == COUNTS[profile_type]
    assert dump(first) == EXPECTED[profile_type]
    assert all(
        list(item) == ["field", "operator", "value", "scope", "hardness"]
        for item in dump(first)
    )
    for item in dump(first):
        if item["field"] == "napWindow":
            assert list(item["value"]) == ["start", "end"]
        if item["field"] == "return":
            assert list(item["value"]) == ["endLocationPath", "deadlinePath"]
    assert first == second == third
    assert compact_bytes(first) == compact_bytes(second) == compact_bytes(third)
    for left, right in zip(first, second):
        assert left is not right
        if isinstance(left.value, dict):
            assert left.value is not right.value
    assert profile.model_dump_json(by_alias=True) == before
    assert '"value":null' not in compact_bytes(first).decode("utf-8")

all_fields = parent_child_profile()
all_fields.walk_limits.max_continuous_meters = 1
all_fields.walk_limits.max_daily_meters = 2
all_fields.max_transfers = 0
all_fields.rest_interval = 1
all_fields.avoid_stairs = True
compiled = compiler.compile(all_fields)
assert [item.field for item in compiled] == [
    "walkLimits.maxContinuousMeters",
    "walkLimits.maxDailyMeters",
    "maxTransfers",
    "restInterval",
    "napWindow",
    "return",
    "avoidStairs",
]
assert [item.value for item in compiled[:4]] == [1, 2, 0, 1]
assert compiled[1].scope == "DAY" and compiled[1].hardness == "HARD"

for mutate, expected_path, expected_issue in (
    (lambda p: setattr(p, "max_transfers", "2"), "maxTransfers", "int_type"),
    (lambda p: setattr(p.walk_limits, "max_continuous_meters", 0), "walkLimits.maxContinuousMeters", "greater_than_equal"),
):
    invalid = low_stamina_profile()
    mutate(invalid)
    planner_values = []
    try:
        planner_values.append(compiler.compile(invalid))
    except AssistanceConstraintCompileError as exc:
        assert exc.code == "ASSISTANCE_PROFILE_INVALID"
        assert exc.issues[0].path == expected_path
        assert exc.issues[0].code == expected_issue
    else:
        raise AssertionError("invalid mutation returned planning constraints")
    assert planner_values == []

try:
    compiler.compile(object())
except AssistanceConstraintCompileError as exc:
    assert exc.code == "ASSISTANCE_PROFILE_INVALID"
    assert exc.issues[0].path == ""
    assert exc.issues[0].code == "model_type"
else:
    raise AssertionError("non-profile input did not fail closed")

print("s1-t007-compiler-black-box-ok")
'@ | & $python -
```

唯一通过标志为进程 exit code 0 且打印 `s1-t007-compiler-black-box-ok`。

### 6.3 T008/T009 独立边界预言机

以下脚本必须使用真实编译器，而非 FakeCompiler。它验证 T008 结构注入、canonical 放行、五类篡改拒绝、非法 Agent 输入，以及 T009 对真实路线规则与 DAY 规则的行为。

```powershell
@'
from __future__ import annotations

from copy import deepcopy

from app.agents.tools.assistance_constraints import (
    AssistanceConstraintAgentTool,
    AssistanceConstraintCompiler,
    ConstraintToolContractError,
)
from app.schemas.assistance import create_assistance_profile, low_stamina_profile, ordinary_profile
from app.schemas.constraint import Constraint
from app.schemas.trip import AssistanceType
from app.services.assistance_constraints import DeterministicAssistanceConstraintCompiler
from app.services.route_risk import (
    RouteRiskContractError,
    RouteRiskInput,
    RouteSegmentRiskFacts,
    ValidationStatus,
    WalkType,
    evaluate_route_risk,
)

compiler = DeterministicAssistanceConstraintCompiler()
tool = AssistanceConstraintAgentTool(compiler)
assert isinstance(compiler, AssistanceConstraintCompiler)

parent = create_assistance_profile(AssistanceType.PARENT_CHILD)
canonical = tool.invoke({"assistanceProfile": parent})
assert canonical.constraints == compiler.compile(parent)
assert tool.validate_for_planning(
    {"assistanceProfile": parent},
    canonical.model_dump(mode="json", by_alias=True),
) == canonical

def scope(payload): payload["constraints"][0]["scope"] = "TRIP"
def hardness(payload): payload["constraints"][0]["hardness"] = "SOFT"
def value(payload): payload["constraints"][0]["value"]["start"] = "12:59:59"
def order(payload): payload["constraints"].reverse()
def count(payload): payload["constraints"].pop()

base = canonical.model_dump(mode="json", by_alias=True)
for mutate in (scope, hardness, value, order, count):
    candidate = deepcopy(base)
    mutate(candidate)
    try:
        tool.validate_for_planning({"assistanceProfile": parent}, candidate)
    except ConstraintToolContractError as exc:
        assert exc.code == "CONSTRAINT_TOOL_OUTPUT_MISMATCH"
    else:
        raise AssertionError(f"tampering escaped: {mutate.__name__}")

for mutate in (
    lambda payload: payload.pop("walkLimits"),
    lambda payload: payload.update({"maxTransfers": "2"}),
    lambda payload: payload.update({"unknownCareField": True}),
):
    payload = low_stamina_profile().model_dump(mode="json", by_alias=True)
    mutate(payload)
    planner_values = []
    try:
        planner_values.append(tool.invoke({"assistanceProfile": payload}))
    except ConstraintToolContractError as exc:
        assert exc.code == "CONSTRAINT_TOOL_INPUT_INVALID"
    else:
        raise AssertionError("invalid Agent input returned a planning value")
    assert planner_values == []

route = RouteRiskInput(segments=(RouteSegmentRiskFacts(
    route_segment="seg-all-risks",
    walking_distance_meters=501,
    cumulative_transfers=3,
    elapsed_since_rest_minutes=91,
    walk_types=(WalkType.STAIRS,),
),))
route_constraints = (
    *compiler.compile(create_assistance_profile(AssistanceType.LOW_STAMINA)),
    *compiler.compile(create_assistance_profile(AssistanceType.MOBILITY_ASSISTANCE_BETA)),
)
report = evaluate_route_risk(route, route_constraints)
assert report.status is ValidationStatus.FAIL
assert [item.rule_id for item in report.results] == [
    "CARE.ROUTE.STAIRS_FORBIDDEN",
    "CARE.ROUTE.WALK_SEGMENT_LIMIT",
    "CARE.ROUTE.TRANSFER_LIMIT",
    "CARE.ROUTE.REST_INTERVAL",
]

parent_report = evaluate_route_risk(route, compiler.compile(parent))
assert parent_report.status is ValidationStatus.PASS
assert parent_report.results == ()

daily = ordinary_profile()
daily.walk_limits.max_daily_meters = 500
daily_report = evaluate_route_risk(route, compiler.compile(daily))
assert daily_report.status is ValidationStatus.FAIL
assert [item.rule_id for item in daily_report.results] == ["CARE.ROUTE.WALK_DAILY_LIMIT"]

unknown = Constraint(
    field="wheelchairRampEvidence",
    operator="EQ",
    value=True,
    scope="ROUTE_SEGMENT",
    hardness="HARD",
)
try:
    evaluate_route_risk(route, (unknown,))
except RouteRiskContractError as exc:
    assert exc.code == "UNSUPPORTED_HARD_ROUTE_CONSTRAINT"
else:
    raise AssertionError("unknown hard route rule did not fail closed")

print("s1-t007-t008-t009-boundaries-ok")
'@ | & $python -
```

唯一通过标志为进程 exit code 0 且打印 `s1-t007-t008-t009-boundaries-ok`。

## 7. 快照、契约与静态门禁

### 7.1 JSON 与快照审计

```powershell
& $python -c "import json,pathlib; p=pathlib.Path('backend/tests/snapshots/assistance_constraints.json'); d=json.loads(p.read_text(encoding='utf-8')); assert list(d)==['ORDINARY','PARENT_CHILD','LOW_STAMINA','MOBILITY_ASSISTANCE_BETA']; assert {k:len(v) for k,v in d.items()}=={'ORDINARY':0,'PARENT_CHILD':2,'LOW_STAMINA':3,'MOBILITY_ASSISTANCE_BETA':1}; print('snapshot-ok')"
& $python -c "import json,pathlib; p=pathlib.Path('docs/traceability/sprint1/chen_ziyuan_s1_t007.json'); d=json.loads(p.read_text(encoding='utf-8')); assert (d['taskId'],d['pbiId'],d['acId'])==('S1-T007','PBI-03-A','AC-03-A'); print('trace-json-ok')"
```

QA 还必须人工逐字段比较快照与第 4.2 节，不能只接受“JSON 可解析”或测试自产生的快照。

### 7.2 冻结文件 diff

```powershell
$contractBaseline = '67206f2c55dcb011c61304de94f95b8b83a72ba0'
$targetCommit = $env:S1_T007_TARGET_COMMIT

git diff --exit-code $contractBaseline $targetCommit -- backend/app/schemas/trip.py backend/app/schemas/assistance.py backend/app/schemas/constraint.py backend/app/agents/tools/assistance_constraints.py backend/app/services/route_risk/evaluator.py
git diff --exit-code $contractBaseline $targetCommit -- backend/tests/test_assistance_profile_schema.py backend/tests/test_assistance_constraint_tool.py backend/tests/test_route_risk.py
git diff --exit-code $contractBaseline $targetCommit -- docs/traceability/sprint1/lin_canhan_day1.json docs/traceability/sprint1/lin_canhan_day1.md backend/tests/test_day1_traceability.py
```

三条命令都必须无输出且 exit code 0。任何冻结生产文件、既有契约测试或原 Day 1 追溯账本变化均为 FAIL；不得通过放宽旧测试来换取通过。

### 7.3 范围、空白与依赖扫描

```powershell
$targetCommit = $env:S1_T007_TARGET_COMMIT
git diff --check 8b5c73322a8c736986f02e563c6586716815c608..$targetCommit
git diff --name-only 8b5c73322a8c736986f02e563c6586716815c608..$targetCommit
rg -n "requests|httpx|openai|langgraph|datetime\.now|date\.today|random|uuid|sleep|cache|os\.environ|time\.time" backend/app/services/assistance_constraints
git status --short --untracked-files=all
```

门槛：`git diff --check` 无输出；变更路径是第 2 节白名单的子集且完整包含计划产物；依赖扫描无输出；状态只允许既存 Excel 锁文件。

### 7.4 最小白盒审查清单

QA 在黑盒通过后检查新增服务并记录文件与行号：

- `compile()` 公开签名为 `compile(profile: AssistanceProfile) -> tuple[Constraint, ...]`，真实对象满足 T008 runtime Protocol。
- 服务层只依赖 schema/validation contract，不反向 import Agent adapter 或路线风险器。
- canonical 顺序由显式控制流或不可变常量固定；未按输入 mapping 顺序迭代产出规则。
- 每次调用新建 tuple 与 Constraint；未复用可变列表、Constraint、嵌套 value 或模块级可变状态。
- 编译前严格重验证可能被创建后 mutation 的 Pydantic 模型；非法输入只抛错误，不返回部分结果。
- 错误对象只含 code、字段路径、错误类型与消息，不回显昵称或关怀原值。
- 不修改输入 Profile；不从 `childAge`、类型或人口特征猜测数值限制。
- 不读取环境、文件、网络、数据库、时钟、随机源或缓存。

任一项无法从代码与运行证据共同证明时，保持 FAIL/PENDING，不得基于实现者说明放行。

## 8. PBI → AC → Task → 证据追溯

| PBI / AC | Task 与角色 | 契约/产物 | 独立证据 | 判定 |
| --- | --- | --- | --- | --- |
| `PBI-01-B / AC-01-B` | `S1-T003` 上游 Profile | `trip.py`、`assistance.py`、四 Profile fixture | `test_assistance_profile_schema.py` + QA-002/003/004 | required-nullable、四预设与 public alias 不变 |
| `PBI-03-A / AC-03-A` | `S1-T007` 被验收实现 | 真实编译器、快照、错误模型 | 编译器定向测试 + 第 6.2 节 + 快照人工审查 | 六类关怀规则、全部字段、顺序、确定性、fail-closed 均成立 |
| `PBI-03-A / AC-03-A` | `S1-T008` 下游守卫 | Protocol、Agent adapter、规划前重编译 | `test_assistance_constraint_tool.py`、集成测试、第 6.3 节 | 真实注入兼容；scope/hardness/value/顺序/数量篡改均拒绝 |
| `PBI-03-B / AC-03-B` | `S1-T009` 路线消费者 | 五个冻结字段、路线风险矩阵 | `test_route_risk.py`、集成测试、第 6.3 节 | 真编译结果无翻译消费；亲子 DAY 规则隔离；未知硬路线规则 fail-closed |
| `PBI-03-A / AC-03-A` | `S1-T007` 交付追溯 | `chen_ziyuan_s1_t007.json/.md` | `test_s1_t007_traceability.py` + 第 7.1/7.2 节 | task/PBI/AC、依赖、消费者、代码、测试、快照路径均存在 |
| 后续消费 | `S1-T011`，非本次完成项 | 解析 `days[0].endLocationText` 与 `days[0].timeWindow.end` | 仅检查 handoff 被明确记录 | 不得将引用生成误报为已完成返程校验 |

新的机器追溯至少必须声明：`taskId=S1-T007`、`pbiId=PBI-03-A`、`acId=AC-03-A`、`dependsOn=[S1-T003]`、`consumedBy=[S1-T008,S1-T009,S1-T011]`，并列出真实存在的代码、契约、测试和快照路径。`status=IMPLEMENTED` 只是元数据，不能替代运行证据。

## 9. 缺陷反馈模板

发现问题后发回代码撰写窗口，必须包含可独立复现的信息：

```text
缺陷 ID：S1-T007-QA-<序号>
严重级别：P0 / P1 / P2 / P3
目标 commit：<40 位 commit>
环境：Python/pytest 版本，操作系统，PYTHONPATH
对应矩阵：QA-<ID>，PBI / AC / Task
最小复现命令：<完整命令>
最小输入：<Profile/Constraint/route payload；敏感值脱敏>
期望：<引用本规程的精确字段、顺序、code 或状态>
实际：<完整错误摘要、exit code；不省略首个失败>
文件与行号：<path:line；静态问题必须给出>
影响：<是否产生错误规划值、破坏冻结契约、非确定性或回归>
证据附件：<QA 自行运行的日志/diff；不得只贴实现者日志>
修复 commit：<收到修复后填写>
复验：未复验 / FAIL / PASS，附新命令与输出
```

严重级别：P0 为安全、隐私或不可恢复数据风险；P1 为错误约束、fail-open、冻结契约破坏、确定性失败或全量回归失败；P2 为边界、兼容、追溯或错误契约不符；P3 为仍影响本规程执行或交付清晰度的文档/可维护性问题。任何未关闭缺陷，无论级别，均不得给 PASS。

## 10. PASS / FAIL 门槛

只有以下条件同时成立才能给出 `PASS`：

1. 交接 commit、本地 HEAD、远端 `origin/czy-S1-T007` 完全一致，且冻结基线是其祖先。
2. 第 6 节全部命令由独立 QA 新鲜执行，exit code 均为 0；定向计数不低于冻结值，T007 无 skip/xfail/deselect。
3. 四预设完整输出为 `0/2/3/1`，七项顺序、所有字段映射、null/false 省略、DAY 规则和字节级确定性均与本规程一致。
4. 非法直接输入与非法 Agent 输入 fail-closed，无任何部分或规划可用值。
5. T008 真实注入成功且所有篡改被拒；T009 消费真实路线规则且正确隔离 nap/return DAY 规则。
6. backend 全量和仓库全量零失败、零错误；任何新增 skip/xfail 或计数漂移均已逐项解释并有 diff 证据。
7. 三组冻结 diff 均为空，变更路径不越界，`git diff --check` 与禁止依赖扫描通过。
8. 快照经 QA 人工逐字段复核，PBI→AC→Task→证据追溯闭环，T011 handoff 明确且未被误报完成。
9. 最小白盒审查无问题，工作树除既存 Excel 锁文件外干净，所有发现的缺陷已在修复 commit 上重复验收并关闭。

出现任一条件不满足即为 `FAIL`；目标 commit 尚未交接或证据尚未执行时为 `PENDING`。不允许 `CONDITIONAL PASS`，也不允许以“实现者自测通过”“预计 CI 会通过”或“仅定向测试通过”替代本门槛。

最终报告必须列出：目标 commit、各命令实际通过数、两个黑盒探针标志、快照 `0/2/3/1`、冻结 diff 结果、静态审查结论、剩余工作树条目、缺陷清单与复验 commit。所有证据通过后才向实现分析窗口交回 PASS，供其最后检查。
