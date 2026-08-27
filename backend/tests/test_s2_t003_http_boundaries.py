from __future__ import annotations

from app.api.collaboration_routes import router


def test_collaboration_route_table_contains_only_scoped_frozen_paths() -> None:
    paths = {(route.path, method) for route in router.routes for method in route.methods}
    expected = {
        ("/api/v2/trips/conversations", "POST"),
        ("/api/v2/trips/{trip_id}/participants/{participant_id}/invitations", "POST"),
        ("/api/v2/participant-invitations/redeem", "POST"),
        ("/api/v2/member-session", "GET"),
        ("/api/v2/member-session/conversation", "PUT"),
        ("/api/v2/member-session/confirm", "POST"),
        ("/api/v2/member-session/confirmation-items/{item_id}/resolve", "POST"),
        ("/api/v2/trips/{trip_id}/participants/{participant_id}/confirm", "POST"),
        ("/api/v2/trips/{trip_id}/collaboration", "GET"),
        ("/api/v2/trips/{trip_id}/confirmation-items/{item_id}/resolve", "POST"),
        ("/api/v2/trips/{trip_id}/participants/{participant_id}/invitations/{invitation_id}", "DELETE"),
    }
    assert expected <= paths
    assert not any("{token}" in path for path, _ in paths)
    assert not any("/conflicts/" in path for path, _ in paths)
