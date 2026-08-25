# S1-T006 独立验收结果报告

## 1. 结论

- 技术验收：`PASS`
- 实现待验提交：`f6c87a3e481b868e13c2e094915162db1b5ac32b`
- QA-001 夹具修复提交：`9efc4809dcdf5039b2ad61c0bb9a43c162456201`
- 结果报告提交：以提交本文件后最终 handoff 的 `git rev-parse HEAD` 为准
- 分支：`czy-S1-T006`
- PR：`pending external push/creation`
- 开放缺陷：无 `Critical`、`Important` 或 `Minor`

本结论来自独立 QA 的新鲜执行结果，不使用实现窗口的 pytest 结果替代。未切换或修改 `main`，未 push、未 merge，也未申请提升权限。

## 2. 环境与预检

- 平台：Windows；所有命令通过 `cmd.exe`、`login=false` 执行。
- Python：`3.12.13`
- pytest：`8.4.2`
- 依赖探针：`s1-t006-deps-ok`
- 实现交接时分支：`czy-S1-T006`
- 实现交接时 HEAD：`f6c87a3e481b868e13c2e094915162db1b5ac32b`
- `merge-base(984f490..., f6c87a3...)`：`984f49085125c0a03229cfde99b45cf00ce1082d`
- `merge-base(92bcff6..., f6c87a3...)`：`92bcff6a28b359b694617a5d4d1d030c8c8c306b`
- 预检工作区：无 tracked/untracked 变更。

实现提交序列：

1. `04d059fcf5203bdb6311dda95c3e2dac33f7ab8a` — cache evidence
2. `b674936ed1462913759291b1fa10578221c363be` — price invariant
3. `34267827c97a0b3ba20f5398214b28ecfe1c7880` — budget aggregation
4. `984f49085125c0a03229cfde99b45cf00ce1082d` — route adapter
5. `f6c87a3e481b868e13c2e094915162db1b5ac32b` — deterministic SQLite close

## 3. QA-001 关闭证据

### 3.1 生产修复审查

`984f490..f6c87a3` 仅修改：

- `app/infrastructure/cache.py`
- `tests/test_place_service.py`

`SqliteProviderCache._initialize/put/get` 均使用 `contextlib.closing` 包裹连接，并在关闭前保留原事务上下文；退出顺序为先提交或回滚，再确定性关闭。SQLite schema、四元缓存键、payload、TTL 与请求 hash 行为未改变。

新增回归 `test_sqlite_provider_cache_closes_connections_before_directory_cleanup` 在真实 SQLite 初始化、写入和读取后立即执行 `shutil.rmtree(cache_root)`。独立定向结果：`1 passed in 0.07s`。

扫描 `app/infrastructure/cache.py` 和 `tests/test_place_service.py`：`gc.collect`、`ignore_cleanup_errors` 均为零命中。

### 3.2 冻结规程夹具修复

QA 夹具只发生两个资源生命周期变化：

1. 导入 `from contextlib import closing`；
2. 将 QA 审计读取改为 `with closing(sqlite3.connect(...)) as connection`。

业务输入、断言、城市码、hash、错误、输出标志、严重度和测试门槛均未改变。夹具修复提交只包含 `docs/testing/2026-08-25-s1-t006-independent-acceptance.md`，提交统计为 2 行新增、1 行删除。

QA-001 原始 RED 是 Windows 在冻结缓存探针首个临时目录退出时对 `cache.sqlite3` 抛 `WinError 32`。生产修复与显式关闭 QA 审计连接后，未使用 GC、未忽略清理错误即可得到 GREEN 标志。

## 4. 三个独立黑盒探针

三个脚本均从提交后的冻结规程重新提取，不 import 实现测试 helper：

| 探针 | Exit code | 唯一标志 | 耗时 |
| --- | ---: | --- | ---: |
| 缓存、快照、价格不变量 | 0 | `s1-t006-cache-price-probe-ok` | 0.636s |
| 预算 | 0 | `s1-t006-budget-probe-ok` | 0.141s |
| Route/T009 | 0 | `s1-t006-route-t009-probe-ok` | 0.173s |

缓存探针确认两城同名 POI 精确隔离、在线失败只读匹配 cityCode、缓存键快照精确、非法与非有限价格保持 unknown、缓存恢复不覆盖价格 UNKNOWN，以及 `0+ONLINE`/`None+UNKNOWN` 双向不变量。

