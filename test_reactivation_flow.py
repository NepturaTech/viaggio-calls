"""Self-check de la lógica de detección de llamadas de reactivación.

Corre con:  python test_reactivation_flow.py
"""
from app.utils.normalization import is_reactivation_script


def test_is_reactivation_script():
    assert is_reactivation_script("reactivacion_seguimiento") is True
    assert is_reactivation_script("Reactivación — Proyecto DM2") is True
    assert is_reactivation_script("default") is False
    assert is_reactivation_script("seguimiento") is False
    assert is_reactivation_script(None) is False
    assert is_reactivation_script("") is False


if __name__ == "__main__":
    test_is_reactivation_script()
    print("OK")
