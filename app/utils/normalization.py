import re


def normalize_phone(phone: str) -> str:
    """Normalize a phone number by removing spaces, dashes, and parentheses."""
    return re.sub(r"[\s\-\(\)]+", "", phone.strip())


def normalize_script_name(name: str | None) -> str:
    """Limpia el script_name recibido del frontend.

    El dropdown de la UI a veces envía 'label — proyecto' en lugar del name
    interno (ej. 'reactivacion_seguimiento — Proyecto de diabetes mellitus
    tipo 2'). Si llega así, el lookup por nombre falla y la llamada sale con
    el script activo equivocado. Nos quedamos con la parte antes del
    separador y sin espacios extremos.
    """
    cleaned = (name or "").strip()
    for sep in (" — ", " – "):
        if sep in cleaned:
            cleaned = cleaned.split(sep, 1)[0].strip()
            break
    return cleaned or "default"


def is_reactivation_script(name: str | None) -> bool:
    """True si el script es de reactivación (ej. 'reactivacion_seguimiento')."""
    return "reactiv" in (name or "").lower()


def truncate_text(text: str, max_length: int = 200) -> str:
    """Truncate text to max_length, adding ellipsis if needed."""
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."
