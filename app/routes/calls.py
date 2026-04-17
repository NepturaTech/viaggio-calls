from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from twilio.base.exceptions import TwilioRestException

from app.services.call_log_service import create_call_record
from app.services.customer_service import get_customer_context
from app.services.call_log_service import get_call_with_events, list_calls
from app.services.twilio_service import make_outbound_call

router = APIRouter(tags=["calls"])


class CallTriggerRequest(BaseModel):
    phone_number: str
    patient_name: str | None = None
    source: str | None = "frontend"
    script_name: str | None = "default"


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


@router.post("/trigger")
async def trigger_call(payload: CallTriggerRequest):
    """Trigger an outbound call from the admin frontend using JSON."""
    try:
        call_sid = await make_outbound_call(payload.phone_number, payload.script_name or "default")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TwilioRestException as exc:
        raise HTTPException(status_code=502, detail=f"Twilio rechazo la llamada: {exc.msg}") from exc

    customer, _ = get_customer_context(payload.phone_number)
    create_call_record(
        twilio_call_sid=call_sid,
        direction="outbound",
        customer_id=customer["id"] if customer else None,
    )

    return {
        "status": "initiated",
        "call_sid": call_sid,
        "to": payload.phone_number,
        "patient_name": (customer or {}).get("full_name") or payload.patient_name,
        "source": payload.source,
        "script_name": payload.script_name or "default",
    }
