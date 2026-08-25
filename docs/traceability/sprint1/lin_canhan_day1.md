# 林粲涵 Sprint 1 Day 1 代码追溯

本页仍只覆盖 Day 1 的 `S1-T003`、`S1-T008`、`S1-T009`。Day 2 的 `S1-T011`、`S1-T018`、`S1-T022` 已在 `lin_canhan_day2.md/json` 单独追溯；本页不作为 Day 2 验收证据。

## 基线与兼容策略

- 已合并团队 main：`3de6d5c446538b27f1ec558d8081821b8362ca21`；其中 WJB 前端提交为 `3894c5993cf2fa229d350199eb64cbf59022bdda`。
- T001 谱系提交：`22eeaae29e141da68c4a6adc6c3efb9fa28690ad`；最终 T001 提交：`e487fa29228181d219226ccd3b24ee76420b38a7`。交付目录 `2026lindashixun12zu-main` 的 `trip.py` SHA-256 为 `17010CE35B9E51CFA871C82002BEB5865DE72FEC6FCA53A2DF74C48235A19ED4`，与该提交一致。
- Python/JSON 延续 T001 约定：Python 字段为 `snake_case`，JSON 字段为 `camelCase`；Pydantic v2 严格类型、拒绝未知字段。
- 已吸收最终 T001 的 UUID4、严格 `HH:mm:ss`、反向偏好冲突定位和公开 Schema；`NapWindow` 复用同一严格时间类型。
- `backend/schemas/trip.schema.json` 与测试快照由组合模型同时生成并保持一致。
- WJB 前端保留原页面与 Mock 流程；`domain/trip.ts` 和 `tripContract.ts` 已按 T003 将四种 UI 模式转换为正式 `AssistanceProfile`，旧的 `null` payload 仍兼容。
- T008 仅注册和守卫 T007 的编译器端口，不在本分支复制 `AssistanceProfile → Constraint` 的编译规则。
- T009 只消费归一化路线事实与 Constraint，不访问高德、网络、LLM、系统时间或随机数。

## PBI → AC → Task → 模块 → 测试

| PBI / AC | Task | 生产模块 | 自动化证据 | 上游 → 下游 |
|---|---|---|---|---|
| PBI-01-B / AC-01-B | S1-T003 | `schemas/trip.py`、`schemas/assistance.py`、前端 `domain/trip.ts` 与 `tripContract.ts` | 四类完整 Trip/Profile fixture、Schema、DRAFT/单参与者测试及前端类型构建 | T001 → T003 → WJB 表单 / T004 / T007 |
| PBI-03-A / AC-03-A | S1-T008 | `schemas/constraint.py`、`agents/tools/assistance_constraints.py` | 注册、严格输入、scope/hardness/value/数量篡改失败、规划前 fail-closed | T007 → T008 → T011/T024 |
| PBI-03-B / AC-03-B | S1-T009 | `services/route_risk/models.py`、`evaluator.py`、前端 `domain/trip.ts` 风险 DTO | 阶梯、超步行、超换乘、缺休息四 fixture；普通档案、未知证据和稳定排序回归；前端类型构建 | T007 + T006 适配 → T009 → WJB 页面 / T010 / T011 |

机器可读的逐文件追溯见 `lin_canhan_day1.json`，测试会校验其中引用的代码、测试和 fixture 均实际存在。

## 给其他成员的接入点

### T007 → T008

T007 实现 `AssistanceConstraintCompiler.compile(profile)` 并在组装层注入 `AssistanceConstraintAgentTool`。LLM 只能提供结构化 Profile；进入规划前应调用 `validate_for_planning()`，它会重新编译并逐字段比较 canonical output。任何 scope、hardness、value、顺序或数量变化都会失败。

### T006/T007 → T009

T006 把团队 RouteSnapshot 映射为 `RouteRiskInput`；稳定的 `routeSegment` 必须保留。T007 使用以下字段名：

main 新增的 PBI-02-A 高德路线服务位于 `app/application/amap_service.py`；它负责 Provider 事实，仍需由 T006 适配为下表所需的稳定字段，T009 不直接访问高德。

| Constraint.field | operator / value | T009 规则 |
|---|---|---|
| `walkLimits.maxContinuousMeters` | `LTE` / integer | 单段步行 |
| `walkLimits.maxDailyMeters` | `LTE` / integer | 当日累计步行 |
| `maxTransfers` | `LTE` / integer | 累计换乘 |
| `restInterval` | `LTE` / integer minutes | 休息间隔 |
| `avoidStairs` | `EQ` / boolean | 已知阶梯 |

未识别的硬路线规则会 fail-closed；`UNKNOWN` 阶梯证据返回 `NEEDS_CONFIRMATION`，不会误判为 PASS。

## 本地验收

在仓库根目录、安装 `.[test]` 后执行：

```powershell
python -m pytest -q
```

合并 main 后本地冻结结果：后端/根服务共 `78 passed`，前端 `npm run build` 与 `npm run lint` 均通过。CI 应在目标分支重新运行并以 CI 结果为最终 Build 证据。

Day 1 原始提交为 `41131d194642ad2f78cc98a6ea1aeaea6a0fc559`。PR/Build-ID、同伴 Review、QA 签署和 PO 验收仍属于外部证据，当前保持为空；CI 或人工完成后再回填，不能由代码自动伪造。
