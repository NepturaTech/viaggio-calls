from fastapi import APIRouter, HTTPException

from app.services.call_log_service import get_call_with_events, list_calls

router = APIRouter(tags=["calls"])


@router.get("/")
async def get_calls():
    """List in-memory calls for QA and debugging."""
    return list_calls()


@router.get("/{call_sid}")
async def get_call(call_sid: str):
    """Get one call with events and transcript lines."""
    call = get_call_with_events(call_sid)
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    return call
