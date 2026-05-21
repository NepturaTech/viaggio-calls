"""
Servicio para disparar flujos de ManyChat via API cuando una llamada no es contestada.

Flujo:
  1. Buscar al suscriptor por número de teléfono  →  GET /fb/subscriber/findByPhone
  2. Enviar el flow configurado                    →  POST /fb/sending/sendFlow

Variables de entorno requeridas:
  MANYCHAT_API_KEY            — token de API de ManyChat (sin prefijo "Bearer")
  MANYCHAT_NO_ANSWER_FLOW_NS  — Flow NS del flow a disparar
                                 (se obtiene en ManyChat → Flow → ⋯ → API Trigger → Copy NS)

Referencia: https://api.manychat.com
"""

import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_MANYCHAT_BASE = "https://api.manychat.com"


def _headers() -> dict[str, str]:
    api_key = get_settings().manychat_api_key
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _find_subscriber_by_phone(phone: str) -> str | None:
    """Busca el subscriber_id de ManyChat por número de teléfono WhatsApp.

    ManyChat unifica contactos de WhatsApp y Facebook bajo el mismo endpoint
    /fb/subscriber/findByPhone — el número debe estar en formato E.164 sin '+'.

    Retorna el subscriber_id como string, o None si no se encuentra.
    """
    # ManyChat espera el número sin '+', solo dígitos (ej. 573209085770)
    normalized = phone.lstrip("+").strip()
    if not normalized:
        return None

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(
                f"{_MANYCHAT_BASE}/fb/subscriber/findByPhone",
                headers=_headers(),
                params={"phone": normalized},
            )
            if resp.status_code == 404:
                logger.info("ManyChat: suscriptor no encontrado para phone=%s", normalized)
                return None
            if resp.status_code == 401:
                logger.error(
                    "ManyChat: API key inválida (401) — verifica MANYCHAT_API_KEY en Settings → API"
                )
                return None
            resp.raise_for_status()
            data = resp.json()
            # La respuesta tiene forma: {"status": "success", "data": {"id": 123456, ...}}
            subscriber_id = (data.get("data") or {}).get("id")
            if subscriber_id:
                logger.info(
                    "ManyChat: suscriptor encontrado phone=%s subscriber_id=%s",
                    normalized,
                    subscriber_id,
                )
            else:
                logger.info(
                    "ManyChat: respuesta OK pero sin id para phone=%s — "
                    "verifica que el contacto esté registrado en ManyChat por WhatsApp",
                    normalized,
                )
            return str(subscriber_id) if subscriber_id else None
    except Exception as exc:
        logger.warning("ManyChat findByPhone error (phone=%s): %s", normalized, exc)
        return None


def _send_flow(subscriber_id: str, flow_ns: str) -> bool:
    """Envía el flow indicado al suscriptor.

    Retorna True si el API respondió con éxito (status 200).
    """
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                f"{_MANYCHAT_BASE}/fb/sending/sendFlow",
                headers=_headers(),
                json={"subscriber_id": subscriber_id, "flow_ns": flow_ns},
            )
            resp.raise_for_status()
            logger.info(
                "ManyChat: flow enviado subscriber_id=%s flow_ns=%s",
                subscriber_id,
                flow_ns,
            )
            return True
    except Exception as exc:
        logger.warning(
            "ManyChat sendFlow error (subscriber=%s flow=%s): %s",
            subscriber_id,
            flow_ns,
            exc,
        )
        return False


async def trigger_no_answer_flow(
    phone: str,
    reason: str = "no_answer",
    manychat_user_id: str | None = None,
) -> bool:
    """Disparar el flow de ManyChat configurado para llamadas no contestadas.

    Args:
        phone:            Teléfono del paciente en formato E.164 (ej. +573209085770).
        reason:           Motivo del disparo — solo informativo para el log.
        manychat_user_id: subscriber_id de ManyChat leído directamente del dataset de Viaggio.
                          Si se provee, se usa directamente y se omite el lookup por teléfono.

    Returns:
        True si el flow fue enviado exitosamente, False en cualquier otro caso.
    """
    import asyncio

    settings = get_settings()
    api_key = settings.manychat_api_key
    flow_ns = settings.manychat_no_answer_flow_ns

    if not api_key:
        logger.debug("ManyChat: MANYCHAT_API_KEY no configurada — omitiendo flow (%s)", reason)
        return False

    if not flow_ns:
        logger.debug("ManyChat: MANYCHAT_NO_ANSWER_FLOW_NS no configurada — omitiendo flow (%s)", reason)
        return False

    loop = asyncio.get_event_loop()

    # Ruta rápida: usar el manychat_user_id del dataset directamente
    if manychat_user_id:
        logger.info(
            "ManyChat: usando manychat_user_id=%s del dataset (reason=%s) — omitiendo findByPhone",
            manychat_user_id,
            reason,
        )
        return await loop.run_in_executor(None, _send_flow, manychat_user_id, flow_ns)

    # Fallback: buscar al suscriptor por teléfono
    if not phone:
        logger.warning("ManyChat: ni manychat_user_id ni teléfono disponibles (%s)", reason)
        return False

    subscriber_id = await loop.run_in_executor(None, _find_subscriber_by_phone, phone)
    if not subscriber_id:
        logger.info(
            "ManyChat: no se encontró suscriptor para phone=%s (reason=%s) — flow omitido",
            phone,
            reason,
        )
        return False

    return await loop.run_in_executor(None, _send_flow, subscriber_id, flow_ns)
