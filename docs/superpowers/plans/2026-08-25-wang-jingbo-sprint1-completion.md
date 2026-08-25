# 王敬博 Sprint 1 收口实施计划

**日期：** 2026-08-25
**负责人：** 王敬博
**范围：** S1-T004、S1-T012、S1-T015、S1-T020、S1-T021、S1-T023

## 目标

把已有的前端演示页面接入真实的状态、PlanVersion、执行事件和总结服务，并提供可部署、可测试、可追溯的 Sprint 1 证据。

## 实施顺序

1. **T004 约束确认**
   - 复用 T003 `AssistanceProfile`。
   - 新增 SQLite 约束状态表。
   - 修改字段写回 `DRAFT`。
   - 确认迁移到 `CONSTRAINT_CONFIRMED`，重复确认幂等。
   - Plan V1 登记时校验已确认 Profile。

2. **T015 执行事件**
   - 新增 `START / COMPLETE / SKIP / EXPENSE` Schema。
   - 事件绑定 `eventId/taskId/planVersionId/idempotencyKey/occurredAt`。
   - 写入与 PlanVersion 相同 SQLite 文件。
   - 校验 Trip 为 `EXECUTING`、Plan 为当前 `CURRENT`、任务属于当前计划。
   - 相同幂等键同请求返回原事件，不同请求返回冲突。

3. **T020 Diff 页面**
   - 保留团队已实现的服务端确定性 Diff。
   - 页面展示地点、时间、路线、费用和关怀变化。
   - 接受/拒绝只调用原子决策接口。

4. **T021 基础总结**
   - 从事件流复算实际消费。
   - 聚合完成和跳过任务。
   - 展示 CURRENT 版本和全部 Plan 历史。

5. **T023 部署骨架**
   - 后端 Dockerfile。
   - 前端多阶段 Dockerfile。
   - Nginx SPA 回退和 API 反向代理。
   - Render HTTPS Blueprint。
   - CI 后端测试和前端 build/lint。

## 验证门禁

- Python 全量测试通过。
- 前端 TypeScript build 与 Oxlint 通过。
- 部署配置静态测试通过。
- `git diff --check` 通过。
- 公网 URL 由有平台权限的成员在 Render 创建 Blueprint 后补录，不伪造外部证据。
