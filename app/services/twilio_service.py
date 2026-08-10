import logging
from urllib.parse import quote

from twilio.rest import Client
from twilio.twiml.voice_response import Connect, VoiceResponse

from app.config import get_settings
from app.services.supabase_rest_service import get_voice_settings

logger = logging.getLogger(__name__)
settings = get_settings()

twilio_client = Client(settings.twilio_account_sid, settings.twilio_auth_token)


def _validate_public_base_url() -> str:
    """Ensure Twilio callbacks point to a publicly reachable URL."""
    base_url = settings.base_url.rstrip("/")
    invalid_hosts = ("localhost", "127.0.0.1", "0.0.0.0")

    if any(host in base_url for host in invalid_hosts):
        raise ValueError(
            "La configuracion base_url no es publica. "
            "Twilio no puede usar localhost/127.0.0.1/0.0.0.0 para webhooks. "
            "Configura una URL publica HTTPS, por ejemplo con cloudflared o ngrok."
        )

    if not base_url.startswith(("https://", "http://")):
        raise ValueError("La configuracion base_url debe iniciar con http:// o https://")

    return base_url


def _build_recording_announcement(welcome_greeting: str | None) -> str:
    greeting = (welcome_greeting or "").strip()
    announcement = (settings.twilio_recording_announcement or "").strip()
    if not announcement:
        return greeting
    if greeting.lower().startswith(announcement.lower()):
        return greeting
    if not greeting:
        return announcement
    return f"{announcement} {greeting}"


def generate_conversation_relay_twiml(
    welcome_greeting: str | None = None,
    script_name: str | None = None,
) -> str:
    """Generate TwiML that connects the call to ConversationRelay via WebSocket."""
    if not welcome_greeting:
        welcome_greeting = "Hola, bienvenido. Con quien tengo el gusto de hablar?"

    response = VoiceResponse()
    base_url = _validate_public_base_url()

    # NOTA: Para ConversationRelay la grabación se inicia via Recordings REST API
    # (make_outbound_call usa record=True; inbound usa start_call_recording() desde el WebSocket).
    # <Start><Record> en TwiML NO es compatible con ConversationRelay.
    # Solo preparamos el saludo con el aviso legal si la grabación está habilitada.
    if settings.twilio_recording_enabled:
        welcome_greeting = _build_recording_announcement(welcome_greeting)

    connect = Connect()
    voice_settings = get_voice_settings()

    tts_provider = (voice_settings.get("tts_provider") or settings.twilio_tts_provider or "").strip()
    tts_voice    = voice_settings.get("tts_voice") or settings.twilio_tts_voice or ""
    tts_model    = voice_settings.get("tts_model") or settings.twilio_tts_model or ""
    language     = voice_settings.get("language") or settings.twilio_conversation_language or "es-US"
    speech_model = voice_settings.get("speech_model") or settings.twilio_speech_model or "telephony"

    # FIX: Google transcription + español solo soporta 'telephony' o 'phone_call'
    # 'experimental_conversations' solo funciona con Google + en-US.
    transcription_provider = (
        voice_settings.get("transcription_provider") or settings.twilio_transcription_provider or "Google"
    )
    if transcription_provider.lower() == "google" and speech_model == "experimental_conversations":
        speech_model = "telephony"
        logger.warning(
            "speech_model cambiado a 'telephony': "
            "Google + experimental_conversations solo funciona con en-US, no con %s",
            language,
        )

    ws_url = f"wss://{base_url.replace('https://', '').replace('http://', '')}/ws/conversation"
    if script_name and script_name.strip() not in ("", "default"):
        ws_url += f"?script_name={quote(script_name.strip(), safe='')}"

    relay_kwargs = {
        "url": ws_url,
        "language": language,
        "tts_provider": tts_provider,
        "transcription_provider": transcription_provider,
        "speech_model": speech_model,
        "welcome_greeting_interruptible": "any",
        "dtmf_detection": True,
        "interruptible": True,
        "welcome_greeting": welcome_greeting,
    }

    # FIX: tts_model NO es un atributo válido de <ConversationRelay>.
    # Para ElevenLabs, el modelo va embebido en el string de voice:
    #   voice="VOICE_ID-MODEL-SPEED_STABILITY_SIMILARITY"
    # No se agrega tts_model como kwarg separado.
    if tts_voice:
        relay_kwargs["voice"] = tts_voice

    logger.info(
        "Generating ConversationRelay TwiML: provider=%s voice=%s language=%s "
        "speech_model=%s transcription_provider=%s",
        tts_provider,
        tts_voice,
        language,
        speech_model,
        transcription_provider,
    )
    connect.conversation_relay(**relay_kwargs)
    response.append(connect)
    return str(response)


