import json
import logging
from datetime import datetime
from typing import Any

import httpx

from app.config import get_settings


logger = logging.getLogger(__name__)


def _settings():
    return get_settings()


def _error_log_config() -> dict[str, str]:
    settings = _settings()
    return {
        "url": (settings.lovable_cloud_url or "").rstrip("/"),
        "table": (settings.lovable_error_logs_table or "").strip(),
        "key": settings.lovable_cloud_service_role_key or settings.lovable_cloud_anon_key,
    }


def _headers() -> dict[str, str]:
    config = _error_log_config()
    key = config["key"]
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }


def _serialize(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool, list, dict)):
        return value
    return str(value)


def log_error_event(
    *,
    source: str,
    severity: str,
    error_type: str,
    message: str,
    path: str | None = None,
    method: str | None = None,
    status_code: int | None = None,
    patient_id: str | None = None,
    call_sid: str | None = None,
    details: Any = None,
    context: dict[str, Any] | None = None,
) -> None:
    config = _error_log_config()
    if not (config["url"] and config["table"] and config["key"]):
        return

    payload = {
        "source": source,
        "severity": severity,
        "error_type": error_type,
        "message": message[:1000],
        "path": path,
        "method": method,
        "status_code": status_code,
        "patient_id": patient_id,
        "call_sid": call_sid,
        "details": _serialize(details),
        "context": _serialize(context or {}),
        "created_at": datetime.utcnow().isoformat(),
    }

    endpoint = f"{config['url']}/rest/v1/{config['table']}"
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                endpoint,
                headers=_headers(),
                content=json.dumps(payload, ensure_ascii=False),
            )
            response.raise_for_status()
    except Exception as exc:
        logger.warning("Failed to persist error log to %s: %s", config["table"], exc)

