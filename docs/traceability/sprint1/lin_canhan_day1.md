# 林粲涵 Sprint 1 Day 1 代码追溯

本页只覆盖用户当前要求完成的 Day 1：`S1-T003`、`S1-T008`、`S1-T009`。Day 2 的 `S1-T011`、`S1-T018`、`S1-T022` 未实现，不能据此声明已验收。

## 基线与兼容策略

- 团队基线：`0a72d88`。
- T001 谱系提交：`22eeaae29e141da68c4a6adc6c3efb9fa28690ad`；最终 T001 提交：`e487fa29228181d219226ccd3b24ee76420b38a7`。交付目录 `2026lindashixun12zu-main` 的 `trip.py` SHA-256 为 `17010CE35B9E51CFA871C82002BEB5865DE72FEC6FCA53A2DF74C48235A19ED4`，与该提交一致。
- Python/JSON 延续 T001 约定：Python 字段为 `snake_case`，JSON 字段为 `camelCase`；Pydantic v2 严格类型、拒绝未知字段。
- 已吸收最终 T001 的 UUID4、严格 `HH:mm:ss`、反向偏好冲突定位和公开 Schema；`NapWindow` 复用同一严格时间类型。
- `backend/schemas/trip.schema.json` 与测试快照由组合模型同时生成并保持一致。
- T008 仅注册和守卫 T007 的编译器端口，不在本分支复制 `AssistanceProfile → Constraint` 的编译规则。
- T009 只消费归一化路线事实与 Constraint，不访问高德、网络、LLM、系统时间或随机数。

## PBI → AC → Task → 模块 → 测试

| PBI / AC | Task | 生产模块 | 自动化证据 | 上游 → 下游 |
|---|---|---|---|---|
| PBI-01-B / AC-01-B | S1-T003 | `schemas/trip.py`、`schemas/assistance.py` | 四类完整 Trip/Profile fixture、Schema 与 DRAFT/单参与者测试 | T001 → T003 → T004/T007 |
| PBI-03-A / AC-03-A | S1-T008 | `schemas/constraint.py`、`agents/tools/assistance_constraints.py` | 注册、严格输入、scope/hardness/value/数量篡改失败、规划前 fail-closed | T007 → T008 → T011/T024 |
| PBI-03-B / AC-03-B | S1-T009 | `services/route_risk/models.py`、`evaluator.py` | 阶梯、超步行、超换乘、缺休息四 fixture；普通档案、未知证据和稳定排序回归 | T007 + T006 适配 → T009 → T010/T011 |

机器可读的逐文件追溯见 `lin_canhan_day1.json`，测试会校验其中引用的代码、测试和 fixture 均实际存在。

## 给其他成员的接入点

### T007 → T008

T007 实现 `AssistanceConstraintCompiler.compile(profile)` 并在组装层注入 `AssistanceConstraintAgentTool`。LLM 只能提供结构化 Profile；进入规划前应调用 `validate_for_planning()`，它会重新编译并逐字段比较 canonical output。任何 scope、hardness、value、顺序或数量变化都会失败。

### T006/T007 → T009

T006 把团队 RouteSnapshot 映射为 `RouteRiskInput`；稳定的 `routeSegment` 必须保留。T007 使用以下字段名：

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

本地冻结结果：`66 passed`。CI 应在目标分支重新运行并以 CI 结果为最终 Build 证据。

PR/Commit/Build-ID、同伴 Review、QA 签署和 PO 验收属于外部证据，当前保持为空；上传个人分支并运行 CI 后再回填，不能由代码自动伪造。
