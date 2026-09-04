"""Check del guard de BASE_URL para el modo Realtime.

Correr: python test_realtime_base_url.py
Falla si el guard deja pasar un BASE_URL que Twilio no puede alcanzar
(la llamada quedaria muda, sin fallback a ConversationRelay).
"""

import os

from app.services.twilio_service import _realtime_ws_url


def demo() -> None:
    assert (
        _realtime_ws_url("https://calls.neptura.tech")
        == "wss://calls.neptura.tech/ws/realtime-media"
    )
    assert (
        _realtime_ws_url("https://calls.neptura.tech/")
        == "wss://calls.neptura.tech/ws/realtime-media"
    )

    # trycloudflare pasa (es el ingress real de la VM hoy), solo con warning
    assert (
        _realtime_ws_url("https://boulder-too-sauce-upper.trycloudflare.com")
        == "wss://boulder-too-sauce-upper.trycloudflare.com/ws/realtime-media"
    )

    for malo in ("", None):
        try:
            _realtime_ws_url(malo)
        except ValueError:
            pass
        else:
            raise AssertionError(f"BASE_URL invalido paso el guard: {malo!r}")

    # Modo grok sin XAI_API_KEY: tiene que caer a ConversationRelay, no quedar
    # mudo dentro del WebSocket (donde ya no hay fallback).
    import importlib

    from app.config import get_settings
    os.environ["TWILIO_VOICE_MODE"] = "grok"
    os.environ["XAI_API_KEY"] = ""
    os.environ["BASE_URL"] = "https://calls.neptura.tech"
    get_settings.cache_clear()
    import app.services.twilio_service as ts
    importlib.reload(ts)
    try:
        ts.generate_realtime_stream_twiml("+573001112233", "Davide", "outbound")
    except ValueError:
        pass
    else:
        raise AssertionError("grok sin XAI_API_KEY genero TwiML: la llamada quedaria muda")

    os.environ["TWILIO_VOICE_MODE"] = "conversation_relay"
    get_settings.cache_clear()
    importlib.reload(ts)

    print("OK: guard de BASE_URL correcto")


if __name__ == "__main__":
    demo()
