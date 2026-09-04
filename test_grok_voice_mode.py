"""Check de la forma de session de xAI y del ruteo por TWILIO_VOICE_MODE.

Correr: python test_grok_voice_mode.py
Cubre lo que se rompio en el lab y que xAI NO siempre rechaza (se descubriria
recien en una llamada real): `voice` fuera de la raiz, falta de
"transport": "json", formato de audio distinto de mu-law 8k, o un VAD que no
crea la respuesta sola (en telefonia nadie commitea el buffer a mano).
"""
import importlib
import os

from app.config import get_settings


def _recargar(modulo, **entorno):
    for k, v in entorno.items():
        os.environ[k] = v
    get_settings.cache_clear()
    mod = importlib.import_module(modulo)
    return importlib.reload(mod)


def demo() -> None:
    grok = _recargar("app.services.grok_realtime_service",
                     XAI_API_KEY="xai-test", XAI_VOICE="carina")
    sesion = grok.build_session_update("Eres Andrea.")["session"]

    # voice en la RAIZ, no dentro de audio.output (el error #1 de la guia de xAI)
    assert sesion["voice"] == "carina", sesion["voice"]
    assert "voice" not in sesion["audio"]["output"]

    # mu-law 8k en ambos sentidos = lo que manda y espera Twilio, sin resampleo
    assert sesion["audio"]["input"]["format"] == {"type": "audio/pcmu"}
    assert sesion["audio"]["output"]["format"] == {"type": "audio/pcmu"}

    # sin transport json no llega audio por el WS
    assert sesion["audio"]["input"]["transport"] == "json"
    assert sesion["audio"]["output"]["transport"] == "json"

    # el VAD tiene que crear la respuesta solo
    td = sesion["audio"]["input"]["turn_detection"]
    assert td["type"] == "server_vad" and td["create_response"] is True, td

    # el estilo oral configurado va pegado a las instructions (no hardcodeado:
    # el .env de la VM lo sobreescribe)
    estilo = get_settings().openai_realtime_speaking_style
    assert sesion["instructions"].startswith("Eres Andrea.")
    assert estilo in sesion["instructions"]

    # el modo elige el backend, y cualquier otro valor deja el de OpenAI
    for modo, esperado in (("grok", "grok_realtime_service"),
                           ("realtime", "realtime_service"),
                           ("conversation_relay", "realtime_service")):
        bridge = _recargar("app.routes.ws_conversationrelay", TWILIO_VOICE_MODE=modo)
        elegido = bridge._voice_backend().__name__
        assert elegido.endswith(esperado), f"{modo} -> {elegido}"

    os.environ["TWILIO_VOICE_MODE"] = "conversation_relay"
    get_settings.cache_clear()
    print("OK: forma de session xAI y ruteo por TWILIO_VOICE_MODE correctos")


if __name__ == "__main__":
    demo()
