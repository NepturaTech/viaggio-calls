# Guía de implementación: Voice-to-Voice con GPT-4o para llamadas de seguimiento en salud

## Objetivo

Esta guía describe cómo migrar un asistente telefónico basado en Twilio ConversationRelay hacia un flujo **Voice-to-Voice** con la Realtime API de OpenAI para reducir latencia, mejorar la naturalidad del habla y simplificar la arquitectura de audio en tiempo real.[cite:31][cite:38]

El objetivo práctico es pasar de un esquema separado de transcripción, generación de texto y síntesis de voz a una sesión única donde el modelo reciba audio, detecte turnos y devuelva audio directamente.[cite:31][cite:32]

## Arquitectura objetivo

La Realtime API de OpenAI permite sesiones por WebSocket con entrada y salida de audio, además de instrucciones del sistema, detección de turnos y selección de voz dentro de la sesión.[cite:31][cite:32]

Twilio anunció integración con la Realtime API para experiencias conversacionales de voz, lo que habilita una arquitectura donde Twilio sigue manejando la telefonía y el servidor propio actúa como puente entre el WebSocket de Twilio y el WebSocket de OpenAI.[cite:38][cite:41]

### Estado actual vs estado objetivo

| Componente | Estado actual | Estado objetivo |
|---|---|---|
| Entrada de usuario | STT indirecto vía ConversationRelay | Audio directo hacia sesión Realtime[cite:31][cite:32] |
| Generación de respuesta | GPT textual separado | GPT-4o Realtime dentro de la misma sesión[cite:31] |
| Salida de voz | TTS separado | Audio generado por el modelo en la respuesta[cite:31][cite:32] |
| Turn taking | Lógica parcial con Twilio | `server_vad` y sesión de audio del modelo[cite:32] |
| Latencia percibida | Mayor por pipeline fragmentado | Menor por flujo unificado[cite:31][cite:38] |

## Requisitos previos

- Cuenta activa de Twilio Voice con ConversationRelay habilitado.[cite:41]
- Acceso a OpenAI Realtime API y clave válida para sesiones WebSocket.[cite:31][cite:32]
- Servidor Python asíncrono, por ejemplo FastAPI o Starlette, capaz de mantener dos WebSockets abiertos por llamada.
- Capacidad para construir el prompt clínico con datos del paciente, agenda y guía DELFOS antes de abrir la sesión.

## Modelos y voces

La documentación y ecosistema alrededor de OpenAI Realtime muestran opciones como `gpt-4o-realtime-preview` y variantes equivalentes para escenarios de audio en tiempo real.[cite:31][cite:32]

En implementaciones de terceros compatibles con OpenAI Realtime se documentan voces como `alloy`, `echo`, `shimmer`, `marin` y `cedar`, con diferencias perceptibles de tono y expresividad; para llamadas humanas en español suele convenir empezar pruebas con una voz cálida y mantener las respuestas cortas.[cite:32]

### Recomendación inicial

| Elemento | Valor sugerido | Motivo |
|---|---|---|
| Modelo | `gpt-4o-realtime-preview` | Punto de partida razonable para pruebas Voice-to-Voice[cite:31][cite:32] |
| Voz | `marin` o `echo` | Suelen percibirse más conversacionales[cite:32] |
| Temperature | `0.5` a `0.7` | Mantiene variedad sin perder control |
| Salida máxima | `150` a `250` tokens | Respuestas cortas en contexto telefónico |
| Detección de turno | `server_vad` | Reduce lógica manual de interrupciones[cite:32] |

## Cambios en el proyecto

La refactorización debe concentrarse en `ws_conversationrelay.py`, `openai_service.py` y `prompt_service.py`. `manual_data.py` y la lógica de negocio sobre clientes, citas y guía DELFOS pueden mantenerse casi intactas, porque el cambio principal está en el transporte de audio y la sesión del modelo.

### 1. `openai_service.py`

Este módulo debe dejar de hacer únicamente consultas de texto y pasar a abrir una sesión Realtime por WebSocket. La sesión debe incluir instrucciones, modalidad de audio, voz, formato de entrada y salida, y parámetros de detección de turno.[cite:31][cite:32]

