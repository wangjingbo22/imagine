# Sprint 2 公网部署烟测

日期：2026-08-28

- Web：`https://imagine-1-31o2.onrender.com/`、`/workspace` 返回 HTTPS 200。
- 同源 API：`/health`、`/api/v1/health` 返回 200，部署 SHA 为 `f7e09b291140fe98861c969d017b60541c9a3d2f`。
- 多人创建：`POST /api/v2/trips/conversations` 返回 200。在未配置 `BAILIAN_API_KEY` 时，响应为 `FIXED_QUESTIONS`、`LLM_NOT_CONFIGURED`、`callCount: 0`、`canPlan: false`，没有把失败伪装为可规划结果。

## 待配置后的复验

Render API 服务尚未配置 `BAILIAN_API_KEY`，因此本次不能证明在线模型识别；配置该 Secret 后，应复验响应 `recognitionSource: BAILIAN`，并完成真实两浏览器成员确认与设备 GPS 录屏。
