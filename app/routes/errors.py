from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.services.error_log_service import log_error_event


router = APIRouter(tags=["errors"])


class FrontendErrorReport(BaseModel):
    source: str = "frontend"
    severity: str = "error"
    error_type: str
    message: str
    path: str | None = None
    method: str | None = None
    status_code: int | None = None
    patient_id: str | None = None
    call_sid: str | None = None
    details: Any = None
    context: dict[str, Any] | None = None


@router.post("/report")
async def report_frontend_error(payload: FrontendErrorReport):
    log_error_event(
        source=payload.source,
        severity=payload.severity,
        error_type=payload.error_type,
        message=payload.message,
        path=payload.path,
        method=payload.method,
        status_code=payload.status_code,
        patient_id=payload.patient_id,
        call_sid=payload.call_sid,
        details=payload.details,
        context=payload.context,
    )
    return {"status": "received"}

