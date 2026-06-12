import asyncio
import contextlib
import json
import logging
import re

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.db.repositories import CallRepository, pop_pending_call_params, mark_human_turn, get_call_patient
from app.services.call_log_service import (
    append_transcript_line,
    finalize_call,
    log_call_event,
    update_call_log_context,
)
from app.services.customer_service import get_customer_context
from app.services.openai_service import (
    MODERATION_CLOSE_RESPONSE,
    MODERATION_REDIRECT_RESPONSE,
    generate_response,
    generate_response_stream,
    moderate_user_input,
)
from app.services.report_service import send_whatsapp_report
from app.services.prompt_service import build_context_prompt
from app.config import get_settings as _get_settings
from app.services.audio_archive_service import CallAudioArchive
from app.services.realtime_service import connect_realtime, request_initial_greeting
from app.services.supabase_rest_service import get_active_call_script, get_huella_visit_context, get_patient_dataset_context
from app.services.twilio_service import hangup_call, start_call_recording

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


class ConversationSession:
    """Holds state for a single active call conversation."""

    def __init__(self):
        self.conversation_history: list[dict] = []
        self.system_prompt: str = ""
        self.call_id: int | None = None
        self.customer_phone: str | None = None
        self.script: dict | None = None
        self.direction: str | None = None
        self.customer_name: str | None = None
        self.patient_id: str | None = None
        self.call_sid: str | None = None
        self.pending_hangup: bool = False
        self.script_name: str = "default"
        self.initial_greeting_completed: bool = False
        self.violation_count: int = 0
        # Context loading is started in background at setup so the WebSocket loop
        # stays active (receives Twilio messages) while Viaggio/Huella fetches run.
        self._context_future: asyncio.Future | None = None
        self._context_loaded: bool = False
        # Snapshot del dict de paciente guardado en cuanto el lookup rápido termina
        # (antes de los fetches lentos de Viaggio/Huella). Permite construir un prompt
        # de fallback con nombre, hospital y proyecto reales si el contexto completo
        # no llega a tiempo.
        self._customer_snapshot: dict | None = None
        # Noise / short input handling: when True the previous bot turn was "¿Disculpa?"
        # and we are waiting for the user to either clarify or confirm "nada".
        self._disculpa_pending: bool = False

    def add_user_message(self, text: str):
        self.conversation_history.append({"role": "user", "content": text})

    def add_assistant_message(self, text: str):
        self.conversation_history.append({"role": "assistant", "content": text})


REPORT_REQUEST_PATTERN = re.compile(
    r"\b(reporte|informe)\b"
    r"|\b(mis\s+resultado|ver\s+mis\s+dato|dame\s+(el|mi|un)\s+reporte"
    r"|quiero\s+(mi|el|un)\s+reporte|env[ií]a?me\s+(el|mi|un)\s+reporte"
    r"|manda\s+(el|mi|un)\s+reporte|quiero\s+ver\s+mis\s+dato)\b",
    re.IGNORECASE,
)

FAREWELL_PATTERN = re.compile(
    r"\b(adios|hasta luego|hasta pronto|chao|chau|bye|buen dia|buenas tardes|buenas noches|gracias igualmente|igualmente)\b",
    re.IGNORECASE,
)

# Entradas de ruido / muy cortas que deben disparar "¿Disculpa?" en lugar de ir a GPT.
_NOISE_SET: frozenset[str] = frozenset({
    "ah", "eh", "mm", "hmm", "um", "uh", "hm", "m", "a", "e", "o",
    "mhm", "ajá", "aja", "aah", "ahem",
})

# Respuestas cortas perfectamente válidas que NUNCA deben detectarse como ruido.
_VALID_SHORT: frozenset[str] = frozenset({
    "sí", "si", "no", "ok", "ya", "claro", "dale", "bueno", "listo", "bien",
})

# Respuestas que el usuario da después de un "¿Disculpa?" para aclarar que no dijo nada.
# En ese caso simplemente se descarta la entrada y se continúa sin llamar a GPT.
_DISCULPA_CONTINUATION = re.compile(
    r"^(?:no[,.]?\s*)?(?:no\s+dije\s+nada|nada|no\s+es\s+nada|no\s+fue\s+nada|nada\s+gracias|no\s+nada|nada[,.]?\s*gracias)\.?\s*$",
    re.IGNORECASE,
)

