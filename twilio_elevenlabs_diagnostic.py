#!/usr/bin/env python3
"""
=============================================================================
DIAGNÓSTICO: Twilio ConversationRelay + ElevenLabs
=============================================================================
Este script valida tu configuración completa para encontrar el error
"We are sorry, an application error has occurred"

USO:
  1. Configura las variables al inicio del script
  2. Ejecuta: python3 twilio_elevenlabs_diagnostic.py

REQUIERE:
  pip install requests twilio --break-system-packages
=============================================================================
"""

import os
import sys
import json
import traceback
from datetime import datetime
from pathlib import Path

# Cargar .env automáticamente
def _load_dotenv():
    env_file = Path(__file__).parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value

_load_dotenv()

# ╔═══════════════════════════════════════════════════════════════╗
# ║  CONFIGURA ESTAS VARIABLES ANTES DE EJECUTAR                ║
# ╚═══════════════════════════════════════════════════════════════╝

# Twilio credentials
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN  = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE_NUMBER = os.environ.get("TWILIO_PHONE_NUMBER", "")

# ElevenLabs (solo si usas modo realtime / API directa)
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")

# Tu configuración actual — se lee del .env si está disponible
_raw_voice = os.environ.get("TWILIO_TTS_VOICE", "b2htR0pMe28pYwCY9gnP")
# Si el voice ya tiene formato completo ID-MODEL-SPEED_STAB_SIM, parsearlo
_voice_parts = _raw_voice.split("-")
VOICE_ID        = _voice_parts[0] if _voice_parts else "b2htR0pMe28pYwCY9gnP"
TTS_MODEL       = _voice_parts[1] if len(_voice_parts) > 1 else os.environ.get("TWILIO_TTS_MODEL", "turbo_v2_5")
_settings_part  = _voice_parts[2] if len(_voice_parts) > 2 else "0.95_0.45_0.70"
_settings       = _settings_part.split("_")
TTS_SPEED       = _settings[0] if len(_settings) > 0 else os.environ.get("TWILIO_TTS_SPEED", "0.95")
TTS_STABILITY   = _settings[1] if len(_settings) > 1 else os.environ.get("TWILIO_TTS_STABILITY", "0.45")
TTS_SIMILARITY  = _settings[2] if len(_settings) > 2 else os.environ.get("TWILIO_TTS_SIMILARITY_BOOST", "0.70")
LANGUAGE        = os.environ.get("TWILIO_CONVERSATION_LANGUAGE", "es-CO")

_base_url = os.environ.get("BASE_URL", "").rstrip("/")
WEBSOCKET_URL = os.environ.get("WEBSOCKET_URL", "")
if not WEBSOCKET_URL and _base_url:
    WEBSOCKET_URL = _base_url.replace("https://", "wss://").replace("http://", "ws://") + "/ws/conversation"

# ╔═══════════════════════════════════════════════════════════════╗
# ║  NO MODIFIQUES DEBAJO DE ESTA LÍNEA                         ║
# ╚═══════════════════════════════════════════════════════════════╝

PASS = "✅"
FAIL = "❌"
WARN = "⚠️ "
INFO = "ℹ️ "

results = []


def log(status, category, message, detail=""):
    results.append({"status": status, "category": category, "message": message, "detail": detail})
    icon = status
    print(f"  {icon} [{category}] {message}")
    if detail:
        print(f"      → {detail}")


