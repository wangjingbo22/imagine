# 行知旅伴前端

基于 Vite、React 和 TypeScript 的旅行规划 Agent Web 前端。

## 本地运行

```bash
npm install
cp .env.example .env.local
npm run dev
```

默认使用 Mock API。连接 FastAPI 时修改：

```env
VITE_API_BASE_URL=http://localhost:8000
VITE_USE_MOCK_API=false
```

## 校验

```bash
npm run build
npm run lint
```

接口契约见 `../doc/frontend_api_contract.md`。