# Frases típicas de buzón de voz / contestador automático.
# Si el STT transcribe alguna de estas, es casi seguro que nadie contestó en persona.
# Se busca también en textos parciales/cortados que el STT puede entregar fragmentados.
VOICEMAIL_PATTERN = re.compile(
    r"deja\s+(?:tu|un)\s+mensaje"
    r"|dejar\s+(?:un|su|tu)\s+mensaje"
    r"|para\s+dejar\s+(?:un|su|tu)\s+mensaje"
    r"|deja\s+tu\s+recado"
    r"|dejar\s+su\s+recado"
    r"|despu[eé]s\s+de\s+(?:escuchar\s+el\s+tono|la\s+se[nñ]al)"
    r"|despu[eé]s\s+del\s+tono"
    r"|al\s+escuchar\s+el\s+tono"
    r"|escuche\s+el\s+tono"
    r"|buz[oó]n\s+de\s+voz"
    r"|contestador\s+autom[aá]tico"
    r"|mensaje\s+de\s+voz\s+guardado"
    r"|mensaje\s+de\s+voz"
    r"|correo\s+de\s+voz"
    r"|para\s+finalizar\s+presi[oó]n"
    r"|para\s+finalizar\s+presione"
    r"|presion[ae]\s+la\s+tecla\s+numeral"
    r"|presione\s+sostenido"
    r"|marque\s+la\s+tecla"
    r"|oprima\s+la\s+tecla"
    r"|volver\s+a\s+grabar"
    r"|grab[ae]\s+(?:tu|su)\s+mensaje"
    r"|grabar\s+(?:tu|su)\s+mensaje"
    r"|al\s+terminar\s+(?:la\s+)?grabaci[oó]n"
    r"|su\s+grabaci[oó]n\s+(?:ha\s+sido|fue)\s+guardada"
    r"|no\s+(?:se\s+encuentra|est[aá])\s+disponible"
    r"|en\s+este\s+momento\s+no\s+(?:puedo|puede)\s+atender"
    r"|no\s+puedo\s+contestar\s+en\s+este\s+momento"
    r"|su\s+llamada\s+ha\s+sido"
    r"|escuchar\s+el\s+siguiente\s+mensaje"
    r"|(?:presione|marque|oprima)\s+(?:el\s+)?(?:[0-9#*]|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|cero)"
    r"|\bguardado\b.{0,40}\bmensaje\b"
    r"|\bmensaje\b.{0,40}\bguardado\b",
    re.IGNORECASE,
)


def _should_end_call(text: str) -> bool:
    return bool(text and FAREWELL_PATTERN.search(text))


def _is_voicemail(text: str) -> bool:
    return bool(text and VOICEMAIL_PATTERN.search(text))


async def _hangup_after_response(call_sid: str | None, delay: float = 1.2, reason: str = "farewell"):
    if not call_sid:
        return
    if delay > 0:
        await asyncio.sleep(delay)
    try:
        hangup_call(call_sid)
        logger.info("Call %s hung up (reason=%s)", call_sid, reason)
    except Exception:
        logger.exception("Failed to hang up call %s (reason=%s)", call_sid, reason)


def _load_call_record(call_sid: str) -> tuple[dict | None, int | None]:
    call_repo = CallRepository()
    call = call_repo.find_by_sid(call_sid)
    if not call:
        return None, None
    return call, call["id"]


