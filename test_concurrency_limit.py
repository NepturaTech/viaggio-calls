"""Self-check del tope de llamadas simultáneas.

Corre con:  python test_concurrency_limit.py
"""
import io

from app.db import repositories as repo


def test_cuenta_y_libera():
    repo._active_calls.clear()
    for i in range(5):
        repo.mark_call_active("CA%d" % i)
    assert repo.active_call_count() == 5
    repo.mark_call_ended("CA0")
    assert repo.active_call_count() == 4
    repo.mark_call_ended("CA0")  # idempotente
    assert repo.active_call_count() == 4


def test_libera_por_antiguedad_si_se_pierde_el_webhook():
    repo._active_calls.clear()
    repo.mark_call_active("CA_vieja")
    repo._active_calls["CA_vieja"] -= repo._ACTIVE_CALL_MAX_SECONDS + 1
    repo.mark_call_active("CA_nueva")
    assert repo.active_call_count() == 1
    assert "CA_vieja" not in repo._active_calls


def test_el_guardia_va_antes_de_marcar_en_twilio():
    src = io.open("app/routes/twilio_webhook.py", encoding="utf-8").read()
    cuerpo = src.split("async def trigger_outbound_call(")[1]
    assert cuerpo.index("active_call_count()") < cuerpo.index("make_outbound_call("), \
        "el tope debe rechazar ANTES de crear la llamada en Twilio"
    assert "mark_call_active(call_sid)" in cuerpo


if __name__ == "__main__":
    test_cuenta_y_libera()
    test_libera_por_antiguedad_si_se_pierde_el_webhook()
    test_el_guardia_va_antes_de_marcar_en_twilio()
    print("OK")
