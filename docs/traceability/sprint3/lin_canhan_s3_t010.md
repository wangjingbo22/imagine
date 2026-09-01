# 林粲涵 Sprint 3：S3-T010 父行程多人协作

**Owner：** 林粲涵

**Traceability：** PBI-18-B / AC-18-B / S3-T010

**交付基线：** `main@17485d230ad5b5fda0745bb67a207b468e821000`

**状态：** `LOCAL_AUTOMATION_PASS / PUBLIC_UAT_NOT_RUN`

## 需求来源

任务来自 `doc/行知旅伴_V2.3_Sprint3收尾待办列表_12小时Alpha扩展版.xlsx`：组织者创建父行程和邀请；成员加入后维护互相隔离的独立资料；成员资料、预算和每日子 Trip 状态使用短轮询同步。范围明确不包含聊天、WebSocket 和投票。

## 交付合同

- 复用 S3-T012 的 2–3 天同城父行程，最多三人：一名组织者和两名成员。
- 组织者凭证、邀请 token、成员会话三者独立。SQLite 只保存 SHA-256 哈希，不保存可复用明文 token。
- 邀请创建与兑换均要求 `Idempotency-Key`；邀请只能兑换一次，同键重试返回同一结果。
- 组织者同步可见父行程内全部资料；成员同步和资料更新只能读取、修改自己的参与者行。
- 邀请创建和资料更新携带 `expectedSyncVersion`。旧版本写入返回 HTTP 409，防止轮询期间静默覆盖。
- 前端固定每 5 秒调用同步接口；不创建 WebSocket、SSE、聊天或投票通道。
- 成员邀请 token 在兑换请求发出前从地址栏移除；组织者和成员能力仅保存于当前标签页的 `sessionStorage`。
- 所有父行程接口成功和失败响应均使用 `Cache-Control: no-store`。

## HTTP 接口

| 方法与路径 | 身份与用途 |
| --- | --- |
| `POST /api/v3/parent-trips/{parentTripId}/invitations` | `X-Parent-Trip-Token`；组织者创建一个成员席位和邀请 |
| `POST /api/v3/parent-trip-invitations/redeem` | 邀请 token；兑换独立成员会话 |
| `GET /api/v3/parent-trips/{parentTripId}/sync` | 组织者 token 或成员 session 二选一；返回权限裁剪后的同步快照 |
| `PUT /api/v3/parent-trips/{parentTripId}/member-profile` | `X-Parent-Member-Session`；成员只更新自己的昵称、兴趣和预算上限 |

`ParentTripSyncView` 固定返回父行程预算汇总、每日 `childStatus`、`syncVersion`、`changedAt`、`pollAfterSeconds: 5` 和按查看者权限裁剪的 `visibleProfiles`。同步响应不返回邀请 token、组织者 token 或成员 session。

## AC 映射

| AC-18-B 条件 | 自动化证据 |
| --- | --- |
| 组织者创建父行程和邀请 | T012 回归覆盖父行程；T010 HTTP 测试覆盖两份邀请、幂等重试和第三名上限 |
| 成员加入并维护独立资料 | 两个邀请兑换为不同 session；成员 A/B 分别更新昵称、兴趣和预算上限 |
| 成员资料隔离 | 成员 A 响应不含成员 B，成员 B 响应不含成员 A；组织者可见三人 |
| 短轮询同步资料、预算、子 Trip 状态 | 前端常量冻结为 5000 ms；同步 DTO 包含父预算和每日 `childStatus` |
| 刷新与服务重启可恢复 | 相同 SQLite 重新创建应用后，成员 session、资料和同步版本保持可读 |
| 不含聊天、WebSocket、投票 | 前端契约测试拒绝 `WebSocket` / `EventSource`，实现中没有聊天或投票入口 |

## 依赖与边界

S3-T012 已提供父行程聚合。当前 `main` 尚无 S3-T009 账号登录实现，因此本交付使用父行程专属 capability session 完成成员身份隔离；公开 DTO 不依赖浏览器随机身份，T009 后续可把账号 ID 绑定到该 session 边界，无需修改 T010 HTTP DTO。

本记录不宣称公网三浏览器、真实账号绑定或验收签字已经完成。公开环境 UAT 应在 T009 接入后另行记录。

## 本地验证

- `python -m pytest backend/tests/test_s3_t010_parent_collaboration.py backend/tests/test_s3_t012_parent_trip.py`
- `npm test`
- `npm run lint`
- `npm run build`
- `python tools/s3_t003_quality_gate.py`

后端验收覆盖邀请、兑换、权限隔离、乐观并发、token 不泄漏、`no-store` 和服务重启恢复；前端验收覆盖路由、能力头、URL 清理、`sessionStorage`、5 秒轮询及组织者/成员交互入口。

本次本地结果：父行程聚焦套件 `8 passed`；S3-T003 全量门禁 `783 passed, 2 skipped` 且状态 `PASS`；前端 `97 passed`，build 通过，lint 仅保留 `ConversationPlannerPage.tsx` 中两条既有 warning；Playwright 真实三人链路在 375px 和 1366px 项目均通过并完成截图审查。两条后端 skip 仍是未启用在线开关时的真实高德烟测，不属于 T010。
