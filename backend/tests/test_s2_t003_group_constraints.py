from uuid import uuid4

import pytest

from app.schemas.assistance import low_stamina_profile, ordinary_profile
from app.schemas.constraint import Constraint
from app.schemas.trip import WalkLimits
from app.services.planning.group_constraints import (
    GroupConstraintMergeError,
    merge_group_constraints,
)


def test_group_merge_keeps_strictest_numeric_limits_and_contributors() -> None:
    first_id, second_id = uuid4(), uuid4()
    first = low_stamina_profile().model_copy(
        update={"walk_limits": WalkLimits(maxContinuousMeters=500, maxDailyMeters=3000),
                "max_transfers": 0, "rest_interval": 60}
    )
    second = low_stamina_profile().model_copy(
        update={"walk_limits": WalkLimits(maxContinuousMeters=1000, maxDailyMeters=5000),
                "max_transfers": 2, "rest_interval": 90}
    )
    merged = merge_group_constraints(((first_id, first), (second_id, second)))
    values = {item.field: item.value for item in merged.constraints}
    assert values["walkLimits.maxContinuousMeters"] == 500
    assert values["maxTransfers"] == 0
    assert values["restInterval"] == 60
    assert merged.contributors["walkLimits.maxContinuousMeters|LTE|ROUTE_SEGMENT|HARD"] == tuple(
        sorted((first_id, second_id), key=str)
    )


def test_group_merge_reports_nonmergeable_field_and_participants() -> None:
    first_id, second_id = uuid4(), uuid4()

    class StubCompiler:
        def compile(self, profile):
            return (
                Constraint(
                    field="customHardField",
                    operator="EQ",
                    value=profile.max_transfers,
                    scope="DAY",
                    hardness="HARD",
                ),
            )

    first = ordinary_profile().model_copy(update={"max_transfers": 1})
    second = ordinary_profile().model_copy(update={"max_transfers": 2})
    with pytest.raises(GroupConstraintMergeError) as captured:
        merge_group_constraints(
            ((first_id, first), (second_id, second)),
            compiler=StubCompiler(),
        )
    assert captured.value.field == "customHardField"
    assert captured.value.participant_ids == tuple(
        sorted((first_id, second_id), key=str)
    )
