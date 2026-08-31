# S3-T002 媒体存储降级恢复独立验收

> 最终结论：**PASS（本地代码与契约验收）**
>
> 验收日期：2026-09-01（Asia/Shanghai）
>
> 验收角色：独立产品测试工程师；未修改生产代码、既有测试或契约文档，未提交、未推送。

## 1. 验收范围与边界

本次只验收 S3-T002 对 S2-T012 任务照片媒体 SQLite 可恢复异常的收口：

- 媒体 SQLite 的初始化、读取、替换、删除错误统一返回 `503 / MEDIA_STORAGE_UNAVAILABLE`，并标记 `retryable: true`；
- 替换时新图写入失败必须回滚旧图的软删除，旧图仍可读取；移除故障后重试可完成替换；
- 契约正确说明该错误码覆盖范围和可重试语义；
- 既有 T017、T024、T032 直接功能回归不退化。

不在本次范围内：百炼、高德缓存、一次定位/人工完成、浏览器拍照权限、真实磁盘故障、并发竞争和生产部署。它们均为现有能力或需要独立场景的验证，不能以本次本地 SQLite 结果替代。

## 2. 环境与基线

| 项目 | 实际值 |
| --- | --- |
| 工作树 | `C:\\Users\\lenovo\\Desktop\\实训\\2026lindashixun12zu\\.worktrees\\czy-S3-T002` |
| 分支 | `czy-S3-T002` |
| 基线提交 | `8d9a33cb3d06dc372ba987ed6796b81faaa918ce` |
| 操作系统与终端 | Windows / PowerShell |
| Python | `3.12.13`（项目 `..\\..\\.venv`） |
| pytest | `8.4.2` |
| 测试方式 | FastAPI ASGI + 独立 SQLite 文件；pytest 使用 worktree 内专用 `--basetemp` |

验收开始时的未提交范围为 `.agent/api_contracts.md`、`app/api/media_routes.py`、`backend/tests/test_s2_t012_media_lifecycle.py`、`frontend/src/api/API.md`，与任务声明一致。代码窗口原有的 `.pytest-tmp-s3-t002-final/`、`green/`、`red/`、`related/` 均未删除或改动。

## 3. 源码与契约审查

| 验收标准 | 证据 | 结果 |
| --- | --- | --- |
| 统一错误映射 | `app/api/media_routes.py` 的 `_media_storage_unavailable()` 固定构造 `MEDIA_STORAGE_UNAVAILABLE`、HTTP 503、可重试；`_media_connection()` 捕获 `sqlite3.Error` 且使用 `from None` 去除底层异常链。 | PASS |
| 初始化、读取、替换、删除均受覆盖 | `_initialize()`、`list_media()`、`replace_media()`、`delete_media()` 分别通过 `_media_connection()` 访问 SQLite。 | PASS |
| 响应不泄露 SQLite | `app/main.py` 的 `AppError` 处理器仅序列化 `code/message/retryable/errors`；媒体错误的固定消息为 `Media storage is temporarily unavailable`。独立黑盒响应检查也未发现 `sqlite`。 | PASS |
| 替换事务回滚 | `replace_media()` 在同一个 SQLite 连接事务内先软删除旧行、再插入新行。插入触发 `sqlite3.Error` 时连接上下文回滚；独立触发器实测旧图仍可读。 | PASS |
| 契约一致 | `.agent/api_contracts.md` 第 15 节与 `frontend/src/api/API.md` 第 14 节均将 `MEDIA_STORAGE_UNAVAILABLE` 登记为 HTTP 503、可重试，并列出初始化/读取/替换/删除覆盖及替换恢复语义。 | PASS |
| 范围无扩张 | 仅上述路由、T012 生命周期测试和两份接口说明有未提交改动；无生产功能旁路或无关文件变更。 | PASS |

## 4. 自动化与黑盒验收

以下命令均在本工作树执行，使用项目虚拟环境；每个本次验收专用 `.qa-tmp-s3-t002-*` 目录已在测试后清理。

| 验收项 | 实际命令 | 实际结果 | 判定 |
| --- | --- | --- | --- |
| 新增最小回归：真实 SQLite `BEFORE INSERT` 触发器 | `& '..\\..\\.venv\\Scripts\\python.exe' -B -m pytest -p no:cacheprovider --basetemp=.qa-tmp-s3-t002-acceptance-min -q backend/tests/test_s2_t012_media_lifecycle.py::test_media_storage_failure_rolls_back_replacement_and_retry_succeeds` | `1 passed in 1.19s` | PASS |
| 全部直接媒体回归 | `& '..\\..\\.venv\\Scripts\\python.exe' -B -m pytest -p no:cacheprovider --basetemp=.qa-tmp-s3-t002-acceptance-media -q backend/tests/test_s2_t012_media_lifecycle.py` | `2 passed in 1.75s` | PASS |
| T017/T024/T032 直接功能回归 | `& '..\\..\\.venv\\Scripts\\python.exe' -B -m pytest -p no:cacheprovider --basetemp=.qa-tmp-s3-t002-acceptance-related -q backend/tests/test_s2_t017_memory_timeline.py backend/tests/test_s2_t024_single_golden_path.py backend/tests/test_s2_t024_full_golden_path.py backend/tests/test_s2_t032_multiplayer_e2e.py` | `7 passed in 8.16s` | PASS |

另以独立内联 ASGI 黑盒脚本复现完整恢复过程：先写入旧照片；以真实 SQLite `BEFORE INSERT` 触发器令新照片插入失败；检查 HTTP 状态、错误码、`retryable` 和整个 JSON 响应不含 `sqlite`；读取旧照片；删除触发器；重试替换。实际输出如下：

```text
manual_failure=503/MEDIA_STORAGE_UNAVAILABLE sqlite_leak=False old_readable=True retry=200
```

该黑盒脚本首次因终端对内联双引号的传参问题在 Python 解析阶段报 `SyntaxError`，目标应用未执行；改用单引号字面量后以相同断言重跑并得到以上结果。一次进程内临时目录清理曾因 Windows 对 SQLite 文件的短暂句柄锁返回 `WinError 32`，因此改为进程退出后清理专用目录；两者均为验收脚本封装/清理问题，不是产品断言失败，且最终运行退出成功。

## 5. 风险与残余验证

- 自动化故障注入直接覆盖插入失败；初始化、读取、删除路径的 503 覆盖由统一连接上下文源码审查确认，尚未为三者分别注入运行时 SQLite 故障。
- 未模拟磁盘写满、跨进程锁竞争、断电或高并发替换；SQLite 事务语义已被触发器恢复场景验证，但这些运行条件仍应由平台/压力测试单独覆盖。
- 本结论不等同于真实设备拍照、浏览器权限或线上部署验收。

## 6. 最终判定

**PASS。** S3-T002 在限定范围内满足可恢复媒体存储异常的错误映射、错误信息脱敏、旧照片事务回滚、故障移除后的重试成功及直接关联回归要求。未发现契约错误、缺失验收或范围漂移；无需退回代码窗口。
