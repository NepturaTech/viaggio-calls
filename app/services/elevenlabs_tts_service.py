"""TTS streaming de ElevenLabs para el modo Realtime hibrido.

GPT Realtime genera texto por fragmentos; esta clase los convierte en audio
ulaw_8000 (el formato nativo de Twilio Media Streams) via el WebSocket
stream-input de ElevenLabs. Una instancia = UNA respuesta del modelo.
"""
import asyncio
import contextlib
import json
import logging

import websockets

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class ElevenLabsSpeaker:
    """Recibe texto por feed() y entrega audio base64 via el callback on_audio."""

    def __init__(self, on_audio):
        self._on_audio = on_audio
        self._ws = None
        self._reader: asyncio.Task | None = None

    async def start(self):
        url = (
            f"wss://api.elevenlabs.io/v1/text-to-speech/{settings.elevenlabs_voice_id}"
            f"/stream-input?model_id={settings.elevenlabs_tts_model}"
            "&output_format=ulaw_8000&language_code=es"
        )
        self._ws = await websockets.connect(url, max_size=None, open_timeout=10)
        await self._ws.send(json.dumps({
            "text": " ",
            "voice_settings": {
                "stability": float(settings.twilio_tts_stability),
                "similarity_boost": float(settings.twilio_tts_similarity_boost),
                "speed": float(settings.twilio_tts_speed),
            },
            # Primer chunk corto para que el audio arranque rapido.
            "generation_config": {"chunk_length_schedule": [50, 90, 120, 150]},
            "xi_api_key": settings.elevenlabs_api_key,
        }))
        self._reader = asyncio.create_task(self._read())

    async def _read(self):
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                if msg.get("error"):
                    logger.error("ElevenLabs TTS error: %s", msg)
                    break
                audio = msg.get("audio")
                if audio:
                    await self._on_audio(audio)
                if msg.get("isFinal"):
                    break
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug("ElevenLabs reader terminado: %s", exc)
        finally:
            await self._close()

    async def feed(self, text: str):
        if self._ws is not None and text:
            with contextlib.suppress(Exception):
                await self._ws.send(json.dumps({"text": text}))

    async def finish_input(self):
        """Cierra la entrada de texto; el audio restante sigue llegando en background."""
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.send(json.dumps({"text": ""}))

    async def abort(self):
        """Barge-in: descartar de inmediato el audio que falte."""
        if self._reader is not None:
            self._reader.cancel()
            self._reader = None
        await self._close()

    async def _close(self):
        ws, self._ws = self._ws, None
        if ws is not None:
            with contextlib.suppress(Exception):
                await ws.close()
