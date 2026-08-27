from __future__ import annotations

from datetime import time
from unicodedata import normalize
from uuid import UUID

from pydantic import ValidationError

from app.application.collaboration_ports import TripDraftRevisionView
from app.domain.collaboration import (
    ActorScope,
    CollaborationIssue,
    IssueCode,
    JsonValue,
    RelaxationAction,
    RelaxationOption,
)
from app.domain.collaboration_digest import POLICY_VERSION, canonical_sha256
from app.domain.trip_draft import CareDraft
from app.schemas.assistance import create_assistance_profile
from app.schemas.trip import AssistanceProfile, AssistanceType, NapWindow
from app.services.assistance_constraints.compiler import (
    AssistanceConstraintCompileError,
    FIELD_NAP_WINDOW,
)
from app.services.planning.group_constraints import (
    GroupConstraintMergeError,
    GroupConstraintMergeResult,
    merge_group_constraints,
)


def _stable_id(prefix: str, payload: object) -> str:
    return f"{prefix}_{canonical_sha256(payload)[:16]}"


def _normalized_place(value: str) -> str:
    return normalize("NFKC", value).strip().casefold()


def _time(value: str) -> time:
    return time.fromisoformat(value)


def _issue(
    *,
    field_path: str,
    participant_id: UUID | None,
    related: tuple[UUID, ...],
    rule_id: str,
    code: IssueCode,
    reason: str,
    operands: object,
    candidates: tuple[str, ...] = (),
    relaxation_specs: tuple[
        tuple[
            RelaxationAction,
            ActorScope,
            UUID | None,
            str,
            JsonValue,
            str,
        ], ...
    ] = (),
) -> CollaborationIssue:
    identity = {
        "policyVersion": POLICY_VERSION,
        "ruleId": rule_id,
        "fieldPath": field_path,
        "participantIds": sorted(
            str(value) for value in (participant_id, *related) if value
        ),
        "operands": operands,
    }
    options = [
        RelaxationOption(
            relaxationId=_stable_id(
                "rx", {"issue": identity, "action": action, "owner": str(owner)}
            ),
            action=action,
            actorScope=scope,
            participantId=owner,
            fieldPath=option_field_path,
            proposedValue=value,
            label=label,
        )
        for action, scope, owner, option_field_path, value, label in relaxation_specs
    ]
    return CollaborationIssue(
        itemId=_stable_id("ci", identity),
        fieldPath=field_path,
        participantId=participant_id,
        relatedParticipantIds=list(sorted(related, key=str)),
        ruleId=rule_id,
        code=code,
        reason=reason,
        candidates=list(candidates),
        relaxations=options,
    )


def assistance_profile_from_care(care: CareDraft) -> AssistanceProfile:
    if care.assistance_type_hint is None:
        raise ValueError("assistanceTypeHint must be confirmed")
    preset = create_assistance_profile(AssistanceType(care.assistance_type_hint))
    walk = preset.walk_limits.model_copy(update={
        "max_continuous_meters": (
            care.walk_limits.max_continuous_meters
            if care.walk_limits.max_continuous_meters is not None
            else preset.walk_limits.max_continuous_meters
        ),
        "max_daily_meters": (
            care.walk_limits.max_daily_meters
            if care.walk_limits.max_daily_meters is not None
            else preset.walk_limits.max_daily_meters
        ),
    })
    nap = preset.nap_window
    if care.nap_window is not None and care.nap_window.start and care.nap_window.end:
        nap = NapWindow(
            start=time.fromisoformat(care.nap_window.start),
            end=time.fromisoformat(care.nap_window.end),
        )
    candidate = preset.model_copy(update={
        "child_age": care.child_age if care.child_age is not None else preset.child_age,
        "walk_limits": walk,
        "max_transfers": care.max_transfers if care.max_transfers is not None else preset.max_transfers,
        "rest_interval": (
            care.rest_interval_minutes
            if care.rest_interval_minutes is not None
            else preset.rest_interval
        ),
        "nap_window": nap,
        "avoid_stairs": care.avoid_stairs if care.avoid_stairs is not None else preset.avoid_stairs,
    })
    return AssistanceProfile.model_validate_json(
        candidate.model_dump_json(by_alias=True),
        strict=True,
    )


def merged_constraints_for_revision(
    revision: TripDraftRevisionView,
) -> GroupConstraintMergeResult:
    participants: list[tuple[UUID, AssistanceProfile]] = []
    for participant in revision.understanding.participants:
        if participant.care_draft is None:
            continue
        participants.append((
            revision.member_bindings[participant.member_key],
            assistance_profile_from_care(participant.care_draft),
        ))
    return merge_group_constraints(tuple(participants))


BASE_RULES = {
    "binding": "S2T003.BINDING.INVALID",
    "missing": "S2T003.FIELD.REQUIRED",
    "ambiguous": "S2T003.FIELD.AMBIGUOUS",
    "time": "S2T003.TIME.WINDOW_ORDER",
    "budget": "S2T003.BUDGET.CAP_BELOW_SHARED",
    "place": "S2T003.PLACE.MUST_AVOID",
}


