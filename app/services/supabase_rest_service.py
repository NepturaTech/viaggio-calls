import logging
from functools import lru_cache
from typing import Any

import httpx

from app.config import get_settings
from app.db.repositories import CallScriptRepository
from app.manual_data import CALL_SCRIPT
from app.services.patient_csv_service import (
    find_patient_by_phone,
    infer_hospital_name,
    list_patients,
    normalize_phone,
)

logger = logging.getLogger(__name__)


def _settings():
    return get_settings()


def _source_config(source: str) -> dict[str, str]:
    settings = _settings()
    mapping = {
        "lovable": {
            "url": settings.lovable_cloud_url.rstrip("/"),
            "key": getattr(settings, "lovable_cloud_service_role_key", "") or settings.lovable_cloud_anon_key,
        },
        "viaggio": {
            "url": settings.external_viaggio_url.rstrip("/"),
            "key": getattr(settings, "external_viaggio_service_role_key", "") or settings.external_viaggio_anon_key,
        },
        "huella": {
            "url": settings.huella_supabase_url.rstrip("/"),
            "key": getattr(settings, "huella_supabase_service_role_key", "") or settings.huella_supabase_anon_key,
        },
    }
    return mapping[source]


def _source_enabled(source: str) -> bool:
    config = _source_config(source)
    return bool(config["url"] and config["key"])


def is_lovable_enabled() -> bool:
    return _source_enabled("lovable")


def is_external_viaggio_enabled() -> bool:
    return _source_enabled("viaggio")


def is_huella_enabled() -> bool:
    return _source_enabled("huella")


def _headers(source: str) -> dict[str, str]:
    config = _source_config(source)
    key = config["key"]
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }


def _request_rows(source: str, table: str, params: dict[str, str] | None = None) -> list[dict]:
    config = _source_config(source)
    if not config["url"] or not config["key"]:
        return []

    endpoint = f"{config['url']}/rest/v1/{table}"
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(endpoint, headers=_headers(source), params=params or {})
            response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else []
    except Exception as exc:
        logger.warning("Supabase %s request failed for table %s: %s", source, table, exc)
        return []


def _preview_row(row: dict | None) -> dict[str, Any]:
    if not row:
        return {}
    return {
        "id": row.get("id"),
        "nombre": row.get("nombre") or row.get("full_name") or row.get("name"),
        "telefono": row.get("numero") or row.get("telefono") or row.get("phone_number"),
        "municipio": row.get("municipio") or row.get("municipality") or row.get("city"),
        "hospital": row.get("hospital_name") or row.get("hospital"),
        "active": row.get("active"),
        "project_name": row.get("project_name") or row.get("name"),
    }


def _phone_candidates(phone_number: str) -> list[str]:
    normalized = normalize_phone(phone_number)
    digits = "".join(ch for ch in normalized if ch.isdigit())
    candidates: list[str] = []
    for value in [
        normalized,
        digits,
        f"+{digits}" if digits else "",
        digits[2:] if digits.startswith("57") else "",
    ]:
        if value and value not in candidates:
            candidates.append(value)
    return candidates


def _pick_first_row(source: str, table: str, extra_params: dict[str, str] | None = None) -> dict:
    params = {"select": "*", "limit": "1"}
    if extra_params:
        params.update(extra_params)
    rows = _request_rows(source, table, params)
    return rows[0] if rows else {}


@lru_cache(maxsize=32)
def _get_lovable_hospital_name(hospital_id: str) -> str | None:
    settings = _settings()
    if not is_lovable_enabled() or not hospital_id:
        return None
    rows = _request_rows(
        "lovable",
        settings.lovable_call_hospitals_table,
        {"select": "id,name,hospital_name", "id": f"eq.{hospital_id}", "limit": "1"},
    )
    if not rows:
        return None
    return rows[0].get("name") or rows[0].get("hospital_name")


def get_call_settings() -> dict:
    settings = _settings()
    if is_lovable_enabled():
        row = _pick_first_row("lovable", settings.lovable_call_settings_table)
        if row:
            logger.info(
                "Loaded call settings from Supabase lovable.%s: %s",
                settings.lovable_call_settings_table,
                _preview_row(row),
            )
            return row
    logger.info("Call settings fallback in use: manual/default")
    return {}


def get_project_settings() -> dict:
    row = get_call_settings()
    if row:
        return {
            "project_name": row.get("project_name") or row.get("name") or CALL_SCRIPT.get("project_name", ""),
            "project_context": row.get("project_context") or row.get("description") or CALL_SCRIPT.get("project_context", ""),
            "knowledge_base_file": row.get("knowledge_base_file") or CALL_SCRIPT.get("knowledge_base_file", ""),
        }
    return {
        "project_name": CALL_SCRIPT.get("project_name", ""),
        "project_context": CALL_SCRIPT.get("project_context", ""),
        "knowledge_base_file": CALL_SCRIPT.get("knowledge_base_file", ""),
    }


def get_voice_settings() -> dict:
    settings = _settings()
    if is_lovable_enabled():
        row = _pick_first_row("lovable", settings.lovable_call_settings_table)
        if row:
            return row
    return {}