```python
import os
import json
import websockets

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
REALTIME_URL = "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview"

async def connect_realtime(instructions: str, voice: str = "marin"):
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "OpenAI-Beta": "realtime=v1",
    }

    ws = await websockets.connect(REALTIME_URL, extra_headers=headers)

    session = {
        "type": "session.update",
        "session": {
            "modalities": ["audio", "text"],
            "instructions": instructions,
            "voice": voice,
            "input_audio_format": "g711_ulaw",
            "output_audio_format": "g711_ulaw",
            "turn_detection": {
                "type": "server_vad",
                "threshold": 0.5,
                "silence_duration_ms": 700,
            },
            "temperature": 0.6,
            "max_response_output_tokens": 220,
        },
    }

    await ws.send(json.dumps(session))
    return ws
```

### 2. `ws_conversationrelay.py`

Este módulo debe actuar como puente bidireccional. Todo frame de audio que llegue desde Twilio debe reenviarse a OpenAI, y cada delta de audio que devuelva OpenAI debe enviarse de vuelta a Twilio en tiempo real.[cite:38][cite:41]

```python
import json
import asyncio
from fastapi import WebSocket
from services.openai_service import connect_realtime
from services.prompt_service import build_prompt

async def handle_call(ws_twilio: WebSocket, patient_ctx: dict):
    await ws_twilio.accept()

    instructions = build_prompt(patient_ctx)
    ws_openai = await connect_realtime(instructions, voice="marin")

    async def twilio_to_openai():
        async for message in ws_twilio.iter_text():
            event = json.loads(message)
            if event.get("event") == "media":
                await ws_openai.send(json.dumps({
                    "type": "input_audio_buffer.append",
                    "audio": event["media"]["payload"],
                }))

    async def openai_to_twilio():
        async for raw in ws_openai:
            event = json.loads(raw)
            if event.get("type") == "response.audio.delta":
                await ws_twilio.send_json({
                    "event": "media",
                    "media": {"payload": event["delta"]},
                })

    await asyncio.gather(twilio_to_openai(), openai_to_twilio())
```

### 3. `prompt_service.py`

El prompt debe optimizarse para habla, no para texto escrito. La sesión Realtime responde mejor cuando las instrucciones dejan claro el rol, la identidad institucional, los límites clínicos, el formato oral y el manejo de incertidumbre.[cite:31][cite:32]

```python
def build_prompt(ctx: dict) -> str:
    patient_name = ctx.get("patient_name", "paciente")
    appointment = ctx.get("appointment_text", "sin cita registrada")
    delfos = ctx.get("delfos_guide", "")

    return f"""
Rol:
Eres un asistente telefónico de Biomarcadores para seguimiento en salud.

Objetivo:
Confirmar, orientar y responder preguntas frecuentes del paciente sobre el proceso DELFOS.

Contexto del paciente:
- Nombre: {patient_name}
- Cita: {appointment}

Estilo de habla:
- Habla en español natural y cálido.
- Usa frases cortas.
- Responde en 1 a 3 oraciones por turno.
- Evita listas, markdown, símbolos y texto demasiado técnico.
- Usa pausas naturales y lenguaje conversacional.
- Si no sabe una respuesta, dilo con honestidad y ofrece escalar o verificar.

Identidad:
- Llamas de parte de Biomarcadores y del equipo de campo.
- Debes saludar por el nombre cuando esté disponible.

Base de conocimiento DELFOS:
{delfos}
""".strip()
```

## Cómo mejorar la naturalidad del habla

La mejora del habla no depende solo de la voz; depende también de la longitud de los turnos, la puntuación, la detección de silencios y la consistencia del prompt. En Voice-to-Voice, el modelo puede sonar más natural cuando se le obliga a contestar breve, con pausas claras y sin estructuras de texto formales.[cite:31][cite:32]

### Reglas recomendadas

- Limitar cada turno a una idea principal.
- Evitar respuestas largas con muchas subordinadas.
- Pedir explicitamente frases cortas y tono cálido.
- Convertir fechas y horas a lenguaje hablado, por ejemplo “siete de abril a las diez de la mañana”.
- Evitar abreviaturas clínicas en la salida de voz, salvo que estén normalizadas para el paciente.
- Mantener una sola pregunta por turno para no sonar como IVR rígido.

