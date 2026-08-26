# S2-T012 任务照片生命周期

**Owner:** 王敬博
**Traceability:** PBI-10-A / AC-10-A / S2-T012
**Dependencies:** S2-T011

## 实现

照片通过 `tripId/taskId` 绑定。上传同一任务会替换旧的活动照片；每任务最多一张、每趟最多八张。删除使用软删除，读取接口仅返回未删除媒体，因此执行页和回忆页不会再次展示已删除照片。上传处理失败或零照片不影响任务完成。

## 接口与代码证据

- `GET/POST/DELETE /api/v2/trips/{tripId}/tasks/{taskId}/media`。
- `app/api/media_routes.py`：SQLite 生命周期与 8 张守卫。
- `frontend/src/components/TaskPhotoCard.tsx`：上传、预览、替换和删除 UI。
- `frontend/src/pages/WorkspacePage.tsx`：当前任务绑定。
- 提交：`33ca88f`。

## 验收状态

接口和页面实现完成、前端构建及后端语法检查通过；1/8/9 张、替换、删除、上传失败和零照片的浏览器证据待采集。
