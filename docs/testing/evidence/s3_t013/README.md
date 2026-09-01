# S3-T013 本地证据

状态：`LOCAL_AUTOMATION_PASS / PUBLIC_UAT_NOT_RUN`

本目录保存 `frontend/e2e/s3-t013-alpha-acceptance.spec.ts` 生成并人工抽查后的代表性截图。测试账号均为一次性 `example.com` 数据；截图不包含邀请 token、父行程 capability 或成员 session。

## 2 日场景：375px

- `2-day-organizer-login-375.png`
- `2-day-member-isolated-profile-375.png`
- `2-day-parent-collaboration-375.png`
- `2-day-child-trip-entry-375.png`
- `2-day-budget-provenance-375.png`

## 3 日场景：1440px

- `3-day-organizer-login-1440.png`
- `3-day-member-isolated-profile-1440.png`
- `3-day-parent-collaboration-1440.png`
- `3-day-child-trip-entry-1440.png`
- `3-day-budget-provenance-1440.png`

`local-result.json` 记录基线、场景矩阵和本地门禁结果。完整四宽度 Playwright 原始输出位于被 Git 忽略的 `frontend/test-results/`，不把临时 trace、HTML 报告或账号数据库提交到仓库。

这些材料只能证明本地自动化。公网真实双设备、真实账号 UAT 和验收签字仍为 `NOT_RUN`。
