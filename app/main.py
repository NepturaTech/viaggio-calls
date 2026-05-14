import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from app.config import get_settings
from app.db.session import init_db
from app.routes.admin import router as admin_router
from app.routes.calls import router as calls_router
from app.routes.errors import router as errors_router
from app.routes.health import router as health_router
from app.routes.patients import router as patients_router
from app.routes.scripts import router as scripts_router
from app.routes.twilio_webhook import router as twilio_router
from app.routes.ws_conversationrelay import router as ws_router
from app.services.error_log_service import log_error_event
from app.utils.logging import setup_logging

logger = logging.getLogger(__name__)

# Intervalo de refresco de caché (90 s — bien por debajo de los TTL de 60-120 s
# para que nunca haya un miss en llamadas reales).
_CACHE_REFRESH_INTERVAL_SECONDS = 90


async def _cache_refresh_loop() -> None:
    """Background task: pre-carga cachés al inicio y los refresca cada 90 s."""
    from app.services.supabase_rest_service import warm_all_caches

    loop = asyncio.get_event_loop()

    # Pre-carga inmediata al arrancar
    logger.info("Cache warmup inicial arrancando...")
    try:
        await loop.run_in_executor(None, warm_all_caches)
    except Exception as exc:
        logger.warning("Cache warmup inicial falló (no crítico): %s", exc)

    # Refresco periódico
    while True:
        await asyncio.sleep(_CACHE_REFRESH_INTERVAL_SECONDS)
        try:
            await loop.run_in_executor(None, warm_all_caches)
        except Exception as exc:
            logger.warning("Cache refresh periódico falló (no crítico): %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    await init_db()
    # Lanzar refresco de caché en background (no bloquea el arranque)
    refresh_task = asyncio.create_task(_cache_refresh_loop())
    yield
    # Cancelar el task limpiamente al apagar
    refresh_task.cancel()
    try:
        await refresh_task
    except asyncio.CancelledError:
        pass


settings = get_settings()
cors_origins = [origin.strip() for origin in settings.cors_allow_origins.split(",") if origin.strip()]

app = FastAPI(
    title="DELFOS Voice AI",
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


@app.middleware("http")
async def capture_backend_errors(request, call_next):
    try:
        return await call_next(request)
    except Exception as exc:
        log_error_event(
            source="backend",
            severity="error",
            error_type=type(exc).__name__,
            message=str(exc),
            path=str(request.url.path),
            method=request.method,
            details=repr(exc),
            context={
                "query_params": dict(request.query_params),
                "client": request.client.host if request.client else None,
            },
        )
        raise

app.include_router(health_router)
app.include_router(admin_router, prefix="/admin")
app.include_router(errors_router, prefix="/errors")
app.include_router(calls_router, prefix="/calls")
app.include_router(patients_router, prefix="/patients")
app.include_router(twilio_router, prefix="/twilio")
app.include_router(ws_router, prefix="/ws")
app.include_router(scripts_router, prefix="/scripts")


# Timestamp fijo al momento de arranque — cambia con cada nuevo despliegue.
_STARTUP_TIME = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
_APP_VERSION = "0.2.0"
_APP_ENV = settings.app_env or "production"


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root_page():
    """Página de inicio animada — confirma visualmente que el despliegue está activo."""
    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DELFOS Voice AI</title>
<style>
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{
    min-height:100vh;background:#09091a;
    display:flex;align-items:center;justify-content:center;
    font-family:'Segoe UI',system-ui,sans-serif;color:#fff;overflow:hidden;
  }}
  /* — Orbs de fondo — */
  .orb{{position:fixed;border-radius:50%;filter:blur(90px);opacity:.3;animation:floatOrb 9s ease-in-out infinite;pointer-events:none}}
  .o1{{width:420px;height:420px;background:#6c63ff;top:-120px;left:-120px;animation-delay:0s}}
  .o2{{width:320px;height:320px;background:#00d4aa;bottom:-100px;right:-100px;animation-delay:3s}}
  .o3{{width:260px;height:260px;background:#ff6584;top:55%;right:8%;animation-delay:5s}}
  @keyframes floatOrb{{0%,100%{{transform:translate(0,0) scale(1)}}50%{{transform:translate(18px,-22px) scale(1.06)}}}}

  /* — Tarjeta — */
  .card{{
    background:rgba(255,255,255,.045);
    backdrop-filter:blur(26px);-webkit-backdrop-filter:blur(26px);
    border:1px solid rgba(255,255,255,.1);
    border-radius:28px;padding:2.8rem 3.5rem;
    max-width:600px;width:92%;text-align:center;
    position:relative;z-index:10;
    box-shadow:0 8px 70px rgba(108,99,255,.18);
  }}

  /* — Personaje — */
  .char-wrap{{position:relative;display:inline-block;margin-bottom:1.4rem}}
  .char-wrap::after{{
    content:'';position:absolute;bottom:-8px;left:50%;transform:translateX(-50%);
    width:110px;height:18px;
    background:radial-gradient(ellipse,rgba(108,99,255,.45),transparent);
    filter:blur(8px);animation:shadow 2.5s ease-in-out infinite;
  }}
  @keyframes shadow{{0%,100%{{opacity:.5;transform:translateX(-50%) scaleX(1)}}50%{{opacity:1;transform:translateX(-50%) scaleX(1.25)}}}}

  /* — Monitor glow — */
  .screen{{animation:screenGlow 3s ease-in-out infinite}}
  @keyframes screenGlow{{
    0%,100%{{filter:drop-shadow(0 0 6px rgba(108,99,255,.7))}}
    50%{{filter:drop-shadow(0 0 16px rgba(0,212,170,.9))}}
  }}
  /* — Cursor parpadeante — */
  .cur{{animation:blink 1s step-end infinite}}
  @keyframes blink{{0%,100%{{opacity:1}}50%{{opacity:0}}}}
  /* — Mic ring — */
  .mic-ring{{animation:ring 1.8s ease-out infinite}}
  @keyframes ring{{0%{{r:3;opacity:.8}}100%{{r:9;opacity:0}}}}

  /* — Texto principal — */
  h1{{
    font-size:1.95rem;font-weight:700;letter-spacing:-.5px;margin-bottom:.3rem;
    background:linear-gradient(90deg,#a78bfa,#34d399);
    -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;
  }}
  .sub{{color:rgba(255,255,255,.45);font-size:.88rem;margin-bottom:1.8rem;letter-spacing:.4px}}

  /* — Badges de estado — */
  .badges{{display:flex;gap:.75rem;justify-content:center;flex-wrap:wrap;margin-bottom:1.8rem}}
  .badge{{
    display:flex;align-items:center;gap:.4rem;
    background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.1);
    border-radius:999px;padding:.3rem .8rem;font-size:.76rem;font-weight:500;
    color:rgba(255,255,255,.8);
  }}
  .dot{{width:7px;height:7px;border-radius:50%;flex-shrink:0}}
  .green{{background:#34d399;box-shadow:0 0 7px #34d399;animation:dotPulse 2s ease-in-out infinite}}
  .purple{{background:#a78bfa;box-shadow:0 0 7px #a78bfa}}
  .yellow{{background:#fbbf24;box-shadow:0 0 7px #fbbf24}}
  @keyframes dotPulse{{0%,100%{{box-shadow:0 0 4px #34d399}}50%{{box-shadow:0 0 12px #34d399,0 0 24px rgba(52,211,153,.25)}}}}

  /* — Divisor — */
  .div{{width:100%;height:1px;background:linear-gradient(90deg,transparent,rgba(255,255,255,.1),transparent);margin:1.4rem 0}}

  /* — Meta grid — */
  .meta{{display:grid;grid-template-columns:1fr 1fr;gap:.85rem;text-align:left}}
  .meta label{{display:block;font-size:.68rem;text-transform:uppercase;letter-spacing:.9px;color:rgba(255,255,255,.3);margin-bottom:.18rem}}
  .meta span{{font-size:.84rem;color:rgba(255,255,255,.85);font-weight:500}}

  /* — Pie — */
  .footer{{font-size:.7rem;color:rgba(255,255,255,.25);margin-top:1.6rem;font-family:monospace;letter-spacing:.4px}}
  .footer strong{{color:rgba(255,255,255,.45)}}
</style>
</head>
<body>
<div class="orb o1"></div>
<div class="orb o2"></div>
<div class="orb o3"></div>

<div class="card">

  <!-- ── Personaje animado ── -->
  <div class="char-wrap">
  <svg width="210" height="185" viewBox="0 0 210 185" fill="none" xmlns="http://www.w3.org/2000/svg">

    <!-- Escritorio -->
    <rect x="18" y="132" width="174" height="11" rx="5" fill="#1e1b4b"/>
    <rect x="38" y="143" width="9" height="32" rx="4" fill="#13112e"/>
    <rect x="163" y="143" width="9" height="32" rx="4" fill="#13112e"/>

    <!-- Monitor base -->
    <rect x="88" y="120" width="34" height="14" rx="4" fill="#312e81"/>
    <rect x="78" y="130" width="54" height="6" rx="3" fill="#1e1b4b"/>

    <!-- Monitor cuerpo -->
    <rect x="52" y="58" width="106" height="66" rx="7" fill="#1e1b4b"/>
    <!-- Pantalla clase "screen" (glow) -->
    <rect x="56" y="62" width="98" height="58" rx="5" fill="#4338ca" class="screen"/>
    <!-- Código en pantalla -->
    <rect x="63" y="70" width="44" height="3.5" rx="1.5" fill="rgba(255,255,255,.65)"/>
    <rect x="63" y="77" width="60" height="3.5" rx="1.5" fill="rgba(52,211,153,.8)"/>
    <rect x="63" y="84" width="33" height="3.5" rx="1.5" fill="rgba(255,255,255,.4)"/>
    <rect x="63" y="91" width="52" height="3.5" rx="1.5" fill="rgba(251,191,36,.75)"/>
    <rect x="63" y="98" width="38" height="3.5" rx="1.5" fill="rgba(167,139,250,.7)"/>
    <rect x="63" y="105" width="18" height="3.5" rx="1.5" fill="rgba(255,255,255,.35)" class="cur"/>

    <!-- Respaldo silla -->
    <rect x="80" y="92" width="50" height="56" rx="14" fill="#312e81"/>

    <!-- Cuerpo / blusa -->
    <ellipse cx="105" cy="122" rx="22" ry="17" fill="#6d28d9"/>
    <rect x="83" y="113" width="44" height="22" rx="9" fill="#6d28d9"/>

    <!-- Brazo izquierdo → teclado -->
    <path d="M85 120 C73 127 57 134 54 137" stroke="#f9a674" stroke-width="8" stroke-linecap="round"/>
    <!-- Brazo derecho → teclado -->
    <path d="M125 120 C137 127 153 134 156 137" stroke="#f9a674" stroke-width="8" stroke-linecap="round"/>

    <!-- Teclado -->
    <rect x="52" y="134" width="106" height="11" rx="4" fill="#1e1b4b"/>
    <rect x="56" y="136.5" width="11" height="5.5" rx="1.5" fill="#312e81"/>
    <rect x="70" y="136.5" width="11" height="5.5" rx="1.5" fill="#312e81"/>
    <rect x="84" y="136.5" width="11" height="5.5" rx="1.5" fill="#312e81"/>
    <rect x="98" y="136.5" width="11" height="5.5" rx="1.5" fill="#312e81"/>
    <rect x="112" y="136.5" width="11" height="5.5" rx="1.5" fill="#312e81"/>
    <rect x="126" y="136.5" width="11" height="5.5" rx="1.5" fill="#312e81"/>
    <rect x="140" y="136.5" width="11" height="5.5" rx="1.5" fill="#312e81"/>

    <!-- Cuello -->
    <rect x="99" y="88" width="12" height="13" rx="5" fill="#f9a674"/>

    <!-- Cabeza -->
    <ellipse cx="105" cy="73" rx="22" ry="23" fill="#f9a674"/>

    <!-- Cabello (oscuro) -->
    <path d="M83 68 C80 56 82 42 89 34 C95 27 103 24 105 24 C107 24 115 27 121 34 C128 42 130 56 127 68" fill="#2d1b0e"/>
    <ellipse cx="105" cy="53" rx="22" ry="13" fill="#2d1b0e"/>
    <!-- Mechones laterales -->
    <ellipse cx="85" cy="75" rx="6" ry="14" fill="#2d1b0e"/>
    <ellipse cx="125" cy="75" rx="6" ry="14" fill="#2d1b0e"/>

    <!-- Ojos -->
    <ellipse cx="97" cy="71" rx="3.2" ry="3.8" fill="#1c0f07"/>
    <ellipse cx="113" cy="71" rx="3.2" ry="3.8" fill="#1c0f07"/>
    <ellipse cx="98.2" cy="70" rx="1.1" ry="1.1" fill="white"/>
    <ellipse cx="114.2" cy="70" rx="1.1" ry="1.1" fill="white"/>
    <!-- Pestañas -->
    <path d="M93.5 67.5 C94.5 65.5 96.5 64.5 99 65" stroke="#1c0f07" stroke-width="1.2" stroke-linecap="round" fill="none"/>
    <path d="M109.5 67.5 C110.5 65.5 112.5 64.5 115 65" stroke="#1c0f07" stroke-width="1.2" stroke-linecap="round" fill="none"/>

    <!-- Sonrisa / mejillas -->
    <path d="M99 80 Q105 86 111 80" stroke="#d4765a" stroke-width="1.8" stroke-linecap="round" fill="none"/>
    <ellipse cx="93" cy="79" rx="4" ry="2.5" fill="rgba(255,150,100,.3)"/>
    <ellipse cx="117" cy="79" rx="4" ry="2.5" fill="rgba(255,150,100,.3)"/>

    <!-- Auricular (diadema) -->
    <path d="M85 64 C85 44 125 44 125 64" stroke="#1e1b4b" stroke-width="4.5" stroke-linecap="round" fill="none"/>
    <!-- Copas -->
    <ellipse cx="85" cy="70" rx="5.5" ry="7.5" fill="#1e1b4b"/>
    <ellipse cx="125" cy="70" rx="5.5" ry="7.5" fill="#1e1b4b"/>
    <!-- Mic boom -->
    <path d="M85 73 C81 80 79 84 77 87" stroke="#1e1b4b" stroke-width="3" stroke-linecap="round"/>
    <!-- Mic cabeza -->
    <circle cx="76" cy="88" r="4" fill="#00d4aa"/>
    <!-- Mic ring animado -->
    <circle cx="76" cy="88" fill="rgba(0,212,170,.25)">
      <animate attributeName="r" values="3;10;3" dur="2s" repeatCount="indefinite"/>
      <animate attributeName="opacity" values=".7;0;.7" dur="2s" repeatCount="indefinite"/>
    </circle>

    <!-- Onda de llamada activa (3 arcos) -->
    <path d="M135 54 Q141 60 135 66" stroke="#34d399" stroke-width="2" stroke-linecap="round" fill="none" opacity=".9">
      <animate attributeName="opacity" values=".9;.2;.9" dur="1.4s" repeatCount="indefinite"/>
    </path>
    <path d="M140 49 Q149 60 140 71" stroke="#34d399" stroke-width="2" stroke-linecap="round" fill="none" opacity=".7">
      <animate attributeName="opacity" values=".7;.1;.7" dur="1.4s" begin="0.2s" repeatCount="indefinite"/>
    </path>
    <path d="M145 44 Q157 60 145 76" stroke="#34d399" stroke-width="2" stroke-linecap="round" fill="none" opacity=".5">
      <animate attributeName="opacity" values=".5;.05;.5" dur="1.4s" begin="0.4s" repeatCount="indefinite"/>
    </path>

  </svg>
  </div>

  <h1>DELFOS Voice AI</h1>
  <p class="sub">Sistema de llamadas con inteligencia artificial</p>

  <div class="badges">
    <div class="badge"><span class="dot green"></span> API activa</div>
    <div class="badge"><span class="dot green"></span> WebSocket listo</div>
    <div class="badge"><span class="dot yellow"></span> {_APP_ENV}</div>
    <div class="badge"><span class="dot purple"></span> v{_APP_VERSION}</div>
  </div>

  <div class="div"></div>

  <div class="meta">
    <div>
      <label>Motor de voz</label>
      <span>Twilio ConversationRelay</span>
    </div>
    <div>
      <label>Modelo IA</label>
      <span>Claude Haiku 4.5</span>
    </div>
    <div>
      <label>TTS</label>
      <span>ElevenLabs</span>
    </div>
    <div>
      <label>Almacenamiento</label>
      <span>Supabase Storage</span>
    </div>
  </div>

  <p class="footer">
    ⚡ <strong>Desplegado:</strong> {_STARTUP_TIME} &nbsp;·&nbsp;
    <span id="now"></span>
  </p>
</div>

<script>
  const el = document.getElementById('now');
  const tick = () => {{
    el.textContent = 'Ahora: ' + new Date().toLocaleString('es-CO', {{
      day:'2-digit', month:'2-digit', year:'numeric',
      hour:'2-digit', minute:'2-digit', second:'2-digit'
    }});
  }};
  tick(); setInterval(tick, 1000);
</script>
</body>
</html>"""
    return HTMLResponse(content=html)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_env == "development",
    )
