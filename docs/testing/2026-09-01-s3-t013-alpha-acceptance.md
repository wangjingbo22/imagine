# 2026-09-01 S3-T013 Alpha 本地验收报告

## 结论

`LOCAL_AUTOMATION_PASS / PUBLIC_UAT_NOT_RUN`

S3-T013 的 2 日和 3 日本地双浏览器链路通过。验收没有修改 S3-T009 至 S3-T012 的生产合同，只新增 T013 自动化与证据归档。

## 环境

- 基线：`main@1d27faf`
- 后端：当前基线从 `127.0.0.1:8013` 启动，使用 `.testdata/s3_t013/` 隔离数据库。
- 前端：Playwright 临时 Vite 服务，代理到 `8013`。
- 浏览器：本机 Edge 通道，组织者与成员使用独立 browser context。
- 宽度：375×812、768×1024、1366×900、1440×900。

本机原 `8000` 端口运行的是缺少 T009/T010 路由的旧进程，因此没有复用；该环境差异不是当前 `main` 的产品缺陷，也未中断用户正在使用的 `8000/5173` 服务。

## 场景结果

| 场景 | 登录与邀请 | 隔离与轮询 | 逐日入口 | 预算来源 | 结果 |
| --- | --- | --- | --- | --- | --- |
| 2 日父行程 | 组织者、成员分别退出再登录；邀请兑换成功 | 成员只见自己；组织者由轮询看到更新 | 第 1、2 天参数正确 | 实时/估算/未知与手动修正可见 | PASS |
| 3 日父行程 | 组织者、成员分别退出再登录；邀请兑换成功 | 成员只见自己；组织者由轮询看到更新 | 第 1、2、3 天参数正确 | 实时/估算/未知与手动修正可见 | PASS |

两个场景均在四个宽度执行，总计 `8 passed`。移动端预算表为自身横向可读区，文档根节点无横向溢出；截图前将表格定位到“来源/状态”列，保证归档内容可读。

## 命令与结果

```powershell
$env:VITE_DEV_PROXY_TARGET='http://127.0.0.1:8013'
cd frontend
npx playwright test e2e/s3-t013-alpha-acceptance.spec.ts --reporter=list
# 8 passed

cd ..
$base = ".pytest-temp/s3-t013-focused-$([guid]::NewGuid().ToString('N'))"
python -m pytest backend/tests/test_s3_t009_account.py `
  backend/tests/test_s3_t010_parent_collaboration.py `
  backend/tests/test_s3_t012_parent_trip.py --basetemp $base -q
# 23 passed

python tools/s3_t003_quality_gate.py
# 816 passed, 2 skipped; S3-T003 quality gate: PASS

cd frontend
npm test
# 107 passed
npm run lint
# PASS，2 条既有 warning
npm run build
# PASS
```

## 证据

选取 375px 的 2 日场景和 1440px 的 3 日场景归档，兼顾移动端与桌面端。每套证据均包含：

- 组织者已登录账号页。
- 成员独立资料页。
- 组织者父行程与轮询后的成员资料。
- 最后一天的单日 Trip 入口及正确预填。
- 预算来源状态、未知费用和非支付手动修正。

文件清单和结构化结果见 `docs/testing/evidence/s3_t013/README.md` 与 `local-result.json`。

## 限制

- 本次是本机隔离浏览器上下文，不是公网两台物理设备。
- 未执行公网网络波动、真实 GPS/照片、真实高德/百炼生成或验收签字。
- T013 只验收既有 S3-T011 预算页面合同和 S3-T012 单日入口，不在本任务中扩展预算服务或完成每一天的 Provider/LLM 生成。
- 邮箱验证、密码找回、支付、聊天、WebSocket 和投票均在需求排除范围内。
