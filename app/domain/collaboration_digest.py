from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from app.application.collaboration_ports import TripDraftRevisionView


POLICY_VERSION = "S2-T003.1"


def _json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=True, exclude_none=False)
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        _json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def shared_digest(revision: TripDraftRevisionView) -> str:
    return canonical_sha256(
        {
            "trip": revision.understanding.trip,
            "memberKeys": sorted(revision.member_bindings),
        }
    )


def member_digest(revision: TripDraftRevisionView, member_key: str) -> str:
    participant = next(
        item for item in revision.understanding.participants
        if item.member_key == member_key
    )
    return canonical_sha256(
        {
            "memberKey": member_key,
            "participantId": str(revision.member_bindings[member_key]),
            "participant": participant,
        }
    )


def readiness_digest(
    revision: TripDraftRevisionView,
    confirmation_digests: Mapping[str, str],
) -> str:
    return canonical_sha256(
        {
            "policyVersion": POLICY_VERSION,
            "draftId": str(revision.draft_id),
            "revision": revision.revision,
            "sourceDigest": revision.source_digest,
            "bindings": {
                key: str(revision.member_bindings[key])
                for key in sorted(revision.member_bindings)
            },
            "confirmations": {
                key: confirmation_digests[key]
                for key in sorted(confirmation_digests)
            },
            "issues": [],
        }
    )


__all__ = [
    "POLICY_VERSION",
    "canonical_sha256",
    "member_digest",
    "readiness_digest",
    "shared_digest",
]
