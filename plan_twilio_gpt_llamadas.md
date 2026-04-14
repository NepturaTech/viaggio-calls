# Plan de implementación y validación
## Llamadas naturales con Twilio + ConversationRelay + GPT + Base de Datos

**Fecha:** 2026-04-08  
**Objetivo:** definir una arquitectura viable para hacer pruebas y luego pasar a una implementación productiva de llamadas telefónicas naturales con IA, consultando datos de una base de datos propia.

---

# 1) Validación de la arquitectura propuesta

La estructura propuesta es válida y encaja bien para un MVP y para una primera fase productiva:

```text
Usuario por llamada
    ↓
Twilio Programmable Voice
    ↓
TwiML <Connect><ConversationRelay>
    ↓
WebSocket hacia backend propio
    ↓
FastAPI
    ├── Lógica conversacional
    ├── Consulta a PostgreSQL/MySQL
    ├── Reglas de negocio
    ├── Logs / auditoría
    └── Integración con OpenAI
    ↓
OpenAI Realtime API / Responses API
    ↓
Texto de respuesta
    ↓
ConversationRelay convierte a voz
    ↓
Respuesta al usuario
```

## Conclusión de validación

Sí es una estructura correcta porque separa responsabilidades:

- **Twilio**: telefonía, número, entrada/salida de llamadas.
- **ConversationRelay**: puente de voz en tiempo real entre Twilio y tu aplicación.
- **FastAPI**: orquestación, seguridad, reglas, integraciones y webhooks/WebSocket.
- **PostgreSQL/MySQL**: contexto real del negocio.
- **GPT/OpenAI**: generación de respuestas naturales y razonamiento limitado por reglas.

---

# 2) Para qué sirve cada componente

## 2.1 Twilio Programmable Voice
Se usa para:
- comprar o conectar un número telefónico,
- recibir o hacer llamadas,
- ejecutar el flujo de voz,
- conectar la llamada con `ConversationRelay` usando TwiML.

## 2.2 ConversationRelay
Se usa para:
- mantener una conversación de voz en tiempo real,
- enviar al backend eventos estructurados por WebSocket,
- recibir texto desde el backend para que Twilio lo convierta a voz,
- reducir complejidad frente a montar toda la capa de audio manualmente.

## 2.3 FastAPI
Se usa como backend central para:
- recibir eventos desde Twilio,
- autenticar y validar sesiones,
- consultar tu base de datos,
- construir el prompt/contexto,
- llamar a OpenAI,
- aplicar reglas de negocio,
- decidir cuándo repetir, confirmar, escalar o transferir,
- guardar logs técnicos y de negocio.

## 2.4 PostgreSQL o MySQL
Se usa para:
- identificar al cliente por teléfono, documento o código,
- leer datos reales como citas, órdenes, cartera, estado del caso,
- registrar resultados de llamadas,
- guardar historial resumido y estados.

## 2.5 OpenAI / GPT
Se usa para:
- generar respuestas más naturales,
- interpretar intención,
- resumir respuestas largas,
- hacer follow-up guiado,
- convertir reglas y datos estructurados en diálogo humano.

---

# 3) Flujo operativo recomendado

## 3.1 Llamada entrante

```text
1. Persona llama al número Twilio
2. Twilio ejecuta TwiML
3. Twilio conecta <ConversationRelay>
4. ConversationRelay abre WebSocket con tu backend
5. Backend recibe eventos del usuario
6. Backend identifica al cliente
7. Backend consulta BD
8. Backend arma contexto y llama a GPT
9. Backend devuelve texto
10. ConversationRelay lo reproduce en voz
11. Se guarda el resultado de la interacción
```

## 3.2 Llamada saliente

```text
1. Tu sistema agenda o dispara la llamada
2. Backend solicita a Twilio crear llamada saliente
3. Twilio ejecuta el flujo con ConversationRelay
4. Se identifica al usuario
5. Se consulta la BD
6. GPT responde según el objetivo de la campaña
7. Se registran estado y resultado final
```

---

# 4) MVP recomendado

