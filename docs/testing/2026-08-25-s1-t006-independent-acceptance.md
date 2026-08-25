# S1-T006 独立测试与验收规程

## 1. 文档状态与独立性边界

本规程是 `S1-T006 / PBI-02-A / AC-02-A` 的独立 QA 预言机，在生产实现开始前冻结。当前状态为 `PENDING_IMPLEMENTATION`：本轮只设计测试与验收，不执行下文的最终验收命令，也不采信实现窗口的测试结论。

- 目标工作树：`C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.worktrees\czy-S1-T006`
- 目标分支：`czy-S1-T006`
- 生产契约基线：`cd9a9d992a2877f718e1577ae331aab2d487406e`
- 分析规格与实施计划冻结点：`e12dc30b6aad6e12e26164e8e2545aafb7c46bbf`
- 权威需求：
  - `doc/行知旅伴_V2.3_Sprint1待办列表_含负责人.xlsx`
  - `docs/superpowers/specs/2026-08-25-s1-t006-design.md`
  - `docs/superpowers/plans/2026-08-25-s1-t006-implementation.md`
  - `docs/traceability/sprint1/lin_canhan_day1.md` 中的 `T006/T007 → T009` 交接
  - 冻结点上的缓存、价格、路线、T009 DTO/evaluator 契约与既有测试

实现者提供的 RED/GREEN 日志、提交说明、快照或“全量通过”声明只能作为待复核材料。最终结论必须来自独立 QA 在交接目标 commit 上重新运行的第 7—9 节命令以及第 10 节静态审查。

## 2. T006 工作簿逐条追溯

### 2.1 SprintBacklog 原始行

以下字段逐项来自 `SprintBacklog模板!A10:V10`，不得由实现计划替换或放宽。

| 工作簿字段 | 原始值 | 独立验收落点 |
| --- | --- | --- |
| Task-ID | `S1-T006` | 全部 `QA-*` |
| PBI-ID / AC-ID | `PBI-02-A / AC-02-A` | `QA-C01`—`QA-E04` |
| 用户故事 / PBI 条目 | 城市地点、路线与可信来源 | 缓存、价格来源、路线事实均须可追溯 |
| 可执行 Task | 实现 cityCode 隔离缓存、来源归一化与 unknown 价格不按 0 元计入预算 | `QA-C01`—`QA-C03`、`QA-P01`—`QA-P03`、`QA-B01`—`QA-B03` |
| 优先级 | `Must` | 任一核心行为失败至少为 `Important` |
| 估算 / 计划日 | `2h / Day2` | 不以工时为由删减边界用例 |
| 前置依赖 | `S1-T005` | 冻结并复用现有 Provider/cache 契约，不重写缓存 |
| 负责人 / 动态评审 | 陈梓元；非作者按缓存串城与预算风险评审 | 本规程由独立窗口设计和执行 |
| 工作簿验收条件 | 两城同名 POI + 在线失败；缓存键含 cityCode 且不串城；unknown 保持未知、触发预警、不参与已知金额求和 | `QA-C01`—`QA-C03`、`QA-P01`—`QA-B03` |
| 工作簿交付证据 | PR、缓存键快照、跨城隔离测试、unknown 预算测试 | `QA-E01`—`QA-E04`；PR 由外部 push/创建，当前窗口不得伪造 |

### 2.2 PBI / AC 原始追溯

`PBI追溯!A8:J8` 冻结的产品 AC 为：给定已确认 `CityContext`，查询候选地点和路线时，`cityCode` 必须进入 Provider 请求与缓存键且不得跨城；地点、路线、价格携带来源、`fetchedAt` 与事实状态；unknown 不得按 0 元参与预算；在线失败只读对应城市缓存。

对应关系如下：

| 产品 AC 子句 | 契约/生产边界 | 自动化证据 | 独立探针 |
| --- | --- | --- | --- |
| `cityCode` 进入请求与缓存键 | `AmapLocationService.search_places`、`SqliteProviderCache` | `tests/test_place_service.py`、缓存键 JSON | `s1-t006-cache-price-probe-ok` |
| 不得跨城 | 四元精确键与目标城市 miss | 两城对称恢复、单城 miss 回归 | `QA-C01`、`QA-C03` |
| 价格携带来源、时间与事实状态 | `PriceFact`、集合/价格两层 `Provenance` | 模型与缓存恢复测试 | `QA-P01`—`QA-P03` |
| unknown 不按 0 元参与预算 | `PriceFact` 双向不变量、`summarize_budget` | `tests/test_price_fact.py`、`tests/test_budget.py` | `s1-t006-budget-probe-ok` |
| 在线失败只读对应城市缓存 | `_fetch` 的精确 cache lookup | 既有与新增 service 测试 | `QA-C01`、`QA-C03` |

### 2.3 下游依赖与路线适配的来源

工作簿 `SprintBacklog模板!A14:V15` 冻结了两个下游：`S1-T010` 依赖 `S1-T006,S1-T009`，`S1-T011` 依赖 `S1-T006,S1-T007,S1-T009`。工作簿 T006 行没有逐字段写出 Route DTO 适配，但现有 `docs/traceability/sprint1/lin_canhan_day1.md` 明确要求 T006 将团队 RouteSnapshot 映射为 T009 `RouteRiskInput` 并保留稳定 `routeSegment`；仓库实际来源模型是 `app.domain.models.Route`。

因此 `QA-R01`—`QA-R05` 验收一个纯、无 I/O 的 `Route → RouteRiskInput` 窄桥接。它不是对 T009 evaluator、T010/T011 规划器或 UI 的授权。

## 3. 允许范围、冻结契约与禁飞区

### 3.1 允许变更白名单

从分析冻结点 `e12dc30b6aad6e12e26164e8e2545aafb7c46bbf` 到交接目标 commit，只允许以下路径发生变化：

```text
app/application/amap_service.py
app/application/route_risk_adapter.py
app/domain/budget.py
app/domain/models.py
docs/testing/2026-08-25-s1-t006-independent-acceptance.md
tests/snapshots/s1_t006_cache_keys.json
tests/test_budget.py
tests/test_place_service.py
tests/test_price_fact.py
tests/test_route_risk_adapter.py
```