def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ============================================================
# TEST 1: Validar variables de entorno
# ============================================================
def test_env_vars():
    section("1. VARIABLES DE ENTORNO")

    if not TWILIO_ACCOUNT_SID:
        log(FAIL, "ENV", "TWILIO_ACCOUNT_SID no está configurado",
            "Exporta: export TWILIO_ACCOUNT_SID=ACxxxxxxxxx")
    elif not TWILIO_ACCOUNT_SID.startswith("AC"):
        log(FAIL, "ENV", "TWILIO_ACCOUNT_SID no empieza con 'AC'",
            f"Valor actual empieza con: {TWILIO_ACCOUNT_SID[:4]}...")
    else:
        log(PASS, "ENV", "TWILIO_ACCOUNT_SID válido",
            f"{TWILIO_ACCOUNT_SID[:6]}...{TWILIO_ACCOUNT_SID[-4:]}")

    if not TWILIO_AUTH_TOKEN:
        log(FAIL, "ENV", "TWILIO_AUTH_TOKEN no está configurado")
    else:
        log(PASS, "ENV", "TWILIO_AUTH_TOKEN presente",
            f"***...{TWILIO_AUTH_TOKEN[-4:]}")

    if not TWILIO_PHONE_NUMBER:
        log(WARN, "ENV", "TWILIO_PHONE_NUMBER no configurado",
            "Necesario para pruebas de llamadas")
    else:
        log(PASS, "ENV", "TWILIO_PHONE_NUMBER presente", TWILIO_PHONE_NUMBER)

    if not WEBSOCKET_URL:
        log(FAIL, "ENV", "WEBSOCKET_URL no configurada",
            "ConversationRelay requiere una URL wss:// para el WebSocket")
    elif not WEBSOCKET_URL.startswith("wss://"):
        log(FAIL, "ENV", "WEBSOCKET_URL debe empezar con wss://",
            f"Actual: {WEBSOCKET_URL[:40]}...")
    else:
        log(PASS, "ENV", "WEBSOCKET_URL detectada", WEBSOCKET_URL)

    log(INFO, "ENV", f"BASE_URL configurada: {_base_url or '(vacía)'}")
    log(INFO, "ENV", f"TWILIO_VOICE_MODE: {os.environ.get('TWILIO_VOICE_MODE', '(no definido)')}")
    log(INFO, "ENV", f"TWILIO_TTS_PROVIDER: {os.environ.get('TWILIO_TTS_PROVIDER', '(no definido)')}")


# ============================================================
# TEST 2: Validar formato del Voice ID para ConversationRelay
# ============================================================
def test_voice_format():
    section("2. FORMATO VOICE ID (ConversationRelay)")

    if not VOICE_ID:
        log(FAIL, "VOICE", "Voice ID está vacío")
        return

    if len(VOICE_ID) < 10:
        log(FAIL, "VOICE", "Voice ID parece demasiado corto",
            f"Longitud: {len(VOICE_ID)} chars. Los IDs de ElevenLabs tienen ~20 chars")
    else:
        log(PASS, "VOICE", f"Voice ID: {VOICE_ID}", f"Longitud: {len(VOICE_ID)} chars")

    # Validar modelo
    SUPPORTED_MODELS = ["flash_v2", "turbo_v2_5", "turbo_v2", "flash_v2_5"]
    UNSUPPORTED_MODELS = [
        "eleven_multilingual_v2", "eleven_v3", "eleven_flash_v2_5",
        "eleven_turbo_v2_5", "eleven_monolingual_v1", "multilingual_v2",
        "eleven_flash_v2", "eleven_turbo_v2",
    ]

    if TTS_MODEL in UNSUPPORTED_MODELS:
        log(FAIL, "VOICE", f"Modelo '{TTS_MODEL}' NO soportado en ConversationRelay",
            f"Usa uno de: {', '.join(SUPPORTED_MODELS)}")
    elif TTS_MODEL in SUPPORTED_MODELS:
        log(PASS, "VOICE", f"Modelo '{TTS_MODEL}' es soportado")
    else:
        log(WARN, "VOICE", f"Modelo '{TTS_MODEL}' no reconocido",
            f"Modelos válidos: {', '.join(SUPPORTED_MODELS)}")

    # Validar speed
    try:
        speed = float(TTS_SPEED)
        if 0.7 <= speed <= 1.2:
            log(PASS, "VOICE", f"Speed {TTS_SPEED} en rango (0.7–1.2)")
        else:
            log(FAIL, "VOICE", f"Speed {TTS_SPEED} fuera de rango", "Debe estar entre 0.7 y 1.2")
    except ValueError:
        log(FAIL, "VOICE", f"Speed '{TTS_SPEED}' no es un número válido")

    # Validar stability
    try:
        stab = float(TTS_STABILITY)
        if 0.0 <= stab <= 1.0:
            log(PASS, "VOICE", f"Stability {TTS_STABILITY} en rango (0.0–1.0)")
        else:
            log(FAIL, "VOICE", f"Stability {TTS_STABILITY} fuera de rango")
    except ValueError:
        log(FAIL, "VOICE", f"Stability '{TTS_STABILITY}' no es un número válido")

    # Validar similarity
    try:
        sim = float(TTS_SIMILARITY)
        if 0.0 <= sim <= 1.0:
            log(PASS, "VOICE", f"Similarity {TTS_SIMILARITY} en rango (0.0–1.0)")
        else:
            log(FAIL, "VOICE", f"Similarity {TTS_SIMILARITY} fuera de rango")
    except ValueError:
        log(FAIL, "VOICE", f"Similarity '{TTS_SIMILARITY}' no es un número válido")

    voice_string = f"{VOICE_ID}-{TTS_MODEL}-{TTS_SPEED}_{TTS_STABILITY}_{TTS_SIMILARITY}"
    print(f"\n  📋 Voice string completo para ConversationRelay:")
    print(f'     voice="{voice_string}"')

    return voice_string