def _load_session_context(session: ConversationSession):
    customer, appointments = get_customer_context(session.customer_phone or "")

    # ── Prioridad del registry (nombre realmente hablado) ────────────────────
    # El registry (poblado en /voice) tiene el nombre/hospital/proyecto que el
    # frontend pidió llamar y que Twilio YA dijo por voz en el welcome_greeting.
    # El lookup por teléfono puede devolver un registro distinto/desfasado del
    # dataset Viaggio (p. ej. un registro de prueba que pisa al paciente real),
    # haciendo que el saludo hablado y el contexto del modelo diverjan
    # ("cambió el nombre a mitad de llamada"). Por eso el registry manda.
    registry = get_call_patient(session.call_sid) if session.call_sid else None
    reg_name = (registry.get("patient_name") or "").strip() if registry else ""
    if reg_name:
        if customer:
            old_name = (customer.get("full_name") or "").strip()
            if old_name and old_name != reg_name:
                logger.info(
                    "Nombre del registry '%s' tiene prioridad sobre el lookup por teléfono '%s' (call=%s)",
                    reg_name, old_name, session.call_sid,
                )
            customer["full_name"] = reg_name
            # hospital/proyecto también se hablaron desde el registry: preferirlos si existen
            if registry.get("hospital_name"):
                customer["hospital_name"] = registry["hospital_name"]
            if registry.get("project_name"):
                customer["project_name"] = registry["project_name"]
        else:
            # Sin match por teléfono → construir el paciente desde el registry.
            customer = {
                "full_name": reg_name,
                "document_number": registry.get("patient_id") or None,
                "phone_number": session.customer_phone,
                "hospital_name": registry.get("hospital_name") or None,
                "project_name": registry.get("project_name") or None,
                "source": "registry",
            }
            appointments = []
            logger.info("=== PACIENTE (desde registry) === nombre=%s", reg_name)

    # Si el paciente no está en la BD pero se construyó desde query params en /voice,
    # recuperarlo desde la caché de corta duración (se elimina al leerlo).
    if not customer and session.call_sid:
        cached = pop_pending_call_params(session.call_sid)
        if cached:
            customer = cached
            appointments = []
            logger.info(
                "=== PACIENTE (desde caché de params) === nombre=%s documento=%s",
                cached.get("full_name"),
                cached.get("document_number"),
            )

    session.customer_name = customer["full_name"] if customer else None
    # patient_id: preferir document_number, caer en identificacion como fallback.
    # Guardamos None (no string vacío) para que la comprobación `if session.patient_id` sea segura.
    _doc = (
        str(customer.get("document_number") or customer.get("identificacion") or "").strip()
        if customer else ""
    )
    session.patient_id = _doc or None
    # Guardar snapshot inmediatamente — los fetches lentos (Viaggio/Huella) vienen después.
    # El fallback de prompt lo usa si el contexto completo no llega a tiempo.
    session._customer_snapshot = customer if customer else None

    # ── Paciente ────────────────────────────────────────────────────────────
    if customer:
        logger.info(
            "=== PACIENTE ===\n"
            "  nombre:       %s\n"
            "  documento:    %s\n"
            "  telefono:     %s\n"
            "  municipio:    %s\n"
            "  hospital:     %s\n"
            "  imc:          %s\n"
            "  findrisc:     %s\n"
            "  edad:         %s\n"
            "  sexo:         %s\n"
            "  fuente:       %s\n"
            "  citas:        %d",
            customer.get("full_name"),
            customer.get("document_number") or "no encontrado",
            customer.get("phone_number"),
            customer.get("municipality") or "sin municipio",
            customer.get("hospital_name") or "sin hospital",
            customer.get("imc") or "—",
            customer.get("findrisc") or "—",
            customer.get("age") or "—",
            customer.get("sex") or "—",
            customer.get("source"),
            len(appointments),
        )
    else:
        logger.warning("=== PACIENTE === no encontrado para telefono=%s", session.customer_phone)

    # ── Script ──────────────────────────────────────────────────────────────
    # Cargar script desde Supabase (Lovable call_scripts) con fallback a manual_data.py
    session.script = get_active_call_script(session.script_name or "default")
    logger.info(
        "=== SCRIPT ===\n"
        "  nombre:         %s\n"
        "  saludo:         %s\n"
        "  prompt (chars): %d",
        session.script.get("name") if session.script else "none",
        (session.script.get("welcome_greeting") or "")[:80] if session.script else "—",
        len(session.script.get("system_prompt") or "") if session.script else 0,
    )

    # ── Prompt PRELIMINAR ───────────────────────────────────────────────────
    # Se construye con los datos ya disponibles (paciente + script) antes de
    # arrancar los fetches lentos de Viaggio/Huella.  Esto permite que el primer
    # turno del WebSocket responda sin esperar el timeout de 8 s; los turnos
    # siguientes usarán el prompt completo cuando el hilo de fondo termine.
    session.system_prompt = build_context_prompt(
        customer, appointments, session.script, {}, {}
    )
    logger.info(
        "=== PROMPT PRELIMINAR ===\n"
        "  chars: %d",
        len(session.system_prompt),
    )

    # ── Datasets Viaggio ────────────────────────────────────────────────────
    dataset_context = get_patient_dataset_context(customer)
    logger.info(
        "=== DATASET VIAGGIO ===\n"
        "  food_entries:   %d registros\n"
        "  conversations:  %d registros\n"
        "  evalml:         %s\n"
        "  data_step:      %s",
        len(dataset_context.get("food_entries") or []),
        len(dataset_context.get("conversations") or []),
        "sí" if dataset_context.get("evalml") else "vacío",
        "sí" if dataset_context.get("data_step") else "vacío",
    )

    # ── Huella ──────────────────────────────────────────────────────────────
    huella_context = get_huella_visit_context(customer)
    logger.info(
        "=== HUELLA ===\n"
        "  interviewee:    %s\n"
        "  sesiones:       %d\n"
        "  visitadores:    %d",
        (huella_context.get("interviewee") or {}).get("name") or "no encontrado",
        len(huella_context.get("sessions") or []),
        len(huella_context.get("visitors") or []),
    )

    # ── Prompt final ────────────────────────────────────────────────────────
    session.system_prompt = build_context_prompt(
        customer, appointments, session.script, dataset_context, huella_context
    )
    logger.info(
        "=== PROMPT CONSTRUIDO ===\n"
        "  total chars: %d\n"
        "  preview:\n%s",
        len(session.system_prompt),
        session.system_prompt[:600].replace("\n", "\n    "),
    )
    return customer, appointments


