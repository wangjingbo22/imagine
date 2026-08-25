# S1-T023 公网响应式部署设计

**Owner:** 王敬博
**Traceability:** PBI-13-S1 / AC-13-S1 / S1-T023

## 产物

- 根 `Dockerfile`：FastAPI + Uvicorn。
- `frontend/Dockerfile`：Node 构建 + Nginx 运行。
- `frontend/nginx.conf`：SPA 回退、静态缓存、API 反代。
- `docker-compose.prod.yml`：本地生产演练和 SQLite 持久卷。
- `render.yaml`：两个公网 HTTPS Web 服务。
- `.github/workflows/ci.yml`：Python 和前端质量门禁。

## 网络与安全

- Render 自动提供 HTTPS。
- Nginx 同源代理 `/api` 和 `/health`。
- 独立域名通过 `API_UPSTREAM` 配置。
- FastAPI 通过 `CORS_ALLOWED_ORIGINS` 配置生产域名。
- 高德 Key 只由平台 Secret 注入。
- SQLite 挂载到 `/app/data`。

## SPA 回退

```nginx
try_files $uri $uri/ /index.html;
```

直接刷新 `/plan`、`/generating`、`/workspace` 不返回 404。

## 验收边界

仓库内已完成可部署产物和静态自动化检查。当前环境无 Docker，且没有可代用户创建 Render 服务的平台凭据，因此：

- Docker 实际构建尚未在本机执行。
- 公网 HTTPS URL、平台部署日志和公网截图需要拥有平台账号的成员创建 Blueprint 后补录。
- 文档不宣称不存在的公网证据。

## 自动化

`tests/test_deployment_config.py` 检查 SPA 回退、反代、持久卷、健康检查、Secret 和 CI 门禁。
