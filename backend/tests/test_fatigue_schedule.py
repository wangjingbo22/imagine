import json
from pathlib import Path

import pytest

from app.schemas.execution_adjustment import (
    ConfirmedExecutionAdjustment, ExecutionConstraintCompileRequest,
    ExecutionAdjustmentType, FatigueLevel, RemainingConstraintContext,
)
from app.services.execution_adjustments.compiler import compile_execution_constraints
from app.services.planning.models import CandidatePlanRequest
from app.services.replanning.suffix_planner import (
    DeterministicEventAwareSuffixPlanner, SuffixPlanningError, SuffixPlanningInput,
)


def request():
    payload = json.loads((Path(__file__).parent / 'fixtures/planning/golden_candidate_plan.json').read_text(encoding='utf-8'))
    return CandidatePlanRequest.model_validate_json(json.dumps(payload['request']))


def schedule_input(facts=None, level=FatigueLevel.MODERATE):
    original = request()
    event = ConfirmedExecutionAdjustment(
        schema_version='1.0', confirmation_status='CONFIRMED',
        event_type=ExecutionAdjustmentType.FATIGUE, task_id=original.task_facts[0].task_id,
        fatigue_level=level, late_minutes=None,
    )
    constraints = compile_execution_constraints(ExecutionConstraintCompileRequest(
        event=event,
        current_constraints=RemainingConstraintContext(
            remaining_walk_budget_meters=3000, max_segment_walk_meters=1000,
            rest_interval_minutes=180,
        ),
    ))
    return SuffixPlanningInput(
        task_facts=facts if facts is not None else original.task_facts[1:],
        frozen_task_ids=(original.task_facts[0].task_id,), actual_spent_cents=0,
        event_constraints=constraints, source_event_task_id=event.task_id,
        anchor_end_at=original.task_facts[0].end_at,
    )


def seconds(value):
    return value.hour * 3600 + value.minute * 60 + value.second


def test_rest_is_on_clock_before_travel_and_activities_are_reduced():
    source = schedule_input()
    suffix = DeterministicEventAwareSuffixPlanner().plan_suffix(source)
    previous_end = source.anchor_end_at
    for original, planned in zip(source.task_facts, suffix):
        assert planned.route == original.route
        assert planned.place == original.place
        assert planned.rest_before.start_at == previous_end
        assert seconds(planned.rest_before.end_at) - seconds(previous_end) >= 1800
        assert seconds(planned.start_at) - seconds(planned.rest_before.end_at) == planned.route.durationSeconds
        assert seconds(planned.end_at) - seconds(planned.rest_before.end_at) <= 45 * 60
        assert planned.elapsed_since_rest_minutes == (planned.route.durationSeconds + 59) // 60
        previous_end = planned.end_at
    assert suffix[0].end_at != source.task_facts[0].end_at or suffix[0].start_at != source.task_facts[0].start_at


def test_rest_evidence_roundtrips_without_changing_legacy_v1_payloads():
    original = request()
    assert 'restBefore' not in original.model_dump_json(by_alias=True)
    suffix = DeterministicEventAwareSuffixPlanner().plan_suffix(schedule_input())
    planned = original.model_copy(update={'task_facts': (original.task_facts[0], *suffix)})
    restored = CandidatePlanRequest.model_validate_json(planned.model_dump_json(by_alias=True))
    assert restored == planned
    assert restored.task_facts[0] == original.task_facts[0]


def test_severe_fatigue_adds_a_real_arrival_break_for_longer_routes():
    facts = request().task_facts[1:]
    suffix = DeterministicEventAwareSuffixPlanner().plan_suffix(schedule_input(facts, FatigueLevel.SEVERE))
    # The last route already takes 30 minutes; there must be a separate break
    # on arrival before another activity, not a fabricated shorter route.
    last = suffix[-1]
    assert last.rest_on_arrival is not None
    assert seconds(last.rest_on_arrival.end_at) - seconds(last.rest_on_arrival.start_at) >= 1800
    assert seconds(last.rest_on_arrival.start_at) - seconds(last.rest_before.end_at) == last.route.durationSeconds
    assert last.start_at == last.rest_on_arrival.end_at
    assert seconds(last.end_at) - seconds(last.start_at) <= 1800
    assert last.elapsed_since_rest_minutes == 30


