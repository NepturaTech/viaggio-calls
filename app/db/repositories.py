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
        if normalized == "default":
            normalized = "seguimiento"

        script = CALL_SCRIPTS.get(normalized)
        if script and script.get("active"):
            return script

        if CALL_SCRIPT.get("active"):
            return CALL_SCRIPT
        return None

    def list_scripts(self) -> list[dict]:
        return list(CALL_SCRIPTS.values())
