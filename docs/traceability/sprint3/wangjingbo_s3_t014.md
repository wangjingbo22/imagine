# S3-T014 账户 AI 设置与按账户模型调用

**Owner：** 王敬博
**Traceability：** PBI-25-A / AC-25-A / S3-T014
**完成日期：** 2026-09-01

## 交付内容

新增账户模型设置页：`/model-settings`。

- 支持登录后按账户绑定自己的 API Key、模型与 OpenAI 兼容 Base URL。
- 使用 HTTPS Base URL，限制模型地址不能接入非安全网络。
- 数据库中仅保存加密后的 API Key，不回显完整 Key；读取时返回末四位提示。
- 选择模型根据当前登录账户保存，并用于该账户后续自然语言解析调用。
- 未登录或未绑定 API Key 时，不进行任何 AI 请求，避免服务端兜底调用。
- 支持替换 Key / 删除 Key；删除后不保留旧密钥，避免覆盖旧配置。

## 实现范围

- `frontend/src/pages/ModelSettingsPage.tsx`：模型选择、API Key 输入、Base URL 输入、显示/隐藏、保存和删除。
- `app/api/account_routes.py`：账户绑定接口及 Cookie 认证。
- `app/application/account_service.py`：加密保存、密钥解密、HTTPS 校验、模型配置查询。
- `app/infrastructure/account_store.py`：`account_model_settings` 表及增删改查逻辑。
- `app/api/trip_draft_routes.py`：按当前登录账户读取 token 对应的模型配置，并在该次请求临时创建提取器，不保留全局调用凭证。

## 验收映射

| AC-25-A 条件 | 实现与证据 |
| --- | --- |
| 账号绑定 API Key | 账户模型设置页 + `account_model_settings` 表，Key 以 Fernet 密文保存。 |
| 替换/删除 | 页面支持重写保存与清除 Key；服务端删除即移除当前用户配置。 |
| 模型配置 | 允许选择 `qwen-turbo` / `qwen-plus` / `qwen-max`。 |
| Base URL 配置 | 支持输入 OpenAI 兼容地址，强制要求 `https`。 |
| 当前账户调用 | 解析请求根据登录 Cookie 读取当前用户配置，不再回落到服务端全局 Key。 |
| 不明文持久化 | 仅保存密文；返回的 `keyHint` 仅展示末四位。 |

## 真实验证

已在本机完成如下验证：

```bash
cd /home/abc/桌面/实训/frontend
npm run build
```

以及后端编译检查：

```bash
cd /home/abc/桌面/实训
python3 -m compileall -q app
```

另外已使用当前登录账户保存的模型配置进行实际 API 调用，仅返回 `OK`；该调用使用了用户绑定的 `qwen-plus` 及账户保存的 DashScope Base URL，证实当前账户模型配置是真正生效的。

## 结论

S3-T014 的账户级模型绑定与加密存储功能已落地并在本地实际调用链中通过验证。它是一项可执行的用户模型设置能力，符合“由用户自己绑定、选择和替换模型 / Key，且不回显敏感信息”的要求。

需要注意的是：这部分的最终“全链路上线验收”仍受真实部署环境、平台余额和真实模型服务状态影响，不能替代公网部署和真实外部设备检查。
