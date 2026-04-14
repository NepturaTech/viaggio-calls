"""
Capa de datos — Modo manual (sin Supabase).

Por ahora los datos se leen de manual_data.py.
Los logs de llamadas se guardan en memoria (se pierden al reiniciar).

Cuando pases a Supabase, descomenta el bloque y cambia las importaciones
en los services/routes.
"""

# ---------------------------------------------------------------
# MODO SUPABASE (descomentar cuando estés listo)
# ---------------------------------------------------------------
# from supabase import create_client, Client
# from app.config import get_settings
#
# _client: Client | None = None
#
# def get_supabase() -> Client:
#     global _client
#     if _client is None:
#         settings = get_settings()
#         _client = create_client(settings.supabase_url, settings.supabase_key)
#     return _client

# ---------------------------------------------------------------
# MODO MANUAL (activo)
# ---------------------------------------------------------------
import logging

logger = logging.getLogger(__name__)


async def init_db():
    """En modo manual no hay conexión a BD — solo verifica los datos."""
    from app.manual_data import CUSTOMERS, APPOINTMENTS, CALL_SCRIPT

    logger.info("Modo MANUAL activo — sin conexión a base de datos")
    logger.info("  Clientes cargados: %d", len(CUSTOMERS))
    logger.info("  Citas cargadas:    %d", len(APPOINTMENTS))
    logger.info("  Script activo:     %s", CALL_SCRIPT.get("name", "none"))
