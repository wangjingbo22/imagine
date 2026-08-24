# 行知旅伴前端 API 联调说明

前端接口契约已按后端 S1-T001 Trip Schema 对齐，详细内容见：

- `frontend/src/api/API.md`
- `backend/app/schemas/trip.py`
- `backend/schemas/trip.schema.json`
- `docs/superpowers/specs/2026-08-24-s1-t001-trip-schema-design.md`

当前唯一确认的业务 payload 是 `CreateSingleDayTrip`。

自然语言解析、城市查询、计划、执行、媒体和总结等 HTTP 接口尚未由后端登记；前端暂时使用 Mock，不得将此前拟定的 URL 当作正式契约。
