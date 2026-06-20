import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from app.config import get_settings

# logs/logs.txt en la raíz del repo (plain_calls/). Lo lee /logs/stream.
LOG_FILE = Path(__file__).resolve().parents[2] / "logs" / "logs.txt"


def setup_logging():
    """Configure application-wide logging."""
    settings = get_settings()
    level = logging.DEBUG if settings.app_env == "development" else logging.INFO

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    # ponytail: rotación 5MB x3 — evita que logs.txt crezca sin límite
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout), file_handler],
    )

    # Reduce noise from third-party libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("python_multipart").setLevel(logging.WARNING)
    logging.getLogger("websockets.client").setLevel(logging.INFO)
    # twilio.http_client imprime en INFO todos los headers de cada request/response
    logging.getLogger("twilio.http_client").setLevel(logging.WARNING)
