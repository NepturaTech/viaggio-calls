import sys
from contextlib import asynccontextmanager
from pathlib import Path

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db.session import init_db
from app.routes.admin import router as admin_router
from app.routes.calls import router as calls_router
from app.routes.health import router as health_router
from app.routes.patients import router as patients_router
from app.routes.scripts import router as scripts_router
from app.routes.twilio_webhook import router as twilio_router
from app.routes.ws_conversationrelay import router as ws_router
from app.utils.logging import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    await init_db()
    yield


settings = get_settings()
cors_origins = [origin.strip() for origin in settings.cors_allow_origins.split(",") if origin.strip()]

app = FastAPI(
    title="Twilio ConversationRelay + GPT",
    description=(
        "Sistema de llamadas telefonicas con IA.\n\n"
        "Puede operar con datos manuales o con dos fuentes Supabase: "
        "una para pacientes/citas y otra para configuracion del proyecto."
    ),
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins or ["*"],
    allow_credentials=(cors_origins != ["*"]),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(admin_router, prefix="/admin")
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
