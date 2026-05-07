import logging
from anthropic import AsyncAnthropic
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

client = AsyncAnthropic(api_key=settings.anthropic_api_key)

# Respuesta cuando se detecta contenido inapropiado por primera vez
MODERATION_REDIRECT_RESPONSE = (
    "Prefiero que nos mantengamos en el tema del seguimiento. "
    "¿Hay algo relacionado con el proyecto en lo que pueda ayudarte?"
)

# Respuesta de cierre cuando se repite el contenido inapropiado
MODERATION_CLOSE_RESPONSE = (
    "Entiendo, te llamare en otro momento. Que estes muy bien, hasta luego."
)


async def moderate_user_input(text: str) -> tuple[bool, str]:
    """Stub de moderación — siempre retorna sin marcar.

    La moderación via API externa fue desactivada (opción C).
    El manejo de contenido inapropiado queda delegado al system prompt del modelo.
    """
    return False, ""


async def generate_response(
    system_prompt: str,
    conversation_history: list[dict],
    user_message: str,
) -> str:
    """Envía la conversación a Claude Haiku 4.5 y retorna la respuesta del asistente."""
    if not settings.anthropic_api_key:
        logger.warning("Anthropic API key is not configured; using fallback response")
        return "Lo siento, no tengo configurada la conexion con el modelo en este momento."

    # Construir historial sin el mensaje del sistema (va como parámetro separado)
    messages = list(conversation_history)
    messages.append({"role": "user", "content": user_message})

    try:
        response = await client.messages.create(
            model=settings.anthropic_model,
            system=system_prompt,
            messages=messages,
            max_tokens=300,
            temperature=0.7,
        )
        assistant_message = response.content[0].text
        logger.info(
            "Claude response generated (input=%d output=%d tokens)",
            response.usage.input_tokens,
            response.usage.output_tokens,
        )
        return assistant_message
    except Exception as e:
        logger.error("Claude API error: %s", e)
        return "Lo siento, estoy teniendo dificultades tecnicas en este momento."
