# S2-T020 已确认事件转换规则

该规则只生成 `EventConstraintSet`，供 S2-T021 的未完成后缀重规划消费。它不写数据库，不修改长期 `AssistanceProfile`，也不追加到 T007 的 `confirmedConstraints`。

## 输入边界

- `confirmationStatus` 必须为 `CONFIRMED`。
- `LATE` 只允许 `lateMinutes`，范围 1–240。
- `FATIGUE` 只允许 `fatigueLevel`，取值 `MILD | MODERATE | SEVERE`。
- 迟到输入只携带剩余分钟；疲劳输入只携带剩余总步行、单段步行和休息间隔。
- 编译器在入口重新严格校验 JSON，拒绝构造后被篡改的模型。

## 确定性规则表

| 事件 | 项目默认阈值 | 输出 | 可见原因 |
|---|---:|---|---|
| `LATE` | `max(0, remainingTime - lateMinutes)` | 仅 `remaining.timeBudgetMinutes <= 结果` | 展示原剩余分钟、迟到分钟和收紧后分钟 |
| `FATIGUE/MILD` | 总步行 3000m；单段 800m；休息 60min | 三项均与当前服务端上限取 `min` | 展示等级和三个生效值 |
| `FATIGUE/MODERATE` | 总步行 1500m；单段 500m；休息 45min | 三项均与当前服务端上限取 `min` | 展示等级和三个生效值 |
| `FATIGUE/SEVERE` | 总步行 500m；单段 200m；休息 30min | 三项均与当前服务端上限取 `min` | 展示等级和三个生效值 |

单段步行还会与生效后的剩余总步行取 `min`，因此不会出现“只剩 100m，却允许单段 800m”的矛盾。

上述疲劳数值是 Day1 为保证可执行测试而冻结的项目默认值，待 PO 最终确认。更换阈值只修改 `FATIGUE_POLICIES` 和对应 Fixture，不改变 HTTP/JSON 契约。

## 联动边界

`S2-T019 草稿 → 用户确认 → S2-T020 EventConstraintSet → S2-T021 后缀重规划 → S2-T022 Diff/决策 → S2-T023 页面展示`。

`inputDigest` 只用于幂等比较，不是签名。S2-T021 必须从服务端可信 CURRENT、任务事实和已确认事件重新编译，不能相信客户端自报的约束或摘要。
