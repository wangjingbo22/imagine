# AI 运行接入与使用说明

## 当前接入结论

项目已接入阿里云百炼 OpenAI 兼容接口，用于把用户的自然语言需求提取为
城市、日期、时间、起终点、预算、兴趣和地点限制等候选字段。

它不是最终规划器：模型输出必须先通过 Pydantic 契约、歧义确认、城市解析、
关怀约束、预算和路线规则，才能进入 PlanVersion。模型不能直接生成已确认计划，
也不能修改 CURRENT、接受 V2 或绕过服务端校验。

## 代码路径

- 运行时装配：`app/main.py:create_app`
- 百炼 HTTP 客户端：`app/infrastructure/bailian.py`
- 候选字段与错误契约：`app/domain/trip_draft.py`
- 规则回填与降级：`app/application/trip_draft_service.py`
- HTTP 入口：`POST /api/v1/trips/drafts/parse`
- 前端入口：新建行程页“智能识别并填入”

`backend/app/__init__.py` 只是共享 Schema、确定性服务和 Agent Tool 所在包的
初始化文件。它必须保持无网络、无密钥读取、无启动副作用；是否接入大模型应看
上述运行时装配和健康检查，而不是看 `__init__.py` 是否导入模型 SDK。

## 启用与验证

真实 Key 只能放在本地 `.env` 或部署平台 Secret：

```env
BAILIAN_API_KEY=你的新百炼Key
BAILIAN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
BAILIAN_MODEL=qwen3.7-plus
```

启动后访问 `GET /api/v1/health`：

- `naturalLanguageParser = BAILIAN_CONFIGURED`：当前进程已按 Secret 装配百炼客户端，
  但健康检查本身不调用模型。
- `naturalLanguageParser = DETERMINISTIC_RULES`：未配置 Key，当前只运行本地规则。

随后实际调用一次 `POST /api/v1/trips/drafts/parse`：返回
`recognitionSource = BAILIAN` 才证明该请求获得了在线模型结果；
`DEGRADED_RULES` 表示百炼失败后由本地规则完成解析。

测试中的 `httpx.MockTransport` 只验证请求契约，不等于真实线上调用。课堂或验收若要
证明在线模型已启用，应同时保留健康检查结果、浏览器 Network 中的解析请求和后端
不含密钥的调用日志。

## 安全与降级

- 不提交 `.env`、API Key、Authorization 请求头或含密钥的课堂日志。
- 百炼超时、鉴权失败或返回非法 JSON 时，服务回退到确定性规则并保留歧义确认。
- 仓库历史中曾出现过调试凭据；旧凭据必须在平台撤销并换新。删除当前文件不能
  清除 Git 历史，也不能替代密钥轮换。
- 当前没有 LangGraph 运行时编排；“Agent”指受契约约束的服务端工作流原型。

## 开发过程 AI 使用记录模板

### Sprint {N} - Day {N}

#### {姓名} - {模块名}

- 日期、任务编号：{日期 / S1-Txxx}
- 协作模式：{约束式氛围编程 / 精确编程 / 结对修正 / 局部辅助}
- AI 使用场景：{生成工具类 / 修复 Bug / 补充测试 / 代码审查}
- Prompt 摘要：{本次提问摘要，不粘贴 Key、Token 或个人数据}
- AI 输出是否直接采用：{是 / 否 / 部分采用}
- 我的修改/调整：{人工改动点与验证方法}
- 遇到的问题：{幻觉、架构混乱、接口不一致、死循环、安全问题等}
- 我理解这段代码的程度（1—5）：{1—5}

记录应反映真实使用与人工判断。即使输出未采用也要说明原因；理解程度 1 表示
基本不理解，5 表示能够脱离 AI 独立重写。