@router.websocket("/conversation")
async def conversation_relay_ws(websocket: WebSocket):
    """WebSocket endpoint for Twilio ConversationRelay."""
    await websocket.accept()
    session = ConversationSession()
    # script_name viaja como query param en la URL del WebSocket generada por el TwiML
    from app.utils.normalization import normalize_script_name
    session.script_name = normalize_script_name(websocket.query_params.get("script_name"))
    archive: CallAudioArchive | None = None
    archive_finalized = False
    loop = asyncio.get_event_loop()
    final_status = "completed"

    logger.info("ConversationRelay WebSocket connected (script=%s)", session.script_name)

    def finalize_archive_once():
        nonlocal archive_finalized, archive
        if archive is None or archive_finalized:
            return
        try:
            archive.close()
            archive_finalized = True
            logger.info("Audio archive finalized for call %s", session.call_sid)
        except Exception as exc:
            logger.error("Failed to finalize audio archive: %s", exc, exc_info=True)

    try:
        while True:
            raw = await websocket.receive_text()
            event = json.loads(raw)
            event_type = event.get("type", "unknown")

            logger.debug("WS event: %s", event_type)

            if event_type == "setup":
                call_sid = event.get("callSid", "")
                session.call_sid = call_sid
                session.direction = event.get("direction", "")
                from_number = event.get("from", "")
                to_number = event.get("to", "")
                # "outbound-api" → llamada saliente programática.
                # En saliente: from=Twilio, to=paciente → usamos to_number.
                # En entrante: from=paciente, to=Twilio → usamos from_number.
                session.customer_phone = to_number if "outbound" in session.direction else from_number

                _, session.call_id = _load_call_record(call_sid)

                # CLAVE: lanzar la carga de contexto en background SIN awaitar.
                # _load_session_context hace 4+ fetches HTTP síncronos (Viaggio, Huella,
                # Lovable) con timeouts de 20 s cada uno. Si lo awaitamos aquí el
                # WebSocket deja de recibir mensajes de Twilio y Twilio cierra la conexión.
                # El primer handler de `prompt` awaitará el future antes de llamar a GPT.
                session._context_future = loop.run_in_executor(None, _load_session_context, session)

                # Para llamadas entrantes: iniciar grabación ahora (no necesita contexto).
                if "outbound" not in session.direction and _get_settings().twilio_recording_enabled:
                    loop.run_in_executor(None, start_call_recording, call_sid)

                if session.call_id:
                    log_call_event(session.call_id, "setup", event)

                logger.info(
                    "Session setup started (context loading in background): "
                    "call_sid=%s direction=%s phone=%s script=%s",
                    call_sid, session.direction, session.customer_phone, session.script_name,
                )

            elif event_type == "prompt":
                user_text = event.get("voicePrompt", "")
                if not user_text.strip():
                    continue

                turn = len(session.conversation_history) // 2 + 1
                logger.info("=== TURNO %d — USUARIO ===\n  %s", turn, user_text)

                # Marcar que el humano ya habló (para que AMD no cuelgue por voicemail
                # si llega tarde un resultado de machine_start/machine_end_silence)
                if session.call_sid:
                    mark_human_turn(session.call_sid)

                # ── Detección de buzón de voz — PRIMERO, antes de cualquier await ──
                # Se chequea ANTES de esperar el contexto para colgar de inmediato
                # sin desperdiciar tiempo en fetches de Viaggio ni en llamadas a GPT.
                if _is_voicemail(user_text):
                    logger.warning(
                        "Voicemail detected via transcript — hanging up. call=%s text=%r",
                        session.call_sid, user_text[:150],
                    )
                    if session.call_id:
                        log_call_event(session.call_id, "voicemail_detected", {"text": user_text})
                        finalize_call(session.call_id, "voicemail")
                    final_status = "voicemail"
                    asyncio.create_task(_hangup_after_response(session.call_sid, delay=0.3, reason="voicemail"))
                    break
                # ────────────────────────────────────────────────────────────

                # ── Esperar a que el contexto esté listo (solo en el primer turno) ──
                if not session._context_loaded:
                    if session._context_future is not None and not session.system_prompt:
                        # Solo bloquear si el prompt preliminar aún no fue construido
                        # por el hilo de fondo.  Si ya está disponible, pasamos directo
                        # y evitamos el delay de 8 s en el primer turno del usuario.
                        logger.info("First prompt — waiting for context to finish loading (call=%s)…",
                                    session.call_sid)
                        try:
                            await asyncio.wait_for(
                                asyncio.shield(session._context_future), timeout=8.0
                            )
                        except asyncio.TimeoutError:
                            logger.warning(
                                "Context loading timed out (8 s) for call %s — building fallback prompt",
                                session.call_sid,
                            )
                        except Exception as exc:
                            logger.error("Context loading failed for call %s: %s", session.call_sid, exc)
                        session._context_future = None
                    elif session._context_future is not None and session.system_prompt:
                        logger.info(
                            "First prompt — preliminary prompt already ready, skipping 8 s wait (call=%s)",
                            session.call_sid,
                        )
                    session._context_loaded = True

                    # Si el prompt completo aún no está listo (timeout o error), construir
                    # un prompt de fallback con los datos rápidos ya disponibles en la sesión
                    # (nombre, hospital, proyecto, script). Esto evita {call_name} literal
                    # y da respuestas coherentes sin esperar los datasets lentos.
                    if not session.system_prompt:
                        from app.services.prompt_service import build_context_prompt
                        session.system_prompt = build_context_prompt(
                            session._customer_snapshot,   # nombre, hospital, proyecto reales
                            [],                           # sin citas (no disponibles aún)
                            session.script,               # script correcto
                            {},                           # sin datasets Viaggio
                            {},                           # sin Huella
                        )
                        logger.warning(
                            "Built fast-fallback prompt (customer=%s hospital=%s script=%s call=%s)",
                            session.customer_name,
                            (session._customer_snapshot or {}).get("hospital_name", "—"),
                            session.script_name,
                            session.call_sid,
                        )

                    # Crear archive y enriquecer log ahora que tenemos datos del paciente
                    archive = CallAudioArchive(
                        session.call_sid,
                        session.customer_name,
                        session.patient_id,
                        session.script_name or "default",
                        mode="conversation_relay",
                    )
                    loop.run_in_executor(
                        None, update_call_log_context,
                        session.call_sid,
                        session.patient_id or None,
                        session.customer_name or None,
                        session.script_name or None,
                    )
                    logger.info(
                        "Context ready — archive created for call %s (patient=%s script=%s)",
                        session.call_sid, session.customer_name, session.script_name,
                    )

                    # ── Sembrar el saludo de bienvenida en el historial ──────────
                    # Twilio ConversationRelay YA reprodujo el welcome_greeting del TwiML
                    # por TTS al conectar la llamada. Si no lo registramos como primer
                    # turno del asistente, el modelo arranca con historial vacío y vuelve
                    # a saludar ("Hola, hablo con X?") en el turno 1 → doble saludo,
                    # sensación de "pierde el hilo" y cuelgues. Lo sembramos aquí.
                    # Anthropic exige que el primer mensaje sea 'user', por eso anteponemos
                    # un marcador mínimo antes del saludo del asistente.
                    if not session.conversation_history:
                        from app.services.prompt_service import get_welcome_greeting
                        _seed_greeting = get_welcome_greeting(
                            session.script, session._customer_snapshot
                        )
                        if _seed_greeting:
                            session.conversation_history.append(
                                {"role": "user", "content": "(El paciente acaba de contestar la llamada.)"}
                            )
                            session.add_assistant_message(_seed_greeting)
                            logger.info(
                                "Saludo de bienvenida sembrado en historial (call=%s): %s",
                                session.call_sid, _seed_greeting[:80],
                            )
                # ─────────────────────────────────────────────────────────────

                # ── Detección de ruido / entrada muy corta ──────────────────
                _stripped = user_text.strip()
                _lower = _stripped.lower()

                # Si el turno anterior fue "¿Disculpa?" y el usuario aclara "nada", repite
                # un saludo ambiguo o dice algo de ≤1 carácter: descartar silenciosamente
                # sin tocar el historial ni llamar a GPT.
                # "hola", "alo", "aló", "buenas" se descartan aquí porque si se envían a GPT
                # en mitad de una conversación el modelo reinicia el flujo de identidad.
                _DISCULPA_ABSORB = {"hola", "alo", "aló", "buenas", "halo"}
                if session._disculpa_pending and (
                    _DISCULPA_CONTINUATION.match(_stripped)
                    or len(_stripped) <= 1
                    or _lower in _DISCULPA_ABSORB
                ):
                    session._disculpa_pending = False
                    logger.info(
                        "Noise continuation after ¿Disculpa? — discarding input (call=%s text=%r)",
                        session.call_sid, user_text,
                    )
                    continue

                session._disculpa_pending = False  # reset para cualquier entrada real

                # Entrada de ruido puro o de ≤1 carácter → responder "¿Disculpa?"
                # sin agregar al historial (el contexto de la conversación no cambia).
                # Las respuestas cortas pero válidas ("sí", "no", "ok", etc.) se excluyen
                # mediante la lista _VALID_SHORT para no tratar un "sí" como ruido.
                if (len(_stripped) <= 1 or _lower in _NOISE_SET) and _lower not in _VALID_SHORT:
                    session._disculpa_pending = True
                    logger.info(
                        "Noise/very-short input — responding with ¿Disculpa? (call=%s text=%r)",
                        session.call_sid, user_text,
                    )
                    await websocket.send_text(json.dumps({
                        "type": "text",
                        "token": "¿Disculpa?",
                        "last": True,
                    }))
                    continue
                # ─────────────────────────────────────────────────────────────

                session.add_user_message(user_text)
                if session.call_id:
                    log_call_event(session.call_id, "user_speech", {"text": user_text})
                    append_transcript_line(session.call_id, "user", user_text)
                if archive is not None:
                    archive.append_transcript("user", user_text)

                # ── Moderación de contenido ──────────────────────────────────
                is_flagged, flag_category = await moderate_user_input(user_text)
                if is_flagged:
                    session.violation_count += 1
                    logger.warning(
                        "Contenido inapropiado detectado (violation=%d, category=%s) call=%s",
                        session.violation_count, flag_category, session.call_sid,
                    )
                    if session.violation_count >= 2:
                        ai_response = MODERATION_CLOSE_RESPONSE
                        session.pending_hangup = True
                    else:
                        ai_response = MODERATION_REDIRECT_RESPONSE
                    # Respuesta fija — enviar directamente sin streaming
                    await websocket.send_text(json.dumps({
                        "type": "text",
                        "token": ai_response,
                        "last": True,
                    }))
                else:
                    session.pending_hangup = _should_end_call(user_text)
                    _report_requested = bool(REPORT_REQUEST_PATTERN.search(user_text))

                    # ── Streaming de respuesta Claude ────────────────────────
                    # Enviamos tokens a Twilio conforme Claude los genera.
                    # ElevenLabs empieza a sintetizar voz con los primeros tokens
                    # (~200-400 ms) en lugar de esperar la respuesta completa.
                    #
                    # Estrategia de buffer: acumular hasta encontrar puntuación
                    # de frase (.!?,;:) o superar 60 chars → flush como chunk.
                    # Esto da chunks coherentes al TTS sin esperar la respuesta
                    # completa, reduciendo la latencia percibida de 2-5 s a <1 s.
                    _FLUSH_ON = frozenset(".!?,;:")
                    _buf = ""
                    _tokens: list[str] = []

                    async for _tok in generate_response_stream(
                        session.system_prompt,
                        session.conversation_history[:-1],
                        user_text,
                    ):
                        _tokens.append(_tok)
                        _buf += _tok
                        # Flush en puntuación o al acumular suficientes chars
                        if any(c in _tok for c in _FLUSH_ON) or len(_buf) >= 60:
                            await websocket.send_text(json.dumps({
                                "type": "text",
                                "token": _buf,
                                "last": False,
                            }))
                            _buf = ""

                    # Enviar el resto del buffer + señal de fin
                    # IMPORTANTE: NO enviar "lang" — Twilio usa el idioma del TwiML (es-CO).
                    # Si se envía "lang: es-US" con TwiML "es-CO" → error 64106.
                    await websocket.send_text(json.dumps({
                        "type": "text",
                        "token": _buf,   # puede ser "" si el último chunk ya fue enviado
                        "last": True,
                    }))

                    ai_response = "".join(_tokens)
                    # ─────────────────────────────────────────────────────────

                    # Enviar reporte WhatsApp si el usuario lo solicitó y hay documento
                    if _report_requested and session.patient_id:
                        asyncio.create_task(send_whatsapp_report(
                            session.patient_id,
                            session.customer_phone or "",
                        ))
                        logger.info(
                            "WhatsApp report disparado: doc=%s phone=%s call=%s",
                            session.patient_id, session.customer_phone, session.call_sid,
                        )
                # ────────────────────────────────────────────────────────────

                session.add_assistant_message(ai_response)
                logger.info("=== TURNO %d — MODELO ===\n  %s", turn, ai_response)

                if session.call_id:
                    log_call_event(session.call_id, "ai_response", {"text": ai_response})
                    append_transcript_line(session.call_id, "assistant", ai_response)
                if archive is not None:
                    archive.append_transcript("assistant", ai_response)

                if session.pending_hangup:
                    await _hangup_after_response(session.call_sid)

            elif event_type == "interrupt":
                logger.info("User interrupted the agent")
                if session.call_id:
                    log_call_event(session.call_id, "interrupt", event)

            elif event_type == "dtmf":
                digit = event.get("digit", "")
                logger.info("DTMF received: %s", digit)
                if session.call_id:
                    log_call_event(session.call_id, "dtmf", {"digit": digit})

            elif event_type == "error":
                logger.error("ConversationRelay error: %s", event)
                if session.call_id:
                    log_call_event(session.call_id, "error", event)

            else:
                logger.warning("Unknown event type: %s", event_type)

    except WebSocketDisconnect:
        logger.info("ConversationRelay WebSocket disconnected (call=%s)", session.call_sid)

    except Exception as exc:
        logger.error("WebSocket error: %s", exc, exc_info=True)
        final_status = "failed"

    finally:
        # Siempre finalizar el archive, sin importar cómo salió el loop
        # (break por voicemail, desconexión de Twilio, excepción, o cierre normal).
        finalize_archive_once()
        if session.call_id:
            if final_status not in ("voicemail",):
                summary = " | ".join(
                    f"{m['role']}: {m['content'][:100]}"
                    for m in session.conversation_history[-6:]
                )
                finalize_call(session.call_id, final_status, summary=summary or None)
        logger.info("ConversationRelay session ended: call=%s status=%s", session.call_sid, final_status)