## Alcance del MVP
Construir una prueba funcional con un caso único y bien controlado.

### Caso sugerido
**Confirmación de cita**

Ejemplo:
- “Hola, hablo del sistema de confirmación de citas.”
- “¿Hablo con Jonathan?”
- “Veo una cita programada para mañana a las 9:30 a. m.”
- “¿Deseas confirmarla, cancelarla o reprogramarla?”

## Por qué empezar por aquí
- flujo simple,
- datos estructurados,
- pocas herramientas,
- fácil medir éxito,
- bajo riesgo conversacional.

---

# 5) Fases de implementación

## Fase 0 — Preparación

### Objetivo
Dejar listas las cuentas, accesos y entorno.

### Tareas
- Crear cuenta de Twilio.
- Comprar o asignar número.
- Configurar credenciales seguras.
- Crear proyecto OpenAI.
- Crear base de datos de pruebas.
- Preparar entorno Python con FastAPI.
- Exponer backend con HTTPS/WSS para pruebas.

### Entregables
- cuenta Twilio operativa,
- credenciales seguras,
- backend base levantado,
- acceso a BD funcional.

## Fase 1 — Conectividad básica

### Objetivo
Lograr una llamada funcional conectada al backend.

### Tareas
- Configurar endpoint TwiML.
- Agregar `Connect` + `ConversationRelay`.
- Abrir WebSocket en FastAPI.
- Confirmar recepción de eventos.
- Responder con texto fijo.

### Criterio de éxito
La llamada entra, el backend recibe eventos y el usuario escucha una respuesta generada desde tu app.

## Fase 2 — Integración con GPT

### Objetivo
Sustituir la respuesta fija por una respuesta generada por IA.

### Tareas
- Definir prompt del agente.
- Enviar mensajes del usuario a OpenAI.
- Recibir respuesta y devolverla a ConversationRelay.
- Limitar estilo, longitud y temas permitidos.

### Criterio de éxito
La llamada ya sostiene una conversación básica con latencia aceptable.

## Fase 3 — Integración con base de datos

### Objetivo
Dar contexto real al agente.

### Tareas
- Buscar cliente por número.
- Consultar cita, pedido o estado.
- Construir contexto estructurado.
- Pasar contexto al modelo.
- Registrar el resultado.

### Criterio de éxito
El agente responde con datos reales del negocio y no con respuestas genéricas.

## Fase 4 — Reglas de negocio

### Objetivo
Controlar la conversación para hacerla segura y útil.

### Tareas
- Definir intents permitidos.
- Limitar acciones disponibles.
- Validar identidad si hace falta.
- Agregar fallback.
- Transferir a humano en casos dudosos.
- Cortar respuestas largas o ambiguas.

### Criterio de éxito
La conversación se mantiene dentro del flujo esperado y no improvisa fuera de alcance.

## Fase 5 — Observabilidad y endurecimiento

### Objetivo
Pasar de demo a piloto real.

### Tareas
- Guardar logs de eventos.
- Medir latencia por turno.
- Medir duración de llamada.
- Registrar tasa de éxito.
- Auditar errores.
- Agregar retry y timeouts.
- Revisar costos.

### Criterio de éxito
El sistema es medible, repetible y se puede pilotear con usuarios reales.

---

# 6) Estructura técnica sugerida

## 6.1 Backend

### Stack sugerido
- Python 3.11+
- FastAPI
- Uvicorn
- SQLAlchemy
- psycopg o mysqlclient / async drivers
- pydantic
- websockets

## 6.2 Estructura de carpetas sugerida

```text
app/
  main.py
  config.py
  routes/
    health.py
    twilio_webhook.py
    ws_conversationrelay.py
  services/
    openai_service.py
    twilio_service.py
    customer_service.py
    prompt_service.py
    call_log_service.py
  db/
    session.py
    models.py
    repositories.py
  schemas/
    twilio.py
    customer.py
    call_result.py
  utils/
    security.py
    logging.py
    normalization.py
```

---

# 7) Diseño de base de datos mínimo

