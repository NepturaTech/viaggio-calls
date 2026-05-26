import json
import logging
import re
from datetime import datetime

import httpx

from app.config import get_settings
from app.db.repositories import CallRepository, CallEventRepository

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Supabase helpers
# ---------------------------------------------------------------------------

def _log_headers() -> dict[str, str]:
    settings = get_settings()
    key = (
        settings.lovable_cloud_service_role_key
        or settings.supabase_service_role_key
        or settings.lovable_cloud_anon_key
    )
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        # ignore-duplicates: si el call_sid ya existe (ej. llamado dos veces
        # desde /outbound y /voice), no falla con 409 — simplemente no hace nada.
        "Prefer": "return=minimal,resolution=ignore-duplicates",
    }


def _log_endpoint() -> str | None:
    settings = get_settings()
    base = (settings.lovable_cloud_url or "").rstrip("/")
    table = (settings.lovable_call_logs_table or "").strip()
    if not base or not table:
        return None
    return f"{base}/rest/v1/{table}"


def _extract_missing_column(text: str) -> str | None:
    m = re.search(r"Could not find the '([^']+)' column", text or "")
    return m.group(1) if m else None


def _post_log_row(row: dict, dropped: list[str] | None = None) -> bool:
    """POST a call_log row to Supabase, retrying if a column is missing."""
    endpoint = _log_endpoint()
    if not endpoint:
        return False
    dropped = dropped or []
    row_to_send = {k: v for k, v in row.items() if k not in dropped}
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                endpoint,
                headers=_log_headers(),
                content=json.dumps([row_to_send], ensure_ascii=False),
            )
            # 409 Conflict = call_sid ya existe (insertado por /outbound o /voice antes).
            # No es un error — el registro ya está, lo actualizaremos con PATCH luego.
            if resp.status_code == 409:
                return True
            if resp.status_code == 400:
                missing = _extract_missing_column(resp.text)
                if missing and missing not in dropped:
                    logger.info("call_logs: column '%s' not in table, retrying without it", missing)
                    return _post_log_row(row, dropped + [missing])
            resp.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("Failed to persist call log to Supabase: %s", exc)
        return False


def _patch_log_row(call_sid: str, updates: dict, dropped: list[str] | None = None) -> bool:
    """PATCH an existing call_log row by call_sid, retrying if a column is missing."""
    endpoint = _log_endpoint()
    if not endpoint:
        return False
    dropped = dropped or []
    updates_to_send = {k: v for k, v in updates.items() if k not in dropped}
    if not updates_to_send:
        return True
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.patch(
                endpoint,
                headers=_log_headers(),
                params={"call_sid": f"eq.{call_sid}"},
                content=json.dumps(updates_to_send, ensure_ascii=False),
            )
            if resp.status_code == 400:
                missing = _extract_missing_column(resp.text)
                if missing and missing not in dropped:
                    logger.info("call_logs PATCH: column '%s' not in table, retrying without it", missing)
                    return _patch_log_row(call_sid, updates, dropped + [missing])
                logger.warning("call_logs PATCH 400 (sid=%s): %s", call_sid, resp.text[:300])
            resp.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("Failed to update call log in Supabase (sid=%s): %s", call_sid, exc)
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_call_record(
    twilio_call_sid: str,
    direction: str,
    customer_id: int | None = None,
    call_source: str | None = None,
) -> dict:
    """Create a new call record in-memory and persist a row to Supabase call_logs.

    Args:
        call_source: Origen de la llamada — quién la generó.
                     Ejemplos: 'lovable', 'whatsapp', 'manychat', 'api', 'inbound'.
    """
    repo = CallRepository()
    data: dict = {"twilio_call_sid": twilio_call_sid, "direction": direction}
    if customer_id:
        data["customer_id"] = customer_id
    record = repo.create(**data)

    # Persist to Supabase (best-effort — never raises)
    row: dict = {
        "call_sid": twilio_call_sid,
        "direction": direction,
        "status": "initiated",
        "started_at": datetime.utcnow().isoformat(),
    }
    if call_source:
        row["call_source"] = call_source
    _post_log_row(row)

    logger.info(
        "Call record created: sid=%s direction=%s source=%s",
        twilio_call_sid,
        direction,
        call_source or "unknown",
    )
    return record


def update_call_log_context(
    call_sid: str,
    patient_document_number: str | None = None,
    patient_name: str | None = None,
    script_name: str | None = None,
) -> None:
    """Enrich the Supabase call_log row with patient/script context.

    Called from the WebSocket setup event once patient lookup is complete.
    """
    updates: dict = {}
    if patient_document_number:
        updates["patient_document_number"] = patient_document_number
    if patient_name:
        updates["patient_name"] = patient_name
    if script_name:
        updates["script_name"] = script_name
    if not updates:
        return
    _patch_log_row(call_sid, updates)


def log_call_event(call_id: int, event_type: str, payload: dict | None = None) -> dict:
    """Log an event for a call (in-memory)."""
    repo = CallEventRepository()
    event = repo.create(call_id=call_id, event_type=event_type, payload=payload)
    logger.debug("Call event logged: call_id=%d, type=%s", call_id, event_type)
    return event


def append_transcript_line(call_id: int, role: str, text: str) -> dict | None:
    """Append one transcript line to a call record (in-memory)."""
    repo = CallRepository()
    call = repo.append_transcript_line(call_id, role, text)
    if call:
        logger.debug("Transcript line appended: call_id=%d, role=%s", call_id, role)
    return call


def list_calls() -> list[dict]:
    """List in-memory call records."""
    return CallRepository().list_all()


def get_call_with_events(call_sid: str) -> dict | None:
    """Get one call plus its related events."""
    call_repo = CallRepository()
    event_repo = CallEventRepository()
    call = call_repo.find_by_sid(call_sid)
    if not call:
        return None
    return {**call, "events": event_repo.list_by_call_id(call["id"])}


def finalize_call(
    call_id: int,
    final_status: str,
    summary: str | None = None,
    action: str | None = None,
) -> dict | None:
    """Mark a call as finished in-memory and update the Supabase call_log row."""
    repo = CallRepository()
    call = repo.update_end(call_id, final_status, summary, action)
    if call:
        logger.info("Call finalized: id=%d, status=%s", call_id, final_status)
        call_sid = call.get("twilio_call_sid")
        if call_sid:
            updates: dict = {
                "status": final_status,
                "ended_at": call.get("ended_at") or datetime.utcnow().isoformat(),
            }
            if summary:
                updates["transcript_summary"] = summary[:2000]
            _patch_log_row(call_sid, updates)
    return call
