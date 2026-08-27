"""Self-check: Andrea solo puede prometer el mensaje si el flow SI se envio.

Corre con:  python test_lost_contact_flow.py
"""
import io
import os

import app.routes.ws_conversationrelay as ws

_WS = io.open(ws.__file__, encoding="utf-8").read()
_HOOK = io.open(
    os.path.join(os.path.dirname(ws.__file__), "twilio_webhook.py"), encoding="utf-8"
).read()


def _branch(sent):
    """Devuelve la nota que se inyecta al modelo segun el bool del flow."""
    blk = _WS.split("if LOST_CONTACT_PATTERN.search(user_text):")[1].split("logger.info")[0]
    i_if = blk.index("if _sent:")
    i_else = blk.index("else:", i_if)
    return blk[i_if:i_else] if sent else blk[i_else:]


def test_pattern_detecta_perdida_de_contacto():
    for frase in ("perdi el numero", "no tengo el chat", "cual es el numero de whatsapp"):
        assert ws.LOST_CONTACT_PATTERN.search(frase), frase


def test_promete_envio_solo_cuando_el_flow_salio():
    assert "acabamos de enviar" in _branch(True)
    fallback = _branch(False)
    assert "acabamos de enviar" not in fallback
    assert "NUNCA prometas" in fallback


def test_no_duplica_el_flow_al_colgar():
    assert '"lost_contact_flow_sent"] = True' in _WS
    assert '"lost_contact_flow_sent"' in _HOOK


if __name__ == "__main__":
    test_pattern_detecta_perdida_de_contacto()
    test_promete_envio_solo_cuando_el_flow_salio()
    test_no_duplica_el_flow_al_colgar()
    print("OK")
