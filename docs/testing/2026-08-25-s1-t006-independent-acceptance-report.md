# S1-T006 独立验收结果报告

## 1. 结论

- 技术验收：`PASS`（第二轮修复后重新验收）
- 当前实现待验提交：`5694a7fdbe35a70699bef14779dc33ef27c63421`
- 首轮实现待验提交：`f6c87a3e481b868e13c2e094915162db1b5ac32b`
- QA-001 夹具修复提交：`9efc4809dcdf5039b2ad61c0bb9a43c162456201`
- 首轮验收报告提交：`fd291e3a4065e59a631ace2dd414a50192207571`
- 第二轮 QA 规程提交：`6df9ff0e3f29be200d1e7d3bdd0acef212fa9db3`
- 第二轮结果报告提交：以提交本次更新后最终 handoff 的 `git rev-parse HEAD` 为准
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

## 8. 首轮判定与终审重开

QA-001 由生产修复提交 `f6c87a3e481b868e13c2e094915162db1b5ac32b` 与 QA 夹具提交 `9efc4809dcdf5039b2ad61c0bb9a43c162456201` 共同关闭。独立 QA 随后在 `fd291e3a4065e59a631ace2dd414a50192207571` 给出首轮 `PASS`。

终审在首轮 PASS 后发现一个 `Important` finding：`_yuan_to_cents("1e10000")` 会在 `quantize` 泄漏 `InvalidOperation`；扩展检查同时发现 `"1e999999"` 会在乘法阶段泄漏 Decimal `Overflow`。因此首轮 PASS 被重新打开，不再作为最终结论。

## 9. 第二轮价格 finding 与生产修复

### 9.1 独立复现

独立 QA 直接执行旧算式并确认：

- `1e10000`：`InvalidOperation`
- `1e999999`：`Overflow`

该行为违反“Provider 非法或不可表示价格不得泄漏 Decimal 异常，必须归一为 `None + UNKNOWN`”的价格边界，严重度为 `Important`。

### 9.2 修复审查

修复提交：`5694a7fdbe35a70699bef14779dc33ef27c63421`，`fd291e3..5694a7f` 只修改：

- `app/application/amap_service.py`
- `tests/test_place_service.py`

`_yuan_to_cents` 的新 `try/except DecimalException` 只包住 `amount * 100`、`quantize` 与 `int` 转换边界；解析仍只捕获 `InvalidOperation`，有限性与负数判断仍在算术块之前。代码未捕获 `Exception` 或 `BaseException`，因此普通编程错误不会被吞掉。

独立直接输入结果：

| 输入 | 结果 |
| --- | ---: |
| `1e10000` | `None` |
| `1e999999` | `None` |
| `-1e10000` | `None` |
| `0` | `0` |
| `12.30` | `1230` |
| `1e20` | `10000000000000000000000` |

实现测试把三个超大边界加入 unknown 参数集，并把合法价格测试扩展为 0、12.30 与 1e20；既有价格、缓存与来源断言未删除或弱化。

## 10. 第二轮冻结规程与黑盒探针

QA 规程提交 `6df9ff0e3f29be200d1e7d3bdd0acef212fa9db3` 只修改 `docs/testing/2026-08-25-s1-t006-independent-acceptance.md`：

- 在原缓存/价格探针的 invalid 集合追加 `1e10000`、`1e999999`、`-1e10000`；
- 追加 Provider 级合法回归 `0→0`、`12.30→1230`、`1e20→10^22`；
- 将目标/全量门槛分别上调到 48/158；
- 未改变既有城市、缓存 hash、错误、预算、Route/T009 断言或输出标志。

从提交后的规程重新提取三个脚本，结果为：

| 探针 | Exit code | 唯一标志 | 耗时 |
| --- | ---: | --- | ---: |
| 缓存、快照、价格不变量 | 0 | `s1-t006-cache-price-probe-ok` | 0.851s |
| 预算 | 0 | `s1-t006-budget-probe-ok` | 0.158s |
| Route/T009 | 0 | `s1-t006-route-t009-probe-ok` | 0.175s |

## 11. 第二轮 pytest 证据

所有命令继续使用 `-p no:cacheprovider`，并把独立 `--basetemp` 放在 `C:\Users\lenovo\Desktop\实训\.codex-pytest-tmp` 下。

| 集合 | 收集 | 执行 | 非通过状态 |
| --- | --- | --- | --- |
| 价格：`tests/test_place_service.py tests/test_price_fact.py` | `22 collected in 0.04s` | `22 passed in 0.69s` | 0 |
| T006/T009 目标集合 | `48 collected in 0.08s` | `48 passed in 0.76s` | 0 |
| 仓库全量 | `158 collected in 0.46s` | `158 passed in 3.16s` | 0 |

非通过状态包括 failed、error、skipped、xfailed、xpassed 与 deselected；三组均为 0。

## 12. 第二轮范围与门禁

- `git diff --check e12dc30..6df9ff0`：exit 0，无输出。
- `fd291e3..5694a7f`：仅价格转换实现与对应测试。
- `5694a7f..6df9ff0`：仅冻结 QA 规程扩展。
- `app/infrastructure/cache.py`、预算、Route adapter、PriceFact、T009 DTO/evaluator、约束/行程契约、既有 T009 测试与 `tests/conftest.py` 相对首轮最终 HEAD 均为零 diff。
- 缓存快照仍输出 `s1-t006-snapshot-ok`；两行四字段与 canonical hash 不变。
- budget 危险表达式与 adapter 边界扫描保持通过。
- secret scan 对 `AMAP_WEB_SERVICE_KEY`、`api[_-]?key` 与 `sk-*` 均为零命中。
- 工作区在规程提交后干净；未修改 `main`，未 push、未 merge。

## 13. 第二轮最终判定

终审发现的 Decimal 算术异常泄漏已由 `5694a7fdbe35a70699bef14779dc33ef27c63421` 修复，并由扩展后的独立探针、价格 22、目标 48、全量 158 与静态范围门禁新鲜复验闭环。

最终开放 finding：无 `Critical`、`Important` 或 `Minor`。

最终技术验收：`PASS`。