class DeterministicHardConflictEvaluator:
    def evaluate(
        self,
        revision: TripDraftRevisionView,
        *,
        organizer_participant_id: UUID | None = None,
    ) -> tuple[CollaborationIssue, ...]:
        issues = [
            *self._binding_issues(revision, organizer_participant_id),
            *self._proposal_input_issues(revision),
            *self._time_issues(revision),
            *self._budget_issues(revision),
            *self._place_issues(revision),
            *self._care_issues(revision),
        ]
        return tuple(sorted(
            issues,
            key=lambda item: (
                item.field_path,
                item.rule_id,
                str(item.participant_id or ""),
                item.item_id,
            ),
        ))

    def _care_issues(
        self,
        revision: TripDraftRevisionView,
    ) -> tuple[CollaborationIssue, ...]:
        profiles: list[tuple[UUID, AssistanceProfile]] = []
        issues: list[CollaborationIssue] = []
        for index, participant in enumerate(revision.understanding.participants):
            owner = revision.member_bindings[participant.member_key]
            path = f"participants[{index}].careDraft.assistanceTypeHint"
            if participant.care_draft is None:
                issues.append(_issue(
                    field_path=path,
                    participant_id=owner,
                    related=(),
                    rule_id="S2T003.CARE.PROFILE_INVALID",
                    code=IssueCode.INVALID,
                    reason="成员必须明确确认关怀模式",
                    operands={"memberKey": participant.member_key, "careDraft": None},
                ))
                continue
            try:
                profiles.append((owner, assistance_profile_from_care(participant.care_draft)))
            except (ValueError, ValidationError, AssistanceConstraintCompileError) as error:
                issues.append(_issue(
                    field_path=path,
                    participant_id=owner,
                    related=(),
                    rule_id="S2T003.CARE.PROFILE_INVALID",
                    code=IssueCode.INVALID,
                    reason="已确认的关怀资料无法构建严格 AssistanceProfile",
                    operands={"memberKey": participant.member_key, "error": type(error).__name__},
                ))
        if issues:
            return tuple(issues)
        try:
            merged = merge_group_constraints(tuple(profiles))
        except GroupConstraintMergeError as error:
            primary, *related = error.participant_ids
            return (_issue(
                field_path="participants",
                participant_id=primary,
                related=tuple(related),
                rule_id="S2T003.CARE.CONSTRAINT_MERGE_UNSUPPORTED",
                code=IssueCode.CONFLICT,
                reason=f"关怀硬约束 {error.field} 无法确定性合并",
                operands={"field": error.field, "participants": [str(value) for value in error.participant_ids]},
            ),)
        nap = next((item for item in merged.constraints if item.field == FIELD_NAP_WINDOW), None)
        trip = revision.understanding.trip
        if (
            nap is not None
            and trip.start_time is not None
            and trip.end_time is not None
            and _time(nap.value["start"]) <= _time(trip.start_time)
            and _time(nap.value["end"]) >= _time(trip.end_time)
        ):
            key = "napWindow|BLOCK|DAY|HARD"
            contributors = merged.contributors[key]
            primary, *related = contributors
            return (_issue(
                field_path="trip.endTime",
                participant_id=primary,
                related=tuple(related),
                rule_id="S2T003.TIME.BLOCKS_ALL_DAY",
                code=IssueCode.CONFLICT,
                reason="合并后的硬休息窗口覆盖全部可用出行时间",
                operands={"trip": [trip.start_time, trip.end_time], "nap": nap.value},
                relaxation_specs=(
                    (RelaxationAction.EXTEND_SHARED_TIME, ActorScope.ORGANIZER, None,
                     "trip.endTime", None, "由组织者扩展共享出行时间"),
                ),
            ),)
        return ()

    def _binding_issues(
        self,
        revision: TripDraftRevisionView,
        organizer_participant_id: UUID | None,
    ) -> tuple[CollaborationIssue, ...]:
        proposal_keys = [item.member_key for item in revision.understanding.participants]
        expected = [f"member-{index}" for index in range(1, len(proposal_keys) + 1)]
        binding_keys = sorted(revision.member_bindings)
        values = list(revision.member_bindings.values())
        valid = (
            proposal_keys == expected
            and binding_keys == expected
            and len(set(values)) == len(values)
            and (
                organizer_participant_id is None
                or revision.member_bindings.get("member-1") == organizer_participant_id
            )
        )
        if valid:
            return ()
        return (_issue(
            field_path="participants",
            participant_id=None,
            related=tuple(sorted(set(values), key=str)),
            rule_id=BASE_RULES["binding"],
            code=IssueCode.INVALID,
            reason="成员绑定必须连续、唯一且保持组织者 member-1 不变",
            operands={"proposalKeys": proposal_keys, "bindingKeys": binding_keys},
        ),)

    def _proposal_input_issues(
        self,
        revision: TripDraftRevisionView,
    ) -> tuple[CollaborationIssue, ...]:
        issues: list[CollaborationIssue] = []
        for missing in revision.understanding.missing_fields:
            owner = revision.member_bindings.get(missing.member_key) if missing.member_key else None
            issues.append(_issue(
                field_path=missing.field_path,
                participant_id=owner,
                related=(),
                rule_id=BASE_RULES["missing"],
                code=IssueCode.MISSING,
                reason=f"字段缺失，需要完成问题 {missing.question_key}",
                operands={"questionKey": missing.question_key, "memberKey": missing.member_key},
            ))
        for ambiguity in revision.understanding.ambiguities:
            owner = revision.member_bindings.get(ambiguity.member_key) if ambiguity.member_key else None
            scope = ActorScope.PARTICIPANT if owner else ActorScope.ORGANIZER
            issues.append(_issue(
                field_path=ambiguity.field_path,
                participant_id=owner,
                related=(),
                rule_id=BASE_RULES["ambiguous"],
                code=IssueCode.AMBIGUOUS,
                reason=ambiguity.reason,
                operands={"candidates": ambiguity.candidates, "memberKey": ambiguity.member_key},
                candidates=tuple(ambiguity.candidates),
                relaxation_specs=tuple(
                    (
                        RelaxationAction.SELECT_CANDIDATE,
                        scope,
                        owner,
                        ambiguity.field_path,
                        candidate,
                        f"确认选择 {candidate}",
                    )
                    for candidate in ambiguity.candidates
                ),
            ))
        return tuple(issues)

    def _time_issues(
        self,
        revision: TripDraftRevisionView,
    ) -> tuple[CollaborationIssue, ...]:
        start = revision.understanding.trip.start_time
        end = revision.understanding.trip.end_time
        if start is None or end is None or _time(end) > _time(start):
            return ()
        return (_issue(
            field_path="trip.endTime",
            participant_id=None,
            related=(),
            rule_id=BASE_RULES["time"],
            code=IssueCode.INVALID,
            reason="结束时间必须晚于开始时间",
            operands={"start": start, "end": end},
            relaxation_specs=(
                (RelaxationAction.SET_SHARED_FIELD, ActorScope.ORGANIZER, None,
                 "trip.endTime", None, "由组织者修改结束时间"),
            ),
        ),)

    def _budget_issues(
        self,
        revision: TripDraftRevisionView,
    ) -> tuple[CollaborationIssue, ...]:
        shared = revision.understanding.trip.budget_cents
        if shared is None:
            return ()
        issues: list[CollaborationIssue] = []
        for index, participant in enumerate(revision.understanding.participants):
            cap = participant.budget_cap_cents
            if cap is None or cap >= shared:
                continue
            owner = revision.member_bindings[participant.member_key]
            path = f"participants[{index}].budgetCapCents"
            issues.append(_issue(
                field_path=path,
                participant_id=owner,
                related=(),
                rule_id=BASE_RULES["budget"],
                code=IssueCode.CONFLICT,
                reason="成员预算上限低于共享预算，不能静默收紧",
                operands={"sharedBudget": shared, "memberCap": cap},
                relaxation_specs=(
                    (RelaxationAction.LOWER_SHARED_BUDGET, ActorScope.ORGANIZER, None,
                     "trip.budgetCents", cap, "由组织者降低共享预算"),
                    (RelaxationAction.RAISE_MEMBER_BUDGET_CAP, ActorScope.PARTICIPANT,
                     owner, path, shared, "由该成员提高个人预算上限"),
                ),
            ))
        return tuple(issues)

    def _place_issues(
        self,
        revision: TripDraftRevisionView,
    ) -> tuple[CollaborationIssue, ...]:
        must: list[tuple[str, UUID, str]] = []
        avoid: list[tuple[str, UUID, str]] = []
        for index, participant in enumerate(revision.understanding.participants):
            owner = revision.member_bindings[participant.member_key]
            must.extend(
                (_normalized_place(value), owner, f"participants[{index}].mustVisit[{item_index}]")
                for item_index, value in enumerate(participant.must_visit)
            )
            avoid.extend(
                (_normalized_place(value), owner, f"participants[{index}].avoidPlaces[{item_index}]")
                for item_index, value in enumerate(participant.avoid_places)
            )
        issues: list[CollaborationIssue] = []
        for must_value, must_owner, must_path in must:
            for avoid_value, avoid_owner, avoid_path in avoid:
                if must_value != avoid_value:
                    continue
                related = () if must_owner == avoid_owner else (must_owner,)
                issues.append(_issue(
                    field_path=avoid_path,
                    participant_id=avoid_owner,
                    related=related,
                    rule_id=BASE_RULES["place"],
                    code=IssueCode.CONFLICT,
                    reason="同一地点同时被设为必去和避开",
                    operands={"place": must_value, "mustPath": must_path, "avoidPath": avoid_path},
                    relaxation_specs=(
                        (RelaxationAction.REMOVE_MUST_VISIT, ActorScope.PARTICIPANT,
                         must_owner, must_path, None, "由字段所有者移除必去限制"),
                        (RelaxationAction.REMOVE_AVOID_PLACE, ActorScope.PARTICIPANT,
                         avoid_owner, avoid_path, None, "由字段所有者移除避开限制"),
                    ),
                ))
        return tuple(issues)


__all__ = ["BASE_RULES", "DeterministicHardConflictEvaluator"]