# ============================================================
# TEST 3: Validar Voice ID en ElevenLabs API
# ============================================================
def test_elevenlabs_voice():
    section("3. VALIDACIÓN VOICE ID EN ELEVENLABS")

    if not ELEVENLABS_API_KEY:
        log(WARN, "11LABS", "No hay ELEVENLABS_API_KEY en el .env",
            "Sin ella Twilio maneja la voz internamente via ConversationRelay.")
        log(INFO, "11LABS", "Para verificar manualmente:",
            f"curl -H 'xi-api-key: TU_KEY' https://api.elevenlabs.io/v1/voices/{VOICE_ID}")
        return

    try:
        import requests

        headers = {"xi-api-key": ELEVENLABS_API_KEY, "Accept": "application/json"}
        print(f"  Consultando ElevenLabs API para voice ID: {VOICE_ID}...")
        resp = requests.get(
            f"https://api.elevenlabs.io/v1/voices/{VOICE_ID}",
            headers=headers, timeout=10
        )

        if resp.status_code == 200:
            voice_data = resp.json()
            name    = voice_data.get("name", "Unknown")
            labels  = voice_data.get("labels", {})
            accent  = labels.get("accent", "N/A")
            lang    = labels.get("language", "N/A")
            gender  = labels.get("gender", "N/A")
            use_case = labels.get("use_case", "N/A")
            log(PASS, "11LABS", f"Voice encontrada: '{name}'")
            log(INFO, "11LABS", f"Acento: {accent} | Idioma: {lang} | Género: {gender} | Uso: {use_case}")
            if voice_data.get("sharing"):
                log(INFO, "11LABS", "Esta es una voz compartida/pública")
        elif resp.status_code == 401:
            log(FAIL, "11LABS", "API key inválida o expirada")
        elif resp.status_code == 404:
            log(FAIL, "11LABS", f"Voice ID '{VOICE_ID}' NO EXISTE en ElevenLabs",
                "Verifica el ID en https://elevenlabs.io/app/voice-library")
        else:
            log(FAIL, "11LABS", f"Error inesperado: HTTP {resp.status_code}", resp.text[:200])

        print(f"\n  Verificando modelos disponibles...")
        resp_models = requests.get("https://api.elevenlabs.io/v1/models", headers=headers, timeout=10)
        if resp_models.status_code == 200:
            models = resp_models.json()
            for m in models:
                mid  = m.get("model_id", "")
                mname = m.get("name", "")
                can_tts = m.get("can_do_text_to_speech", False)
                langs = [l.get("language_id", "") for l in m.get("languages", [])]
                has_es = any("es" in l for l in langs)
                status = PASS if can_tts and has_es else WARN
                print(f"    {status} {mid} - {mname} (TTS: {can_tts}, Español: {has_es})")

    except ImportError:
        log(FAIL, "11LABS", "Módulo 'requests' no instalado",
            "pip install requests --break-system-packages")
    except Exception as e:
        log(FAIL, "11LABS", f"Error al conectar con ElevenLabs: {str(e)}")