@router.websocket("/realtime-media")
async def realtime_media_ws(websocket: WebSocket):
    """Bridge Twilio bidirectional Media Streams with OpenAI Realtime API."""
    await websocket.accept()
    session = ConversationSession()
    stream_sid: str | None = None
    openai_ws = None
    archive: CallAudioArchive | None = None
    archive_finalized = False

    logger.info("Realtime media WebSocket connected")

    def finalize_archive_once():
        nonlocal archive_finalized, archive
        if archive is None or archive_finalized:
            return
        try:
            archive.close()
            archive_finalized = True
            logger.info("Audio archive finalized for call %s", session.call_sid)
        except Exception as exc:
            logger.error("Failed to finalize local audio archive: %s", exc, exc_info=True)

    async def twilio_to_openai():
        nonlocal stream_sid, openai_ws, archive

        while True:
            raw = await websocket.receive_text()
            event = json.loads(raw)
            event_type = event.get("event", "unknown")

            if event_type == "connected":
                logger.info("Twilio media stream connected")

            elif event_type == "start":
                start = event.get("start", {})
                custom_parameters = start.get("customParameters", {})
                call_sid = start.get("callSid", "")
                session.call_sid = call_sid
                stream_sid = start.get("streamSid")

                session.call_id = _load_call_record(call_sid)[1]
                session.customer_phone = custom_parameters.get("customer_phone", "")
                session.customer_name = custom_parameters.get("customer_name", "")
                session.direction = custom_parameters.get("direction", "")
                session.script_name = (custom_parameters.get("script_name", "default") or "default").strip()
                _load_session_context(session)
                archive = CallAudioArchive(
                    call_sid,
                    session.customer_name,
                    session.patient_id,
                    session.script_name,
                )
                openai_ws = await connect_realtime(session.system_prompt)
                logger.info(
                    "Realtime custom parameters received: %s",
                    {
                        "customer_phone": session.customer_phone,
                        "customer_name": session.customer_name,
                        "patient_id": session.patient_id,
                        "direction": session.direction,
                        "script_name": session.script_name,
                        "welcome_greeting": custom_parameters.get("welcome_greeting", ""),
                    },
                )
                await request_initial_greeting(
                    openai_ws,
                    custom_parameters.get("welcome_greeting", ""),
                )

                if session.call_id:
                    log_call_event(session.call_id, "realtime_start", start)

                logger.info(
                    "Realtime session setup: call_sid=%s, stream_sid=%s, phone=%s, direction=%s",
                    call_sid,
                    stream_sid,
                    session.customer_phone,
                    session.direction,
                )

            elif event_type == "media":
                if openai_ws is None:
                    continue
                if archive is not None:
                    archive.append_user_audio(event["media"]["payload"])
                await openai_ws.send(json.dumps({
                    "type": "input_audio_buffer.append",
                    "audio": event["media"]["payload"],
                }))

            elif event_type == "dtmf":
                logger.info("DTMF received during realtime call: %s", event)
                if session.call_id:
                    log_call_event(session.call_id, "dtmf", event)

            elif event_type == "stop":
                logger.info("Twilio media stream stopped")
                if session.call_id:
                    log_call_event(session.call_id, "realtime_stop", event)
                finalize_archive_once()
                if openai_ws is not None:
                    with contextlib.suppress(Exception):
                        await openai_ws.close()
                break

            else:
                logger.debug("Unhandled Twilio media event: %s", event_type)

    async def openai_to_twilio():
        nonlocal openai_ws

        while openai_ws is None:
            await asyncio.sleep(0.05)

        async for raw in openai_ws:
            event = json.loads(raw)
            event_type = event.get("type", "unknown")

            if event_type == "response.created":
                logger.info("OpenAI started a realtime response")

            elif event_type in {"response.audio.delta", "response.output_audio.delta"} and stream_sid:
                if archive is not None:
                    archive.append_assistant_audio(event["delta"])
                await websocket.send_text(json.dumps({
                    "event": "media",
                    "streamSid": stream_sid,
                    "media": {"payload": event["delta"]},
                }))
                logger.debug("Forwarded audio delta to Twilio stream")

            elif event_type in {
                "response.audio_transcript.delta",
                "response.output_audio_transcript.delta",
            }:
                logger.debug("Assistant transcript delta: %s", event.get("delta", ""))

            elif event_type in {
                "response.audio_transcript.done",
                "response.output_audio_transcript.done",
            }:
                transcript = event.get("transcript", "")
                if transcript:
                    logger.info("Assistant said: %s", transcript)
                    if not session.initial_greeting_completed:
                        session.initial_greeting_completed = True
                    session.add_assistant_message(transcript)
                    if session.call_id:
                        log_call_event(session.call_id, "ai_response", {"text": transcript})
                        append_transcript_line(session.call_id, "assistant", transcript)
                    if archive is not None:
                        archive.append_transcript("assistant", transcript)

            elif event_type in {"response.audio.done", "response.output_audio.done"}:
                logger.debug("Assistant audio stream completed")

            elif event_type in {"response.text.delta", "response.output_text.delta"}:
                logger.debug("Assistant text delta: %s", event.get("delta", ""))

            elif event_type == "conversation.item.input_audio_transcription.completed":
                transcript = event.get("transcript", "")
                if transcript:
                    logger.info("User said: %s", transcript)
                    session.add_user_message(transcript)
                    session.pending_hangup = _should_end_call(transcript)
                    if session.call_id:
                        log_call_event(session.call_id, "user_speech", {"text": transcript})
                        append_transcript_line(session.call_id, "user", transcript)
                    if archive is not None:
                        archive.append_transcript("user", transcript)

            elif event_type == "session.updated":
                logger.info("Realtime session updated successfully")

            elif event_type == "response.done":
                logger.info("OpenAI completed a realtime response")
                if session.pending_hangup:
                    session.pending_hangup = False
                    await _hangup_after_response(session.call_sid)

            elif event_type == "input_audio_buffer.speech_started" and stream_sid:
                if not session.initial_greeting_completed:
                    logger.info("Caller speech detected during initial greeting; preserving greeting audio")
                    continue
                await websocket.send_text(json.dumps({
                    "event": "clear",
                    "streamSid": stream_sid,
                }))
                logger.info("Caller speech detected; cleared pending Twilio audio buffer")

            elif event_type == "error":
                logger.error("OpenAI realtime error: %s", event)
                if session.call_id:
                    log_call_event(session.call_id, "error", event)

            else:
                logger.debug("Unhandled OpenAI realtime event: %s", event_type)

    try:
        await asyncio.gather(twilio_to_openai(), openai_to_twilio())
    except WebSocketDisconnect:
        logger.info("Realtime media WebSocket disconnected")
    except Exception as exc:
        logger.error("Realtime media bridge failed: %s", exc, exc_info=True)
        if session.call_id:
            finalize_call(session.call_id, "failed", summary=str(exc))
    finally:
        logger.info("Finalizing realtime media session for call %s", session.call_sid)
        if openai_ws is not None:
            with contextlib.suppress(Exception):
                await openai_ws.close()
        finalize_archive_once()

        if session.call_id:
            summary = " | ".join(
                f"{m['role']}: {m['content'][:100]}"
                for m in session.conversation_history[-6:]
            )
            finalize_call(session.call_id, "completed", summary=summary or "Realtime session ended")
