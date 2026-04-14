import logging

from app.db.repositories import CallRepository, CallEventRepository

logger = logging.getLogger(__name__)


def create_call_record(twilio_call_sid: str, direction: str, customer_id: int | None = None) -> dict:
    """Create a new call record (in-memory)."""
    repo = CallRepository()
    data = {"twilio_call_sid": twilio_call_sid, "direction": direction}
    if customer_id:
        data["customer_id"] = customer_id
    return repo.create(**data)


def log_call_event(call_id: int, event_type: str, payload: dict | None = None) -> dict:
    """Log an event for a call (in-memory)."""
    repo = CallEventRepository()
    event = repo.create(call_id=call_id, event_type=event_type, payload=payload)
    logger.debug("Call event logged: call_id=%d, type=%s", call_id, event_type)
    return event


def append_transcript_line(call_id: int, role: str, text: str) -> dict | None:
    """Append one transcript line to a call record."""
    repo = CallRepository()
    call = repo.append_transcript_line(call_id, role, text)
    if call:
        logger.debug("Transcript line appended: call_id=%d, role=%s", call_id, role)
    return call


def list_calls() -> list[dict]:
    """List in-memory call records."""
    repo = CallRepository()
    return repo.list_all()


def get_call_with_events(call_sid: str) -> dict | None:
    """Get one call plus its related events."""
    call_repo = CallRepository()
    event_repo = CallEventRepository()
    call = call_repo.find_by_sid(call_sid)
    if not call:
        return None

    return {
        **call,
        "events": event_repo.list_by_call_id(call["id"]),
    }


def finalize_call(call_id: int, final_status: str, summary: str = None, action: str = None):
    """Mark a call as finished."""
    repo = CallRepository()
    call = repo.update_end(call_id, final_status, summary, action)
    if call:
        logger.info("Call finalized: id=%d, status=%s", call_id, final_status)
    return call
