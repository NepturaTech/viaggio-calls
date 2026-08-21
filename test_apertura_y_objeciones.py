"""Dos requisitos del prompt que se rompieron antes en produccion:

1. Antes de que la persona confirme su identidad, Andrea no puede decir el nombre
   clinico del proyecto ni el del hospital (quien contesta puede ser un familiar).
2. Tres bloques del prompt se contradecian: "Institucion" prohibia "de parte del
   hospital" mientras "Instrucciones de presentacion" lo ORDENABA. El modelo
   obedecia al segundo y lo dijo en ~la mitad de 38 llamadas reales.

Ademas: el bloque de objeciones debe estar presente en llamadas de seguimiento.
"""
from app.services.prompt_service import build_context_prompt

CLIENTE = {
    "full_name": "Maria Perez",
    "phone_number": "+573001112233",
    "hospital_name": "Hospital San Juan de Dios",
    "project_name": "proyecto de diabetes mellitus tipo 2",
}
SCRIPT_SEGUIMIENTO = {"name": "reactivacion_seguimiento", "system_prompt": ""}


def _prompt(customer=CLIENTE, script=SCRIPT_SEGUIMIENTO):
    return build_context_prompt(customer, [], script=script)


def test_no_dice_de_parte_del_hospital():
    p = _prompt()
    # la ORDEN que existia y contradecia al bloque "Institucion" ya no esta
    assert "Di que te comunicas de parte del" not in p
    assert "vuelve a mencionar con claridad que llamas de parte del" not in p
    assert "Te llamo de parte del [hospital exacto]" not in p
    # y la prohibicion si sigue
    assert "NUNCA digas 'de parte del hospital'" in p
    # ninguna linea que NO sea una prohibicion puede traer la frase
    for linea in p.splitlines():
        if "de parte del" in linea:
            assert "NUNCA" in linea, linea


def test_etiqueta_neutra_antes_de_confirmar():
    p = _prompt()
    # la linea de aclaracion previa a la confirmacion usa la etiqueta neutra...
    assert "Te habla Andrea, del proyecto de Biomarcadores. ¿Hablo con" in p
    # ...y no el nombre clinico ni el hospital
    assert "del proyecto de diabetes mellitus tipo 2. ¿Hablo con" not in p
    assert "del Hospital San Juan de Dios. ¿Hablo con" not in p


def test_no_miente_sobre_lo_que_dijo_el_saludo():
    p = _prompt()
    assert "ya menciono el" not in p
    assert "no menciono el hospital y no menciono el proyecto" in p


def test_bloque_de_objeciones_en_seguimiento():
    p = _prompt()
    assert "Si el paciente no ha registrado sus comidas" in p
    assert "la foto NO es obligatoria" in p
    assert "Nunca confirmes un registro que no te conste" in p
    # no aplica a llamadas de invitacion
    inv = _prompt(script={"name": "invitacion", "system_prompt": ""})
    assert "Si el paciente no ha registrado sus comidas" not in inv


def test_sin_hospital_no_inventa_uno():
    sin_hosp = dict(CLIENTE)
    sin_hosp.pop("hospital_name")
    p = _prompt(customer=sin_hosp)
    assert "NO menciones ningun hospital" in p




# ── Presentacion determinista del turno 1 ───────────────────────────────────
from app.services.prompt_service import (  # noqa: E402
    IDENTITY_CONFIRMED_PATTERN,
    build_call_intro,
)

SCRIPT_PV = {"name": "proxima_visita", "project_name": "Proyecto de diabetes mellitus tipo 2"}


def test_intro_con_identidad_confirmada():
    intro = build_call_intro(CLIENTE, SCRIPT_PV, identity_confirmed=True)
    assert intro.startswith("Que bueno, Maria Perez. ")
    assert "Te habla Andrea, del proyecto de diabetes mellitus tipo 2" in intro
    assert "que realizamos junto con el Hospital San Juan de Dios" in intro
    assert "de parte del" not in intro
    assert intro.endswith(" ")  # se concatena con el aviso legal


def test_intro_sin_confirmar_usa_etiqueta_neutra():
    intro = build_call_intro(CLIENTE, SCRIPT_PV, identity_confirmed=False)
    assert "proyecto de Biomarcadores" in intro
    assert "diabetes" not in intro.lower()
    assert "Hospital" not in intro


def test_intro_sin_hospital_no_inventa():
    sin_hosp = {k: v for k, v in CLIENTE.items() if k != "hospital_name"}
    intro = build_call_intro(sin_hosp, SCRIPT_PV, identity_confirmed=True)
    assert "junto con el" not in intro
    assert "Hospital" not in intro


def test_deteccion_de_confirmacion():
    confirma = ["sí", "con él.", "Sí con él", "con ella", "soy yo", "Sí, hablas con él",
                "claro", "así es", "Con ella habla"]
    no_confirma = ["Aló?", "¿quién habla?", "casi no escucho", "un momento",
                   "gracias", "no", "¿de parte de quién?"]
    for t in confirma:
        assert IDENTITY_CONFIRMED_PATTERN.search(t), t
    for t in no_confirma:
        assert not IDENTITY_CONFIRMED_PATTERN.search(t), t


def test_el_modelo_ya_no_debe_presentarse():
    p = _prompt()
    assert "TU PRESENTACION YA SE DIJO AUTOMATICAMENTE" in p
    assert "NO la escribas tu" in p


if __name__ == "__main__":
    for nombre, fn in sorted(globals().items()):
        if nombre.startswith("test_"):
            fn()
            print("ok", nombre)
    print("OK")