其中生产文件仅允许四个：`models.py` 强化双向价格不变量，`amap_service.py` 增加非有限价格守卫，`budget.py` 实现纯已知小计，`route_risk_adapter.py` 实现纯路线映射。不得借 T006 修改其他生产路径。

### 3.2 必须字节级冻结的契约与既有测试

以下文件相对分析冻结点必须无 diff：

```text
app/infrastructure/cache.py
backend/app/schemas/constraint.py
backend/app/schemas/trip.py
backend/app/services/route_risk/__init__.py
backend/app/services/route_risk/evaluator.py
backend/app/services/route_risk/models.py
backend/tests/test_route_risk.py
tests/conftest.py
```

`tests/test_place_service.py` 是计划内扩展文件，但既有四个测试不得删除、改名、skip、xfail 或放宽断言。

### 3.3 禁飞区

- 不重写 `SqliteProviderCache`，不迁移 SQLite schema，不引入 Redis。
- 不新增或修改 HTTP 路由、公开响应结构、前端文件或 UI。
- 不修改 PlanVersion、`PlanTask.costCents`、预算上限决策或 T010/T011 规划器。
- 不修改 T009 DTO/evaluator，不在生产 adapter 内调用 evaluator。
- 不把 unknown 转为 `0`，也不把真实 `0 + ONLINE` 转为 unknown。
- 不接入网络、LLM、环境时钟决策、随机源或新依赖。
- 不切换、修改、合并 `main`，不 push，不 merge。

任何禁飞区生产改动为 `Important`；跨城数据泄漏、unknown 被当作 0、T009 UNKNOWN 被伪装为 PASS、密钥泄漏为 `Critical`。

## 4. 严重度与反馈门槛

| 等级 | 定义 | 示例 | 是否阻断交回终审 |
| --- | --- | --- | --- |
| `Critical` | 数据隔离、安全或 fail-open 缺陷 | 串城缓存、unknown 计为 0、UNKNOWN 阶梯得到 PASS、密钥进入快照 | 是 |
| `Important` | Must AC、冻结契约、映射、确定性或回归不满足 | 双向不变量失效、预算漏警告、routeId 改写、全量 pytest 失败、越界改生产代码 | 是 |
| `Minor` | 不改变行为但影响可审查性 | 非阻断的说明不清或日志元数据缺项 | 单独报告 |

代码窗口与独立 QA 必须循环到没有开放的 `Critical` 或 `Important`。不得通过删测试、缩小参数集、改预期、添加 skip/xfail 或把异常吞成默认值关闭缺陷。

## 5. 交接预检与环境

收到代码完成通知后，编排窗口提供 40 位目标 commit，并由独立 QA 在仓库根目录执行：

```powershell
$targetCommit = $env:S1_T006_TARGET_COMMIT
$contractBase = 'cd9a9d992a2877f718e1577ae331aab2d487406e'
$analysisCommit = 'e12dc30b6aad6e12e26164e8e2545aafb7c46bbf'

if ($targetCommit -notmatch '^[0-9a-f]{40}$') {
    throw 'S1_T006_TARGET_COMMIT must be a 40-character lowercase SHA'
}

$branch = git branch --show-current
$localHead = git rev-parse HEAD
$analysisMergeBase = git merge-base $analysisCommit $targetCommit
$contractMergeBase = git merge-base $contractBase $targetCommit
$qaDocumentCommit = @(
    git log --reverse --format=%H "$analysisCommit..$targetCommit" -- `
        'docs/testing/2026-08-25-s1-t006-independent-acceptance.md'
)[0]
$worktreeState = @(git status --short --untracked-files=all)

