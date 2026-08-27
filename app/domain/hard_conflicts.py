from __future__ import annotations

from datetime import time
from unicodedata import normalize
from uuid import UUID

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
