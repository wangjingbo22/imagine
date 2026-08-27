# S2-T010 精简唯一推荐页

**Owner:** 王敬博
**Traceability:** PBI-08-A / AC-08-A / S2-T010
**Dependencies:** S2-T009 契约

## 页面行为

`/recommendation/:tripId` 在单一对话流中展示：唯一 3—4 任务方案、高德 FactRef、每位成员分数、最低分优先说明、照顾点、妥协、未知事实和唯一“确认方案”主操作。解释失败时仍可渲染服务端结构化方案；未知事实明确标为待后续路线核验。

页面不展示双方案、伪 PASS，也不允许客户端改变金额、任务或计划状态。

## 代码证据

- `frontend/src/pages/RecommendationPage.tsx`。
- `frontend/src/index.css`：`trusted-plan` 响应式样式。
- `app/domain/recommendation.py`、`app/api/recommendation_routes.py`：冻结 DTO 与真实接口。
- 提交：`a68f819 feat: add fair single recommendation confirmation`。

## 验收状态

构建通过；2/3 人截图、解释失败/未知事实截图和主流程录屏待人工验收时采集。
