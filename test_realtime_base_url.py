"""Check del guard de BASE_URL para el modo Realtime.

Correr: python test_realtime_base_url.py
Falla si el guard deja pasar un BASE_URL que Twilio no puede alcanzar
(la llamada quedaria muda, sin fallback a ConversationRelay).
"""

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

    print("OK: guard de BASE_URL correcto")


if __name__ == "__main__":
    demo()
