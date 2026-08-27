from uuid import UUID
from fastapi import APIRouter, Depends, Request
from app.application.collaboration_service import CollaborationService
from app.domain.collaboration import ConflictResolution, ConversationSubmission
from app.domain.models import ApiResponse

router = APIRouter(prefix="/api/v2", tags=["S2 对话式多人协作"])
def service(request: Request) -> CollaborationService: return request.app.state.collaboration_service

@router.post("/trips/conversations")
async def create_organizer(payload: ConversationSubmission, current: CollaborationService = Depends(service)) -> ApiResponse: return ApiResponse(data=await current.create_organizer(payload))
@router.post("/trips/{trip_id}/participants/invitations")
async def create_invitation(trip_id: UUID, request: Request, current: CollaborationService = Depends(service)) -> ApiResponse: return ApiResponse(data=current.invite(trip_id, request.headers.get("X-Organizer-Token")))
@router.get("/participant-invitations/{token}")
async def invitation(token: str, current: CollaborationService = Depends(service)) -> ApiResponse: return ApiResponse(data=current.invitation(token))
@router.put("/participant-invitations/{token}/conversation")
async def submit_member(token: str, payload: ConversationSubmission, current: CollaborationService = Depends(service)) -> ApiResponse: return ApiResponse(data=await current.submit_member(token, payload))
@router.post("/participant-invitations/{token}/confirm")
async def confirm_member(token: str, current: CollaborationService = Depends(service)) -> ApiResponse: return ApiResponse(data=current.confirm_member(token))
@router.delete("/trips/{trip_id}/participants/{participant_id}/invitations")
async def revoke_invitation(trip_id: UUID, participant_id: UUID, request: Request, current: CollaborationService = Depends(service)) -> ApiResponse: return ApiResponse(data=current.revoke_invitation(trip_id, participant_id, request.headers.get("X-Organizer-Token")))
@router.post("/trips/{trip_id}/conflicts/{conflict_id}/resolve")
async def resolve_conflict(trip_id: UUID, conflict_id: str, payload: ConflictResolution, request: Request, current: CollaborationService = Depends(service)) -> ApiResponse: return ApiResponse(data=current.resolve_conflict(trip_id, conflict_id, payload.relaxation, request.headers.get("X-Organizer-Token")))
@router.get("/trips/{trip_id}/collaboration")
async def state(trip_id: UUID, current: CollaborationService = Depends(service)) -> ApiResponse: return ApiResponse(data=current.state(trip_id))
