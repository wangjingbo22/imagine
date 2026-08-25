# 张琪 S1-T010 路线设施证据追溯

真实 Provider 路线快照新增 `facilityEvidence`。高德路线未提供电梯、坡道、
母婴室或无障碍入口事实时，四项分别返回 `NEEDS_CONFIRMATION`，来源状态为
`UNKNOWN`，并保留路线 `referenceId` 与抓取时间；缺失事实不会被显示为
`PASS`，也不会形成全国无障碍保证。

计划工作台直接消费路线快照中的设施证据，逐项显示缺失原因。只要任一设施
待确认，关怀校验总状态就是“待确认”。接口快照位于
`docs/testing/evidence/s1_t010_route_facility_snapshot.json`，自动化证据位于
`tests/test_t010_facility_evidence.py`。

桌面页面截图为
`docs/testing/evidence/s1_t010_facility_confirmation_desktop.png`。本次提交推送
`zq` 分支；PR、同伴 Review 和远端 CI 由团队合并流程补充。
