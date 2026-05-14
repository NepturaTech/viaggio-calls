"""
Servicio para enviar reportes de salud por WhatsApp via Supabase Edge Function.

Endpoint: POST /functions/v1/send-whatsapp-report
Auth:     header x-api-key (WHATSAPP_REPORT_API_KEY)
Body:     { "prediction_id": "<UUID>", "recipient_phone": "573001234567" }
"""

import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


async def send_whatsapp_report(
    prediction_id: str,
    recipient_phone: str,
) -> bool:
    """Envía el reporte de salud por WhatsApp al paciente.

    Args:
        prediction_id: UUID del registro evalml (predicción más reciente del paciente).
        recipient_phone: Número del paciente en formato internacional (ej. +573001234567).

    Returns:
        True si el envío fue exitoso, False en caso contrario.
    """
    settings = get_settings()
    api_key = settings.whatsapp_report_api_key
    url = settings.whatsapp_report_url

    if not api_key:
        logger.warning("WhatsApp report: WHATSAPP_REPORT_API_KEY no configurada — reporte no enviado")
        return False
    if not prediction_id:
        logger.warning("WhatsApp report: prediction_id vacío — no hay datos de evalml para este paciente")
        return False

    # Normalizar teléfono: el endpoint espera dígitos sin el prefijo '+'
    phone = recipient_phone.lstrip("+") if recipient_phone else ""

    payload: dict = {"prediction_id": prediction_id}
    if phone:
        payload["recipient_phone"] = phone

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                url,
                headers={
                    "x-api-key": api_key,
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            logger.info(
                "WhatsApp report enviado: prediction_id=%s phone=%s status=%d",
                prediction_id,
                phone,
                response.status_code,
            )
            return True

    except httpx.HTTPStatusError as exc:
        logger.error(
            "WhatsApp report HTTP error %d: %s",
            exc.response.status_code,
            exc.response.text[:300],
        )
    except Exception as exc:
        logger.error("WhatsApp report error inesperado: %s", exc)

    return False