# ============================================================
# TEST 4: Validar credenciales de Twilio
# ============================================================
def test_twilio_connection():
    section("4. CONEXIÓN CON TWILIO")

    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        log(FAIL, "TWILIO", "Credenciales no configuradas, saltando test")
        return

    try:
        from twilio.rest import Client
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

        account = client.api.accounts(TWILIO_ACCOUNT_SID).fetch()
        log(PASS, "TWILIO", f"Cuenta activa: {account.friendly_name}",
            f"Status: {account.status}")

        if TWILIO_PHONE_NUMBER:
            try:
                numbers = client.incoming_phone_numbers.list(phone_number=TWILIO_PHONE_NUMBER)
                if numbers:
                    num = numbers[0]
                    log(PASS, "TWILIO", f"Número encontrado: {num.phone_number}")
                    voice_url = num.voice_url
                    log(INFO, "TWILIO", f"Voice URL: {voice_url or 'NO CONFIGURADA'}")
                    log(INFO, "TWILIO", f"Voice Method: {num.voice_method}")
                    if not voice_url:
                        log(FAIL, "TWILIO", "El número NO tiene Voice URL configurada",
                            "Configura el webhook en Console > Phone Numbers > tu número")
                    caps = num.capabilities
                    if caps and caps.get("voice", False):
                        log(PASS, "TWILIO", "Número tiene capacidad de voz habilitada")
                    else:
                        log(FAIL, "TWILIO", "Número NO tiene capacidad de voz")
                else:
                    log(FAIL, "TWILIO", f"Número {TWILIO_PHONE_NUMBER} no encontrado en tu cuenta")
            except Exception as e:
                log(FAIL, "TWILIO", f"Error al buscar número: {str(e)}")

        print(f"\n  Buscando errores recientes en Twilio Debugger...")
        try:
            alerts = client.monitor.alerts.list(limit=5)
            if alerts:
                log(WARN, "TWILIO", f"Se encontraron {len(alerts)} alertas recientes:")
                for alert in alerts[:5]:
                    msg  = alert.alert_text[:120] if alert.alert_text else "Sin detalle"
                    date = alert.date_created
                    print(f"    {FAIL} [{date}] Error {alert.error_code}: {msg}")
            else:
                log(PASS, "TWILIO", "No hay alertas recientes en el debugger")
        except Exception as e:
            log(WARN, "TWILIO", f"No se pudo acceder al debugger: {str(e)}")

    except ImportError:
        log(FAIL, "TWILIO", "Módulo 'twilio' no instalado",
            "pip install twilio --break-system-packages")
    except Exception as e:
        log(FAIL, "TWILIO", f"Error de conexión: {str(e)}")


# ============================================================
# TEST 5: Generar y validar TwiML
# ============================================================
def test_twiml_generation():
    section("5. GENERACIÓN DE TwiML")

    voice_string = f"{VOICE_ID}-{TTS_MODEL}-{TTS_SPEED}_{TTS_STABILITY}_{TTS_SIMILARITY}"

    try:
        from twilio.twiml.voice_response import VoiceResponse, Connect

        response = VoiceResponse()
        connect  = Connect()

        try:
            connect.conversation_relay(
                url=WEBSOCKET_URL or "wss://example.com/ws/conversation",
                tts_provider=os.environ.get("TWILIO_TTS_PROVIDER", "ElevenLabs"),
                voice=voice_string,
                language=LANGUAGE,
                transcription_provider=os.environ.get("TWILIO_TRANSCRIPTION_PROVIDER", "Google"),
                speech_model=os.environ.get("TWILIO_SPEECH_MODEL", "experimental_conversations"),
                welcome_greeting="Hola, hablo con el paciente?",
                hints=os.environ.get("TWILIO_SPEECH_HINTS", "alo,bueno,hola,si,no"),
            )
            response.append(connect)
            twiml_str = str(response)
            log(PASS, "TWIML", "TwiML generado exitosamente con SDK")
            print(f"\n  📄 TwiML generado:")
            print(f"  {'─'*50}")
            print(f"  {twiml_str}")
            print(f"  {'─'*50}")

        except (AttributeError, TypeError) as e:
            log(WARN, "TWIML", f"SDK no soporta conversation_relay directamente: {e}",
                "Generando TwiML manualmente...")
            twiml_manual = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <ConversationRelay
      url="{WEBSOCKET_URL or 'wss://TU-SERVIDOR.com/ws/conversation'}"
      ttsProvider="{os.environ.get('TWILIO_TTS_PROVIDER', 'ElevenLabs')}"
      voice="{voice_string}"
      language="{LANGUAGE}"
      transcriptionProvider="{os.environ.get('TWILIO_TRANSCRIPTION_PROVIDER', 'Google')}"
      speechModel="{os.environ.get('TWILIO_SPEECH_MODEL', 'experimental_conversations')}"
      welcomeGreeting="Hola, hablo con el paciente?"
      hints="{os.environ.get('TWILIO_SPEECH_HINTS', 'alo,bueno,hola,si,no')}"
    />
  </Connect>