def test_long_motorized_travel_gets_a_real_arrival_break_instead_of_a_reason_only_error():
    facts = list(request().task_facts[1:])
    facts[0] = facts[0].model_copy(update={
        'route': facts[0].route.model_copy(update={'durationSeconds': 3600, 'mode': 'TRANSIT'}),
        'elapsed_since_rest_minutes': 0,
    })
    suffix = DeterministicEventAwareSuffixPlanner().plan_suffix(schedule_input(tuple(facts)))
    assert suffix[0].route.durationSeconds == 3600
    assert suffix[0].rest_on_arrival is not None
    assert seconds(suffix[0].rest_on_arrival.end_at) - seconds(suffix[0].rest_on_arrival.start_at) == 1800


def test_long_walking_travel_still_fails_closed():
    facts = list(request().task_facts[1:])
    facts[0] = facts[0].model_copy(update={
        'route': facts[0].route.model_copy(update={'durationSeconds': 3600, 'mode': 'WALKING'}),
    })
    with pytest.raises(SuffixPlanningError) as error:
        DeterministicEventAwareSuffixPlanner().plan_suffix(schedule_input(tuple(facts)))
    assert error.value.code == 'REPLAN_FATIGUE_ROUTE_TOO_LONG'


def test_rest_cannot_overlap_a_route_or_frozen_task():
    original = request()
    suffix = DeterministicEventAwareSuffixPlanner().plan_suffix(schedule_input())
    payload = original.model_copy(update={'task_facts': (original.task_facts[0], *suffix)}).model_dump(mode='json', by_alias=True)
    payload['taskFacts'][1]['restBefore']['startAt'] = '10:00:00'
    with pytest.raises(ValueError, match='planned rest must fit'):
        CandidatePlanRequest.model_validate_json(json.dumps(payload))


def test_fatigue_schedule_cannot_silently_overrun_confirmed_day_end():
    original = request()
    suffix = DeterministicEventAwareSuffixPlanner().plan_suffix(schedule_input())
    payload = original.model_copy(update={'task_facts': (original.task_facts[0], *suffix)}).model_dump(mode='json', by_alias=True)
    payload['trip']['days'][0]['timeWindow']['end'] = '16:30:00'
    with pytest.raises(ValueError, match='inside the trip day time window'):
        CandidatePlanRequest.model_validate_json(json.dumps(payload))


def test_late_event_with_existing_slack_still_produces_an_actionable_v2_change():
    original = request()
    event = ConfirmedExecutionAdjustment(
        schema_version='1.0', confirmation_status='CONFIRMED',
        event_type=ExecutionAdjustmentType.LATE, task_id=original.task_facts[0].task_id,
        late_minutes=30, fatigue_level=None,
    )
    constraints = compile_execution_constraints(ExecutionConstraintCompileRequest(
        event=event,
        current_constraints=RemainingConstraintContext(remaining_time_minutes=600),
    ))
    source = SuffixPlanningInput(
        task_facts=original.task_facts[1:], frozen_task_ids=(original.task_facts[0].task_id,),
        actual_spent_cents=0, event_constraints=constraints,
        source_event_task_id=event.task_id, anchor_end_at=original.task_facts[0].end_at,
    )
    suffix = DeterministicEventAwareSuffixPlanner().plan_suffix(source)
    assert suffix != source.task_facts
    assert '迟到调整' in suffix[0].note
    assert seconds(suffix[0].end_at) <= seconds(source.task_facts[0].end_at)
