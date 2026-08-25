# 张琪 S1-T005 北京/上海 Provider 联调追溯

## 验收范围

同一 Provider 层分别处理北京和上海 CityContext，POI 搜索与步行路线请求
必须携带对应 `cityCode`，结果不得串城，并保留来源状态、抓取时间和价格
事实状态。

## 生产与联调

- `scripts/verify_pbi02_live.py`：在线解析北京/上海城市，执行两城 POI 搜索
  和步行路线；对短暂 Provider 故障做一次有界重试。
- 脚本断言请求与响应分别使用 `110000`、`310000`，POI 城市一致，且
  `sourceStatus`、`fetchedAt`、价格事实状态完整。
- 输出前会检查高德 Web 服务 Key 不在序列化 JSON 中。

## 自动化与证据

- `tests/test_two_city_provider_integration.py`：两城 Provider Stub 集成测试，
  覆盖 POI、路线、城市隔离、来源与价格事实。
- `tests/test_place_service.py`：覆盖在线失败时仅允许同城缓存、禁止跨城回退。
- `docs/testing/evidence/s1_t005_provider_beijing_shanghai.json`：北京、上海在线
  请求/响应的脱敏证据，不含高德 Key。

PR、同伴 Review 和 CI Build-ID 属于仓库外部证据；按当前要求尚未提交或
推送，不能在本地伪造。
