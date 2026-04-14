import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI
from contextlib import asynccontextmanager

from app.config import get_settings
from app.db.session import init_db
from app.routes.health import router as health_router
from app.routes.calls import router as calls_router
from app.routes.twilio_webhook import router as twilio_router
from app.routes.patients import router as patients_router
from app.routes.ws_conversationrelay import router as ws_router
from app.routes.scripts import router as scripts_router
from app.utils.logging import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    await init_db()
    yield


settings = get_settings()

app = FastAPI(
    title="Twilio ConversationRelay + GPT",
    description=(
        "Sistema de llamadas telefónicas con IA.\n\n"
        "**Modo actual:** datos manuales (manual_data.py)\n"
        "Edita ese archivo para cambiar clientes, citas y lo que dice el bot."
    ),
    version="0.2.0",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(calls_router, prefix="/calls")
app.include_router(patients_router, prefix="/patients")
app.include_router(twilio_router, prefix="/twilio")
app.include_router(ws_router, prefix="/ws")
app.include_router(scripts_router, prefix="/scripts")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_env == "development",
    )
