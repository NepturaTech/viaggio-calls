"""
Servicio para enviar reportes de salud por WhatsApp via Supabase Edge Function.

Endpoint: POST /functions/v1/send-report-by-document
Auth:     header x-api-key (WHATSAPP_REPORT_API_KEY)
Body:     { "identificacion": "1234567890", "recipient_phone": "573001234567" }

Respuesta 200: { "ok": true, "patient": "...", "prediction": {...}, ... }
Errores:
  401 → API key inválida
  400 → falta identificacion
  404 → paciente o predicción no encontrada en GlucoWise
  422 → ManyChat no pudo emparejar el subscriber
"""

import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


async def send_whatsapp_report(
    document_number: str,
    recipient_phone: str = "",
) -> bool:
    """Envía el reporte de salud por WhatsApp buscando al paciente por documento.

    Args:
        document_number: Número de documento / identificación del paciente.
        recipient_phone: Teléfono del paciente en formato internacional (ej. +573001234567).
                         Opcional — el endpoint lo toma del perfil si se omite.

    Returns:
        True si el envío fue exitoso (200), False en cualquier otro caso.
    """
    settings = get_settings()
    api_key = settings.whatsapp_report_api_key
    url = settings.whatsapp_report_url

    if not api_key:
        logger.warning("WhatsApp report: WHATSAPP_REPORT_API_KEY no configurada — reporte no enviado")
        return False

    if not document_number:
        logger.warning("WhatsApp report: document_number vacío — no se puede buscar al paciente")
        return False

    payload: dict = {"identificacion": document_number}

    # Teléfono opcional: normalizar quitando el prefijo '+'
    phone = recipient_phone.lstrip("+") if recipient_phone else ""
    if phone:
        payload["recipient_phone"] = phone

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            response = await client.post(
                url,
                headers={
                    "x-api-key": api_key,
                    "Content-Type": "application/json",
                },
                json=payload,
            )

            if response.status_code == 404:
                logger.info(
                    "WhatsApp report: paciente o predicción no encontrada (doc=%s) — el bot debe indicar que no hay datos",
                    document_number,
                )
                return False

            response.raise_for_status()
            data = response.json()
            logger.info(
                "WhatsApp report enviado: doc=%s phone=%s patient=%s prediction_id=%s",
                document_number,
                phone or "del perfil",
                data.get("patient", "—"),
                (data.get("prediction") or {}).get("id", "—"),
            )
            return True

    except httpx.HTTPStatusError as exc:
        logger.error(
            "WhatsApp report HTTP error %d para doc=%s: %s",
            exc.response.status_code,
            document_number,
            exc.response.text[:300],
        )
    except Exception as exc:
        logger.error("WhatsApp report error inesperado (doc=%s): %s", document_number, exc)

    return False
