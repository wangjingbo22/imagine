# 公网部署与本地生产演练

## Render HTTPS

仓库根目录的 `render.yaml` 定义两个服务：

- `xingzhi-travel-api`
- `xingzhi-travel-web`

Render 会为两个服务自动签发 HTTPS 证书，并为每个服务提供 `onrender.com`
二级域名。创建 Blueprint 后，需要在 API 服务中填写
`AMAP_WEB_SERVICE_KEY`。要启用百炼自然语言识别，还必须填写
`BAILIAN_API_KEY`；两项都应使用 Render Secret，不能提交真实值。若启用“用户自带
API Key / 模型设置”，还必须设置 `ACCOUNT_API_KEY_ENCRYPTION_KEY` 为 Fernet 密钥。
该值用来加密账户库中的用户 Key，丢失或更换后将无法读取旧的已绑定 Key。

当前公网地址是独立部署快照。部署后应通过 API 健康检查中的 `buildSha` 确认实际版本；公网可访问不等于最新 `main` 已部署，也不等于 S2-T032 多人公网验收通过。

前端镜像默认以真实 API 模式构建：`VITE_USE_MOCK_API=false`。浏览器只会请求
同源的 `/api/*`，再由 Nginx 转发给 API 服务；不要在前端环境变量中填写后端 Web Service Key。容器启动时还需要为前端 Web 服务配置 `VITE_AMAP_JS_API_KEY` 和 `VITE_AMAP_SECURITY_JS_CODE`，否则真实地图脚本可能不可用；这两个值不能提交到 Git。

### 首次创建

1. 将仓库推送至 GitHub。
2. 在 Render 选择 **New > Blueprint** 并连接仓库。若名称已被占用，将
   `render.yaml` 中两个 `name` 改成你自己的唯一名称，并同步修改前端的
   `API_UPSTREAM` 与后端的 `CORS_ALLOWED_ORIGINS`。
3. 在 API 服务的 Environment 中填入 `AMAP_WEB_SERVICE_KEY`、`BAILIAN_API_KEY`，并以
   Render Secret 新建 `ACCOUNT_API_KEY_ENCRYPTION_KEY`。可在安全环境生成：

   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

   保存后手动重新部署 API；此主密钥必须长期稳定，不能在每次部署时重新生成。
4. 打开 Web 服务的 `https://<web-service-name>.onrender.com` 地址。

Render 的临时文件系统会在重新部署或实例替换时丢失 SQLite 数据。仓库的 Render Blueprint
已为 API 服务声明一个挂载到 `/app/data` 的 1 GB Persistent Disk；账户库路径明确为
`/app/data/account.sqlite3`，行程库与高德缓存也使用同一持久目录。创建 Blueprint 时无需
再手动补挂载，但应确认 Render 服务仍保留该磁盘配置。

S2-T032 当前仍为 `LOCAL_AUTOMATION_PASS / PUBLIC_UAT_NOT_RUN`。真实高德/百炼、三浏览器成员会话、GPS/相机权限和 375px/768px 公网连续链路，必须按仓库中的专项验收文档单独留证。

首次部署后检查：

```bash
curl -fsS https://<api-service-name>.onrender.com/health
curl -fsS https://<api-service-name>.onrender.com/api/v1/health
curl -I https://<web-service-name>.onrender.com/
curl -I https://<web-service-name>.onrender.com/workspace
```

`/workspace` 返回前端页面可证明 Nginx SPA 回退正常。API 健康检查中的
`naturalLanguageParser` 为 `BAILIAN_CONFIGURED`，表示当前线上实例已按 Secret 装配
百炼客户端；`DETERMINISTIC_RULES` 表示未配置 Key。健康检查不主动消耗模型配额，
因此还要实际调用一次自然语言解析，并确认响应 `recognitionSource` 为 `BAILIAN`；
若为 `DEGRADED_RULES`，表示该次调用失败并已回退本地规则。

## Docker 本地生产演练

```bash
cp .env.example .env
# 填入 ACCOUNT_API_KEY_ENCRYPTION_KEY（Fernet 密钥）及需要的 Provider Key
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
- 不得在镜像、日志或仓库中写入高德或百炼 Key。
- `ACCOUNT_API_KEY_ENCRYPTION_KEY` 是服务器端主密钥，仅保存为部署平台 Secret；它与
  `/app/data/account.sqlite3` Persistent Disk 必须一起长期保留，才能继续读取用户已绑定的 API Key。
