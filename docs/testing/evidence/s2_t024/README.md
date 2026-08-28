# S2-T024 验收证据目录

本目录只保存 `PBI-13-A / AC-13-A / S2-T024 / UAT-S2-012 / RESP-S2-001` 的脱敏验收证据。当前尚未执行公网验收，因此本文件不代表 PASS。

本地 Playwright 会用 Mock API/Fixture 检查六问到工作台的浏览器衔接，以及执行、V2 Diff、回忆三个阶段的响应式展示。这些结果必须标注为 `LOCAL MOCK UI CONTRACT`，不能放入下述公网证据目录冒充真实后端全链，也不能命名为公网黄金路径。

`S2-T032 / UAT-S2-E2E-001` 的组织者加两名成员完整邀请链不属于本目录，也不能作为 S2-T024 已完成的替代证据。

## 目录约定

真实执行后按以下结构保存；不存在的文件不要用占位截图冒充：

```text
docs/testing/evidence/s2_t024/
  README.md
  <YYYYMMDD-HHMM>-<shortSHA>/
    manifest.json
    commands/
      backend-traceability.txt
      frontend-test.txt
      frontend-lint.txt
      frontend-build.txt
      playwright.txt
    375/
      video.webm
      trace.zip
      plan.png
      recommendation.png
      execution.png
      replan-diff.png
      memory.png
    768/
      video.webm
      trace.zip
      plan.png
      recommendation.png
      execution.png
      replan-diff.png
      memory.png
    public/
      environment.json
      health.json
      network-redacted.har
      lineage-redacted.json
    signoff.md
```

## `manifest.json` 必填字段

```json
{
  "evidenceId": "RESP-S2-001",
  "taskId": "S2-T024",
  "pbiId": "PBI-13-A",
  "acceptanceCriteriaId": "AC-13-A",
  "uatId": "UAT-S2-012",
  "buildSha": "<40-hex>",
  "testedAt": "<ISO-8601 with timezone>",
  "frontendUrl": "<public URL>",
  "backendUrl": "<public URL>",
  "viewports": [375, 768],
  "result": "PASS|FAIL|BLOCKED",
  "redacted": true
}
```

## 证据质量规则

- 视频必须连续显示地址栏、视口、主要操作和最终页面，不能剪辑掉失败步骤。
- 截图至少覆盖六问、推荐、执行、V2 Diff 和回忆；375px 与 768px 分开保存。
- Playwright trace 和 Network 证据必须来自同一 build SHA。
- `execution.png`、`replan-diff.png`、`memory.png` 必须来自同一公网 Trip 的连续真实状态转换；本地 Mock/Fixture 截图不得使用这些公网证据文件名。
- `lineage-redacted.json` 使用 `tripId -> planVersionId -> taskId -> eventId -> proposedV2Id -> decision -> memoryTimeline` 串联，但只保留验收必要 ID。
- 命令输出包含命令、时间、退出码和实际通过数；不能只写“已通过”。
- FAIL/BLOCKED 证据同样保留，后续复验新建时间戳目录，不覆盖历史。

## 保密规则

禁止提交或录制以下内容：

- 高德、百炼或其他 API Key；
- Cookie、Authorization、组织者凭证、一次性邀请 token；
- 未脱敏的精确个人位置、真实姓名、手机号或照片 EXIF；
- 部署平台秘密变量值；
- 包含上述数据的原始 HAR、trace 或日志。

提交前必须完成脱敏复查；只记录秘密变量“已配置/未配置”，不记录值。
