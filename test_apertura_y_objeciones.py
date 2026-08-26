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
    PRE_CONFIRM_LABEL,
    build_call_intro,
)

SCRIPT_PV = {"name": "proxima_visita", "project_name": "Proyecto de diabetes mellitus tipo 2"}

# El script real de produccion: system_prompt vacio en BD, pero carga esta guia.
SCRIPT_REACTIVACION_REAL = {
    "name": "reactivacion_seguimiento",
    "system_prompt": "",
    "knowledge_base_file": "app/users/DELFOS_Prompt_Bot_Reactivacion.md",
}


def _assert_no_ordena_presentarse(p):
    """Ningun bloque del prompt puede pedir una presentacion: la dice el codigo."""
    for orden in ("preséntate EXACTAMENTE así", "presentate EXACTAMENTE asi",
                  "Preséntate en tu PRIMER turno", "Presentate en tu PRIMER turno",
                  "Te presentas SIEMPRE"):
        assert orden not in p, orden

    # La unica presentacion que el prompt puede pedir hablada es la etiqueta neutra
    # (respuesta a "¿de parte de quien?" antes de confirmar). Cualquier otra linea
    # con "Te habla Andrea" tiene que ser una PROHIBICION, no una instruccion.
    prohibicion = ("YA SE DIJO", "NO te presentes", "NO la escribas")
    for linea in p.splitlines():
        if "Te habla Andrea" not in linea:
            continue
        if PRE_CONFIRM_LABEL in linea:
            assert "diabetes mellitus" not in linea, linea
            assert "Hospital" not in linea, linea
            continue
        assert any(marca in linea for marca in prohibicion), linea


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


def test_ningun_bloque_ordena_presentarse():
    """La presentacion la dice el codigo (build_call_intro), no el modelo.

    El 08-24, con el fix del 08-21 ya desplegado, 3 de 12 llamadas seguian oyendo
    la etiqueta neutra e inmediatamente el nombre clinico + el hospital en el mismo
    turno, sin identidad confirmada. La causa no era el modelo: el bloque
    "Institucion de esta llamada" seguia ORDENANDO "presentate EXACTAMENTE asi:
    'Te habla Andrea, del {proyecto}, junto con el {hospital}'" — mas concreto y
    mas arriba en el prompt que la prohibicion de abajo. Este test falla si algun
    bloque vuelve a pedir una presentacion.
    """
    _assert_no_ordena_presentarse(_prompt())


def test_la_guia_del_proyecto_tampoco_ordena_presentarse():
    """La guia cargada por knowledge_base_file entra en el prompt y es una 4a fuente.

    El bloque "0. DATOS INSTITUCIONALES" de DELFOS_Prompt_Bot_Reactivacion.md decia
    "Te presentas SIEMPRE con estos datos" y daba la frase con el hospital — y ese
    archivo se carga en el 100% de las llamadas de reactivacion, que es el unico
    script que se ha usado en produccion.
    """
    _assert_no_ordena_presentarse(_prompt(script=SCRIPT_REACTIVACION_REAL))



def test_no_promete_enviar_sms_ni_el_numero():
    """No existe canal de SMS en el codigo; Andrea lo prometio igual.

    26-ago, llamada CA29b057 a Fabian Huertas: perdio el chat de Viaggio y Andrea
    respondio "te envio el numero por mensaje de texto en este momento". grep de
    messages.create/send_sms en app/ da 0 resultados: el paciente colgo esperando
    un mensaje que nunca iba a llegar, y sin ese numero no podia registrar nada.
    Lo que si ocurre de verdad es el flow de ManyChat al colgar.
    """
    from app.routes.ws_conversationrelay import LOST_CONTACT_PATTERN

    dichos_reales = [
        "Perdi el contacto de via, Yo no lo tengo en mi WhatsApp borrar las conversaciones.",
        "confirmamelo porque borre todos los de las conversaciones del WhatsApp",
        "no me llego el mensaje de Viaggio",
        "cual es el numero de Viaggio",
        "dame el numero",
    ]
    for frase in dichos_reales:
        assert LOST_CONTACT_PATTERN.search(frase), frase

    no_deben_disparar = [
        "Si, hablas con el.",
        "lo envio mas tarde.",
        "ya lo mande por whatsapp",
        "No he tenido tiempo",
    ]
    for frase in no_deben_disparar:
        assert not LOST_CONTACT_PATTERN.search(frase), frase

    prompt = _prompt().lower()
    assert "nunca ofrezcas enviar un sms" in prompt


if __name__ == "__main__":
    for nombre, fn in sorted(globals().items()):
        if nombre.startswith("test_"):
            fn()
            print("ok", nombre)
    print("OK")
