import json
import logging
from asyncio import TimeoutError as AsyncTimeoutError

import websockets

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def get_realtime_ws_url() -> str:
    return f"wss://api.openai.com/v1/realtime?model={settings.openai_realtime_model}"


async def connect_realtime(instructions: str):
    """Open a Realtime API WebSocket session configured for phone audio."""
    if not settings.openai_api_key:
        raise ValueError("OpenAI API key is not configured for realtime voice mode")

    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "OpenAI-Beta": "realtime=v1",
    }

    ws = await websockets.connect(
        get_realtime_ws_url(),
        additional_headers=headers,
        max_size=None,
        open_timeout=30,
        close_timeout=10,
    )

    session_update = {
        "type": "session.update",
        "session": {
            "instructions": f"{instructions}\n\n## Voz y estilo oral\n{settings.openai_realtime_speaking_style}",
            "modalities": ["audio", "text"],
            "voice": settings.openai_realtime_voice,
            "input_audio_format": "g711_ulaw",
            "output_audio_format": "g711_ulaw",
            "input_audio_transcription": {
                "model": "gpt-4o-mini-transcribe",
                "language": "es",
            },
            "turn_detection": {
                "type": "server_vad",
                "threshold": 0.7,
                "prefix_padding_ms": 400,
                # Calibracion: cuanto silencio espera Andrea antes de responder.
                # 1000 ms se sentia lento; 500 ms es mas natural pero puede cortar
                # a quien habla pausado (adultos mayores). Ajustable por .env
                # (OPENAI_REALTIME_SILENCE_MS) para afinar sin redeploy.
                "silence_duration_ms": settings.openai_realtime_silence_ms,
                "create_response": True,
                "interrupt_response": True,
            },
        },
    }

    await ws.send(json.dumps(session_update))
    logger.info(
        "Realtime session initialized with model=%s voice=%s",
        settings.openai_realtime_model,
        settings.openai_realtime_voice,
    )
    return ws


def describe_realtime_error(exc: Exception) -> str:
    """Return a user-friendly diagnostic for realtime connection failures."""
    if isinstance(exc, AsyncTimeoutError):
        return (
            "No se pudo abrir la sesion Realtime con OpenAI dentro del tiempo esperado. "
            "Esto suele indicar bloqueo de red, proxy/firewall, o salida websocket restringida "
            "hacia api.openai.com."
        )
    return str(exc)


async def request_initial_greeting(ws, greeting: str):
    """Ask the realtime model to open the conversation with the scripted greeting."""
    if not greeting:
        return

    event = {
        "type": "response.create",
        "response": {
            "modalities": ["audio", "text"],
            "instructions": (
                "Abre la llamada en espanol, con tono calido y natural. "
                f"{settings.openai_realtime_speaking_style} "
                "Tu primera intervencion debe decir exactamente este saludo, sin reformularlo, "
                "sin resumirlo, sin cambiar el orden y sin hacer otra pregunta antes. "
                "Pronuncialo con naturalidad, pero respeta el texto. "
                f"Saludo exacto: {greeting}"
            ),
        },
    }
    await ws.send(json.dumps(event))
