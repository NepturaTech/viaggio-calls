import asyncio
import json
from asyncio import TimeoutError as AsyncTimeoutError

import websockets

from app.config import get_settings


async def run_smoketest():
    settings = get_settings()

    if not settings.openai_api_key:
        print("ERROR: OPENAI_API_KEY no esta configurada.")
        return 1

    url = f"wss://api.openai.com/v1/realtime?model={settings.openai_realtime_model}"
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "OpenAI-Beta": "realtime=v1",
    }

    print(f"Conectando a: {url}")

    try:
        async with websockets.connect(
            url,
            additional_headers=headers,
            open_timeout=30,
            close_timeout=10,
            max_size=None,
        ) as ws:
            print("OK: handshake WebSocket completado.")

            session_update = {
                "type": "session.update",
                "session": {
                    "modalities": ["audio", "text"],
                    "instructions": (
                        "Responde siempre en espanol. "
                        "Saluda de forma breve, natural y calida."
                    ),
                    "voice": settings.openai_realtime_voice,
                    "input_audio_format": "g711_ulaw",
                    "output_audio_format": "g711_ulaw",
                    "input_audio_transcription": {
                        "model": "gpt-4o-mini-transcribe",
                        "language": "es",
                    },
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": 0.5,
                        "prefix_padding_ms": 300,
                        "silence_duration_ms": 700,
                        "create_response": True,
                        "interrupt_response": True,
                    },
                    "max_output_tokens": 120,
                },
            }

            await ws.send(json.dumps(session_update))
            print("OK: session.update enviado.")

            response_create = {
                "type": "response.create",
                "response": {
                    "output_modalities": ["text"],
                    "instructions": (
                        "Di exactamente una frase breve de saludo en espanol para una llamada telefonica."
                    ),
                },
            }
            await ws.send(json.dumps(response_create))
            print("OK: response.create enviado.")

            collected_text = []
            for _ in range(20):
                raw = await asyncio.wait_for(ws.recv(), timeout=10)
                event = json.loads(raw)
                event_type = event.get("type", "unknown")
                print(f"EVENT: {event_type}")

                if event_type in {"error", "response.done", "session.created", "session.updated"}:
                    print(json.dumps(event, ensure_ascii=False, indent=2))

                if event_type == "response.text.delta":
                    delta = event.get("delta", "")
                    if delta:
                        collected_text.append(delta)

                if event_type == "response.done":
                    output = event.get("response", {}).get("output", [])
                    if collected_text:
                        print("TEXT:", "".join(collected_text))
                    if output:
                        print("OK: el modelo devolvio una respuesta.")
                    return 0

            print("WARN: no llego response.done dentro del limite esperado.")
            if collected_text:
                print("TEXT PARCIAL:", "".join(collected_text))
            return 2

    except AsyncTimeoutError:
        print("ERROR: timeout durante handshake o recepcion de eventos.")
        print("Esto suele indicar bloqueo de red/proxy/firewall o salida websocket restringida.")
        return 3
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        return 4


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run_smoketest()))
