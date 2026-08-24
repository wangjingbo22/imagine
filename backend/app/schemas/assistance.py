from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import time
from types import MappingProxyType

from .trip import AssistanceProfile, AssistanceType, NapWindow, WalkLimits


def ordinary_profile() -> AssistanceProfile:
    return AssistanceProfile(
        type=AssistanceType.ORDINARY,
        child_age=None,
        walk_limits=WalkLimits(
            max_continuous_meters=None,
            max_daily_meters=None,
        ),
        max_transfers=None,
        rest_interval=None,
        nap_window=None,
        avoid_stairs=False,
    )


def parent_child_profile() -> AssistanceProfile:
    return AssistanceProfile(
        type=AssistanceType.PARENT_CHILD,
        child_age=None,
        walk_limits=WalkLimits(
            max_continuous_meters=None,
            max_daily_meters=None,
        ),
        max_transfers=None,
        rest_interval=None,
        nap_window=NapWindow(start=time(13, 0), end=time(14, 0)),
        avoid_stairs=False,
    )


def low_stamina_profile() -> AssistanceProfile:
    return AssistanceProfile(
        type=AssistanceType.LOW_STAMINA,
        child_age=None,
        walk_limits=WalkLimits(
            max_continuous_meters=500,
            max_daily_meters=None,
        ),
        max_transfers=2,
        rest_interval=90,
        nap_window=None,
        avoid_stairs=False,
    )


def mobility_assistance_beta_profile() -> AssistanceProfile:
    return AssistanceProfile(
        type=AssistanceType.MOBILITY_ASSISTANCE_BETA,
        child_age=None,
        walk_limits=WalkLimits(
            max_continuous_meters=None,
            max_daily_meters=None,
        ),
        max_transfers=None,
        rest_interval=None,
        nap_window=None,
        avoid_stairs=True,
    )


ProfileFactory = Callable[[], AssistanceProfile]

PROFILE_FACTORIES: Mapping[AssistanceType, ProfileFactory] = MappingProxyType(
    {
        AssistanceType.ORDINARY: ordinary_profile,
        AssistanceType.PARENT_CHILD: parent_child_profile,
        AssistanceType.LOW_STAMINA: low_stamina_profile,
        AssistanceType.MOBILITY_ASSISTANCE_BETA: mobility_assistance_beta_profile,
    }
)


def create_assistance_profile(profile_type: AssistanceType) -> AssistanceProfile:
    """Return a fresh profile so callers cannot mutate shared preset state."""

    return PROFILE_FACTORIES[profile_type]()


__all__ = [
    "PROFILE_FACTORIES",
    "ProfileFactory",
    "create_assistance_profile",
    "low_stamina_profile",
    "mobility_assistance_beta_profile",
    "ordinary_profile",
    "parent_child_profile",
]
