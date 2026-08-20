"""Check de la ubicacion del aviso legal (ley 1581).

Correr: python test_legal_notice.py
Falla si el aviso vuelve a anteponerse al saludo de ConversationRelay
(era lo primero que oia el paciente y la llamada sonaba a bot).
"""

from app.services.twilio_service import settings
from app.services import twilio_service


def demo() -> None:
    aviso = "Esta llamada sera grabada conforme a la ley 1581."
    saludo = "Hola, hablo con Ana?"
    settings.twilio_recording_announcement = aviso
    settings.twilio_recording_enabled = True

    cr = twilio_service.generate_conversation_relay_twiml(saludo)
    assert "ley 1581" not in cr, "el aviso volvio al welcomeGreeting de ConversationRelay"
    assert "Ana" in cr, "el saludo se perdio"

    # El path Realtime esta dormido y conserva el aviso en el saludo (alli la
    # grabacion sigue arrancando con record=True en calls.create).
    rt = twilio_service.generate_realtime_stream_twiml(
        "+573001112233", "Ana", "outbound-api", welcome_greeting=saludo
    )
    assert "ley 1581" in rt, "el path Realtime se quedo sin aviso legal"

    print("OK: aviso fuera del saludo en CR, presente en Realtime")


if __name__ == "__main__":
    demo()
