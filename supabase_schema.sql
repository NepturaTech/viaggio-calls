-- ============================================
-- Schema para el sistema de llamadas con IA
-- Ejecutar en Supabase SQL Editor
-- ============================================

-- 1) Clientes
CREATE TABLE IF NOT EXISTS customers (
    id BIGSERIAL PRIMARY KEY,
    phone_number VARCHAR(20) UNIQUE NOT NULL,
    full_name VARCHAR(200) NOT NULL,
    document_number VARCHAR(50) UNIQUE,
    status VARCHAR(20) DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'blocked')),
    preferred_language VARCHAR(10) DEFAULT 'es',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers(phone_number);

-- 2) Citas
CREATE TABLE IF NOT EXISTS appointments (
    id BIGSERIAL PRIMARY KEY,
    customer_id BIGINT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    appointment_date TIMESTAMPTZ NOT NULL,
    appointment_type VARCHAR(100) NOT NULL,
    status VARCHAR(20) DEFAULT 'scheduled' CHECK (status IN ('scheduled', 'confirmed', 'cancelled', 'completed', 'rescheduled')),
    location VARCHAR(300),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_appointments_customer ON appointments(customer_id);
CREATE INDEX IF NOT EXISTS idx_appointments_date ON appointments(appointment_date);

-- 3) Llamadas
CREATE TABLE IF NOT EXISTS calls (
    id BIGSERIAL PRIMARY KEY,
    customer_id BIGINT REFERENCES customers(id),
    twilio_call_sid VARCHAR(100) UNIQUE NOT NULL,
    direction VARCHAR(10) NOT NULL CHECK (direction IN ('inbound', 'outbound')),
    started_at TIMESTAMPTZ DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    final_status VARCHAR(20) CHECK (final_status IN ('completed', 'failed', 'no_answer', 'transferred')),
    transcript_summary TEXT,
    action_taken VARCHAR(200),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_calls_sid ON calls(twilio_call_sid);
CREATE INDEX IF NOT EXISTS idx_calls_customer ON calls(customer_id);

-- 4) Eventos de llamada
CREATE TABLE IF NOT EXISTS call_events (
    id BIGSERIAL PRIMARY KEY,
    call_id BIGINT NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    event_type VARCHAR(50) NOT NULL,
    payload_json TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_call_events_call ON call_events(call_id);

-- 5) Scripts de llamada (lo que dice y cómo se comporta el modelo)
CREATE TABLE IF NOT EXISTS call_scripts (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    description TEXT DEFAULT '',
    welcome_greeting TEXT NOT NULL,
    system_prompt TEXT NOT NULL,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- Datos de prueba
-- ============================================

-- Clientes de ejemplo
INSERT INTO customers (phone_number, full_name, document_number, status, preferred_language) VALUES
    ('+573001234567', 'Jonathan Pérez', '1234567890', 'active', 'es'),
    ('+573009876543', 'María García', '0987654321', 'active', 'es'),
    ('+573005551234', 'Carlos López', '5555555555', 'active', 'es')
ON CONFLICT (phone_number) DO NOTHING;

-- Citas de ejemplo (mañana y próxima semana)
INSERT INTO appointments (customer_id, appointment_date, appointment_type, status, location) VALUES
    (1, NOW() + INTERVAL '1 day' + TIME '09:30', 'Consulta general', 'scheduled', 'Consultorio 301, Edificio Médico Central'),
    (1, NOW() + INTERVAL '7 days' + TIME '14:00', 'Control de laboratorio', 'scheduled', 'Laboratorio Clínico, Piso 2'),
    (2, NOW() + INTERVAL '1 day' + TIME '11:00', 'Odontología', 'scheduled', 'Consultorio 105, Clínica Dental'),
    (3, NOW() + INTERVAL '7 days' + TIME '08:00', 'Cardiología', 'scheduled', 'Consultorio 402, Torre Médica Norte')
ON CONFLICT DO NOTHING;

-- Script por defecto para confirmación de citas
INSERT INTO call_scripts (name, description, welcome_greeting, system_prompt, active) VALUES
(
    'default',
    'Script principal para confirmación de citas médicas',
    'Hola, buenas tardes. Le habla el asistente virtual del centro médico. ¿Tengo el gusto de hablar con el paciente titular de esta línea?',
    'Eres un asistente telefónico automatizado para confirmación de citas médicas.

## Reglas
- Habla de forma clara y breve.
- No inventes datos. Usa solo la información entregada por el sistema.
- Si falta información, dilo.
- Si el usuario se sale del flujo, redirígelo amablemente.
- Si hay duda, ofrece transferencia a un humano.
- No prometas acciones no confirmadas.
- Pide confirmación antes de ejecutar cambios.

## Estilo
- Frases cortas.
- Tono cordial y profesional.
- Una pregunta a la vez.
- Confirmar datos sensibles antes de continuar.

## Flujo
1. Saluda e identifícate como asistente del centro médico.
2. Confirma la identidad del paciente.
3. Informa sobre la cita programada (fecha, hora, tipo, lugar).
4. Pregunta si desea confirmar, cancelar o reprogramar.
5. Si confirma, agradece y despídete.
6. Si cancela, confirma la cancelación y despídete.
7. Si quiere reprogramar, indica que lo transferirás a un agente.
8. Despídete cordialmente.',
    TRUE
)
ON CONFLICT (name) DO NOTHING;

-- Script alternativo de ejemplo: cobranza amigable
INSERT INTO call_scripts (name, description, welcome_greeting, system_prompt, active) VALUES
(
    'cobranza_amigable',
    'Script para recordatorio de pagos pendientes — tono amigable',
    'Buenas tardes, le habla el asistente de gestión de pagos. ¿Me comunico con el titular de esta línea?',
    'Eres un asistente telefónico de gestión de pagos. Tu tono es amigable y comprensivo.

## Reglas
- Nunca amenaces ni presiones.
- Ofrece opciones de pago y plazos.
- Si el usuario no puede pagar, ofrece transferencia a un asesor.
- No reveles montos exactos hasta confirmar identidad.
- Sé empático con la situación del usuario.

## Flujo
1. Saluda e identifícate.
2. Confirma identidad del titular.
3. Informa que hay un saldo pendiente.
4. Pregunta si desea conocer las opciones de pago.
5. Si acepta, informa las opciones disponibles.
6. Si no puede pagar, ofrece hablar con un asesor humano.
7. Despídete cordialmente.',
    FALSE
)
ON CONFLICT (name) DO NOTHING;