预算探针确认 `knownSubtotalCents` 只累计已知项，unknown 逐项产生 `UNKNOWN_PRICE`、不进入算术、稳定保持输入顺序，并把状态置为 `NEEDS_CONFIRMATION`。

Route 探针确认 `Route` 是当前 RouteSnapshot 等价来源，`routeId` 原样成为 `routeSegment`；elapsed 必须显式且 fail-closed；未知阶梯证据进入真实 T009 后得到 `NEEDS_CONFIRMATION`，不可能得到 PASS。

## 5. pytest 证据

所有 pytest 命令均带 `-p no:cacheprovider`，并把独立 `--basetemp` 放在 `C:\Users\lenovo\Desktop\实训\.codex-pytest-tmp` 下。

### 5.1 目标集合

测试文件：

- `tests/test_place_service.py`
- `tests/test_price_fact.py`
- `tests/test_budget.py`
- `tests/test_route_risk_adapter.py`
- `backend/tests/test_route_risk.py`

结果：

- 收集：`43 tests collected in 0.07s`
- 执行：`43 passed in 0.64s`
- failed/error/skipped/xfailed/xpassed/deselected：均为 `0`

### 5.2 全量集合

- 收集：`153 tests collected in 0.40s`
- 执行：`153 passed in 2.85s`
- failed/error/skipped/xfailed/xpassed/deselected：均为 `0`

## 6. 快照、范围和静态审查

- `tests/snapshots/s1_t006_cache_keys.json` 恰为两行四字段。
- 城市顺序：`110000`、`310000`。
- 两个 `requestHash` 已从冻结 canonical parameters 独立重算并匹配；输出 `s1-t006-snapshot-ok`。
- 快照不含 payload、Provider Key 或时间戳。
- `git diff --check e12dc30..9efc480`：exit 0，无输出。
- `f6c87a3..9efc480`：只修改冻结规程的 QA 夹具。
- `e12dc30..f6c87a3` 的路径为原计划路径加本轮明确授权的 `app/infrastructure/cache.py`；新增修复提交本身仅涉及缓存实现与对应测试。
- 当前委派对 QA-001 的范围例外优先于原冻结规程中“缓存实现零 diff”的旧门禁；该例外未扩张到 SQLite schema、T009、PlanVersion、UI、HTTP 或规划器。
- T009 DTO/evaluator、约束/行程契约、既有 T009 测试及 `tests/conftest.py` 均为零 diff。
- budget 危险表达式扫描：无 `amount or 0`、`totalCostCents` 或 unknown 求和。
- adapter 边界扫描：无 Provider、网络、文件、数据库、环境、时钟、随机源或 evaluator 调用。
- secret scan：`AMAP_WEB_SERVICE_KEY` 赋值、`api[_-]?key` 赋值与 `sk-*` 均为零命中。
- 新增依赖：无。

白盒复核未发现断言弱化、skip/xfail、跨城回退、unknown→0、routeId 改写、fail-open 或敏感信息问题。

## 7. 追溯矩阵结论

| 范围 | QA 项 | 结果 |
| --- | --- | --- |
| 两城缓存、精确键、在线失败 | QA-C01—C03 | PASS |
| PriceFact 与缓存价格 provenance | QA-P01—P03 | PASS |
| 已知小计、unknown warning、稳定顺序 | QA-B01—B03 | PASS |
| Route 映射、显式 elapsed、fail-closed、T009 | QA-R01—R05 | PASS |
| 范围、快照、目标/全量、交付元数据 | QA-S01—S02、QA-E01—E04 | PASS；PR 仍待外部创建 |

工作簿 Must AC 所要求的 cityCode 隔离、来源归一化、unknown 不按 0 计预算、warning 与已知小计均已满足。分析规格额外要求的纯 Route→T009 适配也满足，且未越界修改 T009 或规划器。

## 8. 最终判定

QA-001 已由生产修复提交 `f6c87a3e481b868e13c2e094915162db1b5ac32b` 与 QA 夹具提交 `9efc4809dcdf5039b2ad61c0bb9a43c162456201` 共同关闭。三个独立探针、目标 43、全量 153、快照、范围、禁飞区和静态审查全部满足当前授权后的门槛。

最终技术验收：`PASS`。
