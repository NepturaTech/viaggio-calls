from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    """Endpoint de salud. También usado por el cron de keep-alive para evitar
    que Render duerma el servicio en el plan gratuito."""
    try:
        from app.services.supabase_rest_service import get_warmup_status
        cache = get_warmup_status()
    except Exception:
        cache = {"error": "unavailable"}

    return {
        "status": "ok",
        "service": "delfos-voice-ai",
        "cache": cache,
    }