if ($branch -ne 'czy-S1-T006') { throw "wrong branch: $branch" }
if ($localHead -ne $targetCommit) { throw "HEAD $localHead != handoff $targetCommit" }
if ($analysisMergeBase -ne $analysisCommit) { throw 'analysis commit is not an ancestor' }
if ($contractMergeBase -ne $contractBase) { throw 'contract baseline is not an ancestor' }
if ($qaDocumentCommit -notmatch '^[0-9a-f]{40}$') { throw 'QA document commit not found' }
if ($worktreeState.Count -ne 0) { throw "dirty worktree: $worktreeState" }
```

使用计划冻结的仓库虚拟环境，不在验收时安装或升级依赖：

```powershell
$python = 'C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw "missing interpreter: $python" }
$env:PYTHONPATH = "$(Get-Location);$(Join-Path (Get-Location) 'backend')"
& $python --version
& $python -m pytest --version
& $python -c "import pydantic,pytest; print('s1-t006-deps-ok')"
```

Python 必须为 `>=3.11`，pytest 必须可用，依赖探针必须打印 `s1-t006-deps-ok`。预检失败时停止，不得在错误分支、错误 commit 或脏工作树上形成验收结论。

## 6. 独立验收矩阵

“命令”列中的 pytest 命令与第 7 节独立探针都必须执行；两类证据互相补充，不能只选一种。

### 6.1 缓存与价格来源

| ID | 前置 | 输入 | 命令 | 精确预期 | 失败严重度 |
| --- | --- | --- | --- | --- | --- |
| `QA-C01` | 临时空 SQLite；在线 stub 可依次返回两城数据，随后统一抛 `PROVIDER_TIMEOUT` | 同关键词“城市博物馆”、相同 types/page/pageSize；北京 `110000`/`same-name-beijing`，上海 `310000`/`same-name-shanghai` | `& $python -m pytest -p no:cacheprovider -q tests/test_place_service.py::test_same_named_poi_cache_is_isolated_by_city_code_and_matches_key_snapshot`；再跑第 7.1 节 | 两城离线各恢复自身 `placeId/adCode/cityCode`；集合均为 `VERIFIED_CACHE`；无串城 | `Critical` |
| `QA-C02` | `QA-C01` 已完成两次在线写入 | 只读查询 `provider,operation,city_code,request_hash`，按 city 排序 | `& $python -m pytest -p no:cacheprovider -q tests/test_place_service.py::test_same_named_poi_cache_is_isolated_by_city_code_and_matches_key_snapshot`；再跑第 7.1 节和第 9.2 节 | 恰有两行；四元键城市分别为 `110000/310000`；hash 精确等于冻结值；快照无 payload、Key、时间戳 | `Critical` |
| `QA-C03` | 仅北京精确键存在；上海无缓存 | 上海同查询在线抛 `AppError('PROVIDER_TIMEOUT',...)` | `& $python -m pytest -p no:cacheprovider -q tests/test_place_service.py::test_online_failure_reads_only_matching_city_cache`；再跑第 7.1 节 | 原错误 code 保持 `PROVIDER_TIMEOUT`；不模糊命中北京记录 | `Critical` |
| `QA-P01` | Provider 在线响应可控 | `""`、`[]`、`"not-a-price"`、`"-1"`、`"NaN"`、`"Infinity"`、`"-Infinity"` | `& $python -m pytest -p no:cacheprovider -q tests/test_place_service.py::test_missing_or_invalid_provider_price_stays_unknown`；再跑第 7.1 节 | 每项稳定归一为 `amountCents=None + sourceStatus=UNKNOWN`；无 Decimal 异常泄漏 | `Important` |
| `QA-P02` | 直接构造 `PriceFact` | 合法：`0+ONLINE`、`None+UNKNOWN`；非法：`None+ONLINE`、`0+UNKNOWN`、`100+UNKNOWN` | `& $python -m pytest -p no:cacheprovider -q tests/test_price_fact.py`；再跑第 7.1 节 | 两个合法状态精确保留；三个矛盾状态均抛 Pydantic `ValidationError`，不强制转换 | `Critical` |
| `QA-P03` | 先在线缓存缺失价格，再以在线失败读取 | 同一北京查询，payload `cost=""` | `& $python -m pytest -p no:cacheprovider -q tests/test_place_service.py::test_cached_unknown_price_keeps_unknown_price_provenance`；再跑第 7.1 节 | 集合来源 `VERIFIED_CACHE`；价格仍 `None+UNKNOWN`；价格与集合保留同一 `fetchedAt/isStale` | `Critical` |

### 6.2 预算汇总

| ID | 前置 | 输入 | 命令 | 精确预期 | 失败严重度 |
| --- | --- | --- | --- | --- | --- |
| `QA-B01` | `PriceFact` 双向不变量已通过 | `museum=1250+ONLINE`、`walk=0+ONLINE` | `& $python -m pytest -p no:cacheprovider -q tests/test_budget.py::test_all_known_prices_include_real_zero_without_warning`；再跑第 7.2 节 | `knownSubtotalCents=1250`、`unknownAmountCount=0`、`COMPLETE`、无 warnings；0 保持已知免费 | `Critical` |
| `QA-B02` | 同上 | `museum=1250+ONLINE`、`restaurant=None+UNKNOWN` | `& $python -m pytest -p no:cacheprovider -q tests/test_budget.py::test_unknown_price_is_not_summed_as_zero_and_emits_located_warning`；再跑第 7.2 节 | 小计仍为 1250；unknown 不进入任何算术；计数 1；`NEEDS_CONFIRMATION`；一条可定位 `UNKNOWN_PRICE` | `Critical` |
| `QA-B03` | 同上 | 顺序输入 `route-b`、`place-a` 两个 unknown，kind 各异 | `& $python -m pytest -p no:cacheprovider -q tests/test_budget.py::test_multiple_unknown_warnings_preserve_input_order`；再跑第 7.2 节 | 小计 0、计数 2、`NEEDS_CONFIRMATION`；warnings 与输入顺序一致并逐项保留 `referenceId/kind/message` | `Important` |

### 6.3 Route → RouteRiskInput 与 T009

| ID | 前置 | 输入 | 命令 | 精确预期 | 失败严重度 |
| --- | --- | --- | --- | --- | --- |
| `QA-R01` | T009 冻结 DTO 可导入 | 公交 Route：`routeId=route-stable-001`、600m、2 次换乘、2400s；显式 elapsed=40 | `& $python -m pytest -p no:cacheprovider -q tests/test_route_risk_adapter.py::test_transit_route_maps_exact_facts_and_stable_route_segment`；再跑第 7.3 节 | 单段；`routeId` 原样成为 `routeSegment`；600/2/40 精确；`walkTypes=(UNKNOWN,)`；重复映射 camelCase JSON 字节一致 | `Important` |
| `QA-R02` | 有效 Route 工厂 | WALKING/DRIVING/BICYCLING，61s、elapsed=2 | `& $python -m pytest -p no:cacheprovider -q tests/test_route_risk_adapter.py::test_non_transit_mode_boundaries`；再跑第 7.3 节 | WALKING 使用总距离且 `UNKNOWN`；DRIVING/BICYCLING 为 0/0/`LEVEL`；不借空 Provider 字段失败 | `Important` |
| `QA-R03` | 适配函数可反射签名 | 2400s 分别传 40、39、`True`、`40.0`；另传位置参数 | `& $python -m pytest -p no:cacheprovider -q tests/test_route_risk_adapter.py::test_invalid_required_route_fact_fails_closed`；再跑第 7.3 节 | elapsed 是 keyword-only、类型必须恰为 int、且 `>=ceil(duration/60)`；非法均为 field=`elapsedSinceRestMinutes`，不猜值 | `Critical` |
| `QA-R04` | Route 模型本身合法 | TRANSIT 缺 `walkingDistanceMeters`；缺 `transferCount`；routeId 长度 120/121 | `& $python -m pytest -p no:cacheprovider -q tests/test_route_risk_adapter.py::test_invalid_required_route_fact_fails_closed`；再跑第 7.3 节 | 缺事实及 121 字符均抛 `ROUTE_RISK_INPUT_INVALID` 且 field 精确；120 字符可映射；不填 0、不散列 ID | `Critical` |
| `QA-R05` | 真实 T009 evaluator 与 `avoidStairs EQ true HARD` | `QA-R01` 的 adapter 输出 | `& $python -m pytest -p no:cacheprovider -q tests/test_route_risk_adapter.py::test_unknown_stair_evidence_reaches_t009_with_same_route_segment backend/tests/test_route_risk.py::test_unknown_stair_evidence_requires_confirmation_not_pass`；再跑第 7.3 节 | 报告为 `NEEDS_CONFIRMATION`，首条结果保留 `route-stable-001`；绝不为 PASS | `Critical` |

### 6.4 范围、回归与交付证据

| ID | 前置 | 输入 | 命令 | 精确预期 | 失败严重度 |
| --- | --- | --- | --- | --- | --- |
| `QA-S01` | 目标 commit 已冻结 | `$analysisCommit..$targetCommit` | 第 9.1 节全部范围命令 | 变更路径是白名单子集且计划产物齐全；冻结契约无 diff；禁飞区无改动 | `Important` |
| `QA-S02` | 四个生产文件可审查 | budget/adapter/import 与危险表达式扫描 | 第 9.3 节 | 无 `amount or 0`、`totalCostCents`、Provider/I/O/evaluator 调用、新依赖、secret | `Critical` |
| `QA-E01` | 实现提交齐全 | 缓存快照与测试文件 | 第 9.2 节 | JSON 精确、可独立重算、无敏感字段；所有计划测试文件存在 | `Important` |
| `QA-E02` | 定向测试可收集 | 五个 T006/T009 测试文件 | 第 8.1 节 | 至少 42 个用例全部通过；0 skip/xfail/deselect/collection error | `Important` |
| `QA-E03` | 定向通过 | 仓库全部 pytest | 第 8.2 节 | 至少 152 passed；0 failed/error/skip/xfail/deselect | `Important` |
| `QA-E04` | 所有行为与范围门禁通过 | commit 列表、状态、实现 RED/GREEN 材料 | 第 9.4 节 | HEAD 等于交接 SHA；工作树干净；实现证据可追溯；`PR: pending external push/creation` 直至真实 PR 存在 | `Important` |

## 7. 独立黑盒预言机

以下探针不 import 实现测试 helper，不读取实现窗口的 expected 常量。它们只消费冻结的公开契约并自行构造输入。

### 7.1 缓存、快照、价格双向不变量探针

```powershell
@'
from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.application.amap_service import AmapLocationService
from app.core.errors import AppError
from app.domain.models import PriceFact, Provenance, SourceStatus
from app.infrastructure.cache import SqliteProviderCache
from app.schemas.trip import CityContext, GeoPoint, ProviderConfig


