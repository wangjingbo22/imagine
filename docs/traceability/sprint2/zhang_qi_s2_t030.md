# S2-T030 多人可信候选 FactRef 签发与硬约束预过滤

**Owner:** 张琪
**Traceability:** PBI-16-A / AC-16-A / S2-T030

## 实现边界

- 仅在协作状态为 `READY_TO_PLAN` 后读取服务端当前确认版本，并投影为兼容既有规划契约的 1–3 人 `Trip`；该投影不写入 PlanVersion 或工作流状态。
- 起点、终点和地点候选均由服务端高德 Provider 或 `VERIFIED_CACHE` 恢复，浏览器与模型不能提交候选事实。
- 服务端在千问看到候选前执行确定性硬约束预过滤：同城、可信来源、Provider ID 去重、多人硬性避开、硬性必去覆盖，以及已知单地点价格不超过共享预算和任一成员预算上限。
- 预过滤后必须保留 6–8 个地点；少于 6 个或无法覆盖硬性必去地点时拒绝签发，不调用千问或规划器。
- 通过 Provider FactRef 注册表签发不可变 `factSetId`、`providerFactDigest` 和每个候选的来源摘要；推荐预览只把已签发白名单交给千问。

## 返回与验收证据

`GET /api/v2/trips/{tripId}/recommendations` 的推荐数据包含：

- `factSetId`；
- `providerFactDigest`；
- 6–8 个候选；
- 与候选对应的 `provenance`，包括 `factRefId`、Provider 对象 ID、`sourceStatus`、`fetchedAt` 与 `isStale`。

`backend/tests/test_s2_t030_provider_candidate_issuance.py` 覆盖：

- 两名成员的 READY Trip 能从在线/可信缓存事实签发 6–8 个候选；
- 跨城、未知来源、多人硬性避开、超预算和重复 Provider ID 被预过滤；
- 多人硬性必去候选不会被排序截断；
- 预过滤后不足 6 个时不创建 FactRef 集合和 PlanVersion；
- 篡改 `providerFactDigest` 后，既有推荐编排返回 `PROVIDER_FACT_DIGEST_MISMATCH`，真实路线构建调用数与 PlanVersion 写入数均为 0。

## 验证结果

- T030 定向测试：`2 passed`。
- T006/T009/T024/T030 相关回归：`33 passed`。
- 合并远端最新内容后的后端完整回归：`635 passed`。

本地 `.env` 的百炼超时仍为旧值 45 秒；测试仅通过进程环境临时覆盖为 10 秒，没有修改密钥或 `.env`。
