import logging
from openai import AsyncOpenAI
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

client = AsyncOpenAI(api_key=settings.openai_api_key)

# Respuesta cuando se detecta contenido inapropiado por primera vez
MODERATION_REDIRECT_RESPONSE = (
    "Prefiero que nos mantengamos en el tema del seguimiento. "
    "¿Hay algo relacionado con el proyecto en lo que pueda ayudarte?"
)

# Respuesta de cierre cuando se repite el contenido inapropiado
MODERATION_CLOSE_RESPONSE = (
    "Entiendo, te llamare en otro momento. Que estes muy bien, hasta luego."
)

# Categorías de la API de moderación que disparan la protección
_FLAGGED_CATEGORIES = {
    "sexual",
    "sexual/minors",
    "harassment",
    "harassment/threatening",
    "hate",
    "hate/threatening",
    "violence",
    "violence/graphic",
    "self-harm",
    "self-harm/intent",
    "self-harm/instructions",
}


async def moderate_user_input(text: str) -> tuple[bool, str]:
    """Check user input against OpenAI Moderation API.

    Returns (is_flagged, detected_category).
    The moderation endpoint is free and does not count toward token usage.
    """
    if not settings.openai_api_key or not text.strip():
        return False, ""
    try:
        result = await client.moderations.create(input=text)
        output = result.results[0]
        if output.flagged:
            # Find the highest-scored flagged category for logging
            scores = output.category_scores.model_dump()
            top_category = max(
                (cat for cat in _FLAGGED_CATEGORIES if scores.get(cat, 0) > 0),
                key=lambda cat: scores.get(cat, 0),
                default="unknown",
            )
            logger.warning(
                "Moderation flagged user input. category=%s score=%.3f text_preview=%s",
                top_category,
                scores.get(top_category, 0),
                text[:80],
            )
            return True, top_category
        return False, ""
    except Exception as exc:
        # Si la moderación falla, no bloqueamos la llamada — solo logueamos
        logger.warning("Moderation API error (non-blocking): %s", exc)
        return False, ""


async def generate_response(
    system_prompt: str,
    conversation_history: list[dict],
    user_message: str,
) -> str:
    """Send conversation to OpenAI and return the assistant's text response."""
    if not settings.openai_api_key:
        logger.warning("OpenAI API key is not configured; using fallback response")
        return "Lo siento, no tengo configurada la conexion con el modelo en este momento."

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(conversation_history)
    messages.append({"role": "user", "content": user_message})

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=messages,
            max_tokens=300,
            temperature=0.7,
        )
        assistant_message = response.choices[0].message.content
        logger.info("OpenAI response generated (%d tokens)", response.usage.total_tokens)
        return assistant_message
    except Exception as e:
        logger.error("OpenAI API error: %s", e)
        return "Lo siento, estoy teniendo dificultades tecnicas en este momento."
