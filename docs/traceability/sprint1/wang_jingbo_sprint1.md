# 王敬博 Sprint 1 追溯

## 责任范围

```text
PBI-01-B / AC-01-B / S1-T004
PBI-04-A / AC-04-A / S1-T012
PBI-05-A / AC-05-A / S1-T015
PBI-05-C / AC-05-C / S1-T020
PBI-06-A / AC-06-A / S1-T021
PBI-13-S1 / AC-13-S1 / S1-T023
```

## T004

- Schema：`backend/app/schemas/trip.py`
- 状态 Schema：`backend/app/schemas/workflow.py`
- 存储：`app/infrastructure/workflow_store.py`
- API：`app/api/workflow_routes.py`
- 前端：`frontend/src/pages/PlannerPage.tsx`
- 测试：`tests/test_workflow_execution.py`

## T012

- 工作台：`frontend/src/pages/WorkspacePage.tsx`
- Plan Schema：`backend/app/schemas/plan.py`
- 城市/路线接口：`app/api/routes.py`
- 视觉与来源状态：`frontend/src/styles/white-web.css`

## T015

- 事件 Schema：`backend/app/schemas/execution.py`
- 服务：`app/application/workflow_service.py`
- 存储：`app/infrastructure/workflow_store.py`
- API：`POST/GET /api/v1/trips/{tripId}/events`
- 前端：`frontend/src/api/tripApi.ts`、`WorkspacePage.tsx`
- 测试：`tests/test_workflow_execution.py`

## T020

- Diff 领域：`app/domain/plan_diff.py`
- Plan 状态：`app/infrastructure/plan_store.py`
- API：`app/api/plan_routes.py`
- 前端：`WorkspacePage.tsx`
- 测试：`tests/test_plan_v2_diff.py`

## T021

- 聚合：`SqliteWorkflowRepository.get_summary`
- API：`GET /api/v1/trips/{tripId}/summary`
- 页面：`WorkspacePage.tsx`
- 测试：`tests/test_workflow_execution.py`

## T023

- 后端镜像：`Dockerfile`
- 前端镜像：`frontend/Dockerfile`
- SPA/反代：`frontend/nginx.conf`
- Compose：`docker-compose.prod.yml`
- HTTPS 蓝图：`render.yaml`
- CI：`.github/workflows/ci.yml`
- 静态测试：`tests/test_deployment_config.py`

## 诚实边界

公网 URL、平台部署日志和公网截图未在当前无平台凭据环境生成；机器可读追溯文件中的对应字段为 `null`。