## Tabla `customers`
- id
- phone_number
- full_name
- document_number
- status
- preferred_language

## Tabla `appointments`
- id
- customer_id
- appointment_date
- appointment_type
- status
- location

## Tabla `calls`
- id
- customer_id
- twilio_call_sid
- direction
- started_at
- ended_at
- final_status
- transcript_summary
- action_taken

## Tabla `call_events`
- id
- call_id
- event_type
- payload_json
- created_at

---

# 8) Prompt base recomendado para el agente

## Rol
Eres un asistente telefónico automatizado.

## Reglas
- Habla de forma clara y breve.
- No inventes datos.
- Usa solo la información entregada por el sistema.
- Si falta información, dilo.
- Si el usuario se sale del flujo, redirígelo.
- Si hay duda, ofrece transferencia a un humano.
- No prometas acciones no confirmadas.
- Pide confirmación antes de ejecutar cambios.

## Estilo
- Frases cortas.
- Tono cordial y profesional.
- Una pregunta a la vez.
- Confirmar datos sensibles antes de continuar.

---

# 9) Riesgos y controles

## Riesgo: latencia alta
**Control:** respuestas cortas, contexto resumido, timeouts, fallback a texto fijo.

## Riesgo: respuestas inventadas
**Control:** prompt estricto, datos estructurados, acciones vía backend y no por texto libre.

## Riesgo: errores de identificación
**Control:** validación por dos datos si la operación es sensible.

## Riesgo: llamadas fuera de horario o sin consentimiento
**Control:** reglas de negocio, listas permitidas, ventanas horarias y auditoría.

## Riesgo: conversaciones demasiado abiertas
**Control:** limitar el alcance del agente al caso de uso definido.

---

# 10) Recomendación de modelo para pruebas

## Opción principal
**OpenAI Realtime API** si quieres experimentar con voz en tiempo real y latencia baja.

## Opción práctica para MVP controlado
Si la implementación inicial usa ConversationRelay para la parte de voz y tú orquestas desde backend, puedes empezar con OpenAI como motor de respuesta del agente y luego refinar el modo de conexión según el nivel de tiempo real que necesites.

## Recomendación operativa
Para un primer piloto:
- Twilio Voice
- ConversationRelay
- FastAPI
- PostgreSQL
- OpenAI
- un solo caso de uso

---

# 11) Criterios de aceptación del MVP

El MVP se considera válido si cumple esto:

- la llamada entra o sale correctamente,
- el usuario escucha voz natural,
- el backend recibe eventos,
- el backend consulta la BD,
- GPT responde usando datos reales,
- el agente logra una tarea concreta,
- se guarda resultado y trazabilidad,
- existe fallback o escalamiento.

---

# 12) Próximos pasos recomendados

## Paso 1
Levantar backend FastAPI con:
- endpoint health,
- endpoint TwiML,
- WebSocket para ConversationRelay.

## Paso 2
Crear prueba con respuesta fija.

## Paso 3
Integrar OpenAI.

## Paso 4
Integrar una consulta simple a PostgreSQL.

## Paso 5
Cerrar el primer flujo: confirmación de cita o consulta de estado.

## Paso 6
Agregar métricas, logging y transferencia a humano.

---

# 13) Validación final

## Estructura aprobada para iniciar
Sí, la estructura:

**Twilio + ConversationRelay + FastAPI + PostgreSQL/MySQL + OpenAI**

es una arquitectura correcta, moderna y razonable para:
- hacer pruebas rápidas,
- validar UX conversacional,
- conectar datos reales,
- y evolucionar a piloto productivo.

## Qué no haría al inicio
- no abriría demasiados casos de uso,
- no intentaría un agente completamente libre,
- no metería integraciones complejas adicionales en la primera fase,
- no haría llamadas masivas sin antes medir latencia, costo y calidad.

---

# 14) Fuentes de validación técnica

- Twilio ConversationRelay Overview
- Twilio TwiML `<ConversationRelay>`
- Twilio WebSocket messages for ConversationRelay
- OpenAI Realtime API Reference

