# 2026 林大实训 12 组

| 账号 | 姓名 | 职责 |
| ---- | ---- | ---- |
| wangjingbo | 王敬博 | Scrum Master |
| fangfangxiao | 张琪 | QA |
| rasz12345 | 林粲涵 | QA |
| c_z_yy | 陈梓元 | PO |

## 张琪：PBI-02-A 城市地点、路线与可信来源

当前本地实现 FastAPI 高德 Web 服务适配，范围仅包含城市解析、地点检索、路线规划、可信来源和按城市隔离的 SQLite 缓存。

### 本地启动

要求 Python 3.11 或更高版本：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

在 `.env` 中填写高德开放平台申请的 Web 服务 Key：

```env
AMAP_WEB_SERVICE_KEY=你的Web服务Key
```

不要把 `.env` 或真实 Key 提交到 Git。启动服务：

```powershell
uvicorn app.main:app --reload
```

接口文档：`http://127.0.0.1:8000/docs`

### 测试

```powershell
pytest
```

测试默认使用模拟高德响应，不需要真实 Key，也不会消耗高德调用额度。
