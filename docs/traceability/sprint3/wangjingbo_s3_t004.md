# S3-T004 RC 部署、答辩材料与回退方案

**Owner：** 王敬博

**Traceability：** PBI-15-B / AC-15-B / S3-T004

**状态：** RC 本地产物与发布材料已就绪；公网发布待 Render 项目管理员执行
**记录日期：** 2026-08-31

## RC 产物

- 前端生产构建：`frontend/npm run build` 已通过。
- 前端容器：`frontend/Dockerfile` + `frontend/nginx.conf`，含 SPA 回退和同源 `/api` 反代。
- API 容器：根 `Dockerfile`；`render.yaml` 定义 API 与 Web 两个 HTTPS 服务。
- 本地生产演练入口：`docker-compose.prod.yml`；数据库和高德缓存使用 `/app/data` 卷。
- 发布配置、环境变量和持久化要求见 `deploy/README.md`。

## 发布步骤与验收清单

1. 将包含本次 RC 的提交推送到 Render 已连接分支，确认构建日志显示前后端镜像构建成功。
2. 在 API 服务配置 `AMAP_WEB_SERVICE_KEY`、`BAILIAN_API_KEY`；在 Web 服务配置地图 JS Key；所有密钥只保存为 Render Secret。
3. 为 API 服务挂载 `/app/data` Persistent Disk，防止重部署丢失行程和证据。
4. 访问 `/`、`/workspace`、`/health` 和 `/api/v1/health`，记录返回状态与 `buildSha`。
5. 用校园网和手机流量各执行一次北京关怀黄金链：需求确认 → 事实确认 → 唯一 V1 → 执行/GPS → 照片 → V2 决策 → 回忆。连续通过三次后归档视频、截图、API 响应和 build SHA。
6. 用 375px、768px 手机/模拟器复核无横向滚动、44px 目标、Tab 焦点和减少动画；1366px/1440px 使用桌面浏览器复核。

## 回退

1. 在 Render Dashboard 选择上一个成功 deploy 回滚；记录回滚 deploy ID 与旧 `buildSha`。
2. 不删除 Persistent Disk，确认旧版本能读取既有 SQLite 数据。
3. 若仅前端失效，优先回滚 Web 服务；若 API 合同或数据库迁移失效，再同时回滚 API 服务。
4. 回滚后重新执行 `/health`、`/api/v1/health`、`/workspace` 及一条已存在行程的读取检查。

## 当前外部验证

2026-08-31 21:01（Asia/Shanghai）探测结果：Web `https://imagine-1-31o2.onrender.com/` 返回 HTTPS 200，页面元信息正常；API `https://imagine-mp7v.onrender.com/api/v1/health` 在 15 秒内未返回。该运行实例也未证明包含本次 RC 的 build SHA。

因此不将“公网 RC 已发布”“北京黄金链连续三次通过”或“校园网/手机流量均通过”写为完成。以上三项必须由拥有 Render 发布权限及真实设备的成员按本清单留证后，才能把 S3-T004 标记为 PASS。
