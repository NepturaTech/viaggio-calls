"""
Repositories — Modo manual.
Leen de manual_data.py en lugar de Supabase.
Los logs de llamadas se guardan en memoria.

Cuando pases a Supabase, reemplaza estos por los que usan el cliente sb.
"""
import json
import logging
from datetime import datetime

from app.manual_data import CUSTOMERS, APPOINTMENTS, CALL_SCRIPT, CALL_SCRIPTS

logger = logging.getLogger(__name__)

# Almacenamiento en memoria para logs de llamadas (se pierde al reiniciar)
_calls: list[dict] = []
_call_events: list[dict] = []
_next_call_id = 1
_next_event_id = 1

# Caché de corta duración para pasar el contexto de paciente (construido desde
# query params en /voice) al WebSocket handler, que no tiene acceso a la request.
# Clave: call_sid  |  Valor: dict con full_name, phone_number, document_number, etc.
_pending_call_params: dict[str, dict] = {}


def store_pending_call_params(call_sid: str, customer: dict) -> None:
    """Guarda el contexto de paciente construido desde params para que lo use el WS."""
    _pending_call_params[call_sid] = customer


def pop_pending_call_params(call_sid: str) -> dict | None:
    """Recupera y elimina el contexto de paciente guardado para este call_sid."""
    return _pending_call_params.pop(call_sid, None)


# Registro permanente call_sid → {patient_name, patient_id, script_name}.
# Se pobla desde /voice y /outbound cuando ya se conoce el paciente.
# store_twilio_recording lo usa para asignar la carpeta correcta aunque el
# WebSocket se haya cerrado antes de crear el CallAudioArchive.
_call_patient_registry: dict[str, dict] = {}


def register_call_patient(
    call_sid: str,
    patient_name: str | None,
    patient_id: str | None,
    script_name: str | None = None,
    patient_phone: str | None = None,
    manychat_user_id: str | None = None,
) -> None:
    """Registra datos del paciente asociados a un call_sid."""
    _call_patient_registry[call_sid] = {
        "patient_name": patient_name or "",
        "patient_id": patient_id or "",
        "script_name": script_name or "default",
        "patient_phone": patient_phone or "",
        "manychat_user_id": manychat_user_id or "",
    }


def get_call_patient(call_sid: str) -> dict | None:
    """Devuelve los datos del paciente registrados para este call_sid, o None."""
    return _call_patient_registry.get(call_sid)


def mark_human_turn(call_sid: str) -> None:
    """Marca que el humano ya habló en esta llamada (primer turno real del usuario).

    Usado por el AMD handler para distinguir buzón de voz de llamada humana real.
    """
    entry = _call_patient_registry.get(call_sid)
    if entry is not None:
        entry["human_spoke"] = True


def human_has_spoken(call_sid: str) -> bool:
    """Retorna True si el humano ya tuvo al menos un turno de voz en esta llamada."""
    entry = _call_patient_registry.get(call_sid)
    return bool(entry and entry.get("human_spoke"))


class CustomerRepository:
    def find_by_phone(self, phone_number: str) -> dict | None:
        normalized = phone_number.strip().replace(" ", "")
        for c in CUSTOMERS:
            if c["phone_number"] == normalized:
                return c
        return None

    def find_by_id(self, customer_id: int) -> dict | None:
        for c in CUSTOMERS:
            if c["id"] == customer_id:
                return c
        return None


class AppointmentRepository:
    def find_upcoming_by_customer(self, customer_id: int) -> list[dict]:
        now = datetime.utcnow().isoformat()
        return [
            a for a in APPOINTMENTS
            if a["customer_id"] == customer_id
            and a["appointment_date"] >= now
            and a["status"] in ("scheduled", "confirmed")
        ]

    def update_status(self, appointment_id: int, status: str) -> dict | None:
        for a in APPOINTMENTS:
            if a["id"] == appointment_id:
                a["status"] = status
                return a
        return None


class CallRepository:
    def create(self, **kwargs) -> dict:
        global _next_call_id
        twilio_call_sid = kwargs.get("twilio_call_sid")
        if twilio_call_sid:
            existing = self.find_by_sid(twilio_call_sid)
            if existing:
                return existing

        call = {
            "id": _next_call_id,
            "started_at": datetime.utcnow().isoformat(),
            "ended_at": None,
            "final_status": None,
            "transcript_summary": None,
            "transcript_lines": [],
            "action_taken": None,
            **kwargs,
        }
        _calls.append(call)
        logger.info("Call record created (in-memory): id=%d, sid=%s", call["id"], kwargs.get("twilio_call_sid"))
        _next_call_id += 1
        return call

    def find_by_sid(self, twilio_call_sid: str) -> dict | None:
        for c in _calls:
            if c.get("twilio_call_sid") == twilio_call_sid:
                return c
        return None

    def list_all(self) -> list[dict]:
        return list(_calls)

    def append_transcript_line(self, call_id: int, role: str, text: str) -> dict | None:
        for c in _calls:
            if c["id"] == call_id:
                c.setdefault("transcript_lines", []).append({
                    "role": role,
                    "text": text,
                    "created_at": datetime.utcnow().isoformat(),
                })
                return c
        return None

    def update_end(self, call_id: int, final_status: str, summary: str = None, action: str = None) -> dict | None:
        for c in _calls:
            if c["id"] == call_id:
                c["ended_at"] = datetime.utcnow().isoformat()
                c["final_status"] = final_status
                if summary:
                    c["transcript_summary"] = summary
                if action:
                    c["action_taken"] = action
                return c
        return None


class CallEventRepository:
    def create(self, call_id: int, event_type: str, payload: dict | None = None) -> dict:
        global _next_event_id
        event = {
            "id": _next_event_id,
            "call_id": call_id,
            "event_type": event_type,
            "payload_json": json.dumps(payload) if payload else None,
            "created_at": datetime.utcnow().isoformat(),
        }
        _call_events.append(event)
        _next_event_id += 1
        return event

    def list_by_call_id(self, call_id: int) -> list[dict]:
        return [event for event in _call_events if event["call_id"] == call_id]


class CallScriptRepository:
    def get_active_script(self, name: str = "default") -> dict | None:
        normalized = (name or "default").strip().lower()

        # Si se pide un script por nombre específico, devolverlo aunque active=False.
        # El flag active solo se usa para seleccionar el script por defecto cuando
        # no se pide ninguno en particular.
        if normalized and normalized != "default":
            script = CALL_SCRIPTS.get(normalized)
            if script:
                return script

        # Sin nombre específico: buscar el activo
        for script in CALL_SCRIPTS.values():
            if script.get("active"):
                return script

        # Fallback final al CALL_SCRIPT principal
        if CALL_SCRIPT.get("active"):
            return CALL_SCRIPT
        return None

    def list_scripts(self) -> list[dict]:
        return list(CALL_SCRIPTS.values())
