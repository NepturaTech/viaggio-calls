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
from app.db.repositories import store_pending_call_params, register_call_patient, get_call_patient, human_has_spoken, record_call_attempt, is_in_cooldown, mark_call_active, mark_call_ended, active_call_count
from app.services.call_log_service import create_call_record, mark_call_not_answered, was_call_not_answered
from app.services.customer_service import get_customer_context
from app.services.prompt_service import get_welcome_greeting
from app.services.audio_archive_service import delete_call_archive, store_twilio_recording
from app.services.supabase_rest_service import (
    get_active_call_script,
    get_active_call_script_cached,
    find_patient_from_warm_cache,
)


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
from app.services.manychat_service import trigger_no_answer_flow, trigger_reactivation_flow
from app.utils.normalization import is_reactivation_script

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
    """Handle incoming Twilio voice call — connect to ConversationRelay.

    CRÍTICO DE LATENCIA: este handler debe devolver el TwiML en <200 ms.
    Cualquier lookup de base de datos aquí bloquea el saludo — el paciente
    escucha silencio hasta que responde. Todo el contexto pesado (Viaggio,
    Huella, datasets) se carga en background en el WebSocket handler.
    """
    logger.info("Incoming call: SID=%s, From=%s, To=%s, Status=%s", CallSid, From, To, CallStatus)

    customer_phone = To if From == settings.twilio_phone_number else From
    direction = "outbound" if From == settings.twilio_phone_number else "inbound"
    from app.utils.normalization import normalize_script_name
    script_name = normalize_script_name(request.query_params.get("script_name", "default"))
    patient_name_param  = (request.query_params.get("patient_name") or "").strip()
    patient_doc_param   = (request.query_params.get("patient_document_number") or "").strip()
    manychat_user_id_param = (request.query_params.get("manychat_user_id") or "").strip()
    _call_source_param  = (request.query_params.get("call_source") or "").strip()
    _call_source = _call_source_param if _call_source_param else (
        "inbound" if direction == "inbound" else "api"
    )

    # ── FAST PATH: datos del paciente SIN llamadas de red ───────────────────
    # Prioridad:
    #   1. Registro en memoria (para llamadas salientes ya registradas por
    #      /calls/trigger o /twilio/outbound — siempre disponible antes de
    #      que el paciente conteste).
    #   2. Query params (patient_name enviado en la voice_url).
    #   3. Scan del caché de datasets en memoria (O(n) sin red, solo si warm).
    #   4. None → saludo genérico, el WebSocket carga el contexto completo.
    #
    # NO se llama get_customer_context() aquí — ese fetch puede bloquear 8-20 s
    # y el paciente escucharía silencio. El WebSocket lo hace en background.

    _registry = get_call_patient(CallSid)

    if _registry and _registry.get("patient_name"):
        # Llamada saliente ya registrada — usar datos del registro (instant)
        customer = {
            "id":              None,
            "full_name":       _registry["patient_name"],
            "phone_number":    customer_phone,
            "document_number": _registry.get("patient_id") or None,
            "hospital_name":   _registry.get("hospital_name") or None,
            "project_name":    _registry.get("project_name") or None,
            "manychat_user_id":_registry.get("manychat_user_id") or None,
            "source":          "registry",
        }
        logger.info(
            "FAST PATH (registry): name=%s hospital=%s for call %s",
            customer["full_name"], customer["hospital_name"], CallSid,
        )
    elif patient_name_param or patient_doc_param:
        # Params en la URL (fallback para llamadas sin registro previo)
        customer = {
            "id": None, "full_name": patient_name_param or None,
            "phone_number": customer_phone,
            "document_number": patient_doc_param or None,
            "hospital_name": None, "project_name": None, "source": "param",
        }
        store_pending_call_params(CallSid, customer)
        logger.info("FAST PATH (params): name=%s for call %s", patient_name_param, CallSid)
    else:
        # Último recurso: scan del caché en memoria (sin red, <50 ms si warm)
        customer = find_patient_from_warm_cache(customer_phone)
        if customer:
            logger.info(
                "FAST PATH (warm cache): name=%s for call %s",
                customer.get("full_name"), CallSid,
            )
        else:
            logger.info("FAST PATH: no patient data available for call %s — generic greeting", CallSid)

    # ── Script: solo desde caché (sin red) ──────────────────────────────────
    # get_active_call_script_cached() es instant; si aún no está warm usamos
    # el script local de manual_data.py como fallback.
    script = get_active_call_script_cached(script_name)
    if script is None:
        # Caché fría — usar script local fallback (nunca bloquea)
        from app.manual_data import CALL_SCRIPT
        script = CALL_SCRIPT
        logger.info("Script cache cold — using local fallback for call %s", CallSid)

    # ── Registro del paciente (instant, in-memory) ───────────────────────────
    _manychat_id = manychat_user_id_param or (customer.get("manychat_user_id") if customer else None)
    register_call_patient(
        CallSid,
        patient_name=customer.get("full_name") if customer else None,
        patient_id=str(customer.get("document_number") or "") if customer else None,
        script_name=script_name,
        patient_phone=customer_phone,
        manychat_user_id=_manychat_id or None,
        hospital_name=customer.get("hospital_name") if customer else None,
        project_name=customer.get("project_name") if customer else None,
    )
    if _manychat_id:
        logger.info("manychat_user_id registrado para call %s: %s", CallSid, _manychat_id)

    # ── Call record (in-memory, customer_id=None es OK) ──────────────────────
    create_call_record(
        twilio_call_sid=CallSid,
        direction=direction,
        customer_id=None,   # Se enriquece en el WebSocket; no bloqueamos por el ID aquí
        call_source=_call_source,
    )

    # ── Saludo de bienvenida y TwiML ─────────────────────────────────────────
    welcome = get_welcome_greeting(script, customer)
    logger.info(
        "Call context prepared: name=%s hospital=%s script=%s source=%s welcome=%s…",
        customer.get("full_name") if customer else None,
        customer.get("hospital_name") if customer else None,
        script.get("name") if script else None,
        customer.get("source") if customer else None,
        welcome[:80],
    )

    # Return TwiML using the configured voice mode
    # "grok" usa el MISMO stream y el mismo bridge; solo cambia el backend de voz.
    if settings.twilio_voice_mode in ("realtime", "grok"):
        try:
            twiml = generate_realtime_stream_twiml(
                customer_phone=customer_phone,
                customer_name=customer["full_name"] if customer else None,
                direction=direction,
                script_name=script_name,
                welcome_greeting=welcome,
            )
        except Exception:
            logger.exception(
                "TwiML de %s fallo; se cae a ConversationRelay", settings.twilio_voice_mode)
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
    if normalized in {"completed", "no-answer", "busy", "failed", "canceled"}:
        mark_call_ended(CallSid)
    if normalized in {"no-answer", "busy", "failed", "canceled"}:
        delete_call_archive(CallSid)
        registry = get_call_patient(CallSid)
        # Persistir en Supabase por qué no hubo conversación (no_answer, busy…)
        mark_call_not_answered(CallSid, normalized.replace("-", "_"), registry=registry)
        # Disparar flow de ManyChat si el paciente no contestó
        if normalized == "no-answer":
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
    elif normalized == "completed":
        # Llamada contestada y finalizada. Si era de reactivación, disparar el
        # flow de seguimiento de ManyChat para que le llegue un mensaje al paciente.
        registry = get_call_patient(CallSid)
        script_name = (registry or {}).get("script_name", "")
        if was_call_not_answered(CallSid):
            # Colgada por AMD (buzón) o no contestada: el flow de no-answer ya
            # se disparó; no mandar TAMBIÉN el de reactivación al paciente.
            logger.info(
                "ManyChat reactivation flow: omitido, la llamada %s fue voicemail/no-answer",
                CallSid,
            )
        elif (registry or {}).get("lost_contact_flow_sent"):
            # Ya le mandamos el flow del numero EN MEDIO de la llamada.
            logger.info(
                "ManyChat reactivation flow: omitido, ya se envio el de contacto perdido sid=%s",
                CallSid,
            )
        elif is_reactivation_script(script_name):
            phone = (registry or {}).get("patient_phone", "")
            manychat_user_id = (registry or {}).get("manychat_user_id", "")
            if phone or manychat_user_id:
                call_purpose = _build_call_purpose(registry)
                logger.info(
                    "ManyChat reactivation flow: disparando para phone=%s manychat_user_id=%s script=%s sid=%s",
                    phone, manychat_user_id, script_name, CallSid,
                )
                asyncio.create_task(
                    trigger_reactivation_flow(
                        phone,
                        manychat_user_id=manychat_user_id or None,
                        call_purpose=call_purpose,
                    )
                )
            else:
                logger.info("ManyChat reactivation flow: sin teléfono ni manychat_user_id para sid=%s", CallSid)
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

    def _voicemail_hangup() -> None:
        hangup_call(CallSid)
        delete_call_archive(CallSid)
        logger.info("Call %s colgada por voicemail AMD (%s)", CallSid, answered_by)
        registry = get_call_patient(CallSid)
        # Persistir en Supabase que contestó el buzón, no el paciente
        mark_call_not_answered(CallSid, "voicemail", registry=registry)
        # Disparar flow de ManyChat para buzón de voz
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

    # Casos definitivos de buzón de voz — colgar siempre:
    #   machine_end_beep    → contestador con beep (buzón seguro)
    #   machine_end_silence → contestador sin beep (mensaje grabado corto)
    #   fax                 → señal de fax
    definitive_voicemail = {"machine_end_beep", "machine_end_silence", "fax"}

    # machine_start: el AMD puede decidir en <3s — ANTES de que el STT alcance a
    # transcribir al humano (3 llamadas contestadas colgadas el 08-10) — así que
    # "sin turno humano" a esta altura no prueba nada. Periodo de gracia: esperar
    # unos segundos y colgar SOLO si sigue sin haber turno humano. Los buzones
    # reales no marcan turno con voz... y si su saludo se transcribe, lo caza la
    # detección por texto (_is_voicemail) del WebSocket.
    if answered_by == "machine_start":
        if human_has_spoken(CallSid):
            logger.info("AMD machine_start ignorado: el humano ya habló. sid=%s", CallSid)
            return {"status": "ignored", "answered_by": answered_by}

        grace_s = 7  # ponytail: fijo; knob por .env solo si en campo hace falta

        async def _grace_recheck():
            await asyncio.sleep(grace_s)
            if human_has_spoken(CallSid):
                logger.info(
                    "AMD machine_start descartado tras %ds de gracia: hubo turno humano. sid=%s",
                    grace_s, CallSid,
                )
                return
            logger.info(
                "AMD machine_start confirmado tras %ds sin turno humano — buzón. Colgando. sid=%s",
                grace_s, CallSid,
            )
            try:
                _voicemail_hangup()
            except Exception:
                logger.exception("Fallo colgando buzón tras gracia AMD sid=%s", CallSid)

        asyncio.create_task(_grace_recheck())
        logger.info("AMD machine_start sin turno humano aún — gracia de %ds antes de colgar. sid=%s", grace_s, CallSid)
        return {"status": "grace_period", "answered_by": answered_by}

    if answered_by in definitive_voicemail:
        try:
            _voicemail_hangup()
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
    source: str = "api",
):
    """Trigger an outbound call to a specific number.

    Args:
        to_number: Phone number to call (E.164 format, e.g. +573001234567).
        script_name: Name of the script to use.
        patient_name: Nombre del paciente — fallback de saludo si no está en la BD.
        patient_document_number: Número de identificación (cédula) — permite buscar
            datos del paciente en el dataset Viaggio (identificacion) aunque no esté
            registrado en call_patients.
        source: Origen de la llamada — quién la generó (ej. 'whatsapp', 'viaggio',
            'api', 'frontend'). Por defecto 'api'.
    """
    # Tope de simultáneas: se rechaza ANTES de marcar en Twilio. Si dejamos
    # entrar más de las que la VM aguanta, el paciente escucha el "we're sorry"
    # de Twilio en vez de a Andrea.
    _max = get_settings().max_concurrent_calls
    _en_curso = active_call_count()
    if _en_curso >= _max:
        logger.warning(
            "trigger_outbound_call rechazado por tope de simultáneas: %d/%d phone=%s",
            _en_curso, _max, to_number,
        )
        raise HTTPException(
            status_code=429,
            detail=f"Hay {_en_curso} llamadas en curso (tope {_max}). "
                   f"Espera a que termine alguna e intenta de nuevo.",
        )

    # Cooldown: rechazar si el mismo número recibió una llamada hace menos de 5 min.
    in_cd, remaining = is_in_cooldown(to_number)
    if in_cd:
        logger.warning(
            "trigger_outbound_call rechazado por cooldown: phone=%s, faltan %ds",
            to_number,
            remaining,
        )
        raise HTTPException(
            status_code=429,
            detail=f"Este número recibió una llamada hace menos de 5 minutos. "
                   f"Espera {remaining} segundos antes de volver a llamar.",
        )

    try:
        call_sid = await make_outbound_call(
            to_number,
            script_name,
            patient_name=patient_name,
            patient_document_number=patient_document_number,
            call_source=source,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TwilioRestException as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Twilio rechazó la llamada: {exc.msg}",
        ) from exc

    mark_call_active(call_sid)

    # Marcar el intento para activar el cooldown en las próximas 5 minutos
    record_call_attempt(to_number)

    customer, _ = get_customer_context(to_number)
    create_call_record(
        twilio_call_sid=call_sid,
        direction="outbound",
        customer_id=customer["id"] if customer else None,
        call_source=source,
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
        hospital_name=customer.get("hospital_name") if customer else None,
        project_name=customer.get("project_name") if customer else None,
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
