import asyncio

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field
from twilio.base.exceptions import TwilioRestException

from app.services.call_log_service import create_call_record
from app.services.customer_service import get_customer_context
from app.services.supabase_rest_service import (
    find_backend_patient_by_phone,
    get_backend_contract,
    list_backend_patients,
)
from app.services.twilio_service import make_outbound_call

router = APIRouter(tags=["patients"])


class BatchCallFilters(BaseModel):
    q: str | None = None
    municipio: str | None = None
    hospital_name: str | None = None
    patient_name: str | None = None
    phone_number: str | None = None
    source: str | None = None


class BatchCallRequest(BaseModel):
    limit: int = Field(default=5, ge=1, le=100)
    script_name: str = "default"
    delay_between_calls_ms: int = Field(default=0, ge=0, le=60000)
    max_concurrent_calls: int = Field(default=1, ge=1, le=1)
    filters: BatchCallFilters = Field(default_factory=BatchCallFilters)


def _safe_local_customer_id(customer: dict | None) -> int | None:
    if not customer:
        return None
    raw_id = customer.get("id")
    if raw_id is None:
        return None
    try:
        numeric_id = int(raw_id)
    except (TypeError, ValueError):
        return None
    return numeric_id if numeric_id < 10000 else None


def _contains(value: str | None, needle: str | None) -> bool:
    if not needle:
        return True
    return needle.strip().lower() in (value or "").strip().lower()


def _match_patients(
    q: str | None = None,
    *,
    municipio: str | None = None,
    hospital_name: str | None = None,
    patient_name: str | None = None,
    phone_number: str | None = None,
    source: str | None = None,
) -> list[dict]:
    patients = list_backend_patients()
    if q:
        needle = q.strip().lower()
        patients = [
            patient
            for patient in patients
            if needle in patient["full_name"].lower() or needle in patient["phone_number"]
        ]
    return [
        patient
        for patient in patients
        if _contains(patient.get("municipality") or patient.get("municipio"), municipio)
        and _contains(patient.get("hospital_name") or patient.get("hospital"), hospital_name)
        and _contains(patient.get("full_name"), patient_name)
        and _contains(patient.get("phone_number"), phone_number)
        and _contains(patient.get("source"), source)
    ]


@router.get("/")
async def get_patients(
    q: str | None = Query(default=None, description="Texto para filtrar por nombre o telefono"),
):
    """List patients from the active backend source."""
    return _match_patients(q)


@router.get("/_meta/source")
async def get_patient_source_meta():
    """Expose active patient data source metadata for frontend setup."""
    return get_backend_contract()["sources"]


@router.get("/{phone_number}")
async def get_patient(phone_number: str):
    """Get one patient by phone number from the active backend source."""
    patient = find_backend_patient_by_phone(phone_number)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    return patient


@router.post("/{phone_number}/call")
async def call_patient(phone_number: str):
    """Trigger an outbound call to a patient found in the active backend source."""
    patient = find_backend_patient_by_phone(phone_number)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    try:
        call_sid = await make_outbound_call(patient["phone_number"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TwilioRestException as exc:
        raise HTTPException(status_code=502, detail=f"Twilio rechazo la llamada: {exc.msg}") from exc

    customer, _ = get_customer_context(patient["phone_number"])
    create_call_record(
        twilio_call_sid=call_sid,
        direction="outbound",
        customer_id=_safe_local_customer_id(customer),
    )

    return {
        "call_sid": call_sid,
        "to": patient["phone_number"],
        "patient_name": patient["full_name"],
        "status": "initiated",
    }


@router.post("/call-batch")
async def call_patients_batch(
    limit: int = Query(default=5, ge=1, le=100, description="Numero maximo de pacientes a llamar"),
    q: str | None = Query(default=None, description="Filtro opcional por nombre o telefono"),
    payload: BatchCallRequest | None = Body(default=None),
):
    """Trigger outbound calls for a filtered batch of patients."""
    filters = payload.filters if payload else BatchCallFilters(q=q)
    effective_limit = payload.limit if payload else limit
    effective_script_name = (payload.script_name if payload else "default") or "default"
    delay_between_calls_ms = payload.delay_between_calls_ms if payload else 0

    patients = _match_patients(
        filters.q if payload else q,
        municipio=filters.municipio,
        hospital_name=filters.hospital_name,
        patient_name=filters.patient_name,
        phone_number=filters.phone_number,
        source=filters.source,
    )[:effective_limit]
    if not patients:
        raise HTTPException(status_code=404, detail="No patients found for batch call")

    results: list[dict] = []
    for index, patient in enumerate(patients):
        try:
            call_sid = await make_outbound_call(patient["phone_number"], effective_script_name)
            customer, _ = get_customer_context(patient["phone_number"])
            create_call_record(
                twilio_call_sid=call_sid,
                direction="outbound",
                customer_id=_safe_local_customer_id(customer),
            )
            results.append({
                "phone_number": patient["phone_number"],
                "patient_name": patient["full_name"],
                "status": "initiated",
                "call_sid": call_sid,
                "script_name": effective_script_name,
            })
        except ValueError as exc:
            results.append({
                "phone_number": patient["phone_number"],
                "patient_name": patient["full_name"],
                "status": "error",
                "detail": str(exc),
            })
        except TwilioRestException as exc:
            results.append({
                "phone_number": patient["phone_number"],
                "patient_name": patient["full_name"],
                "status": "error",
                "detail": exc.msg,
            })
        if delay_between_calls_ms > 0 and index < len(patients) - 1:
            await asyncio.sleep(delay_between_calls_ms / 1000)

    return {
        "requested": effective_limit,
        "matched": len(_match_patients(
            filters.q if payload else q,
            municipio=filters.municipio,
            hospital_name=filters.hospital_name,
            patient_name=filters.patient_name,
            phone_number=filters.phone_number,
            source=filters.source,
        )),
        "processed": len(results),
        "script_name": effective_script_name,
        "delay_between_calls_ms": delay_between_calls_ms,
        "filters": filters.model_dump(),
        "results": results,
    }
