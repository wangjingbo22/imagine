# S2-T011 浏览器照片重编码与隐私处理

**Owner:** 王敬博
**Traceability:** PBI-10-A / AC-10-A / S2-T011

## 实现

浏览器通过 `createImageBitmap` 读取用户主动选择的图片，在 Canvas 中缩放至最长边不超过 1600px，并以 JPEG 质量 `.84 → .48` 逐级重编码。Canvas 导出的 JPEG 不保留原始 EXIF；超过 1.5MB 时给出可见失败提示，且不会阻断任务完成。

## 代码证据

- `frontend/src/components/TaskPhotoCard.tsx`：`reencode()`。
- 压缩输出仅接受 `image/jpeg` / `image/webp` 和最多 1,500,000 字节。
- 提交：`33ca88f feat: add task photo compression and media lifecycle`。

## 验收状态

实现和前端构建通过；带 EXIF 大图的压缩前后样本、EXIF 检查和失败录屏待人工验收采集。
