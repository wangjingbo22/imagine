# S1-T017 接入与页面补充清单

> 基线：远端 main `12caa055`。本清单区分“本 T017 分支会完成的内容”和“队友仍需补充的产品/部署内容”。

## 本 T017 分支负责

- 新增事件驱动 V2 接口：`POST /api/v1/trips/{tripId}/replans/from-events`。
- 浏览器只提交消费/完成事件，不再上传候选计划、锁定 ID、POI、路线或满意度分。
- 服务端读取 CURRENT V1、已签发可信事实和执行事件，推导冻结前缀，只把未完成后缀交给规划器。
- Sprint 1 仅支持 `EXPENSE_CHANGE` 触发一次 V2；自由文本疲劳/延迟/偏好重排不在 T017 验收范围。
- 仍可行时生成 PROPOSED V2；无解时保留 CURRENT V1，不留下 V2 PlanVersion 或 V2 可信草稿。
- 继续复用 T011 校验、T018 单候选选择边界和 T019 Diff/接受/拒绝。
- Workspace 的实际金额统一转换为整数分，删除客户端 `buildAmapReplanCandidate` V2 路径。

## 本 T017 分支已验证

- 后端 S1-T017 定向：`backend/tests/test_s1_t017_event_replan.py`，9 passed。
- 后端全量回归：273 passed。
- 前端契约与既有单测：21 passed。
- 前端 lint/build：exit 0；Vite 仍打印既有 `/runtime-config.js` non-module warning，但构建完成。
- `python -m compileall app backend/app`：exit 0。
- `git diff --check`：exit 0；仅 Git LF→CRLF 工作副本提示。
- 详细证据见 `docs/testing/evidence/s1_t017/clean-slice-acceptance.md`。

## 张琪：服务端必须补充

1. **V1 待确认恢复**：现在只有 `GET .../plan-reviews/{reviewId}`，但刷新后页面不知道 reviewId。请让 `getTrip` 返回 `pendingReviewId`，或新增“查询当前 pending review”接口。
2. **一次 V2 的页面恢复提示**：服务端已拒绝终态 V2 的重复生成；Trip 状态仍可在 T024 暴露 `v2Attempted`/V2 决策历史，让刷新后的页面提前禁用入口并显示原因。
3. **部署持久化**：Render 为 SQLite 的 `/app/data` 配 Persistent Disk；否则重部署会丢 V1、证据确认、执行事件、实际消费和 V2。
4. **部署版本可见**：health/version 响应返回构建 SHA，发布后确认公网确实运行最新 main，而不是旧前端包。
5. **错误详情稳定化**：保留 `code/field/message/affectedRuleIds/results/relaxations`，不要只返回“所有候选失败”。

## 王敬博：前端与部署必须补充

1. **19 项确认不是故障**：典型四段路线的 16 个设施事实，加 3 个未知地点价格，共 19 项。页面应显示“待补齐可信事实”，按任务/路线分组并显示 `已完成 x/19`，不要用大段红色崩溃样式。
2. **刷新恢复 V1 review**：张琪补完 pending review 契约后，Workspace 启动时恢复相同 review 和填写进度；不要用 URL state/localStorage 冒充服务端状态。
3. **区分错误类型**：
   - `CANDIDATE_CONFIRMATION_REQUIRED`：V1 事实待人工确认；
   - T011 candidate failure：候选事实/硬约束失败；
   - T018 no feasible：冻结前缀后无可行方案；
   - 网络/502：部署问题。
4. **无解继续执行**：EXPENSE/COMPLETE 已保存但 V2 无解时，恢复 CURRENT V1，并 START 下一个未完成任务；不要卡在“正在生成”。
5. **成功信息不要用错误样式**：例如“Plan V1 已获得 PASS”应放在 success/notice 区。
6. **修总结真实性**：移除硬编码“关怀满足率 100% / 4 项硬约束全部满足”，改读服务端校验/总结事实。
7. **修公网代理**：当前公网根页可访问，但同源 `/api/v1/health` 曾返回 502。要么修反向代理，要么明确使用直连 HTTPS API 并正确配置 CORS。
8. **Render 前端环境**：确认 `VITE_AMAP_JS_API_KEY`、`VITE_AMAP_SECURITY_JS_CODE` 与 API upstream 都在部署环境配置，且不写入仓库。

## 已完成，不要重复改

- 真实起点/终点输入与有限自然语言提取；
- 高德地点、路线、底图和 Polyline；
- V1 价格/设施/来源的逐项确认、服务端重算与 PASS 后签发；
- V1/V2 Diff、接受与拒绝的服务端基础能力。

## 明确不要做

- 不要把 UNKNOWN 价格当 0、UNKNOWN 设施自动改成 PASS。
- 不要增加“一键全部存在/全部通过”来绕过证据确认。
- 不要让浏览器重新构造或直接登记 Plan V2。
- 不要把 T018 多候选排序塞回 T017。
- 不要把 GPS 到达、任务照片、迟到/疲劳事件、完整旅行回忆页提前放进 Sprint 1。