def get_call_rules() -> dict:
    settings = _settings()
    if is_lovable_enabled():
        row = _pick_first_row("lovable", settings.lovable_call_settings_table)
        if row:
            return row
    return {}


def _enrich_patient(patient: dict | None) -> dict | None:
    if not patient:
        return None

    enriched = dict(patient)

    full_name = enriched.get("full_name") or enriched.get("nombre")
    phone_number = enriched.get("phone_number") or enriched.get("telefono") or enriched.get("numero")
    document_number = enriched.get("document_number") or enriched.get("identificacion")
    municipality = enriched.get("municipality") or enriched.get("municipio") or enriched.get("city")

    if full_name:
        enriched["full_name"] = full_name
    if phone_number:
        enriched["phone_number"] = normalize_phone(phone_number)
    if document_number:
        enriched["document_number"] = document_number
    if municipality:
        enriched["municipality"] = municipality

    if not enriched.get("hospital_name"):
        hospital_id = enriched.get("hospital_id")
        if hospital_id:
            enriched["hospital_name"] = _get_lovable_hospital_name(str(hospital_id))
        else:
            enriched["hospital_name"] = enriched.get("hospital") or infer_hospital_name(municipality or "")

    project_settings = get_project_settings()
    if project_settings and not enriched.get("project_name"):
        enriched["project_name"] = project_settings.get("project_name")

    enriched.setdefault("source", "supabase")
    return enriched


def list_backend_patients() -> list[dict]:
    settings = _settings()
    if is_external_viaggio_enabled():
        rows = _request_rows(
            "viaggio",
            settings.external_viaggio_pacientes_table,
            {"select": "*", "order": "nombre.asc"},
        )
        return [_enrich_patient(row) for row in rows]
    if is_lovable_enabled():
        rows = _request_rows(
            "lovable",
            settings.lovable_call_patients_table,
            {"select": "*", "order": "nombre.asc"},
        )
        return [_enrich_patient(row) for row in rows]
    return list_patients()


def find_backend_patient_by_phone(phone_number: str) -> dict | None:
    normalized = normalize_phone(phone_number)
    settings = _settings()
    candidates = _phone_candidates(phone_number)
    logger.info(
        "Looking up patient by phone: input=%s normalized=%s candidates=%s",
        phone_number,
        normalized,
        candidates,
    )

    if is_external_viaggio_enabled():
        phone_fields = [
            field.strip()
            for field in settings.external_viaggio_patient_phone_fields.split(",")
            if field.strip()
        ] or ["numero"]
        for field in phone_fields:
            for candidate in candidates:
                logger.info(
                    "Trying patient lookup in Supabase viaggio.%s using field=%s value=%s",
                    settings.external_viaggio_pacientes_table,
                    field,
                    candidate,
                )
                rows = _request_rows(
                    "viaggio",
                    settings.external_viaggio_pacientes_table,
                    {"select": "*", field: f"eq.{candidate}", "limit": "1"},
                )
                if rows:
                    logger.info(
                        "Patient found in Supabase viaggio.%s: %s",
                        settings.external_viaggio_pacientes_table,
                        _preview_row(rows[0]),
                    )
                    return _enrich_patient(rows[0])

    if is_lovable_enabled():
        phone_fields = [
            field.strip()
            for field in settings.lovable_call_patients_phone_fields.split(",")
            if field.strip()
        ] or ["phone_number"]
        for field in phone_fields:
            for candidate in candidates:
                logger.info(
                    "Trying patient lookup in Supabase lovable.%s using field=%s value=%s",
                    settings.lovable_call_patients_table,
                    field,
                    candidate,
                )
                rows = _request_rows(
                    "lovable",
                    settings.lovable_call_patients_table,
                    {"select": "*", field: f"eq.{candidate}", "limit": "1"},
                )
                if rows:
                    logger.info(
                        "Patient found in Supabase lovable.%s: %s",
                        settings.lovable_call_patients_table,
                        _preview_row(rows[0]),
                    )
                    return _enrich_patient(rows[0])

    logger.info("No patient match found in Supabase sources for phone=%s", normalized)
    return find_patient_by_phone(normalized)


def list_backend_appointments(patient: dict | None, fallback_customer_id: int | None = None) -> list[dict]:
    if not patient:
        return []

    settings = _settings()
    if is_lovable_enabled():
        patient_id = patient.get("id") or patient.get("patient_id")
        document_number = patient.get("document_number")

        if patient_id is not None:
            rows = _request_rows(
                "lovable",
                settings.lovable_call_appointments_table,
                {"select": "*", "patient_id": f"eq.{patient_id}", "order": "appointment_date.asc"},
            )
            if rows:
                return rows

        if document_number:
            rows = _request_rows(
                "lovable",
                settings.lovable_call_appointments_table,
                {"select": "*", "document_number": f"eq.{document_number}", "order": "appointment_date.asc"},
            )
            if rows:
                return rows

    if fallback_customer_id is None:
        return []

    from app.db.repositories import AppointmentRepository

    return AppointmentRepository().find_upcoming_by_customer(fallback_customer_id)


