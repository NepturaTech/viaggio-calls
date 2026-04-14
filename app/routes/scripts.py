"""API endpoints to view the current call script (manual mode)."""
import logging
from fastapi import APIRouter

from app.manual_data import CALL_SCRIPT

logger = logging.getLogger(__name__)

router = APIRouter(tags=["scripts"])


@router.get("/")
async def list_scripts():
    """List all call scripts (in manual mode, just one)."""
    return [CALL_SCRIPT]


@router.get("/active")
async def get_active_script():
    """Get the currently active call script.

    To change what the bot says, edit app/manual_data.py directly:
      - welcome_greeting → lo que dice al contestar
      - system_prompt → instrucciones del modelo GPT
    """
    return CALL_SCRIPT
