# S1-T004 约束确认状态守卫设计

**Owner:** 王敬博
**Traceability:** PBI-01-B / AC-01-B / S1-T004
**Dependency:** S1-T003

## 状态模型

```text
不存在
  -> PUT profile
DRAFT
  -> POST confirm
CONSTRAINT_CONFIRMED
  -> PUT changed profile
DRAFT
```

相同 Profile 在 `CONSTRAINT_CONFIRMED` 状态再次保存或确认保持原状态和原确认时间，满足幂等要求。

## 数据结构

SQLite 表 `constraint_profiles` 保存：

- `trip_id`
- `status`
- `profile_json`
- `updated_at`
- `confirmed_at`

Profile 使用 T003 `AssistanceProfile` strict JSON，页面不能增加私有字段。

## 接口

- `PUT /api/v1/trips/{tripId}/constraints`
- `POST /api/v1/trips/{tripId}/constraints/confirm`
- `GET /api/v1/trips/{tripId}/constraints`

## 规划门禁

`PlanVersionService.register_proposed()` 在存在约束记录时检查：

1. 状态必须为 `CONSTRAINT_CONFIRMED`。
2. Plan 的 `tripSnapshot.participants[0].assistanceProfile` 必须与已确认 JSON 一致。
3. 不满足时返回 `CONSTRAINTS_NOT_CONFIRMED` 或 `CONSTRAINT_PROFILE_MISMATCH`。

## 前端行为

- 页面创建后显示 `DRAFT 待确认`。
- 修改任一关怀字段后写入真实 DRAFT。
- 点击“确认关怀约束”调用真实接口。
- 未确认时生成按钮禁用。
- 重复确认不创建第二次状态迁移。

## 测试

`tests/test_workflow_execution.py` 覆盖确认幂等、修改回退、规划门禁、Profile 不一致和 HTTP 状态恢复。
