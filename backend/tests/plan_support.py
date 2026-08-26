from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from app.schemas.plan import ProposedPlanVersion


class UnusedLocationService:
    """Explicit HTTP-test stub for endpoints that never access Provider data."""


def proposal_payload() -> dict[str, object]:
    fixture_path = Path(__file__).parent / "fixtures" / "trips" / "beijing.json"
    trip = json.loads(fixture_path.read_text(encoding="utf-8"))
    trip["status"] = "PLAN_REVIEW"
    return {
        "schemaVersion": "1.0",
        "planId": "20000000-0000-4000-8000-000000000001",
        "tripSnapshot": trip,
        "version": 1,
        "parentId": None,
        "reason": "INITIAL_PLAN",
        "metrics": {
            "totalCostCents": 29_800,
            "bufferCents": 5_200,
            "totalWalkMeters": 2_650,
            "transferCount": 2,
            "validationStatus": "PASS",
        },
        "days": [
            {
                "dayIndex": 0,
                "date": "2026-09-05",
                "tasks": [
                    {
                        "taskId": "task-1",
                        "order": 1,
                        "title": "中国国家博物馆",
                        "category": "历史文化",
                        "timeRange": "09:40 — 11:40",
                        "durationMinutes": 120,
                        "transport": "地铁 8 号线 · 38 分钟",
                        "costCents": 600,
                        "walkMeters": 420,
                        "note": "东门无障碍入口信息待现场确认",
                    },
                    {
                        "taskId": "task-2",
                        "order": 2,
                        "title": "四季民福 · 前门店",
                        "category": "特色餐饮",
                        "timeRange": "12:05 — 13:20",
                        "durationMinutes": 75,
                        "transport": "步行 460 米 · 8 分钟",
                        "costCents": 13_800,
                        "walkMeters": 460,
                        "note": "已预留午餐与休息时间",
                    },
                    {
                        "taskId": "task-3",
                        "order": 3,
                        "title": "景山公园",
                        "category": "城市风景",
                        "timeRange": "14:10 — 16:00",
                        "durationMinutes": 110,
                        "transport": "公交 5 路 · 31 分钟",
                        "costCents": 400,
                        "walkMeters": 780,
                        "note": "山顶路线包含坡道，建议量力而行",
                    },
                    {
                        "taskId": "task-4",
                        "order": 4,
                        "title": "什刹海落日漫步",
                        "category": "轻松收尾",
                        "timeRange": "16:35 — 18:20",
                        "durationMinutes": 105,
                        "transport": "出租车 · 18 分钟",
                        "costCents": 15_000,
                        "walkMeters": 990,
                        "note": "18:20 返程，满足最晚结束时间",
                    },
                ],
            }
        ],
        "constraintsSnapshot": [
            {
                "ruleId": "budget-limit",
                "scope": "trip",
                "hardness": "HARD",
                "status": "PASS",
                "description": "方案总金额不超过行程预算",
                "details": {"budgetCents": "35000"},
            }
        ],
        "sourcesSnapshot": [
            {
                "provider": "FRONTEND_MOCK",
                "sourceStatus": "ESTIMATED",
                "fetchedAt": "2026-08-24T10:00:00+08:00",
                "isStale": False,
                "referenceId": "workspace-recommendation-v1",
            }
        ],
    }


def parse_proposal(
    payload: dict[str, object] | None = None,
) -> ProposedPlanVersion:
    return ProposedPlanVersion.model_validate_json(
        json.dumps(payload or proposal_payload(), ensure_ascii=False),
        strict=True,
    )


def v2_payload() -> dict[str, object]:
    payload = deepcopy(proposal_payload())
    payload["planId"] = "20000000-0000-4000-8000-000000000002"
    payload["version"] = 2
    payload["parentId"] = "20000000-0000-4000-8000-000000000001"
    payload["reason"] = "EXPENSE_CHANGE"
    payload["metrics"] = {
        "totalCostCents": 27_400,
        "bufferCents": 7_600,
        "totalWalkMeters": 1_980,
        "transferCount": 1,
        "validationStatus": "PASS",
    }
    tasks = payload["days"][0]["tasks"]  # type: ignore[index]
    payload["days"][0]["tasks"] = [  # type: ignore[index]
        tasks[0],
        {**tasks[1], "timeRange": "12:20 — 13:30", "costCents": 11_800},
        {
            **tasks[3],
            "order": 3,
            "costCents": 14_000,
            "walkMeters": 800,
            "transport": "地铁直达 · 22 分钟",
        },
        {
            "taskId": "task-5",
            "order": 4,
            "title": "北京城市艺术馆",
            "category": "室内文化",
            "timeRange": "16:10 — 17:20",
            "durationMinutes": 70,
            "transport": "步行 300 米 · 5 分钟",
            "costCents": 1_000,
            "walkMeters": 300,
            "note": "根据实际消费减少费用和户外步行",
        },
    ]
    payload["constraintsSnapshot"].append(  # type: ignore[union-attr]
        {
            "ruleId": "rest-after-expense",
            "scope": "trip.days[0]",
            "hardness": "SOFT",
            "status": "WARNING",
            "description": "调整后增加一次室内休息",
            "details": {"reason": "EXPENSE_CHANGE"},
        }
    )
    payload["sourcesSnapshot"].append(  # type: ignore[union-attr]
        {
            "provider": "FRONTEND_MOCK",
            "sourceStatus": "ESTIMATED",
            "fetchedAt": "2026-08-24T11:00:00+08:00",
            "isStale": False,
            "referenceId": "workspace-recommendation-v2",
        }
    )
    return payload


__all__ = [
    "UnusedLocationService",
    "parse_proposal",
    "proposal_payload",
    "v2_payload",
]