def _realtime_ws_url(base_url: str) -> str:
    """Derive the wss:// URL Twilio must reach for the Realtime media stream.

    Raises solo si BASE_URL esta vacio: el caller (twilio_webhook) captura la
    excepcion y cae a ConversationRelay. Sin este guard el TwiML sale valido
    apuntando a la nada y la llamada queda MUDA, sin fallback.

    Un tunel trycloudflare pasa con WARNING: es el ingress real de la VM hoy
    (los webhooks de Twilio ya entran por ahi), pero la URL cambia si
    cloudflared se reinicia — migrar a dominio estable cuando se pueda.
    """
    host = (base_url or "").replace("https://", "").replace("http://", "").strip("/")
    if not host:
        raise ValueError(
            "BASE_URL vacio: Twilio no tiene adonde conectar el media stream. "
            "Se cae a ConversationRelay."
        )
    if "trycloudflare.com" in host:
        logger.warning(
            "BASE_URL es un tunel quick de Cloudflare (%s): funciona, pero la URL "
            "cambia si cloudflared se reinicia — usar dominio estable en prod.",
            host,
        )
    return f"wss://{host}/ws/realtime-media"


def generate_realtime_stream_twiml(
    customer_phone: str,
    customer_name: str | None,
    direction: str,
    script_name: str | None = None,
    welcome_greeting: str | None = None,
) -> str:
    """Generate TwiML that connects the call to a bidirectional media stream."""
    # Igual que el path ConversationRelay: anteponer el aviso legal de grabacion
    # al saludo para que Andrea lo diga (request_initial_greeting exige el saludo exacto).
    if settings.twilio_recording_enabled:
        welcome_greeting = _build_recording_announcement(welcome_greeting)
    response = VoiceResponse()
    connect = response.connect()
    stream = connect.stream(url=_realtime_ws_url(settings.base_url))
    stream.parameter(name="customer_phone", value=customer_phone or "")
    stream.parameter(name="customer_name", value=customer_name or "")
    stream.parameter(name="direction", value=direction)
    stream.parameter(name="script_name", value=script_name or "default")
    stream.parameter(name="project_name", value="Biomarcadores")
    if welcome_greeting:
        stream.parameter(name="welcome_greeting", value=welcome_greeting)
    return str(response)


async def make_outbound_call(
    to_number: str,
    script_name: str = "default",
    patient_name: str = "",
    patient_document_number: str = "",
    manychat_user_id: str = "",
    call_source: str = "",
) -> str:
    """Initiate an outbound call using Twilio."""
    try:
        from app.utils.normalization import normalize_script_name
        script_name = normalize_script_name(script_name)
        base_url = _validate_public_base_url()
        encoded_script_name = quote(script_name, safe="")
        voice_url = f"{base_url}/twilio/voice?script_name={encoded_script_name}"
        if patient_name:
            voice_url += f"&patient_name={quote(patient_name, safe='')}"
        if patient_document_number:
            voice_url += f"&patient_document_number={quote(patient_document_number, safe='')}"
        if manychat_user_id:
            voice_url += f"&manychat_user_id={quote(manychat_user_id, safe='')}"
        if call_source:
            voice_url += f"&call_source={quote(call_source, safe='')}"

        recording_kwargs = {}
        if settings.twilio_recording_enabled:
            recording_kwargs = {
                "record": True,
                "recording_channels": settings.twilio_recording_channels or "dual",
                "recording_status_callback": f"{base_url}/twilio/recording-status",
                "recording_status_callback_method": "POST",
                "recording_status_callback_event": ["completed"],
            }

        call = twilio_client.calls.create(
            to=to_number,
            from_=settings.twilio_phone_number,
            url=voice_url,
            method="POST",
            status_callback=f"{base_url}/twilio/status",
            status_callback_method="POST",
            machine_detection=settings.twilio_machine_detection,
            machine_detection_timeout=settings.twilio_machine_detection_timeout,
            async_amd="true" if settings.twilio_async_amd else "false",
            async_amd_status_callback=f"{base_url}/twilio/amd",
            async_amd_status_callback_method="POST",
            **recording_kwargs,
        )
        logger.info(
            "Outbound call initiated: %s -> %s (SID: %s, script=%s)",
            settings.twilio_phone_number,
            to_number,
            call.sid,
            script_name,
        )
        return call.sid
    except Exception as exc:
        logger.error("Failed to make outbound call to %s: %s", to_number, exc)
        raise


def start_call_recording(call_sid: str) -> str | None:
    """Start a dual-channel recording on an already-active call via la Recordings API.

    Útil para llamadas **entrantes** donde no se puede pasar ``record=True`` en
    ``calls.create()``.  Twilio notificará a ``/twilio/recording-status``
    cuando el MP3 esté listo.
    """
    try:
        base_url = _validate_public_base_url()
        recording = twilio_client.calls(call_sid).recordings.create(
            recording_channels="dual",
            recording_status_callback=f"{base_url}/twilio/recording-status",
            recording_status_callback_method="POST",
        )
        logger.info("Recording started for call %s: recording_sid=%s", call_sid, recording.sid)
        return recording.sid
    except Exception as exc:
        logger.warning("Failed to start recording for call %s: %s", call_sid, exc)
        return None


def hangup_call(call_sid: str):
    """Force-complete a live call, useful for voicemail detection."""
    return twilio_client.calls(call_sid).update(status="completed")
