from fastapi import APIRouter, HTTPException

from app.services.supabase_rest_service import (
    find_backend_patient_by_phone,
    get_backend_contract,
    get_call_rules,
    get_call_settings_debug,
    get_data_sources_contract,
    get_patient_dataset_context,
    get_project_settings,
    get_voice_settings,
    list_backend_patients,
)

router = APIRouter(tags=["admin"])


@router.get("/meta")
async def get_admin_meta():
    """Return the backend contract expected by the admin frontend."""
    return get_backend_contract()


@router.get("/data-sources")
async def get_data_sources():
    """Expose the real database topology expected by the backend."""
    return get_data_sources_contract()


@router.get("/settings/runtime")
async def get_runtime_settings():
    """Expose non-secret runtime settings for the admin frontend."""
    return {
        "project_settings": get_project_settings(),
        "voice_settings": get_voice_settings(),
        "call_rules": get_call_rules(),
    }


@router.get("/settings/debug")
async def get_settings_debug(refresh: bool = False):
    """Expose current call settings resolution and cache status."""
    return {
        "call_settings": get_call_settings_debug(refresh=refresh),
    }


@router.get("/patient-dataset-context")
async def get_patient_dataset_context_debug(phone: str | None = None, document_number: str | None = None):
    """Expose resolved patient data plus dataset context for debugging."""
    patient = None

    if phone:
        patient = find_backend_patient_by_phone(phone)
    elif document_number:
        normalized_document = str(document_number).strip()
        patient = next(
            (
                candidate
                for candidate in list_backend_patients()
                if str(candidate.get("document_number") or candidate.get("identificacion") or "").strip() == normalized_document
            ),
            None,
        )

    if not patient:
        raise HTTPException(
            status_code=404,
            detail="No patient found. Provide a valid phone or document_number.",
        )

    dataset_context = get_patient_dataset_context(patient)
    return {
        "patient": patient,
        "dataset_context": dataset_context,
        "summary": {
            "source": patient.get("source"),
            "document_number": patient.get("document_number") or patient.get("identificacion"),
            "has_food_entries": bool(dataset_context.get("food_entries")),
            "has_conversations": bool(dataset_context.get("conversations")),
            "has_evalml": bool(dataset_context.get("evalml")),
            "has_data_step": bool(dataset_context.get("data_step")),
        },
    }
