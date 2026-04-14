"""
Script para poblar Supabase con datos de prueba desde Python.
Alternativa al SQL — usa el cliente de Supabase.

Ejecutar: python seed_data.py

NOTA: Es más sencillo ejecutar supabase_schema.sql directo en el
      SQL Editor de Supabase. Este script es una alternativa por código.
"""
from datetime import datetime, timedelta
from app.db.session import get_supabase


def seed():
    sb = get_supabase()

    # Check if data already exists
    existing = sb.table("customers").select("id").limit(1).execute()
    if existing.data:
        print(f"Database already has customers. Skipping seed.")
        return

    # --- Customers ---
    customers = sb.table("customers").insert([
        {
            "phone_number": "+573001234567",
            "full_name": "Jonathan Pérez",
            "document_number": "1234567890",
            "status": "active",
            "preferred_language": "es",
        },
        {
            "phone_number": "+573009876543",
            "full_name": "María García",
            "document_number": "0987654321",
            "status": "active",
            "preferred_language": "es",
        },
        {
            "phone_number": "+573005551234",
            "full_name": "Carlos López",
            "document_number": "5555555555",
            "status": "active",
            "preferred_language": "es",
        },
    ]).execute()

    print(f"  Created {len(customers.data)} customers")

    # --- Appointments ---
    tomorrow = datetime.utcnow() + timedelta(days=1)
    next_week = datetime.utcnow() + timedelta(days=7)

    appointments = sb.table("appointments").insert([
        {
            "customer_id": customers.data[0]["id"],
            "appointment_date": tomorrow.replace(hour=9, minute=30).isoformat(),
            "appointment_type": "Consulta general",
            "status": "scheduled",
            "location": "Consultorio 301, Edificio Médico Central",
        },
        {
            "customer_id": customers.data[0]["id"],
            "appointment_date": next_week.replace(hour=14, minute=0).isoformat(),
            "appointment_type": "Control de laboratorio",
            "status": "scheduled",
            "location": "Laboratorio Clínico, Piso 2",
        },
        {
            "customer_id": customers.data[1]["id"],
            "appointment_date": tomorrow.replace(hour=11, minute=0).isoformat(),
            "appointment_type": "Odontología",
            "status": "scheduled",
            "location": "Consultorio 105, Clínica Dental",
        },
        {
            "customer_id": customers.data[2]["id"],
            "appointment_date": next_week.replace(hour=8, minute=0).isoformat(),
            "appointment_type": "Cardiología",
            "status": "scheduled",
            "location": "Consultorio 402, Torre Médica Norte",
        },
    ]).execute()

    print(f"  Created {len(appointments.data)} appointments")

    # --- Call Scripts ---
    scripts = sb.table("call_scripts").insert([
        {
            "name": "default",
            "description": "Script principal para confirmación de citas médicas",
            "welcome_greeting": "Hola, buenas tardes. Le habla el asistente virtual del centro médico. ¿Tengo el gusto de hablar con el paciente titular de esta línea?",
            "system_prompt": """Eres un asistente telefónico automatizado para confirmación de citas médicas.

## Reglas
- Habla de forma clara y breve.
- No inventes datos. Usa solo la información entregada por el sistema.
- Si falta información, dilo.
- Si el usuario se sale del flujo, redirígelo amablemente.
- Si hay duda, ofrece transferencia a un humano.
- No prometas acciones no confirmadas.
- Pide confirmación antes de ejecutar cambios.

## Estilo
- Frases cortas. Tono cordial y profesional. Una pregunta a la vez.

## Flujo
1. Saluda e identifícate como asistente del centro médico.
2. Confirma la identidad del paciente.
3. Informa sobre la cita programada.
4. Pregunta si desea confirmar, cancelar o reprogramar.
5. Ejecuta la acción y despídete.""",
            "active": True,
        },
        {
            "name": "cobranza_amigable",
            "description": "Script para recordatorio de pagos pendientes",
            "welcome_greeting": "Buenas tardes, le habla el asistente de gestión de pagos. ¿Me comunico con el titular de esta línea?",
            "system_prompt": """Eres un asistente telefónico de gestión de pagos. Tu tono es amigable y comprensivo.

## Reglas
- Nunca amenaces ni presiones.
- Ofrece opciones de pago y plazos.
- Si el usuario no puede pagar, ofrece transferencia a un asesor.
- No reveles montos exactos hasta confirmar identidad.

## Flujo
1. Saluda e identifícate.
2. Confirma identidad del titular.
3. Informa sobre saldo pendiente.
4. Ofrece opciones de pago.
5. Si no puede pagar, transfiere a asesor.
6. Despídete cordialmente.""",
            "active": False,
        },
    ]).execute()

    print(f"  Created {len(scripts.data)} call scripts")
    print("\nSeed completed!")


if __name__ == "__main__":
    seed()