</Response>"""
            log(PASS, "TWIML", "TwiML manual generado")
            print(f"\n  📄 TwiML que tu endpoint debe devolver:")
            print(f"  {'─'*50}")
            print(twiml_manual)
            print(f"  {'─'*50}")

    except ImportError:
        log(WARN, "TWIML", "SDK de Twilio no instalado, generando TwiML manual")


# ============================================================
# TEST 6: Verificar WebSocket URL accesible
# ============================================================
def test_websocket_url():
    section("6. VERIFICACIÓN WEBSOCKET")

    if not WEBSOCKET_URL:
        log(FAIL, "WS", "WEBSOCKET_URL no configurada")
        return

    https_url = WEBSOCKET_URL.replace("wss://", "https://").replace("ws://", "http://")
    # Quitar el path /ws/conversation para verificar solo el servidor raíz
    base_check = https_url.replace("/ws/conversation", "/health")

    try:
        import requests
        resp = requests.get(base_check, timeout=10, verify=True)
        log(PASS, "WS", f"Servidor responde: HTTP {resp.status_code}", base_check)
        if resp.status_code == 200:
            try:
                body = resp.json()
                log(PASS, "WS", f"Health check OK: {body}")
            except Exception:
                log(INFO, "WS", f"Respuesta (no JSON): {resp.text[:80]}")
    except Exception as e:
        log(WARN, "WS", f"No se pudo verificar el servidor: {str(e)}", base_check)


# ============================================================
# TEST 7: Verificar .env duplicados y variables críticas
# ============================================================
def test_env_file():
    section("7. ANÁLISIS DE ARCHIVO .ENV")

    env_file = Path(__file__).parent / ".env"
    if not env_file.exists():
        log(WARN, "DOTENV", "No se encontró archivo .env")
        return

    log(INFO, "DOTENV", f"Archivo: {env_file}")
    lines = env_file.read_text(encoding="utf-8").splitlines()

    seen_keys = {}
    duplicates = []
    for i, line in enumerate(lines, 1):
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key = line.split('=', 1)[0].strip()
        if key in seen_keys:
            duplicates.append((key, seen_keys[key], i))
        else:
            seen_keys[key] = i

    if duplicates:
        for key, first_line, second_line in duplicates:
            log(FAIL, "DOTENV", f"Variable DUPLICADA: '{key}'",
                f"Línea {first_line} y línea {second_line}")
    else:
        log(PASS, "DOTENV", "No hay variables duplicadas")

    critical = {
        "TWILIO_TTS_PROVIDER": "ElevenLabs",
        "TWILIO_VOICE_MODE": "conversation_relay",
        "TWILIO_CONVERSATION_LANGUAGE": None,
        "TWILIO_TTS_VOICE": None,
        "BASE_URL": None,
        "OPENAI_API_KEY": None,
    }

    for var, expected in critical.items():
        val = os.environ.get(var, "")
        if not val:
            log(WARN, "DOTENV", f"{var} está vacía o no definida")
        elif expected and val != expected:
            log(WARN, "DOTENV", f"{var}={val}", f"Se esperaba: {expected}")
        else:
            display = val if len(val) < 40 else val[:37] + "..."
            log(PASS, "DOTENV", f"{var}={display}")


# ============================================================
# TEST 8: Verificar call logs de Twilio
# ============================================================
def test_recent_calls():
    section("8. ÚLTIMAS LLAMADAS EN TWILIO")

    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        log(WARN, "CALLS", "Sin credenciales, no se pueden verificar llamadas")
        return

    try:
        from twilio.rest import Client
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

        calls = client.calls.list(limit=5)
        if calls:
            print(f"  Últimas {len(calls)} llamadas:")
            for call in calls:
                status    = call.status
                direction = call.direction
                duration  = call.duration or "0"
                date      = call.date_created
                sid       = call.sid
                icon = PASS if status == "completed" else FAIL
                print(f"    {icon} [{date}] {direction} | Status: {status} | "
                      f"Duración: {duration}s | SID: {sid[:20]}...")
                if status in ["failed", "busy", "no-answer"]:
                    log(FAIL, "CALLS", f"Llamada fallida: {sid}",
                        f"Revisa: https://console.twilio.com/us1/monitor/logs/debugger")
        else:
            log(INFO, "CALLS", "No hay llamadas recientes")

    except ImportError:
        log(WARN, "CALLS", "SDK de Twilio no instalado")
    except Exception as e:
        log(FAIL, "CALLS", f"Error: {str(e)}")


# ============================================================
# RESUMEN FINAL
# ============================================================
def print_summary():
    section("RESUMEN DE DIAGNÓSTICO")

    fails  = [r for r in results if r["status"] == FAIL]
    warns  = [r for r in results if r["status"] == WARN]
    passes = [r for r in results if r["status"] == PASS]

    print(f"\n  {PASS} Pasaron:       {len(passes)}")
    print(f"  {WARN} Advertencias:  {len(warns)}")
    print(f"  {FAIL} Fallaron:      {len(fails)}")

    if fails:
        print(f"\n  {'─'*50}")
        print(f"  ERRORES CRÍTICOS QUE DEBES CORREGIR:")
        print(f"  {'─'*50}")
        for i, f in enumerate(fails, 1):
            print(f"  {i}. [{f['category']}] {f['message']}")
            if f['detail']:
                print(f"     → {f['detail']}")

    if warns:
        print(f"\n  {'─'*50}")
        print(f"  ADVERTENCIAS A REVISAR:")
        print(f"  {'─'*50}")
        for i, w in enumerate(warns, 1):
            print(f"  {i}. [{w['category']}] {w['message']}")
            if w['detail']:
                print(f"     → {w['detail']}")

    print(f"\n  {'═'*50}")
    print(f"  CAUSAS MÁS PROBABLES DEL ERROR:")
    print(f"  {'═'*50}")
    print(f"  1. El voice ID puede no estar habilitado para ConversationRelay")
    print(f"     (no todas las voces de ElevenLabs funcionan en CR de Twilio)")
    print(f"  2. Tu endpoint /twilio/voice no devuelve TwiML válido o no es accesible")
    print(f"  3. El WebSocket server no está activo o tiene SSL inválido")
    print(f"  4. Verifica: https://console.twilio.com/us1/monitor/logs/debugger")
    print(f"\n  {'═'*50}")
    print(f"  PRÓXIMOS PASOS:")
    print(f"  {'═'*50}")
    print(f"  1. Ve a Twilio Console > Monitor > Logs > Errors y busca el error exacto")
    print(f"  2. Asegúrate de que cloudflared o ngrok están activos")
    print(f"  3. Prueba el /health de tu servidor desde el navegador")
    print(f"  4. Prueba con voz sin customización: voice=\"{VOICE_ID}\" (sin modelo)")


# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    print(f"\n{'═'*60}")
    print(f"  DIAGNÓSTICO TWILIO + ELEVENLABS")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'═'*60}")

    test_env_vars()
    test_voice_format()
    test_elevenlabs_voice()
    test_twilio_connection()
    test_twiml_generation()
    test_websocket_url()
    test_env_file()
    test_recent_calls()
    print_summary()
