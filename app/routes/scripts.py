"""API endpoints to view the active call script."""
import logging

from fastapi import APIRouter

from app.services.supabase_rest_service import get_active_call_script

logger = logging.getLogger(__name__)

router = APIRouter(tags=["scripts"])


@router.get("/")
async def list_scripts():
    """List the active call script."""
    return [get_active_call_script()]


@router.get("/active")
async def get_active_script():
    """Get the currently active call script."""
    return get_active_call_script()
