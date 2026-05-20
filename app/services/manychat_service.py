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
    """Busca el subscriber_id de ManyChat para un número de teléfono (formato E.164 sin +).

    Retorna el subscriber_id como string, o None si no se encuentra.
    """
    # ManyChat espera el número sin el símbolo '+', solo dígitos
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
            resp.raise_for_status()
            data = resp.json()
            subscriber_id = (data.get("data") or {}).get("id")
            if subscriber_id:
                logger.info(
                    "ManyChat: suscriptor encontrado phone=%s id=%s",
                    normalized,
                    subscriber_id,
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


async def trigger_no_answer_flow(phone: str, reason: str = "no_answer") -> bool:
    """Disparar el flow de ManyChat configurado para llamadas no contestadas.

    Args:
        phone:  Teléfono del paciente en formato E.164 (ej. +573209085770 o 573209085770).
        reason: Motivo del disparo — solo informativo para el log ('no_answer', 'voicemail').

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

    if not phone:
        logger.warning("ManyChat: teléfono vacío — no se puede buscar al suscriptor (%s)", reason)
        return False

    # Ejecutar las llamadas síncronas de httpx en el thread pool para no bloquear el event loop
    loop = asyncio.get_event_loop()

    subscriber_id = await loop.run_in_executor(None, _find_subscriber_by_phone, phone)
    if not subscriber_id:
        logger.info(
            "ManyChat: no se encontró suscriptor para phone=%s (reason=%s) — flow omitido",
            phone,
            reason,
        )
        return False

    return await loop.run_in_executor(None, _send_flow, subscriber_id, flow_ns)
