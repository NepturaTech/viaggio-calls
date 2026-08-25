"""Andrea puede responder por llamadas anteriores.

Hasta ahora call_logs solo se escribia: cada llamada arrancaba de cero y ante
"¿que me dijeron la vez pasada?" no habia nada en el contexto. El dato ya estaba
guardado (transcript_summary), solo faltaba leerlo.

Sin red: se le pasa el dataset_context ya armado, como hace el WebSocket.
"""
from app.services.prompt_service import build_context_prompt
from app.services.supabase_rest_service import get_recent_calls

CLIENTE = {
    "full_name": "Maria Perez",
    "document_number": "1101989123",
    "phone_number": "+573001112233",
    "project_name": "proyecto de diabetes mellitus tipo 2",
}
SCRIPT = {"name": "reactivacion_seguimiento", "system_prompt": ""}
LLAMADAS = [
    {"created_at": "2026-08-19T14:05:00+00:00", "script_name": "reactivacion_seguimiento",
     "status": "completed",
     "transcript_summary": "user: si | assistant: Cuentame, ¿pasó algo con la plataforma? "
                           "| user: no he tenido tiempo | assistant: Tranquila, con un registro al dia basta."},
    {"created_at": "2026-08-12T16:40:00+00:00", "script_name": "proxima_visita",
     "status": "completed",
     "transcript_summary": "user: claro | assistant: Te confirmo la visita para el jueves."},
]


def _prompt(previous_calls):
    return build_context_prompt(
        CLIENTE, [], script=SCRIPT, dataset_context={"previous_calls": previous_calls}
    )


def test_bloque_presente_con_fecha_y_contenido():
    p = _prompt(LLAMADAS)
    assert "## Llamadas anteriores a este paciente" in p
    assert "19/08/2026" in p and "12/08/2026" in p
    assert "no he tenido tiempo" in p
    assert "Te confirmo la visita para el jueves" in p
    assert "reactivacion_seguimiento" in p and "proxima_visita" in p


def test_advierte_que_no_es_la_conversacion_completa():
    """transcript_summary son los ultimos 6 turnos a 100 chars: si el prompt no lo
    dice, Andrea afirmara cosas de una llamada que no puede ver entera."""
    p = _prompt(LLAMADAS)
    assert "NO la conversacion completa" in p
    assert "no afirmes que se dijo algo que no aparezca aqui" in p


def test_sin_llamadas_previas_no_hay_bloque():
    p = _prompt([])
    assert "## Llamadas anteriores" not in p
    # y la ruta de "que me dijeron la vez pasada" sigue existiendo, para que
    # responda con honestidad en vez de inventar
    assert "Llamadas anteriores a este paciente" in p  # la linea de Fuentes de apoyo


def test_multilinea_queda_en_una_sola_linea():
    """Un salto de linea dentro del resumen partiria el item del prompt en dos."""
    p = _prompt([{"created_at": "2026-08-19T14:05:00+00:00", "script_name": "x",
                  "transcript_summary": "user: hola\nassistant: buenas\nuser: chao"}])
    bloque = p.split("## Llamadas anteriores a este paciente\n")[1]
    assert bloque.splitlines()[0].endswith("user: chao")


def test_documento_vacio_no_consulta():
    assert get_recent_calls("") == []
    assert get_recent_calls(None) == []


if __name__ == "__main__":
    for nombre, fn in sorted(globals().items()):
        if nombre.startswith("test_"):
            fn()
            print("ok", nombre)
    print("OK")
