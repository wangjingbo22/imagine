# S3-T005 / S3-T006 本地验收记录

## 验收来源

- 来源：`行知旅伴_V2.3_Sprint3收尾待办列表_含负责人.xlsx`
- 工作表：`Sprint3收尾待办`
- 范围：`A14:M15`
- S3-T005：北京、上海、成都完成 CityContext、关怀、地点/路线、唯一 V1、执行事件、V2 决策及回忆，并验证缓存隔离和来源完整。
- S3-T006：西安、杭州返回同城候选和路线；`cityCode` 进入请求与缓存键；`UNKNOWN`/`ESTIMATED` 不误判为实时或 0 元。

## 同步边界

- 本地分支：`zq-S2-NEW`
- 同步后的基线提交：`58d72a4`
- 同步方式：`git pull --ff-only origin zq-S2-NEW`
- 本轮仅修改本地工作区，没有 commit、push、merge 或其他远端写操作。
- 同步前已有的前端本地修改先暂存、同步后原样恢复，未纳入本轮城市验证修改。

## S3-T005 三城完整端到端验证

测试：`backend/tests/test_s2_t024_full_golden_path.py`

同一条生产 ASGI 路由和 SQLite 持久化链分别以三套城市上下文执行：

| 城市 | cityCode | 结果 |
| --- | --- | --- |
| 北京市 | `110000` | PASS |
| 上海市 | `310000` | PASS |
| 成都市 | `510100` | PASS |

每个城市都覆盖：六问理解、成员确认、`READY_TO_PLAN`、CityContext、同城地点、Provider FactRef 推荐、关怀限制下的步行路线、唯一 V1、到达证据、照片替换/删除、START/LATE/FATIGUE 执行事件、V2 预览与 ACCEPT、最终状态、MemoryTimeline，以及 SQLite 中 Trip/PlanVersion/事件/媒体的单一血缘。

测试：`backend/tests/test_s3_t005_t006_city_verification.py::test_s3_t005_three_city_cache_keys_are_isolated`

- 北京、上海、成都使用相同搜索参数写入三个独立的 `city_code + request_hash` 缓存键。
- 在线失败后分别命中各自的 `VERIFIED_CACHE` 数据，没有跨城串缓存。
- 三个缓存结果的地点 ID 和 `cityCode` 一一对应。

## S3-T006 西安、杭州在线烟测

运行时显式启用 `RUN_AMAP_LIVE_SMOKE=1`，使用本地已配置的高德 Web 服务 Key 访问真实高德接口；证据中不保存 Key 或原始敏感请求。

| 城市 | cityCode | 在线地点 | 步行路线 | 公交路线 | 关怀约束 | 请求/缓存城市隔离 |
| --- | --- | --- | --- | --- | --- | --- |
| 西安市 | `610100` | PASS | PASS | PASS | PASS | PASS |
| 杭州市 | `330100` | PASS | PASS | PASS | PASS | PASS |

关怀烟测将真实路线转换为 RouteRisk 输入并执行连续步行、换乘次数和避楼梯硬约束。高德路线没有提供电梯/坡道/楼梯等设施事实时，避楼梯规则返回 `NEEDS_CONFIRMATION`，没有把未知证据误判为 PASS。

价格语义同时验证：

- 缺失价格保持 `amountCents=null + sourceStatus=UNKNOWN`，不转换成 0 元。
- 高德出租车费用标记为 `TAXI_ESTIMATE + sourceStatus=ESTIMATED`，不标记为实时价格。
- 步行和骑行的明确免费事实仍可合法表示为 0 元，不与未知价格混淆。

## 执行结果

```text
专项离线与三城端到端：6 passed, 2 skipped
西安/杭州真实在线烟测：3 passed, 1 deselected
旧测试桩兼容专项：8 passed
完整后端回归：719 passed, 2 skipped
```

完整回归中的 2 个 skipped 是默认关闭的西安、杭州公网烟测；它们已在显式打开在线开关的独立命令中实际执行并通过。

## 可重复命令

```powershell
.\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q backend/tests/test_s3_t005_t006_city_verification.py backend/tests/test_s2_t024_full_golden_path.py backend/tests/test_s2_t024_single_golden_path.py

$env:RUN_AMAP_LIVE_SMOKE='1'
.\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider --basetemp '.pytest-live-tmp' -q backend/tests/test_s3_t005_t006_city_verification.py -k live -vv

.\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q
```

