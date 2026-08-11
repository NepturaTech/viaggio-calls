"""Check mínimo de la validación en vivo de comida (regex + helper sin doc)."""
from app.routes.ws_conversationrelay import FOOD_SENT_CLAIM_PATTERN
from app.services.supabase_rest_service import get_recent_food_entries

MATCH = [
    "Sí ya lo envié.",
    "ya la mandé",
    "Ya agregué la comida",
    "acabo de subir la foto",
    "ya lo hice",
    "ya quedó",
    "listo, ya está registrado",
    "ya registré el almuerzo",
]
NO_MATCH = [
    "no he tenido tiempo",
    "¿cómo la envío?",
    "todavía no",
    "muy bien gracias",
    "voy a enviarla ahora",
]

for t in MATCH:
    assert FOOD_SENT_CLAIM_PATTERN.search(t), f"debía matchear: {t!r}"
for t in NO_MATCH:
    assert not FOOD_SENT_CLAIM_PATTERN.search(t), f"NO debía matchear: {t!r}"

# Sin documento → lista vacía sin tocar la red
assert get_recent_food_entries("") == []
assert get_recent_food_entries(None) == []

print("OK — regex y helper pasan")
