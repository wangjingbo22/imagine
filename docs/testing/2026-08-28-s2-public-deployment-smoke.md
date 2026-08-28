# Sprint 2 公网部署烟测

日期：2026-08-28

- Web：`https://imagine-1-31o2.onrender.com/`、`/workspace` 返回 HTTPS 200。
- 同源 API：`/health`、`/api/v1/health` 返回 200；当前记录的部署 build 为 `32bb112a5eb7ec1e0e3d052ec060defe9f3627c1`。
- 多人创建：`POST /api/v2/trips/conversations` 返回 200。在未配置 `BAILIAN_API_KEY` 时，响应为 `FIXED_QUESTIONS`、`LLM_NOT_CONFIGURED`、`callCount: 0`、`canPlan: false`，没有把失败伪装为可规划结果。

## T024 关闭提交部署差异

- T024 本地关闭提交：`1a7fcf7169f3e3656507be878e896bf4db1dd9fd`；T023 前端接线提交：`e4f9c50f7c9ee6c058030c5d6e6739e9f1a480af`；验证基线 main：`012fa364894ffc7dd36a6dd91cdd21641550da06`。
- 当前公网 build `32bb112...` 不是关闭提交，因此新增 full backend golden path 与 `plan.parent_id` 修复尚不能作为公网已部署证据。
- 本地门禁为 backend `633 passed in 78.57s`、frontend `52 passed`、build PASS、lint 通过且仅 2 条既有 warning、Playwright `14 passed in 31.4s`。
- T024 公网结论保持 `NOT_RUN / BLOCKED`；T023 前端已本地闭环，T032 是单独验收任务并明确排除。

## 待配置后的复验

Render API 服务尚未配置 `BAILIAN_API_KEY`，因此本次不能证明在线模型识别；配置该 Secret、部署 `1a7fcf7` 或其后续包含提交后，应复验响应 `recognitionSource: BAILIAN`，并完成 T024 的 375/768 真实浏览器连续链与设备 GPS/照片录屏。多人两浏览器与 T032 证据必须另行记录，不能混入 T024 PASS。
