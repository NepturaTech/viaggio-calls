import json
import logging
from asyncio import TimeoutError as AsyncTimeoutError

import websockets

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _turn_detection_config() -> dict:
    """Turn detection calibrable por .env sin redeploy.

    OPENAI_REALTIME_TURN_DETECTION=semantic_vad → decide fin de turno por
    contenido (mejor con ruido/muletillas, +latencia). Default server_vad con
    OPENAI_REALTIME_VAD_THRESHOLD (subirlo si el eco corta a Andrea) y
    OPENAI_REALTIME_SILENCE_MS (subirlo si corta a quien habla pausado).
    """
    if settings.openai_realtime_turn_detection == "semantic_vad":
        return {
            "type": "semantic_vad",
            "create_response": True,
            "interrupt_response": True,
        }
    return {
        "type": "server_vad",
        "threshold": settings.openai_realtime_vad_threshold,
        "prefix_padding_ms": 400,
        "silence_duration_ms": settings.openai_realtime_silence_ms,
        "create_response": True,
        "interrupt_response": True,
    }


def get_realtime_ws_url() -> str:
    return f"wss://api.openai.com/v1/realtime?model={settings.openai_realtime_model}"


async def connect_realtime(instructions: str):
    """Open a Realtime API WebSocket session configured for phone audio."""
    if not settings.openai_api_key:
        raise ValueError("OpenAI API key is not configured for realtime voice mode")

    # Sin header OpenAI-Beta: la forma beta fue deshabilitada (beta_api_shape_disabled)
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
    }

    ws = await websockets.connect(
        get_realtime_ws_url(),
        additional_headers=headers,
        max_size=None,
        open_timeout=30,
        close_timeout=10,
    )

    # Forma GA de la API Realtime (la beta fue deshabilitada): session.type=realtime,
    # audio.input/output.format en vez de input_audio_format, audio/pcmu = g711_ulaw.
    session_update = {
        "type": "session.update",
        "session": {
            "type": "realtime",
            "output_modalities": ["audio"],
            "instructions": f"{instructions}\n\n## Voz y estilo oral\n{settings.openai_realtime_speaking_style}",
            "audio": {
                "input": {
                    "format": {"type": "audio/pcmu"},
                    "transcription": {
                        "model": "gpt-4o-mini-transcribe",
                        "language": "es",
                    },
                    "turn_detection": _turn_detection_config(),
                },
                "output": {
                    "format": {"type": "audio/pcmu"},
                    "voice": settings.openai_realtime_voice,
                },
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


async def update_session_instructions(ws, instructions: str):
    """Replace the session instructions mid-call (GA partial session.update)."""
    await ws.send(json.dumps({
        "type": "session.update",
        "session": {
            "type": "realtime",
            "instructions": (
                f"{instructions}\n\n## Voz y estilo oral\n"
                f"{settings.openai_realtime_speaking_style}"
            ),
        },
    }))


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
