# S2-T032 验收证据目录

本目录只用于 `PBI-17-A / AC-17-A / S2-T032 / UAT-S2-E2E-001（计划编号）` 的脱敏验收证据。

当前状态为 `PUBLIC_UAT_NOT_RUN`。目前没有公网视频、截图、trace、HAR、真实设备记录或签字；本 README 不是 PASS 证据，也不会创建空 manifest 或占位截图冒充执行结果。

当前也没有真实高德、真实百炼、真实 GPS 或相机验收记录；这些外部结果不能由本地 stub 或组件测试替代。

`UAT-S2-E2E-001` 只来自 `SprintBacklog模板!O36`，尚未在用户功能验收清单中拥有独立行。证据包必须保留这一来源说明，不能把计划编号描述成老师已登记或已签字。

本地 ASGI/SQLite/stub、Vitest 与 375px/768px Mock Playwright 结果只能标记为 `LOCAL_AUTOMATION`。Mock API、Fixture、源码截图和分阶段页面不能放入公网目录并命名为真实三人闭环。

## 目录约定

真实执行后，为每次复验新建目录；不存在的文件不要预建：

```text
docs/testing/evidence/s2_t032/
  README.md
  <YYYYMMDD-HHMM>-<shortSHA>/
    manifest.json
    commands/
      backend-t032.txt
      traceability.txt
      frontend-test.txt
      frontend-build.txt
      frontend-lint.txt
    375/
      organizer-video.webm
      member-a-video.webm
      member-b-video.webm
      organizer-trace-redacted.zip
      screenshots/
        six-questions.png
        invitations-redacted.png
        member-progress.png
        conflict-review.png
        unique-recommendation.png
        execution-arrival.png
        task-photo-redacted.png
        replan-diff.png
        memory.png
    768/
      organizer-video.webm
      member-a-video.webm
      member-b-video.webm
      organizer-trace-redacted.zip
      screenshots/
        six-questions.png
        invitations-redacted.png
        member-progress.png
        conflict-review.png
        unique-recommendation.png
        execution-arrival.png
        task-photo-redacted.png
        replan-diff.png
        memory.png
    public/
      environment.json
      health.json
      call-count-redacted.json
      network-redacted.har
      lineage-redacted.json
      permissions-redacted.json
    signoff.md
```

若 trace/HAR 无法可靠移除邀请 token、组织者凭证或成员 session，就不要提交该文件，只在 manifest 中记录“因安全策略未保存”和替代证据。

## `manifest.json` 必填字段

```json
{
  "schemaVersion": "1.0",
  "taskId": "S2-T032",
  "pbiId": "PBI-17-A",
  "acceptanceCriteriaId": "AC-17-A",
  "uatId": "UAT-S2-E2E-001",
  "uatRegistrationStatus": "PLANNED_ID_IN_BACKLOG_O36_NO_DEDICATED_UAT_ROW",
  "scenarioName": "E2E-S2-新增需求-多人六问到回忆闭环",
  "buildSha": "<40-hex>",
  "testedAt": "<ISO-8601 with timezone>",
  "frontendUrl": "<public URL>",
  "backendUrl": "<public URL>",
  "viewports": [375, 768],
  "actors": ["ORGANIZER", "MEMBER_A", "MEMBER_B"],
  "result": "PASS|FAIL|BLOCKED",
  "redacted": true
}
```

只有真实开始执行后才能创建 manifest；当前 `NOT_RUN` 不创建 manifest。

## 血缘与调用计数

`lineage-redacted.json` 至少关联：

```text
run -> tripId
  -> participant aliases / revisions / readiness digest
  -> factSetId / provider fact digest / selected FactRefs
  -> V1 / taskId / arrival evidence / current photo
  -> LATE or FATIGUE event / proposed V2 / decision
  -> MemoryTimeline
```

两个视口可使用不同的新 Trip，但每个视口内部必须从六问到回忆连续使用同一个 Trip，不能跨运行拼接截图。

`call-count-redacted.json` 必须证明：任一成员未确认或 HARD 冲突存在时，Provider、推荐和 planner 调用次数均为 0；READY 后的调用另行记录。每个完整六问 transcript 的解析调用按会话记录，更正后的新 transcript 单独计数，不能把三个参与者笼统写成整个 Trip 只调用一次。

## 证据质量规则

- 视频显示公网地址、视口、主要操作、状态变化和最终页面，不剪掉失败步骤。
- 三个 actor 使用独立浏览器上下文；成员 A/B 的资料和权限结果分别留证。
- 截图覆盖邀请隔离、未 READY 门禁、冲突放宽、三人重确认、FactRef 推荐、V1、执行/到达、照片、V2 Diff 和回忆。
- build、视频、Network、服务日志和 lineage 必须属于同一次部署。
- V2 接受前的 CURRENT、接受或拒绝后的唯一 CURRENT、已完成/锁定任务不变需要分别留证。
- 回忆证据显示事件顺序、计划/实际费用、版本、关怀和未删除照片；删除照片不得出现。
- 375px/768px 分开记录无横向滚动、44px 操作区、焦点、失败信息和 reduced-motion。
- FAIL/BLOCKED 同样保留；复验新建目录，不覆盖历史。
- 命令输出包含命令、时间、退出码和实际通过数，不能只写“测试通过”。

## 保密规则

禁止提交或录制：

- 高德、百炼或部署平台 API Key/Secret；
- Cookie、Authorization、组织者凭证、成员 session；
- 一次性邀请 token，即使已经失效；
- 未脱敏的精确个人位置、真实姓名、手机号；
- 真实个人照片、照片 EXIF 或无关个人媒体；
- 含上述信息的原始 HAR、trace、视频或日志。

允许记录 Secret “已配置/未配置”、actor 别名、必要的测试 ID 和脱敏业务状态。提交前必须由非执行者完成脱敏复查。

## 签字最低内容

`signoff.md` 至少包含任务、PBI/AC、计划 UAT 编号及其来源说明、build SHA、URL、日期时区、验收人、375/768 结果、三会话结果、完整闭环结果、阻断/缺陷和最终 `PASS|FAIL|BLOCKED`。作者自测不能替代非作者与老师签字。