def city(code: str, name: str, longitude: float, latitude: float) -> CityContext:
    return CityContext(
        country_code="CN",
        city_code=code,
        city_name=name,
        center=GeoPoint(longitude=longitude, latitude=latitude),
        provider_config=ProviderConfig(provider="AMAP", coordinate_system="GCJ02"),
    )


def payload(*, provider_city: str, ad_code: str, place_id: str, cost: Any = ""):
    return {
        "status": "1",
        "count": "1",
        "pois": [{
            "id": place_id,
            "name": "城市博物馆",
            "address": "测试路 1 号",
            "location": "116.397499,39.908722",
            "citycode": provider_city,
            "adcode": ad_code,
            "type": "风景名胜",
            "tel": [],
            "biz_ext": {"rating": "4.8", "cost": cost},
        }],
    }


class Client:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.city_codes = []

    async def search_places(self, **kwargs):
        self.city_codes.append(kwargs["city_code"])
        if self.error is not None:
            raise self.error
        return self.result


def service(root: Path, client: Client) -> AmapLocationService:
    return AmapLocationService(
        client=client,
        cache=SqliteProviderCache(root / "cache.sqlite3"),
        place_ttl_seconds=86400,
        route_ttl_seconds=1800,
    )


def canonical_hash(parameters: dict[str, Any]) -> str:
    canonical = json.dumps(
        parameters,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def main() -> None:
    beijing = city("110000", "北京市", 116.397499, 39.908722)
    shanghai = city("310000", "上海市", 121.473701, 31.230416)
    query = {"keywords": "城市博物馆", "types": [], "page": 1, "page_size": 20}

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        beijing_client = Client(payload(
            provider_city="010", ad_code="110101", place_id="same-name-beijing"
        ))
        shanghai_client = Client(payload(
            provider_city="021", ad_code="310101", place_id="same-name-shanghai"
        ))
        await service(root, beijing_client).search_places(beijing, **query)
        await service(root, shanghai_client).search_places(shanghai, **query)
        assert beijing_client.city_codes == ["110000"]
        assert shanghai_client.city_codes == ["310000"]

        failure = AppError("PROVIDER_TIMEOUT", "timeout", 503, True)
        offline_client = Client(error=failure)
        offline = service(root, offline_client)
        bj = await offline.search_places(beijing, **query)
        sh = await offline.search_places(shanghai, **query)
        assert offline_client.city_codes == ["110000", "310000"]
        assert (bj.cityCode, bj.places[0].placeId, bj.places[0].adCode) == (
            "110000", "same-name-beijing", "110101"
        )
        assert (sh.cityCode, sh.places[0].placeId, sh.places[0].adCode) == (
            "310000", "same-name-shanghai", "310101"
        )
        assert bj.provenance.sourceStatus is SourceStatus.VERIFIED_CACHE
        assert sh.provenance.sourceStatus is SourceStatus.VERIFIED_CACHE

        with closing(sqlite3.connect(root / "cache.sqlite3")) as connection:
            rows = connection.execute(
                "SELECT provider,operation,city_code,request_hash "
                "FROM provider_cache WHERE operation='place_search' ORDER BY city_code"
            ).fetchall()
        expected = [
            {
                "provider": "AMAP",
                "operation": "place_search",
                "cityCode": "110000",
                "requestHash": "2e0661f0a04ac1e591a39979ea61f5ce3f0c0a5ec9ab7536492d0710b2eec9c5",
            },
            {
                "provider": "AMAP",
                "operation": "place_search",
                "cityCode": "310000",
                "requestHash": "49e5ec5dfe9a06e4ebaeaf58c872d64bc95f564a8b547f1e2bacb82e4e127e2d",
            },
        ]
        actual = [
            {"provider": r[0], "operation": r[1], "cityCode": r[2], "requestHash": r[3]}
            for r in rows
        ]
        assert actual == expected
        for item in expected:
            params = {
                "cityCode": item["cityCode"],
                "keywords": "城市博物馆",
                "types": [],
                "page": 1,
                "pageSize": 20,
            }
            assert canonical_hash(params) == item["requestHash"]
        snapshot = json.loads(
            Path("tests/snapshots/s1_t006_cache_keys.json").read_text(encoding="utf-8")
        )
        assert snapshot == expected
        assert set().union(*(row.keys() for row in snapshot)) == {
            "provider", "operation", "cityCode", "requestHash"
        }

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        await service(root, Client(payload(
            provider_city="010", ad_code="110101", place_id="beijing-only"
        ))).search_places(beijing, **query)
        timeout = AppError("PROVIDER_TIMEOUT", "timeout", 503, True)
        try:
            await service(root, Client(error=timeout)).search_places(shanghai, **query)
        except AppError as exc:
            assert exc is timeout
            assert exc.code == "PROVIDER_TIMEOUT"
        else:
            raise AssertionError("cross-city cache fallback escaped")

    invalid_costs = ["", [], "not-a-price", "-1", "NaN", "Infinity", "-Infinity"]
    for index, cost in enumerate(invalid_costs):
        with tempfile.TemporaryDirectory() as directory:
            result = await service(Path(directory), Client(payload(
                provider_city="010", ad_code="110101", place_id=f"price-{index}", cost=cost
            ))).search_places(beijing, **query)
            fact = result.places[0].priceReference
            assert fact.amountCents is None
            assert fact.provenance.sourceStatus is SourceStatus.UNKNOWN

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        await service(root, Client(payload(
            provider_city="010", ad_code="110101", place_id="cached-unknown", cost=""
        ))).search_places(beijing, **query)
        cached = await service(root, Client(error=AppError(
            "PROVIDER_TIMEOUT", "timeout", 503, True
        ))).search_places(beijing, **query)
        price = cached.places[0].priceReference
        assert cached.provenance.sourceStatus is SourceStatus.VERIFIED_CACHE
        assert price.amountCents is None
        assert price.provenance.sourceStatus is SourceStatus.UNKNOWN
        assert price.provenance.fetchedAt == cached.provenance.fetchedAt
        assert price.provenance.isStale == cached.provenance.isStale

    now = datetime(2026, 8, 25, 8, 0, tzinfo=UTC)
    online = Provenance(sourceStatus=SourceStatus.ONLINE, fetchedAt=now)
    unknown = Provenance(sourceStatus=SourceStatus.UNKNOWN, fetchedAt=now)
    assert PriceFact(amountCents=0, kind="FREE", provenance=online).amountCents == 0
    assert PriceFact(amountCents=None, kind="ADMISSION", provenance=unknown).amountCents is None
    for amount, provenance in ((None, online), (0, unknown), (100, unknown)):
        try:
            PriceFact(amountCents=amount, kind="ADMISSION", provenance=provenance)
        except ValidationError:
            pass
        else:
            raise AssertionError((amount, provenance.sourceStatus))


asyncio.run(main())
print("s1-t006-cache-price-probe-ok")
'@ | & $python -
```

唯一通过标志是 exit code 0 且打印 `s1-t006-cache-price-probe-ok`。

### 7.2 预算预言机

```powershell
@'
from datetime import UTC, datetime

from app.domain.budget import BudgetLine, BudgetStatus, summarize_budget
from app.domain.models import PriceFact, Provenance, SourceStatus

NOW = datetime(2026, 8, 25, 8, 0, tzinfo=UTC)

def line(reference_id, amount, status, kind):
    return BudgetLine(
        referenceId=reference_id,
        priceFact=PriceFact(
            amountCents=amount,
            kind=kind,
            provenance=Provenance(sourceStatus=status, fetchedAt=NOW),
        ),
    )

known = summarize_budget([
    line("museum", 1250, SourceStatus.ONLINE, "ADMISSION"),
    line("walk", 0, SourceStatus.ONLINE, "FREE"),
])
assert known.model_dump() == {
    "knownSubtotalCents": 1250,
    "unknownAmountCount": 0,
    "status": BudgetStatus.COMPLETE,
    "warnings": [],
}
assert not hasattr(known, "totalCostCents")

mixed = summarize_budget([
    line("museum", 1250, SourceStatus.ONLINE, "ADMISSION"),
    line("restaurant", None, SourceStatus.UNKNOWN, "PER_CAPITA_REFERENCE"),
])
assert mixed.knownSubtotalCents == 1250
assert mixed.unknownAmountCount == 1
assert mixed.status is BudgetStatus.NEEDS_CONFIRMATION
assert [item.model_dump() for item in mixed.warnings] == [{
    "code": "UNKNOWN_PRICE",
    "referenceId": "restaurant",
    "kind": "PER_CAPITA_REFERENCE",
    "message": "价格未知，未计入已知金额小计",
}]

ordered = summarize_budget([
    line("route-b", None, SourceStatus.UNKNOWN, "TRANSIT_FARE"),
    line("place-a", None, SourceStatus.UNKNOWN, "ADMISSION"),
])
assert ordered.knownSubtotalCents == 0
assert ordered.unknownAmountCount == 2
assert ordered.status is BudgetStatus.NEEDS_CONFIRMATION
assert [item.referenceId for item in ordered.warnings] == ["route-b", "place-a"]
assert [item.kind for item in ordered.warnings] == ["TRANSIT_FARE", "ADMISSION"]
assert all(item.code == "UNKNOWN_PRICE" for item in ordered.warnings)
assert all(item.message == "价格未知，未计入已知金额小计" for item in ordered.warnings)

print("s1-t006-budget-probe-ok")
'@ | & $python -
```

唯一通过标志是 exit code 0 且打印 `s1-t006-budget-probe-ok`。

### 7.3 Route/T009 边界预言机

```powershell
@'
from datetime import UTC, datetime
from inspect import Parameter, signature

from app.application.route_risk_adapter import (
    RouteRiskAdapterError,
    route_snapshot_to_risk_input,
)
from app.domain.models import PriceFact, Provenance, Route, SourceStatus, TravelMode
from app.schemas.constraint import Constraint
from app.schemas.trip import GeoPoint
from app.services.route_risk import ValidationStatus, evaluate_route_risk
from app.services.route_risk.models import WalkType

NOW = datetime(2026, 8, 25, 8, 0, tzinfo=UTC)
ORIGIN = GeoPoint(longitude=116.397499, latitude=39.908722)
DESTINATION = GeoPoint(longitude=116.481028, latitude=39.989643)

def route(
    *,
    route_id="route-stable-001",
    mode=TravelMode.TRANSIT,
    distance=8000,
    duration=2400,
    walking=600,
    transfers=2,
):
    provenance = Provenance(sourceStatus=SourceStatus.ONLINE, fetchedAt=NOW)
    return Route(
        routeId=route_id,
        mode=mode,
        origin=ORIGIN,
        destination=DESTINATION,
        distanceMeters=distance,
        durationSeconds=duration,
        walkingDistanceMeters=walking,
        transferCount=transfers,
        steps=[],
        priceReference=PriceFact(
            amountCents=500, kind="TRANSIT_FARE", provenance=provenance
        ),
        provenance=provenance,
    )

parameter = signature(route_snapshot_to_risk_input).parameters[
    "elapsed_since_rest_minutes"
]
assert parameter.kind is Parameter.KEYWORD_ONLY

source = route()
first = route_snapshot_to_risk_input(source, elapsed_since_rest_minutes=40)
second = route_snapshot_to_risk_input(source, elapsed_since_rest_minutes=40)
assert len(first.segments) == 1
segment = first.segments[0]
assert segment.route_segment == "route-stable-001"
assert segment.walking_distance_meters == 600
assert segment.cumulative_transfers == 2
assert segment.elapsed_since_rest_minutes == 40
assert segment.walk_types == (WalkType.UNKNOWN,)
assert first.model_dump_json(by_alias=True) == second.model_dump_json(by_alias=True)
assert '"routeSegment":"route-stable-001"' in first.model_dump_json(by_alias=True)

for mode, expected_walk, expected_type in (
    (TravelMode.WALKING, 850, WalkType.UNKNOWN),
    (TravelMode.DRIVING, 0, WalkType.LEVEL),
    (TravelMode.BICYCLING, 0, WalkType.LEVEL),
):
    mapped = route_snapshot_to_risk_input(
        route(
            mode=mode,
            distance=850,
            duration=61,
            walking=None,
            transfers=None,
        ),
        elapsed_since_rest_minutes=2,
    ).segments[0]
    assert mapped.walking_distance_meters == expected_walk
    assert mapped.cumulative_transfers == 0
    assert mapped.elapsed_since_rest_minutes == 2
    assert mapped.walk_types == (expected_type,)

def expect_error(source, elapsed, field):
    try:
        route_snapshot_to_risk_input(
            source, elapsed_since_rest_minutes=elapsed
        )
    except RouteRiskAdapterError as exc:
        assert exc.code == "ROUTE_RISK_INPUT_INVALID"
        assert exc.route_segment == source.routeId
        assert exc.field == field
    else:
        raise AssertionError((source.routeId, elapsed, field))

expect_error(route(walking=None), 40, "walkingDistanceMeters")
expect_error(route(transfers=None), 40, "transferCount")
expect_error(route(), 39, "elapsedSinceRestMinutes")
expect_error(route(), True, "elapsedSinceRestMinutes")
expect_error(route(), 40.0, "elapsedSinceRestMinutes")
expect_error(route(route_id="r" * 121), 40, "routeId")
assert route_snapshot_to_risk_input(
    route(route_id="r" * 120), elapsed_since_rest_minutes=40
).segments[0].route_segment == "r" * 120

try:
    route_snapshot_to_risk_input(route(), 40)
except TypeError:
    pass
else:
    raise AssertionError("elapsed_since_rest_minutes accepted positionally")

constraint = Constraint(
    field="avoidStairs",
    operator="EQ",
    value=True,
    scope="ROUTE_SEGMENT",
    hardness="HARD",
)
report = evaluate_route_risk(first, [constraint])
assert report.status is ValidationStatus.NEEDS_CONFIRMATION
assert report.results[0].route_segment == "route-stable-001"
assert report.results[0].observed == {"walkTypes": ["UNKNOWN"]}

print("s1-t006-route-t009-probe-ok")
'@ | & $python -
```

唯一通过标志是 exit code 0 且打印 `s1-t006-route-t009-probe-ok`。

## 8. 最终自动化命令

### 8.1 目标测试

先收集再执行，防止测试被删除、改成不可收集或被选择器静默排除：

```powershell
& $python -m pytest -p no:cacheprovider --collect-only -q tests/test_place_service.py tests/test_price_fact.py tests/test_budget.py tests/test_route_risk_adapter.py backend/tests/test_route_risk.py
& $python -m pytest -p no:cacheprovider -ra -q tests/test_place_service.py tests/test_price_fact.py tests/test_budget.py tests/test_route_risk_adapter.py backend/tests/test_route_risk.py
```

冻结计划预计目标集合至少 `42` 个 pytest case：原地点 4、新 T006 25、既有 T009 13。实际数量可因经审查的新测试增加，但不得低于 42；`failed/error/skipped/xfailed/xpassed/deselected` 均须为 0。

### 8.2 全量 pytest

```powershell
& $python -m pytest -p no:cacheprovider --collect-only -q
& $python -m pytest -p no:cacheprovider -ra -q
```

冻结生产基线为 `127 passed`，实施计划新增 25 个参数展开后的 case，因此全量不得低于 `152 passed`。新增测试可使数字更高；减少、skip、xfail、deselect、collection error 或任何失败均为 `Important`。

## 9. 快照、diff、范围与交付证据

### 9.1 路径白名单与冻结 diff

```powershell
$allowed = @(
    'app/application/amap_service.py',
    'app/application/route_risk_adapter.py',
    'app/domain/budget.py',
    'app/domain/models.py',
    'docs/testing/2026-08-25-s1-t006-independent-acceptance.md',
    'tests/snapshots/s1_t006_cache_keys.json',
    'tests/test_budget.py',
    'tests/test_place_service.py',
    'tests/test_price_fact.py',
    'tests/test_route_risk_adapter.py'
)
$changed = @(git diff --name-only "$analysisCommit..$targetCommit")
$unexpected = @($changed | Where-Object { $_ -notin $allowed })
if ($unexpected.Count -ne 0) { throw "out-of-scope paths: $unexpected" }

$missingChanged = @($allowed | Where-Object { $_ -notin $changed })
if ($missingChanged.Count -ne 0) { throw "missing planned changes: $missingChanged" }

git diff --check "$analysisCommit..$targetCommit"
git diff --exit-code $qaDocumentCommit $targetCommit -- `
    docs/testing/2026-08-25-s1-t006-independent-acceptance.md
git diff --exit-code $analysisCommit $targetCommit -- `
    app/infrastructure/cache.py `
    backend/app/schemas/constraint.py `
    backend/app/schemas/trip.py `
    backend/app/services/route_risk/__init__.py `
    backend/app/services/route_risk/evaluator.py `
    backend/app/services/route_risk/models.py `
    backend/tests/test_route_risk.py `
    tests/conftest.py
```

门槛：白名单脚本不抛错，计划产物存在，`git diff --check` 无输出，冻结 diff 无输出且 exit code 0。

### 9.2 缓存键快照的独立结构检查

```powershell
& $python -c "import json,pathlib; p=pathlib.Path('tests/snapshots/s1_t006_cache_keys.json'); d=json.loads(p.read_text(encoding='utf-8')); assert len(d)==2; assert [x['cityCode'] for x in d]==['110000','310000']; assert all(set(x)=={'provider','operation','cityCode','requestHash'} for x in d); assert [x['requestHash'] for x in d]==['2e0661f0a04ac1e591a39979ea61f5ce3f0c0a5ec9ab7536492d0710b2eec9c5','49e5ec5dfe9a06e4ebaeaf58c872d64bc95f564a8b547f1e2bacb82e4e127e2d']; print('s1-t006-snapshot-ok')"
```

该命令通过后仍须以第 7.1 节根据 canonical parameters 独立重算 hash；“JSON 可解析”不等于快照正确。

### 9.3 禁止表达式、依赖与密钥扫描

```powershell
$budgetHits = @(rg -n 'amount_cents\s+or\s+0|sum\([^\n]*or\s+0|totalCostCents' app/domain/budget.py)
if ($budgetHits.Count -ne 0) { throw "unsafe budget expression: $budgetHits" }

$adapterHits = @(rg -n 'Amap|httpx|requests|openai|datetime\.now|date\.today|random|time\.time|evaluate_route_risk' app/application/route_risk_adapter.py)
if ($adapterHits.Count -ne 0) { throw "adapter boundary violation: $adapterHits" }

$secretHits = @(
    git diff "$analysisCommit..$targetCommit" -- app tests |
        Select-String -Pattern 'AMAP_WEB_SERVICE_KEY\s*=|api[_-]?key\s*=|sk-[A-Za-z0-9_-]+' -CaseSensitive:$false
)
if ($secretHits.Count -ne 0) { throw "possible secret leakage: $secretHits" }
```

随后人工审查 import、控制流与序列化；正则零命中不能单独证明纯函数或无密钥。

### 9.4 本地交付元数据

```powershell
git log --oneline "$analysisCommit..$targetCommit"
git rev-parse HEAD
git status --short --branch
```

最终交付报告必须包含：

- 目标 commit 及实现小步 commit 列表；
- 三个独立探针标志；
- 目标/全量 pytest 的 collected、passed、failed、error、skip、xfail、deselect 和耗时；
- 缓存快照路径与独立 hash 重算结果；
- `Route` 是当前 RouteSnapshot 等价来源、`routeId` 原样成为 `routeSegment` 的明确结论；
- 冻结 diff、变更白名单、禁飞区和 secret scan 结果；
- 实现阶段每个 slice 的真实 RED 失败与对应 GREEN 命令；
- 缺陷清单、修复 commit 和复验结果；
- 在真实 PR 尚未外部创建时精确写 `PR: pending external push/creation`，不得伪造链接或编号。

## 10. 最小白盒静态审查

黑盒和 pytest 通过后，再检查目标 commit 的新增/修改生产代码并记录精确 `path:line`：

### 10.1 `PriceFact` 与 Provider 价格

- `PriceFact` 实现 `(amountCents is None) == (sourceStatus is UNKNOWN)`，不只检查一个方向。
- `amountCents=0` 仅在来源非 UNKNOWN 时合法；校验失败抛错，不自动改 amount/status。
- `_yuan_to_cents` 在比较、乘法和 quantize 前显式检查 `Decimal.is_finite()`；缺失、非字符串、非法、负数、NaN、正负 Infinity 均返回 unknown。
- 缓存恢复时集合 provenance 与 price provenance 分层保留；集合 `VERIFIED_CACHE` 不覆盖价格 `UNKNOWN`。

### 10.2 预算

- 公开字段只有 `knownSubtotalCents`，没有 `totalCostCents` 或暗示完整总额的别名。
- unknown 分支先产生一条 warning 再 `continue`，不进入求和表达式；未使用 `or 0`。
- warning 数量等于 unknown 行数量，顺序严格等于输入顺序，保留 `referenceId/kind`。
- 状态只由 warnings 是否为空决定：有任意 unknown 即 `NEEDS_CONFIRMATION`。

### 10.3 路线适配

- 签名为 `route_snapshot_to_risk_input(route_snapshot: Route, *, elapsed_since_rest_minutes: int)`；elapsed 只能由调用方显式提供。
- `routeId` 不编号、不 hash、不截断，原样写入 `routeSegment`；超过 120 字符 fail-closed。
- TRANSIT 缺步行或换乘事实分别定位到 `walkingDistanceMeters/transferCount`；不填 0。
- elapsed 使用 `ceil(durationSeconds/60)` 下界，拒绝 bool、float 和不足值，不把单段时长冒充累计休息上下文。
- WALKING/TRANSIT 在缺结构化阶梯证据时使用 `UNKNOWN`；DRIVING/BICYCLING 使用 0/0/`LEVEL`。
- adapter 不访问 Provider、网络、文件、数据库、环境、时钟或随机源，也不调用 T009 evaluator。

### 10.4 测试不可弱化

- 新增参数化测试确实展开缺失、列表、非法、负数、NaN、正负 Infinity；没有把异常吞掉后只断言“非空”。
- `0+ONLINE` 与 `0+UNKNOWN` 分别有正反断言；`None+ONLINE` 也被拒绝。
- 缓存测试先完成两次在线写和两次离线读，再比较快照；不能只测试数据库行。
- T009 集成使用真实 `evaluate_route_risk` 和硬 `avoidStairs` Constraint，不 mock evaluator。
- 未删除、skip、xfail、改名或放宽既有地点与 T009 测试。

## 11. 缺陷反馈格式与复验循环

每个缺陷发回编排窗口时必须包含以下字段，不得只说“测试失败”：

```text
缺陷 ID：按 S1-T006-QA-001 起连续编号
严重级别：Critical / Important / Minor
目标 commit：实际执行的 40 位 SHA
环境：Windows、Python、pytest、PYTHONPATH
对应追溯：QA ID、PBI-02-A、AC-02-A、S1-T006
最小复现命令：可直接复制执行的完整命令
前置与最小输入：城市、价格、BudgetLine 或 Route 的精确值
期望：本规程中的字段、状态、错误 code、顺序或字节结果
实际：首个失败、完整异常摘要与 exit code
文件与行号：静态审查时必须精确到 path:line
影响：串城、错误预算、fail-open、回归或交付风险
精确修复建议：指出应收紧的边界和不得改变的相邻契约
修复 commit：代码窗口回传的 40 位 SHA
复验：在修复 commit 上重新执行原复现、所属探针、目标测试和全量 pytest
```

修复建议必须最小且可验证，例如“在 `_yuan_to_cents` 的 Decimal 比较前增加 `not amount.is_finite()` 守卫并保留其他转换规则”，不能写成“处理边界情况”。复验必须使用新目标 commit；原失败命令通过后还要重跑所属独立探针、目标集合、全量 pytest 和范围检查。循环直到无开放 `Critical/Important`，再把结果发回实现分析窗口终审。

## 12. PASS / FAIL 门槛

只有以下条件全部成立，独立 QA 才能给技术验收 `PASS`：

1. 分支、目标 commit、两级祖先和干净工作树通过第 5 节。
2. `QA-C01`—`QA-R05` 全部满足精确预期；三个独立探针均 exit code 0 并打印唯一标志。
3. 目标测试至少 42 passed、全量至少 152 passed，且无 failed/error/skip/xfail/xpass/deselect。
4. 缓存快照恰含两行四字段，两个 hash 由 canonical parameters 独立重算一致，无 payload、Key 或时间戳。
5. PriceFact 双向不变量、unknown/known-zero 区分、逐项预算 warning、稳定顺序和 `knownSubtotalCents` 全部成立。
6. Route 映射、显式 elapsed、精确 fail-closed field、稳定 JSON 和 T009 `UNKNOWN → NEEDS_CONFIRMATION` 全部成立。
7. 变更路径为白名单子集且计划产物齐全；冻结文件无 diff；`git diff --check`、禁止表达式、adapter 边界和 secret scan 全部通过。
8. 最小白盒审查没有开放问题；所有 `Critical/Important` 均有修复 commit 与新鲜复验闭环。
9. 交付元数据真实；PR 未创建时保持 external pending，不把本地技术 PASS 冒充工作簿的外部 PR 交付已完成。

任一项不满足为 `FAIL`；尚未收到实现目标 commit 或尚未执行证据时保持 `PENDING_IMPLEMENTATION`。不允许 `CONDITIONAL PASS`，也不允许用实现者自测、旧日志、预计 CI 结果或单一 pytest 集合代替独立验收。

## 13. 分析规格差异记录

1. 工作簿 T006 行只显式写缓存、来源归一化和 unknown 预算，没有逐字段写 Route→T009 适配；分析规格根据已存在的 T006/T007→T009 交接把纯 adapter 纳入 T006。两者存在范围表述差异，但有仓库交接证据且不修改 T009/T010/T011，因此本规程保留 `QA-R01`—`QA-R05`，不把它解释为规划器授权。
2. 工作簿与设计的交付证据含 PR；当前分支指令禁止 push/merge。实施计划已把真实 PR 明确留给外部创建。本规程区分“本地技术验收 PASS”和“外部 PR 交付完成”，在真实 PR 出现前不得声称后者完成。
3. 除上述范围/交付边界外，工作簿 AC、设计规格、实施计划、现存缓存契约和 T009 UNKNOWN 行为未发现相互矛盾；最终执行若出现代码与本规程不一致，以工作簿 Must AC、冻结生产契约和 fail-closed 原则判定，不为实现放宽预期。

## 14. 当前执行记录

本规程冻结时仅完成文档设计与静态来源核对，未执行第 7—9 节最终验收，也未检查任何实现窗口结果。当前结论为 `PENDING_IMPLEMENTATION`；收到代码完成 commit 后，独立 QA 才在本节追加实际命令输出、缺陷循环和最终结论。
