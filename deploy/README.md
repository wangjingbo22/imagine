# Sprint 1 公网部署

## Render HTTPS

仓库根目录的 `render.yaml` 定义两个服务：

- `xingzhi-travel-api`
- `xingzhi-travel-web`

Render 会为两个服务自动签发 HTTPS 证书。创建 Blueprint 后，需要在 API
服务中填写 `AMAP_WEB_SERVICE_KEY`。

首次部署后检查：

```bash
curl -fsS https://xingzhi-travel-api.onrender.com/health
curl -I https://xingzhi-travel-web.onrender.com/
curl -I https://xingzhi-travel-web.onrender.com/workspace
```

`/workspace` 返回前端页面可证明 Nginx SPA 回退正常。

## Docker 本地生产演练

```bash
cp .env.example .env
docker compose -f docker-compose.prod.yml up --build
```

打开：

```text
http://localhost:8080
```

验证：

```bash
curl -fsS http://localhost:8080/health
curl -I http://localhost:8080/workspace
```

## 生产配置

- 前端同源访问 `/api` 时由 Nginx 反代到 FastAPI。
- 独立域名部署时使用 `VITE_API_BASE_URL` 指定 HTTPS API。
- 后端通过 `CORS_ALLOWED_ORIGINS` 配置允许的前端 HTTPS 域名，多个域名用逗号分隔。
- SQLite 数据挂载到持久卷 `/app/data`。
- 不得在镜像、日志或仓库中写入高德 Key。
