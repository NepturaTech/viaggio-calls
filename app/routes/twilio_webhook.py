import logging
from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import Response
from twilio.base.exceptions import TwilioRestException

from app.config import get_settings
from app.services.twilio_service import (
    generate_conversation_relay_twiml,
    generate_realtime_stream_twiml,
    hangup_call,
    make_outbound_call,
)
from app.db.repositories import store_pending_call_params, register_call_patient, get_call_patient, human_has_spoken
from app.services.call_log_service import create_call_record
from app.services.customer_service import get_customer_context
from app.services.prompt_service import get_welcome_greeting
from app.services.audio_archive_service import delete_call_archive, store_twilio_recording
from app.services.supabase_rest_service import get_active_call_script


def _build_call_purpose(registry: dict | None) -> str:
    """Construye el texto del propósito de la llamada para el custom field de ManyChat.

    Usa el script_name del registro para obtener el nombre y proyecto del script activo.
    Ejemplo: "Seguimiento — Proyecto de diabetes mellitus tipo 2"
    """
    if not registry:
        return "Llamada de seguimiento del equipo de salud"
    script_name = (registry.get("script_name") or "default").strip()
    try:
        script = get_active_call_script(script_name)
        if script:
            name = (script.get("name") or script_name).strip()
            project = (script.get("project_name") or "").strip()
            if project:
                return f"{name} — {project}"
            return name
    except Exception:
        pass
    return script_name or "Llamada de seguimiento"
from app.services.manychat_service import trigger_no_answer_flow

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
    script_name = request.query_params.get("script_name", "default")
    # patient_name puede venir como query param cuando se inicia la llamada desde el frontend
    # y el paciente no está registrado en la BD (fallback de nombre para el saludo).
    patient_name_param = (request.query_params.get("patient_name") or "").strip()
    # manychat_user_id puede venir como query param desde /calls/trigger (subscriber_id del JSON)
    manychat_user_id_param = (request.query_params.get("manychat_user_id") or "").strip()

    # Look up customer in manual data / Supabase
    customer, _ = get_customer_context(customer_phone)

    # Si no se encontró en la BD pero se pasaron datos como parámetros, construir un
    # cliente mínimo para que el saludo, el prompt y el contexto del dataset usen
    # el nombre y documento correctos.
    patient_doc_param = (request.query_params.get("patient_document_number") or "").strip()
    if not customer and (patient_name_param or patient_doc_param):
        customer = {
            "id": None,
            "full_name": patient_name_param or None,
            "phone_number": customer_phone,
            "document_number": patient_doc_param or None,
            "hospital_name": None,
            "project_name": None,
            "source": "param",
        }
        logger.info(
            "Using param patient: name=%s document_number=%s for call %s",
            patient_name_param,
            patient_doc_param,
            CallSid,
        )

    # Create call record (in-memory)
    create_call_record(
        twilio_call_sid=CallSid,
        direction=direction,
        customer_id=customer["id"] if customer else None,
    )

    # Si el paciente fue construido desde params (no existe en BD), guardar en la caché
    # para que el WebSocket handler lo recupere durante _load_session_context.
    if customer and customer.get("source") == "param":
        store_pending_call_params(CallSid, customer)

    # Get active script for the welcome greeting
    script = get_active_call_script(script_name)

    # Registrar paciente+script para que store_twilio_recording use el nombre correcto
    # aunque el WebSocket se cierre antes de crear el CallAudioArchive.
    # subscriber_id: prioridad → query param (viene de /calls/trigger) → base de datos
    _manychat_id = manychat_user_id_param or (customer.get("manychat_user_id") if customer else None)
    register_call_patient(
        CallSid,
        patient_name=customer.get("full_name") if customer else None,
        patient_id=str(customer.get("document_number") or "") if customer else None,
        script_name=script_name,
        patient_phone=customer_phone,
        manychat_user_id=_manychat_id or None,
    )
    if _manychat_id:
        logger.info("manychat_user_id registrado para call %s: %s", CallSid, _manychat_id)
    welcome = get_welcome_greeting(script, customer)
    logger.info(
        "Call context prepared: customer=%s script=%s voice_mode=%s welcome=%s",
        {
            "full_name": customer.get("full_name") if customer else None,
            "phone_number": customer.get("phone_number") if customer else customer_phone,
            "hospital_name": customer.get("hospital_name") if customer else None,
            "project_name": customer.get("project_name") if customer else None,
            "source": customer.get("source") if customer else None,
        },
        {
            "name": script.get("name") if script else None,
            "project_name": script.get("project_name") if script else None,
            "requested_script_name": script_name,
        },
        settings.twilio_voice_mode,
        welcome,
    )

    # Return TwiML using the configured voice mode
    if settings.twilio_voice_mode == "realtime":
        try:
            twiml = generate_realtime_stream_twiml(
                customer_phone=customer_phone,
                customer_name=customer["full_name"] if customer else None,
                direction=direction,
                script_name=script_name,
                welcome_greeting=welcome,
            )
        except Exception:
            logger.exception("Realtime mode TwiML generation failed; falling back to ConversationRelay")
            twiml = generate_conversation_relay_twiml(welcome_greeting=welcome, script_name=script_name)
    else:
        twiml = generate_conversation_relay_twiml(welcome_greeting=welcome, script_name=script_name)
    return Response(content=twiml, media_type="application/xml")


