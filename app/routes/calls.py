from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from twilio.base.exceptions import TwilioRestException

from app.services.call_log_service import create_call_record
from app.services.customer_service import get_customer_context
from app.services.call_log_service import get_call_with_events, list_calls
from app.services.twilio_service import make_outbound_call
from app.db.repositories import register_call_patient, record_call_attempt, is_in_cooldown

router = APIRouter(tags=["calls"])


class CallTriggerRequest(BaseModel):
    phone_number: str
    patient_name: str | None = None
    patient_document_number: str | None = None
    # patient_id: alias para patient_document_number (compatibilidad con frontend Lovable)
    patient_id: str | None = None
    # subscriber_id: ManyChat subscriber ID — se guarda para disparar flow si no contesta
    subscriber_id: str | None = None
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
    # patient_id es alias de patient_document_number (el frontend Lovable envía patient_id)
    doc_number = payload.patient_document_number or payload.patient_id or ""

    # Cooldown: rechazar si el mismo número recibió una llamada hace menos de 5 min.
    # Previene que el flow de ManyChat (u otro sistema externo) dispare una re-llamada
    # automática justo después de enviar el mensaje de "no contestó".
    in_cd, remaining = is_in_cooldown(payload.phone_number)
    if in_cd:
        logger.warning(
            "trigger_call rechazado por cooldown: phone=%s, faltan %ds",
            payload.phone_number,
            remaining,
        )
        raise HTTPException(
            status_code=429,
            detail=f"Este número recibió una llamada hace menos de 5 minutos. "
                   f"Espera {remaining} segundos antes de volver a llamar.",
        )

    try:
        call_sid = await make_outbound_call(
            payload.phone_number,
            payload.script_name or "default",
            patient_name=payload.patient_name or "",
            patient_document_number=doc_number,
            manychat_user_id=payload.subscriber_id or "",
            call_source=payload.source or "frontend",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TwilioRestException as exc:
        raise HTTPException(status_code=502, detail=f"Twilio rechazo la llamada: {exc.msg}") from exc

    # Registrar el intento para que el cooldown proteja las próximas 5 minutos
    record_call_attempt(payload.phone_number)

    customer, _ = get_customer_context(payload.phone_number)
    create_call_record(
        twilio_call_sid=call_sid,
        direction="outbound",
        customer_id=customer["id"] if customer else None,
        call_source=payload.source or "frontend",
    )

    # Registrar subscriber_id en el registry para que esté disponible inmediatamente
    # si el paciente no contesta (antes de que /voice lo registre)
    if payload.subscriber_id:
        register_call_patient(
            call_sid,
            patient_name=payload.patient_name or (customer or {}).get("full_name"),
            patient_id=doc_number or None,
            script_name=payload.script_name or "default",
            patient_phone=payload.phone_number,
            manychat_user_id=payload.subscriber_id,
        )

    resolved_name = (customer or {}).get("full_name") or payload.patient_name
    return {
        "status": "initiated",
        "call_sid": call_sid,
        "to": payload.phone_number,
        "patient_name": resolved_name,
        "patient_document_number": doc_number or None,
        "subscriber_id": payload.subscriber_id,
        "source": payload.source,
        "script_name": payload.script_name or "default",
    }
