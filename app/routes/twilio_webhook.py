import logging
from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import Response
from twilio.base.exceptions import TwilioRestException

from app.config import get_settings
from app.db.repositories import CallScriptRepository
from app.services.twilio_service import (
    generate_conversation_relay_twiml,
    generate_realtime_stream_twiml,
    hangup_call,
    make_outbound_call,
)
from app.services.call_log_service import create_call_record
from app.services.customer_service import get_customer_context
from app.services.prompt_service import get_welcome_greeting
from app.services.audio_archive_service import delete_call_archive

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(tags=["twilio"])


@router.post("/voice")
async def handle_incoming_call(
    request: Request,
    CallSid: str = Form(...),
    From: str = Form(...),
    To: str = Form(...),
    CallStatus: str = Form("ringing"),
):
    """Handle incoming Twilio voice call — connect to ConversationRelay."""
    logger.info("Incoming call: SID=%s, From=%s, To=%s, Status=%s", CallSid, From, To, CallStatus)

    customer_phone = To if From == settings.twilio_phone_number else From
    direction = "outbound" if From == settings.twilio_phone_number else "inbound"

    # Look up customer in manual data
    customer, _ = get_customer_context(customer_phone)

    # Create call record (in-memory)
    create_call_record(
        twilio_call_sid=CallSid,
        direction=direction,
        customer_id=customer["id"] if customer else None,
    )

    # Get active script for the welcome greeting
    script_repo = CallScriptRepository()
    script = script_repo.get_active_script("default")
    welcome = get_welcome_greeting(script, customer)

    # Return TwiML using the configured voice mode
    if settings.twilio_voice_mode == "realtime":
        try:
            twiml = generate_realtime_stream_twiml(
                customer_phone=customer_phone,
                customer_name=customer["full_name"] if customer else None,
                direction=direction,
                welcome_greeting=welcome,
            )
        except Exception:
            logger.exception("Realtime mode TwiML generation failed; falling back to ConversationRelay")
            twiml = generate_conversation_relay_twiml(welcome_greeting=welcome)
    else:
        twiml = generate_conversation_relay_twiml(welcome_greeting=welcome)
    return Response(content=twiml, media_type="application/xml")


@router.post("/status")
async def handle_call_status(
    request: Request,
    CallSid: str = Form(...),
    CallStatus: str = Form(...),
    CallDuration: str = Form(None),
):
    """Handle Twilio call status callbacks."""
    logger.info("Call status update: SID=%s, Status=%s, Duration=%s", CallSid, CallStatus, CallDuration)
    normalized = (CallStatus or "").strip().lower()
    if normalized in {"no-answer", "busy", "failed", "canceled"}:
        delete_call_archive(CallSid)
    return {"status": "received"}


@router.post("/amd")
async def handle_answering_machine_detection(
    CallSid: str = Form(...),
    AnsweredBy: str = Form("unknown"),
    MachineDetectionDuration: str = Form(default=""),
):
    """Handle Twilio async answering machine detection and hang up on voicemail."""
    answered_by = (AnsweredBy or "unknown").strip().lower()
    logger.info(
        "AMD result: SID=%s, AnsweredBy=%s, Duration=%s",
        CallSid,
        answered_by,
        MachineDetectionDuration,
    )

    if any(token in answered_by for token in ("machine", "fax")):
        try:
            hangup_call(CallSid)
            delete_call_archive(CallSid)
            logger.info("Call %s completed early due to voicemail detection (%s)", CallSid, answered_by)
            return {"status": "hung_up", "answered_by": answered_by}
        except Exception:
            logger.exception("Failed to hang up voicemail call %s after AMD result %s", CallSid, answered_by)
            raise HTTPException(status_code=500, detail="No se pudo colgar la llamada detectada como buzon") from None

    return {"status": "ignored", "answered_by": answered_by}


@router.post("/outbound")
async def trigger_outbound_call(
    to_number: str,
    script_name: str = "default",
):
    """Trigger an outbound call to a specific number.

    Args:
        to_number: Phone number to call (E.164 format, e.g. +573001234567).
        script_name: Name of the script to use.
    """
    try:
        call_sid = await make_outbound_call(to_number)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TwilioRestException as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Twilio rechazó la llamada: {exc.msg}",
        ) from exc

    customer, _ = get_customer_context(to_number)
    create_call_record(
        twilio_call_sid=call_sid,
        direction="outbound",
        customer_id=customer["id"] if customer else None,
    )

    return {"call_sid": call_sid, "to": to_number, "script": script_name, "status": "initiated"}