@router.post("/status")
async def handle_call_status(
    request: Request,
    CallSid: str = Form(...),
    CallStatus: str = Form(...),
    CallDuration: str = Form(None),
):
    """Handle Twilio call status callbacks."""
    import asyncio
    logger.info("Call status update: SID=%s, Status=%s, Duration=%s", CallSid, CallStatus, CallDuration)
    normalized = (CallStatus or "").strip().lower()
    if normalized in {"no-answer", "busy", "failed", "canceled"}:
        delete_call_archive(CallSid)
        # Disparar flow de ManyChat si el paciente no contestó
        if normalized == "no-answer":
            registry = get_call_patient(CallSid)
            phone = (registry or {}).get("patient_phone", "")
            manychat_user_id = (registry or {}).get("manychat_user_id", "")
            if phone or manychat_user_id:
                call_purpose = _build_call_purpose(registry)
                logger.info(
                    "ManyChat no-answer flow: disparando para phone=%s manychat_user_id=%s purpose='%s' sid=%s",
                    phone, manychat_user_id, call_purpose, CallSid,
                )
                asyncio.create_task(
                    trigger_no_answer_flow(
                        phone,
                        reason="no_answer",
                        manychat_user_id=manychat_user_id or None,
                        call_purpose=call_purpose,
                    )
                )
            else:
                logger.info("ManyChat no-answer flow: sin teléfono ni manychat_user_id para sid=%s", CallSid)
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

    import asyncio

    # Casos definitivos de buzón de voz — colgar siempre:
    #   machine_end_beep    → contestador con beep (buzón seguro)
    #   machine_end_silence → contestador sin beep (mensaje grabado corto)
    #   fax                 → señal de fax
    #
    # machine_start: puede ser falso positivo cuando ElevenLabs habla primero
    # (AMD confunde la voz sintetizada con una máquina). Solo colgamos si el
    # humano AÚN NO ha hablado — si ya interactuó, ignoramos el resultado.
    definitive_voicemail = {"machine_end_beep", "machine_end_silence", "fax"}

    # machine_start sin turno humano previo → probable buzón de voz real
    if answered_by == "machine_start" and not human_has_spoken(CallSid):
        logger.info(
            "AMD machine_start sin turno humano — probable buzón. Colgando. sid=%s", CallSid
        )
        definitive_voicemail = definitive_voicemail | {"machine_start"}

    if answered_by in definitive_voicemail:
        try:
            hangup_call(CallSid)
            delete_call_archive(CallSid)
            logger.info("Call %s colgada por voicemail AMD (%s)", CallSid, answered_by)
            # Disparar flow de ManyChat para buzón de voz
            registry = get_call_patient(CallSid)
            phone = (registry or {}).get("patient_phone", "")
            manychat_user_id = (registry or {}).get("manychat_user_id", "")
            if phone or manychat_user_id:
                call_purpose = _build_call_purpose(registry)
                logger.info(
                    "ManyChat voicemail flow: disparando para phone=%s manychat_user_id=%s purpose='%s' sid=%s",
                    phone, manychat_user_id, call_purpose, CallSid,
                )
                asyncio.create_task(
                    trigger_no_answer_flow(
                        phone,
                        reason="voicemail",
                        manychat_user_id=manychat_user_id or None,
                        call_purpose=call_purpose,
                    )
                )
            return {"status": "hung_up", "answered_by": answered_by}
        except Exception:
            logger.exception("Failed to hang up voicemail call %s after AMD result %s", CallSid, answered_by)
            raise HTTPException(status_code=500, detail="No se pudo colgar la llamada detectada como buzon") from None

    logger.info("AMD result ignored (not definitive voicemail): %s", answered_by)
    return {"status": "ignored", "answered_by": answered_by}


@router.post("/outbound")
async def trigger_outbound_call(
    to_number: str,
    script_name: str = "default",
    patient_name: str = "",
    patient_document_number: str = "",
):
    """Trigger an outbound call to a specific number.

    Args:
        to_number: Phone number to call (E.164 format, e.g. +573001234567).
        script_name: Name of the script to use.
        patient_name: Nombre del paciente — fallback de saludo si no está en la BD.
        patient_document_number: Número de identificación (cédula) — permite buscar
            datos del paciente en el dataset Viaggio (identificacion) aunque no esté
            registrado en call_patients.
    """
    try:
        call_sid = await make_outbound_call(
            to_number,
            script_name,
            patient_name=patient_name,
            patient_document_number=patient_document_number,
        )
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
    # Registrar paciente para store_twilio_recording (fallback cuando no hay archive)
    _patient_name = (customer.get("full_name") if customer else None) or patient_name or None
    _patient_id = (str(customer.get("document_number") or "") if customer else None) or patient_document_number or None
    _manychat_user_id = customer.get("manychat_user_id") if customer else None
    register_call_patient(
        call_sid,
        patient_name=_patient_name,
        patient_id=_patient_id,
        script_name=script_name,
        patient_phone=to_number,
        manychat_user_id=_manychat_user_id,
    )

    return {"call_sid": call_sid, "to": to_number, "script": script_name, "status": "initiated"}


@router.post("/recording-status")
async def handle_recording_status(
    CallSid: str = Form(...),
    RecordingSid: str = Form(""),
    RecordingStatus: str = Form(""),
    RecordingUrl: str = Form(""),
    RecordingChannels: str = Form(""),
):
    """Handle Twilio recording callbacks for conversation relay recordings."""
    logger.info(
        "Recording status update: CallSid=%s RecordingSid=%s Status=%s Channels=%s",
        CallSid,
        RecordingSid,
        RecordingStatus,
        RecordingChannels,
    )

    normalized_status = (RecordingStatus or "").strip().lower()
    # Solo procesar grabaciones completas — "in-progress" son parciales (cada 60s)
    # y no vale la pena descargarlas ni subirlas a Supabase.
    if RecordingUrl and normalized_status == "completed":
        store_twilio_recording(
            call_sid=CallSid,
            recording_url=RecordingUrl,
            recording_sid=RecordingSid or None,
            recording_status=RecordingStatus or None,
        )

    return {"status": "received"}
