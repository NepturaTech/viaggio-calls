import logging

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


def generate_conversation_relay_twiml(welcome_greeting: str | None = None) -> str:
    """Generate TwiML that connects the call to ConversationRelay via WebSocket."""
    if not welcome_greeting:
        welcome_greeting = "Hola, bienvenido. Con quien tengo el gusto de hablar?"

    response = VoiceResponse()
    connect = Connect()
    voice_settings = get_voice_settings()

    relay_kwargs = {
        "url": f"wss://{settings.base_url.replace('https://', '').replace('http://', '')}/ws/conversation",
        "language": voice_settings.get("language") or settings.twilio_conversation_language,
        "tts_provider": voice_settings.get("tts_provider") or settings.twilio_tts_provider,
        "transcription_provider": (
            voice_settings.get("transcription_provider") or settings.twilio_transcription_provider
        ),
        "speech_model": voice_settings.get("speech_model") or settings.twilio_speech_model,
        "welcome_greeting_interruptible": "any",
        "dtmf_detection": True,
        "interruptible": True,
        "welcome_greeting": welcome_greeting,
    }

    tts_voice = voice_settings.get("tts_voice") or settings.twilio_tts_voice
    tts_model = voice_settings.get("tts_model") or settings.twilio_tts_model
    tts_speed = voice_settings.get("tts_speed") or settings.twilio_tts_speed
    tts_stability = voice_settings.get("tts_stability") or settings.twilio_tts_stability
    tts_similarity_boost = (
        voice_settings.get("tts_similarity_boost") or settings.twilio_tts_similarity_boost
    )

    if tts_voice:
        relay_kwargs["voice"] = tts_voice
    if tts_model:
        relay_kwargs["tts_model"] = tts_model
    if tts_speed:
        relay_kwargs["tts_speed"] = tts_speed
    if tts_stability:
        relay_kwargs["tts_stability"] = tts_stability
    if tts_similarity_boost:
        relay_kwargs["tts_similarity_boost"] = tts_similarity_boost

    connect.conversation_relay(**relay_kwargs)
    response.append(connect)
    return str(response)


def generate_realtime_stream_twiml(
    customer_phone: str,
    customer_name: str | None,
    direction: str,
    welcome_greeting: str | None = None,
) -> str:
    """Generate TwiML that connects the call to a bidirectional media stream."""
    response = VoiceResponse()
    connect = response.connect()
    stream = connect.stream(
        url=f"wss://{settings.base_url.replace('https://', '').replace('http://', '')}/ws/realtime-media"
    )
    stream.parameter(name="customer_phone", value=customer_phone or "")
    stream.parameter(name="customer_name", value=customer_name or "")
    stream.parameter(name="direction", value=direction)
    stream.parameter(name="project_name", value="Biomarcadores")
    if welcome_greeting:
        stream.parameter(name="welcome_greeting", value=welcome_greeting)
    return str(response)


async def make_outbound_call(to_number: str) -> str:
    """Initiate an outbound call using Twilio."""
    try:
        base_url = _validate_public_base_url()
        call = twilio_client.calls.create(
            to=to_number,
            from_=settings.twilio_phone_number,
            url=f"{base_url}/twilio/voice",
            method="POST",
            status_callback=f"{base_url}/twilio/status",
            status_callback_method="POST",
            machine_detection=settings.twilio_machine_detection,
            machine_detection_timeout=settings.twilio_machine_detection_timeout,
            async_amd="true" if settings.twilio_async_amd else "false",
            async_amd_status_callback=f"{base_url}/twilio/amd",
            async_amd_status_callback_method="POST",
        )
        logger.info("Outbound call initiated: %s -> %s (SID: %s)", settings.twilio_phone_number, to_number, call.sid)
        return call.sid
    except Exception as exc:
        logger.error("Failed to make outbound call to %s: %s", to_number, exc)
        raise


def hangup_call(call_sid: str):
    """Force-complete a live call, useful for voicemail detection."""
    return twilio_client.calls(call_sid).update(status="completed")
