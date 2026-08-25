# 王敬博 Sprint 1 验收记录

## 范围

| Task | 结果 | 主要证据 |
| --- | --- | --- |
| S1-T004 | PASS | 真实 DRAFT/CONSTRAINT_CONFIRMED、修改回退、确认幂等、Plan 门禁 |
| S1-T012 | PASS | 唯一推荐工作台、3—4 任务、预算/路线/风险/来源展示 |
| S1-T015 | PASS | START/COMPLETE/SKIP/EXPENSE、SQLite、幂等、刷新恢复 |
| S1-T020 | PASS（自动化） | 服务端 Diff、原子接受拒绝、前端中文 Diff |
| S1-T021 | PASS | 真实事件流总结、费用复算、完成/跳过、版本历史 |
| S1-T023 | DEPLOY-READY | Docker/Nginx/Render/CI 完成；公网 URL 待平台账号发布 |

## 新增自动化

### 状态与事件

```bash
python3 -m pytest tests/test_workflow_execution.py
```

覆盖：

- 约束确认幂等。
- 修改后回退 DRAFT。
- 未确认不得规划。
- Profile 不一致不得规划。
- ExecutionEvent 幂等。
- 幂等键冲突。
- SQLite 重开恢复。
- 事件流费用聚合。
- 所有任务终态后 Trip 完成。
- HTTP 约束与事件链。

### 部署配置

```bash
python3 -m pytest tests/test_deployment_config.py
```

覆盖：

- Nginx SPA 回退。
- `/api` 反向代理。
- Render 服务与健康检查。
- SQLite 持久卷。
- CI 后端和前端门禁。
- Docker 可复现安装命令。

### 全量回归

```bash
python3 -m pytest
cd frontend
npm run lint
npm run build
```

最终全量 Python 回归得到：

```text
179 passed in 0.81s
```

前端最终门禁：

```text
npm run lint  PASS
npm run build PASS
```

## 外部证据状态

| 证据 | 状态 |
| --- | --- |
| PR | 待推送分支后创建 |
| CI | 工作流已创建，待远端执行 |
| 公网 HTTPS URL | 待有 Render 权限的成员发布 |
| 公网桌面/375px 截图 | 待 URL 可用后补录 |
| 本地 Docker 日志 | 当前机器没有 Docker，未伪造 |

## 结论

T004、T012、T015、T020、T021 的代码和自动化范围已闭合。T023 的代码仓库交付已完成，但严格“公网证据”仍依赖外部平台权限，因此标为 `DEPLOY-READY` 而不是虚假宣称公网验收完成。
