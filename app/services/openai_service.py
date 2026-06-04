import logging
from typing import AsyncIterator

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


def _system_param(system_prompt: str) -> list[dict]:
    """Construye el parámetro `system` con cache_control para prompt caching.

    El system prompt es estable dentro de una llamada (no cambia entre turnos),
    por lo que es el candidato perfecto para cachear. Requisito mínimo: 2048 tokens
    (Claude Haiku 4.5). Nuestro prompt tiene ~3000 tokens → siempre califica.

    Impacto: turnos 2, 3, 4... procesan los tokens cacheados ~10x más rápido
    y a ~90% del costo. Reduce la latencia percibida en 1-2 segundos por turno.
    """
    return [
        {
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }
    ]


async def generate_response_stream(
    system_prompt: str,
    conversation_history: list[dict],
    user_message: str,
) -> AsyncIterator[str]:
    """Genera la respuesta de Claude en modo streaming, token a token.

    Permite que Twilio ConversationRelay + ElevenLabs empiecen a sintetizar
    voz casi inmediatamente (~200-400 ms desde el primer token), en lugar de
    esperar la respuesta completa (1-3 s adicionales con el modo no-streaming).

    Yields:
        Fragmentos de texto (tokens) a medida que Claude los genera.
    """
    if not settings.anthropic_api_key:
        yield "Lo siento, no tengo configurada la conexion con el modelo en este momento."
        return

    messages = list(conversation_history)
    # Recordatorio anti-markdown en cada turno: Claude Haiku tiende a usar
    # formato visual incluso cuando el system prompt lo prohíbe. Este prefijo
    # fuerza el comportamiento correcto sin modificar el system prompt cacheado.
    _reminder = (
        "[REGLA ABSOLUTA: responde SOLO en texto hablado. "
        "CERO asteriscos, negritas, listas, viñetas ni guiones de lista. "
        "Máximo 2-3 frases. Si tienes más info, pausa y espera.]\n\n"
    )
    messages.append({"role": "user", "content": _reminder + user_message})

    try:
        async with client.messages.stream(
            model=settings.anthropic_model,
            system=_system_param(system_prompt),
            messages=messages,
            max_tokens=280,
            temperature=0.4,
        ) as stream:
            async for text in stream.text_stream:
                yield text
            # Loguear uso al finalizar el stream (incluye cache hits)
            final = await stream.get_final_message()
            cache_read    = getattr(final.usage, "cache_read_input_tokens", 0)
            cache_write   = getattr(final.usage, "cache_creation_input_tokens", 0)
            logger.info(
                "Claude stream (model=%s input=%d output=%d cache_read=%d cache_write=%d)",
                settings.anthropic_model,
                final.usage.input_tokens,
                final.usage.output_tokens,
                cache_read,
                cache_write,
            )
    except Exception as exc:
        logger.error("Claude streaming API error: %s", exc)
        yield "Lo siento, estoy teniendo dificultades tecnicas en este momento."


async def generate_response(
    system_prompt: str,
    conversation_history: list[dict],
    user_message: str,
) -> str:
    """Versión no-streaming de generate_response (mantiene compatibilidad).

    Usa internamente el stream y acumula para devolver el texto completo.
    También aplica prompt caching.
    """
    parts: list[str] = []
    async for token in generate_response_stream(system_prompt, conversation_history, user_message):
        parts.append(token)
    return "".join(parts)
