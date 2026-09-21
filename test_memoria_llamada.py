"""Nota post-llamada (`call_logs.memoria`): lo determinista, sin red ni modelo.

El prompt del resumidor pide no escribir cedulas ni telefonos, pero un requisito
no se deja en manos de un prompt: `clean_memory` los borra pase lo que pase.
"""
import asyncio

from app.services import call_memory_service as cms
from app.services.prompt_service import build_context_prompt

CLIENTE = {"full_name": "Maria Perez", "document_number": "1101989123",
           "phone_number": "+573001112233", "project_name": "proyecto de diabetes mellitus tipo 2"}
SCRIPT = {"name": "reactivacion_seguimiento", "system_prompt": ""}
NOTA = ("CONTESTO: paciente\nREGISTRO: no registra, dice que ya se comio el plato\n"
        "SITUACION_PERSONAL: vive sola desde que los hijos se fueron, se siente abandonada")


def test_sin_contenido_no_se_guarda():
    assert cms.clean_memory("SIN_CONTENIDO") is None
    assert cms.clean_memory("  ") is None
    assert cms.clean_memory(None) is None


def test_borra_cedula_y_telefono_aunque_el_modelo_los_escriba():
    nota = cms.clean_memory("CONTESTO: paciente\nPREFERENCIAS: llamar al 320 908 5770, cedula 1.101.989.123")
    assert "5770" not in nota and "989" not in nota
    assert nota.count("[numero]") == 2
    # los numeros cortos (hora, dias) son contenido util y se quedan
    assert "a las 10" in cms.clean_memory("PREFERENCIAS: llamar a las 10 de la mañana")


def test_tope_de_largo_corta_por_lineas_enteras():
    assert len(cms.clean_memory("REGISTRO: " + "x" * 5000)) == cms.MEMORY_MAX_CHARS
    # una etiqueta a medias ("EVITAR: n") le llegaria a Andrea como dato
    nota = cms.clean_memory("\n".join(f"LINEA{i}: " + "y" * 100 for i in range(12)))
    assert len(nota) <= cms.MEMORY_MAX_CHARS
    assert all(len(l) > 100 for l in nota.splitlines())


def test_lineas_sin_dato_se_descartan():
    nota = cms.clean_memory("CONTESTO: paciente\nSALUD: sin información\nPREFERENCIAS: Ninguna.\n"
                            "SITUACION_PERSONAL:\nEVITAR: ninguna mencionada\n"
                            "SALUD: Sin información relevante reportada en esta llamada.\n"
                            "COMPROMISO: ninguno explícito del paciente\n"
                            "BARRERAS: sin información de barreras identificadas\n"
                            "BARRERAS: sin información de cómo usar WhatsApp, nadie le explicó")
    assert nota == "CONTESTO: paciente\nBARRERAS: sin información de cómo usar WhatsApp, nadie le explicó"


def test_tercero_se_conserva_tal_cual():
    assert cms.clean_memory("CONTESTO: tercero\n") == "CONTESTO: tercero"


def test_menos_de_dos_turnos_del_paciente_no_llama_al_modelo():
    corta = [{"role": "assistant", "content": "Hola, ¿hablo con Maria?"},
             {"role": "user", "content": "Aló?"}]
    assert not cms.has_enough_content(corta)
    # si llegara al modelo fallaria por red/clave: None prueba que ni lo intento
    assert asyncio.run(cms.summarize_call(corta, "x")) is None


def test_transcript_ida_y_vuelta():
    history = [{"role": "assistant", "content": "Hola"}, {"role": "user", "content": "si,\ncon ella"}]
    texto = cms.format_transcript(history)
    assert texto == "[assistant] Hola\n[user] si, con ella"
    assert cms.parse_transcript(texto) == [{"role": "assistant", "content": "Hola"},
                                           {"role": "user", "content": "si, con ella"}]


def test_el_prompt_usa_la_memoria_y_cae_al_cierre_si_no_hay():
    llamadas = [
        {"created_at": "2026-09-19T14:05:00+00:00", "script_name": "reactivacion_seguimiento",
         "transcript_summary": "user: chao | assistant: hasta luego", "memoria": NOTA},
        {"created_at": "2026-08-12T16:40:00+00:00", "script_name": "proxima_visita",
         "transcript_summary": "assistant: Te confirmo la visita para el jueves.", "memoria": None},
    ]
    p = build_context_prompt(CLIENTE, [], script=SCRIPT, dataset_context={"previous_calls": llamadas})
    bloque = p.split("## Llamadas anteriores a este paciente\n")[1]
    primera, segunda = bloque.splitlines()[:2]
    assert "se siente abandonada" in primera and "hasta luego" not in primera
    assert "Te confirmo la visita para el jueves" in segunda
    assert "DESPUES de confirmar" in bloque


if __name__ == "__main__":
    for nombre, fn in sorted(globals().items()):
        if nombre.startswith("test_"):
            fn()
            print("ok", nombre)
    print("OK")
