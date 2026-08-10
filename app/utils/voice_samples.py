"""Genera muestras WAV locales de las voces de gpt-realtime para escoger la de Andrea.

Uso:  python -m app.utils.voice_samples [voz1 voz2 ...]
Sin argumentos genera todas. Salida: voice_samples/<voz>.wav (24 kHz mono).
Usa el MISMO modelo Realtime de las llamadas, asi que lo que se oye aqui es
exactamente lo que oye el paciente (sin el filtro telefonico de 8 kHz).
"""
import asyncio
import base64
import json
import sys
import wave
from pathlib import Path

import websockets

from app.config import get_settings

settings = get_settings()

VOICES = ["marin", "cedar", "alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse"]

SAMPLE_TEXT = (
    "Hola, ¿hablo con Angie Tatiana? Le habla Andrea, del proyecto de diabetes "
    "mellitus tipo dos que realizamos junto con el hospital. La llamo para "
    "acompañarla en su registro de comidas. ¿Cómo se ha sentido últimamente?"
)

OUT_DIR = Path("voice_samples")


async def sample_voice(voice: str) -> bool:
    url = f"wss://api.openai.com/v1/realtime?model={settings.openai_realtime_model}"
    headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
    try:
        async with websockets.connect(url, additional_headers=headers, max_size=None) as ws:
            await ws.send(json.dumps({
                "type": "session.update",
                "session": {
                    "type": "realtime",
                    "output_modalities": ["audio"],
                    # El MISMO estilo que se aplica en llamadas reales, para que la
                    # muestra suene igual que Andrea en produccion.
                    "instructions": settings.openai_realtime_speaking_style,
                    "audio": {
                        # pcm16 24 kHz: calidad completa para comparar voces
                        "input": {"format": {"type": "audio/pcm", "rate": 24000}},
                        "output": {"format": {"type": "audio/pcm", "rate": 24000}, "voice": voice},
                    },
                },
            }))
            await ws.send(json.dumps({
                "type": "response.create",
                "response": {"instructions": f"Di exactamente, sin cambiar nada: {SAMPLE_TEXT}"},
            }))

            pcm = bytearray()
            async for raw in ws:
                event = json.loads(raw)
                etype = event.get("type", "")
                if etype in {"response.audio.delta", "response.output_audio.delta"}:
                    pcm.extend(base64.b64decode(event["delta"]))
                elif etype == "response.done":
                    break
                elif etype == "error":
                    print(f"  {voice}: ERROR {event.get('error', event)}")
                    return False

            if not pcm:
                print(f"  {voice}: sin audio")
                return False

            OUT_DIR.mkdir(exist_ok=True)
            path = OUT_DIR / f"{voice}.wav"
            with wave.open(str(path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(24000)
                wf.writeframes(bytes(pcm))
            print(f"  {voice}: OK -> {path} ({len(pcm) // 48000}s aprox)")
            return True
    except Exception as exc:
        print(f"  {voice}: fallo ({exc})")
        return False


async def main():
    voices = sys.argv[1:] or VOICES
    print(f"Generando muestras con {settings.openai_realtime_model}: {', '.join(voices)}")
    ok = 0
    for voice in voices:  # secuencial: una sesion Realtime a la vez
        if await sample_voice(voice):
            ok += 1
    print(f"{ok}/{len(voices)} muestras en {OUT_DIR.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())
