"""Cuando el paciente se abre, Andrea se queda en el tema.

Medido sobre 163 transcripts (21-sep): ante un duelo, falta de plata o una ida a
urgencias, Andrea decia "Entiendo... Pero mira... ¿me mandas la foto?" (9 llamadas,
12 veces) o "eso esta fuera de lo que puedo ayudarte aqui". No era el modelo: el
prompt base ordenaba redirigir y la guia de reactivacion declaraba la foto como
"objetivo unico". Las frases de FRASES_REALES salen de esas llamadas.
"""
from pathlib import Path

from app.services import prompt_service as ps

CLIENTE = {"full_name": "Maria Perez", "document_number": "1101989123",
           "phone_number": "+573001112233", "project_name": "proyecto de diabetes mellitus tipo 2"}
SCRIPT = {"name": "reactivacion_seguimiento", "system_prompt": ""}
GUIA = Path("app/users/DELFOS_Prompt_Bot_Reactivacion.md")

FRASES_REALES = [
    "Mira la verdad es que mi padre se murió y estoy en esa de las citas con colpensiones de estar pendiente de mi mamá",
    "me he sentido un poco triste porque no puedo dormir bien.",
    "yo le digo, no tengo ni plata ni para ir a comprar ni los huevitos",
    "me tenía que tomar unos líquidos, pero como no tengo plata para comprarlos, entonces me toca que aguantar",
    "a los 8 días me tocó ingresar por urgencias al hospital, porque es que la cita está muy demoradas",
    "estoy pasando por un momento muy crítico, soy independiente y no he podido trabajar",
    "desde que mis hijos se fueron yo vivo sola y me siento abandonada",
]
NO_SON_APERTURA = [
    "no he tenido tiempo de registrar las comidas",
    "ya me la comí, no le tomé foto",
    "sí, ya lo envié",
    "no tengo el número de Viaggio",
    "me estresaba mucho esa pregunta de qué cantidad comía",
    "aló? sí, con ella",
]
CRISIS = [
    "a veces pienso que ya no quiero vivir",
    "yo mejor me muero y no le estorbo a nadie",
    "he pensado en quitarme la vida",
]


def test_detecta_las_aperturas_reales():
    for frase in FRASES_REALES:
        assert ps.DISCLOSURE_PATTERN.search(frase), frase


def test_no_confunde_las_objeciones_de_siempre_con_una_apertura():
    for frase in NO_SON_APERTURA:
        assert not ps.DISCLOSURE_PATTERN.search(frase), frase
        assert not ps.CRISIS_PATTERN.search(frase), frase


def test_tras_abrirse_hay_dos_turnos_mas_sin_pedir_foto():
    nota, quedan = ps.emotional_note(FRASES_REALES[0], 0)
    assert "se acaba de abrir" in nota and quedan == ps.DISCLOSURE_QUIET_TURNS == 2
    nota, quedan = ps.emotional_note("pues sí, ha sido duro", quedan)
    assert "NO pidas la foto" in nota and quedan == 1
    nota, quedan = ps.emotional_note("ahí vamos", quedan)
    assert "NO pidas la foto" in nota and quedan == 0
    assert ps.emotional_note("bueno, y lo de la foto cómo es", quedan) == ("", 0)


def test_crisis_tiene_guia_fija_y_gana_sobre_la_apertura():
    for frase in CRISIS:
        nota, quedan = ps.emotional_note(frase, 0)
        assert "RIESGO" in nota and "123" in nota, frase
        assert quedan > ps.DISCLOSURE_QUIET_TURNS
    # no se promete lo que no existe
    assert "te van a contactar" not in ps.CRISIS_NOTE and "te contacten" not in ps.CRISIS_NOTE
    assert ps.is_crisis(CRISIS[0]) and not ps.is_crisis(FRASES_REALES[0])


def test_el_prompt_trae_el_bloque_y_ya_no_ordena_cambiar_de_tema():
    p = ps.build_context_prompt(CLIENTE, [], script=SCRIPT, dataset_context={})
    assert "## Cuando el paciente se abre" in p
    # la regla vieja mandaba a redirigir TODO lo que no fuera seguimiento, con esta frase
    assert "eso esta fuera de lo que puedo ayudarte aqui" not in p
    # el bloque la nombra solo para prohibirla
    assert "PROHIBIDO decir 'eso esta fuera de lo que puedo ayudarte'" in p


def test_la_guia_de_reactivacion_ya_no_declara_la_foto_como_objetivo_unico():
    guia = GUIA.read_text(encoding="utf-8")
    assert "Objetivo único" not in guia
    assert "Cuando el paciente se abre" in guia
    # contradecia a '## Nunca confirmes un registro que no te conste'
    assert "Con eso ya retomaste" not in guia


if __name__ == "__main__":
    for nombre, fn in sorted(globals().items()):
        if nombre.startswith("test_"):
            fn()
            print("ok", nombre)
    print("OK")
