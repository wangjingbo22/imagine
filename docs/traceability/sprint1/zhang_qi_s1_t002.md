# 张琪 S1-T002 自然语言解析与歧义确认追溯

## 验收范围

本任务把旅行描述中的日期、时间、预算、兴趣、必去/避开地点解析为统一
Trip V1 数据，并把缺失、歧义和冲突逐项返回。确认清单未清零时，后端
`confirm` 接口拒绝进入规划；前端也不跳转到生成页面。

## 生产实现

- `POST /api/v1/trips/drafts/parse`：返回解析字段、确认清单和 `canPlan`。
- `POST /api/v1/trips/drafts/confirm`：重新解析并执行后端状态守卫；仅在
  `canPlan=true` 时返回完整 Trip V1。
- `TripDraftParserService`：确定性解析城市、日期、时间、预算、兴趣和地点
  约束；显式表单值可以消解自然语言歧义。
- 前端 `createDraft()` 与 `confirmDraft()` 均调用真实接口，不再使用 Mock；
  确认项未解决时显示中文清单并禁止进入规划。

## 自动化与人工证据

- 五组 fixture：`complete.json`、`missing_budget.json`、
  `ambiguous_date.json`、`ambiguous_time.json`、`place_conflict.json`。
- `tests/test_trip_draft_parser.py`：覆盖五组解析结果、HTTP 接口、未确认不得
  规划以及证据 JSON 契约。
- `docs/testing/evidence/s1_t002_complete_parse_result.json`：完整输入的解析
  结果。
- `docs/testing/evidence/s1_t002_confirmation_desktop.jpg`：缺预算时的中文
  歧义确认页面。

PR、同伴 Review 和 CI Build-ID 属于仓库外部证据；按当前要求尚未提交或
推送，不能在本地伪造。