### Parámetros iniciales sugeridos

| Parámetro | Valor | Ajuste esperado |
|---|---|---|
| `temperature` | 0.6 | Menos monotonía, aún controlable |
| `silence_duration_ms` | 600–800 | Pausas más humanas antes de responder[cite:32] |
| `threshold` | 0.45–0.55 | Mejor detección del final del turno[cite:32] |
| `max_response_output_tokens` | 180–220 | Evita monólogos |
| Estilo del prompt | Conversacional | Reduce respuestas tipo chatbot escrito |

## Estrategia de implementación por fases

### Fase 1. Prototipo aislado

Crear una rama nueva y activar un endpoint experimental de WebSocket para una sola llamada de prueba. En esta fase solo se valida el puente Twilio ↔ OpenAI y la sesión Realtime con un prompt corto.[cite:38][cite:41]

### Fase 2. Integración con contexto clínico

Conectar el prompt actual con nombre del paciente, datos de cita y contenido DELFOS. En esta fase también conviene agregar reglas de seguridad para no inventar información clínica y para reconocer cuándo debe escalar a un humano.

### Fase 3. Optimización de voz

Probar al menos dos voces y tres configuraciones de `temperature` y `silence_duration_ms`. La evaluación debe hacerse con audios reales y una rúbrica simple: naturalidad, claridad, velocidad percibida, empatía y tasa de interrupciones.

### Fase 4. Endurecimiento operativo

Agregar timeouts, manejo de reconexión, logging por evento, métricas por llamada y fallback a la arquitectura anterior si falla la sesión Realtime. Esto reduce riesgo en producción y permite activar el nuevo flujo solo para un porcentaje pequeño de llamadas.

## Checklist técnico

- Endpoint Twilio operativo con ConversationRelay.[cite:41]
- WebSocket servidor aceptando audio bidireccional.
- Sesión Realtime creada con `session.update`.[cite:31][cite:32]
- Formato de audio alineado entre Twilio y OpenAI.
- Prompt corto, oral y con reglas institucionales.
- Manejo de cierre de sesión y errores de red.
- Logs por llamada con trazabilidad por `callSid`.
- Pruebas A/B contra el flujo actual.

## Riesgos y mitigación

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Costo por audio en tiempo real | Medio/alto | Limitar pilotos a llamadas cortas y medir duración promedio |
| Respuestas demasiado largas | Medio | Bajar tokens máximos y reforzar prompt oral |
| Cortes o interrupciones erráticas | Medio | Ajustar `server_vad` y umbral[cite:32] |
| Dependencia de red en tiempo real | Alto | Implementar fallback al flujo textual actual |
| Deriva clínica en respuestas | Alto | Restringir el prompt a DELFOS y respuestas permitidas |

## Métricas para validar mejora

La validación no debe hacerse solo “por percepción”; conviene registrar métricas comparables por llamada. Las más útiles son tiempo hasta primera respuesta, duración promedio del turno del bot, porcentaje de interrupciones exitosas, duración total de llamada, tasa de transferencia a humano y evaluación subjetiva de naturalidad por parte del equipo.

### Rúbrica sugerida

| Métrica | Escala |
|---|---|
| Naturalidad de voz | 1 a 5 |
| Claridad del mensaje | 1 a 5 |
| Empatía percibida | 1 a 5 |
| Fluidez de turnos | 1 a 5 |
| Exactitud sobre DELFOS | 1 a 5 |

## Recomendación final

Sí, es totalmente posible mejorar de forma importante el modelo y el habla. La ruta más efectiva es mantener Twilio para telefonía, migrar la inteligencia conversacional a una sesión Realtime de GPT-4o, acortar el prompt hacia estilo oral y medir la calidad con un piloto controlado antes de mover todo el tráfico.[cite:31][cite:38][cite:41]

Como primer paso práctico, conviene implementar el puente de audio en una rama nueva, hacer 10 a 20 llamadas internas de prueba y ajustar voz, `temperature` y VAD antes de conectar pacientes reales.
