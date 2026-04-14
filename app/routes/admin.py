from fastapi import APIRouter

from app.services.supabase_rest_service import (
    get_backend_contract,
    get_call_rules,
    get_data_sources_contract,
    get_project_settings,
    get_voice_settings,
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
