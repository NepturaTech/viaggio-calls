"""Paciente sin nombre: "hablo con ?" no puede salir al aire, venga del
codigo ("Hola, hablo con ?") o de la BD ("Hola, ¿hablo con ?")."""
from app.services.prompt_service import _clean_welcome_greeting as clean

ESPERADO = "Hola, te habla Andrea."


def test_greeting():
    for crudo in ("Hola, hablo con ?", "Hola, ¿hablo con ?", "Hola, ¿Hablo con ?"):
        assert clean(crudo) == ESPERADO, (crudo, clean(crudo))
    # con nombre no se toca
    assert clean("Hola, ¿hablo con Maria?") == "Hola, ¿hablo con Maria?"


if __name__ == "__main__":
    test_greeting()
    print("OK")
