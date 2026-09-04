"""Grok Voice (xAI Realtime) como backend de voz, gemelo de realtime_service.

Mismo contrato que el de OpenAI (connect_realtime / update_session_instructions
/ request_initial_greeting) para que el bridge /ws/realtime-media no cambie.

MEDIDO en el lab (grok-voice-lab/probe_pcmu.py, 2026-09-04):
  - xAI habla g711 mu-law 8 kHz en los dos sentidos => el bridge pasa el base64
    de Twilio tal cual, sin resamplear.
  - server_vad con los mismos knobs (threshold / silence_duration_ms), y un
    turn_detection invalido SI da error (aqui la API valida, a diferencia de la voz).
  - los nombres de evento son los mismos que ya maneja el bridge
    (response.output_audio.delta, input_audio_buffer.speech_started, etc).

Diferencias de forma con OpenAI, todas medidas:
  - `voice` va en la RAIZ de session, NO dentro de audio.output.
  - hace falta "transport": "json" en input y output; sin eso no llega audio.
  - el idioma va en transcription.language_hint (no "language" + modelo).
  - NO hay session.type ni output_modalities.

TRAMPA CONOCIDA: una voz invalida NO da error — la API la acepta callada y usa
la de por defecto (`ara`), y session.updated no devuelve el nombre. El unico
modo de saber que voz sono es OIRLA.
"""
import json
import logging
from asyncio import TimeoutError as AsyncTimeoutError

import websockets

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _turn_detection_config() -> dict:
    """Mismos knobs que el path OpenAI, calibrables por .env sin redeploy."""
    if settings.xai_realtime_turn_detection == "semantic_vad":
        return {
            "type": "semantic_vad",
            "create_response": True,
            "interrupt_response": True,
        }
    return {
        "type": "server_vad",
        "threshold": settings.xai_realtime_vad_threshold,
        "prefix_padding_ms": 400,
        "silence_duration_ms": settings.xai_realtime_silence_ms,
        "create_response": True,
        "interrupt_response": True,
    }


def _style(instructions: str) -> str:
    # ponytail: reusa el estilo oral del path OpenAI — es el mismo pedido
    # (acento colombiano, nada de zeta castellana) y ya esta calibrado.
    return f"{instructions}\n\n## Voz y estilo oral\n{settings.openai_realtime_speaking_style}"


def get_realtime_ws_url() -> str:
    return f"wss://api.x.ai/v1/realtime?model={settings.xai_realtime_model}"


async def connect_realtime(instructions: str, text_only: bool = False):
    """Abre la sesion de voz xAI configurada para telefonia (mu-law 8k)."""
    if not settings.xai_api_key:
        raise ValueError("XAI_API_KEY no configurada para el modo de voz grok")
    if text_only:
        # El hibrido (modelo en texto + ElevenLabs) solo existe para OpenAI.
        raise ValueError(
            "El modo hibrido con ElevenLabs no esta implementado para Grok; "
            "usa REALTIME_TTS_PROVIDER=openai o TWILIO_VOICE_MODE=realtime"
        )

    ws = await websockets.connect(
        get_realtime_ws_url(),
        additional_headers={"Authorization": f"Bearer {settings.xai_api_key}"},
        max_size=None,
        open_timeout=30,
        close_timeout=10,
    )

    await ws.send(json.dumps(build_session_update(instructions)))
    logger.info(
        "Grok realtime session initialized with model=%s voice=%s",
        settings.xai_realtime_model,
        settings.xai_voice,
    )
    return ws


def build_session_update(instructions: str) -> dict:
    """Separado de connect_realtime para poder testear la forma sin red."""
    return {
        "type": "session.update",
        "session": {
            "instructions": _style(instructions),
            "voice": settings.xai_voice,          # en la RAIZ, no en audio.output
            "audio": {
                "input": {
                    "format": {"type": "audio/pcmu"},   # lo que manda Twilio
                    "transport": "json",
                    "transcription": {"language_hint": "es"},
                    "turn_detection": _turn_detection_config(),
                },
                "output": {
                    "format": {"type": "audio/pcmu"},
                    "transport": "json",
                },
            },
        },
    }


async def update_session_instructions(ws, instructions: str):
    """Reemplaza las instructions a mitad de llamada (session.update parcial)."""
    await ws.send(json.dumps({
        "type": "session.update",
        "session": {"instructions": _style(instructions)},
    }))


def describe_realtime_error(exc: Exception) -> str:
    if isinstance(exc, AsyncTimeoutError):
        return (
            "No se pudo abrir la sesion Realtime con xAI dentro del tiempo esperado. "
            "Suele ser bloqueo de red, proxy/firewall o salida websocket restringida "
            "hacia api.x.ai."
        )
    return str(exc)


async def request_initial_greeting(ws, greeting: str):
    """Abre la conversacion con el saludo exacto del guion."""
    if not greeting:
        return
    await ws.send(json.dumps({
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
    }))
