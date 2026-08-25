# Sprint 1 公网部署

## Render HTTPS

仓库根目录的 `render.yaml` 定义两个服务：

- `xingzhi-travel-api`
- `xingzhi-travel-web`

Render 会为两个服务自动签发 HTTPS 证书，并为每个服务提供 `onrender.com`
二级域名。创建 Blueprint 后，需要在 API 服务中填写
`AMAP_WEB_SERVICE_KEY`。

前端镜像默认以真实 API 模式构建：`VITE_USE_MOCK_API=false`。浏览器只会请求
同源的 `/api/*`，再由 Nginx 转发给 API 服务；不要在前端环境变量中填写高德 Key。

### 首次创建

1. 将仓库推送至 GitHub。
2. 在 Render 选择 **New > Blueprint** 并连接仓库。若名称已被占用，将
   `render.yaml` 中两个 `name` 改成你自己的唯一名称，并同步修改前端的
   `API_UPSTREAM` 与后端的 `CORS_ALLOWED_ORIGINS`。
3. 在 API 服务的 Environment 中填入 `AMAP_WEB_SERVICE_KEY`，保存并手动
   重新部署 API。
4. 打开 Web 服务的 `https://<web-service-name>.onrender.com` 地址。

Render 的临时文件系统会在重新部署或实例替换时丢失 SQLite 数据。需要保留行程、
执行记录和高德缓存时，请在 API 服务添加一个挂载到 `/app/data` 的 Persistent Disk；
然后保持 `PLAN_VERSION_DB_PATH` 与 `AMAP_CACHE_DB_PATH` 的默认配置不变。

首次部署后检查：

```bash
curl -fsS https://<api-service-name>.onrender.com/health
curl -I https://<web-service-name>.onrender.com/
curl -I https://<web-service-name>.onrender.com/workspace
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
- SQLite 数据路径为 `/app/data`；在 Render 控制台加 Persistent Disk 后才会跨部署保留。
- 不得在镜像、日志或仓库中写入高德 Key。
