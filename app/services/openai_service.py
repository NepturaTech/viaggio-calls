import logging
from openai import AsyncOpenAI
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

client = AsyncOpenAI(api_key=settings.openai_api_key)


async def generate_response(
    system_prompt: str,
    conversation_history: list[dict],
    user_message: str,
) -> str:
    """Send conversation to OpenAI and return the assistant's text response."""
    if not settings.openai_api_key:
        logger.warning("OpenAI API key is not configured; using fallback response")
        return "Lo siento, no tengo configurada la conexión con el modelo en este momento. ¿Deseas que te transfiera con un agente humano?"

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
        return "Lo siento, estoy teniendo dificultades técnicas. ¿Deseas que te transfiera con un agente humano?"
