from fastapi import APIRouter, HTTPException, Query
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


def _match_patients(q: str | None = None) -> list[dict]:
    patients = list_backend_patients()
    if q:
        needle = q.strip().lower()
        patients = [
            patient
            for patient in patients
            if needle in patient["full_name"].lower() or needle in patient["phone_number"]
        ]
    return patients


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
        customer_id=customer["id"] if customer and customer.get("id", 0) < 10000 else None,
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
):
    """Trigger outbound calls for a filtered batch of patients."""
    patients = _match_patients(q)[:limit]
    if not patients:
        raise HTTPException(status_code=404, detail="No patients found for batch call")

    results: list[dict] = []
    for patient in patients:
        try:
            call_sid = await make_outbound_call(patient["phone_number"])
            customer, _ = get_customer_context(patient["phone_number"])
            create_call_record(
                twilio_call_sid=call_sid,
                direction="outbound",
                customer_id=customer["id"] if customer and customer.get("id", 0) < 10000 else None,
            )
            results.append({
                "phone_number": patient["phone_number"],
                "patient_name": patient["full_name"],
                "status": "initiated",
                "call_sid": call_sid,
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

    return {
        "requested": limit,
        "matched": len(_match_patients(q)),
        "processed": len(results),
        "results": results,
    }