def get_active_call_script(script_name: str | None = None) -> dict:
    settings = _settings()
    normalized_name = (script_name or "").strip()
    if is_lovable_enabled():
        query_options = []
        if normalized_name and normalized_name != "default":
            query_options.append({"select": "*", "name": f"eq.{normalized_name}", "limit": "1"})
        query_options.append({"select": "*", "active": "eq.true", "limit": "1"})
        for params in query_options:
            rows = _request_rows("lovable", settings.lovable_call_scripts_table, params)
            if rows:
                script = dict(rows[0])
                project_settings = get_project_settings()
                if project_settings:
                    script.setdefault("project_name", project_settings.get("project_name"))
                    script.setdefault("project_context", project_settings.get("project_context"))
                    script.setdefault("knowledge_base_file", project_settings.get("knowledge_base_file"))
                logger.info(
                    "Loaded active call script from Supabase lovable.%s: %s",
                    settings.lovable_call_scripts_table,
                    {
                        "name": script.get("name"),
                        "active": script.get("active"),
                        "project_name": script.get("project_name"),
                        "welcome_greeting": (script.get("welcome_greeting") or "")[:180],
                    },
                )
                return script

    script = CallScriptRepository().get_active_script(normalized_name or "default") or CALL_SCRIPT
    logger.info(
        "Loaded active call script from local fallback: %s",
        {
            "name": script.get("name"),
            "active": script.get("active"),
            "project_name": script.get("project_name"),
            "welcome_greeting": (script.get("welcome_greeting") or "")[:180],
        },
    )
    return script


def get_data_sources_contract() -> dict[str, Any]:
    settings = _settings()
    return {
        "primary": {
            "name": "lovable_cloud",
            "enabled": is_lovable_enabled(),
            "purpose": "Base principal del proyecto y del modulo de llamadas",
            "tables": {
                "whitelist": settings.lovable_whitelist_table,
                "user_roles": settings.lovable_user_roles_table,
                "call_patients": settings.lovable_call_patients_table,
                "call_logs": settings.lovable_call_logs_table,
                "call_artifacts": settings.lovable_call_artifacts_table,
                "call_appointments": settings.lovable_call_appointments_table,
                "call_hospitals": settings.lovable_call_hospitals_table,
                "call_scripts": settings.lovable_call_scripts_table,
                "call_settings": settings.lovable_call_settings_table,
                "visitas_campo": settings.lovable_visitas_campo_table,
            },
        },
        "external_viaggio": {
            "enabled": is_external_viaggio_enabled(),
            "purpose": "Datos clinicos y de seguimiento replicados de Viaggio",
            "tables": {
                "pacientes": settings.external_viaggio_pacientes_table,
                "patient_phone_fields": settings.external_viaggio_patient_phone_fields,
                "food_entries": settings.external_viaggio_food_entries_table,
                "conversaciones": settings.external_viaggio_conversaciones_table,
                "meal_patterns": settings.external_viaggio_meal_patterns_table,
                "evalml": settings.external_viaggio_evalml_table,
                "data_step": settings.external_viaggio_data_step_table,
            },
        },
        "huella_delfos": {
            "enabled": is_huella_enabled(),
            "purpose": "Datos de huella, entrevistados y visitadores",
            "tables": {
                "interviewees": settings.huella_interviewees_table,
                "sessions": settings.huella_sessions_table,
                "visitors": settings.huella_visitors_table,
            },
        },
    }


def get_backend_contract() -> dict[str, Any]:
    settings = _settings()
    return {
        "data_source_mode": settings.data_source_mode,
        "public_base_url": settings.base_url,
        "supports_cloudflared": True,
        "sources": get_data_sources_contract(),
        "frontend_forms": {
            "call_patients": [
                "nombre",
                "telefono",
                "hospital_id",
                "hospital",
                "municipio",
                "identificacion",
                "edad",
                "sexo",
                "imc",
                "findrisc",
                "condiciones_cronicas",
            ],
            "call_appointments": [
                "patient_id",
                "appointment_date",
                "appointment_type",
                "status",
                "location",
                "notes",
            ],
            "call_scripts": [
                "name",
                "description",
                "welcome_greeting",
                "system_prompt",
                "active",
            ],
            "call_settings": [
                "project_name",
                "project_context",
                "knowledge_base_file",
                "voice_mode",
                "tts_provider",
                "tts_voice",
                "tts_model",
                "tts_speed",
                "tts_stability",
                "tts_similarity_boost",
                "transcription_provider",
                "speech_model",
                "realtime_model",
                "realtime_voice",
                "realtime_speaking_style",
                "machine_detection_enabled",
                "machine_detection_timeout",
                "async_amd_enabled",
                "auto_hangup_on_voicemail",
                "farewell_auto_hangup_enabled",
                "max_batch_calls",
            ],
            "call_hospitals": [
                "name",
                "municipality",
                "department",
                "status",
            ],
            "visitas_campo": [
                "investigador",
                "ubicacion",
                "evidencia",
                "patient_id",
                "document_number",
            ],
        },
    }
