import logging
import time
from functools import lru_cache
from datetime import datetime
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

_CALL_SETTINGS_CACHE_TTL_SECONDS = 120.0
_call_settings_cache: dict[str, Any] | None = None
_call_settings_cache_source = "uninitialized"
_call_settings_cache_loaded_at = 0.0
_SCRIPT_CACHE_TTL_SECONDS = 120.0
_script_cache: dict[str, tuple[float, dict]] = {}  # key → (loaded_at, script)
_DATASET_CACHE_TTL_SECONDS = 60.0
_dataset_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
# Cache para manychat_user_id leído directamente de la tabla Viaggio (no del dataset)
_VIAGGIO_MANYCHAT_LOOKUP_TTL = 120.0
_viaggio_manychat_lookup_cache: tuple[float, dict[str, str]] | None = None
_HUELLA_CACHE_TTL_SECONDS = 120.0
_huella_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


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


# Sentinel returned by _request_rows when the column used as filter doesn't exist (HTTP 400).
# Callers that probe multiple field names can check `is _COLUMN_NOT_FOUND` to skip silently.
_COLUMN_NOT_FOUND: list = []


def _request_rows(
    source: str,
    table: str,
    params: dict[str, str] | None = None,
    *,
    silent_400: bool = False,
) -> list[dict]:
    config = _source_config(source)
    if not config["url"] or not config["key"]:
        return []

    endpoint = f"{config['url']}/rest/v1/{table}"
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.get(endpoint, headers=_headers(source), params=params or {})
            if silent_400 and response.status_code == 400:
                # Column doesn't exist in this table — expected when probing field names.
                logger.debug(
                    "Supabase %s: column not found in %s (400), skipping field probe",
                    source,
                    table,
                )
                return _COLUMN_NOT_FOUND  # type: ignore[return-value]
            response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else []
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 404:
            # Table doesn't exist in this Supabase project — not a runtime error.
            logger.debug(
                "Supabase %s: table '%s' not found (404) — skipping",
                source,
                table,
            )
        else:
            logger.warning(
                "Supabase %s request failed for table %s (%d): %s",
                source,
                table,
                status,
                exc.response.text[:200],
            )
        return []
    except Exception as exc:
        logger.warning("Supabase %s request failed for table %s: %s", source, table, exc)
        return []


def _dataset_headers() -> dict[str, str]:
    settings = _settings()
    key = (
        settings.external_viaggio_dataset_api_key
        or settings.external_viaggio_service_role_key
        or settings.external_viaggio_anon_key
    )
    return {
        "x-api-key": key,
        "Accept": "application/json",
    }


def _request_dataset_records(dataset_url: str) -> list[dict[str, Any]]:
    settings = _settings()
    key = (
        settings.external_viaggio_dataset_api_key
        or settings.external_viaggio_service_role_key
        or settings.external_viaggio_anon_key
    )
    if not dataset_url or not key:
        return []

    now = time.monotonic()
    cached = _dataset_cache.get(dataset_url)
    if cached and (now - cached[0]) < _DATASET_CACHE_TTL_SECONDS:
        return cached[1]

    try:
        with httpx.Client(timeout=5.0) as client:
            records: list[dict[str, Any]] = []
            offset = 0
            limit = 100

            while True:
                response = client.get(
                    dataset_url,
                    headers=_dataset_headers(),
                    params={"offset": offset, "limit": limit},
                )
                response.raise_for_status()
                payload = response.json()
                page_records = payload.get("records", []) if isinstance(payload, dict) else []
                if not isinstance(page_records, list):
                    page_records = []
                records.extend(page_records)

                has_more = bool(payload.get("has_more")) if isinstance(payload, dict) else False
                page_limit = int(payload.get("limit") or limit) if isinstance(payload, dict) else limit
                page_offset = int(payload.get("offset") or offset) if isinstance(payload, dict) else offset

                if not has_more or not page_records:
                    break

                offset = page_offset + page_limit

        _dataset_cache[dataset_url] = (now, records)
        return records
    except Exception as exc:
        logger.warning("Viaggio dataset request failed for %s: %s", dataset_url, exc)
        return []


def _dataset_data(record: dict[str, Any]) -> dict[str, Any]:
    data = record.get("data", {})
    return data if isinstance(data, dict) else {}


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _get_viaggio_manychat_lookup() -> dict[str, str]:
    """Carga {normalized_phone: manychat_user_id} desde la tabla Viaggio directa.

    La tabla pacientes tiene la columna real `manychat_user_id` (ej. 394326569).
    El dataset API devuelve ese campo con el número de teléfono (valor incorrecto),
    por eso se consulta la tabla directamente.

    Resultado cacheado _VIAGGIO_MANYCHAT_LOOKUP_TTL segundos.
    """
    global _viaggio_manychat_lookup_cache
    now = time.monotonic()
    if (
        _viaggio_manychat_lookup_cache is not None
        and (now - _viaggio_manychat_lookup_cache[0]) < _VIAGGIO_MANYCHAT_LOOKUP_TTL
    ):
        return _viaggio_manychat_lookup_cache[1]

    settings = _settings()
    table = getattr(settings, "external_viaggio_pacientes_table", "pacientes") or "pacientes"

    if not is_external_viaggio_enabled() or not table:
        return {}

    try:
        rows = _request_rows(
            "viaggio",
            table,
            {"select": "numero,manychat_user_id", "limit": "5000"},
            silent_400=True,
        )
        if rows is _COLUMN_NOT_FOUND:
            logger.debug("Viaggio pacientes: columna manychat_user_id no encontrada")
            _viaggio_manychat_lookup_cache = (now, {})
            return {}

        lookup: dict[str, str] = {}
        for row in rows:
            phone = normalize_phone(_as_text(row.get("numero") or ""))
            mc_id = _as_text(row.get("manychat_user_id") or "")
            # Descartar entradas donde manychat_user_id sea el propio teléfono
            if phone and mc_id and mc_id not in (phone, phone.lstrip("+")):
                lookup[phone] = mc_id
        _viaggio_manychat_lookup_cache = (now, lookup)
        logger.info("Viaggio manychat_user_id lookup cargado: %d entradas", len(lookup))
        return lookup
    except Exception as exc:
        logger.warning("Viaggio manychat lookup falló: %s", exc)
        if _viaggio_manychat_lookup_cache is not None:
            return _viaggio_manychat_lookup_cache[1]
        return {}


def _normalize_dataset_patient(record: dict[str, Any]) -> dict[str, Any]:
    data = _dataset_data(record)
    return {
        "id": data.get("id") or record.get("id"),
        "full_name": data.get("nombre"),
        "phone_number": normalize_phone(_as_text(data.get("numero"))),
        "document_number": _as_text(data.get("identificacion") or record.get("patient_internal_id")),
        "age": data.get("edad"),
        "sex": data.get("sexo"),
        "municipality": data.get("municipio"),
        "email": data.get("email"),
        "imc": data.get("imc"),
        "diet": data.get("tipo_dieta"),
        "findrisc": data.get("puntaje_findrisc"),
        "objective": data.get("objetivo"),
        "activity_level": data.get("actividad_fisica"),
        # manychat_user_id NO se extrae del dataset porque el campo del dataset
        # contiene el teléfono en lugar del subscriber_id real.
        # Se inyecta desde _get_viaggio_manychat_lookup() después de normalizar.
        "manychat_user_id": "",
        "source": "viaggio_dataset",
        "_dataset_raw": data,
    }


def _record_timestamp(record: dict[str, Any]) -> float:
    data = _dataset_data(record)
    candidates: list[Any] = [
        data.get("created_at"),
        record.get("created_at"),
        data.get("health_synced_at"),
        data.get("ts"),
    ]
    for value in candidates:
        if value is None:
            continue
        if isinstance(value, (int, float)):
            value = float(value)
            if value > 10_000_000_000:
                value = value / 1000.0
            return value
        text = _as_text(value)
        if not text:
            continue
        text = text.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(text).timestamp()
        except ValueError:
            continue
    return 0.0


def _matching_dataset_records(dataset_url: str, document_number: str) -> list[dict[str, Any]]:
    document = _as_text(document_number)
    if not document:
        return []
    matches = []
    for record in _request_dataset_records(dataset_url):
        data = _dataset_data(record)
        if _as_text(data.get("identificacion") or record.get("patient_internal_id")) == document:
            matches.append(record)
    return sorted(matches, key=_record_timestamp, reverse=True)


def _summarize_food_entries(document_number: str) -> list[dict[str, Any]]:
    settings = _settings()
    summaries = []
    for record in _matching_dataset_records(settings.external_viaggio_food_entries_dataset_url, document_number)[:3]:
        data = _dataset_data(record)
        summaries.append({
            "meal_type": data.get("meal_type"),
            "logged_food": data.get("logged_food"),
            "calorie": data.get("calorie"),
            "protein": data.get("protein"),
            "total_carb": data.get("total_carb"),
            "created_at": data.get("created_at") or record.get("created_at"),
        })
    return summaries


def _summarize_conversations(document_number: str) -> list[dict[str, Any]]:
    settings = _settings()
    summaries = []
    for record in _matching_dataset_records(settings.external_viaggio_conversaciones_dataset_url, document_number)[:3]:
        data = _dataset_data(record)
        summaries.append({
            "tipo_mensaje": data.get("tipo_mensaje"),
            "tipo_contenido": data.get("tipo_contenido"),
            "contenido": _as_text(data.get("contenido"))[:300],
            "created_at": data.get("created_at") or record.get("created_at"),
        })
    return summaries


def _summarize_evalml(document_number: str) -> dict[str, Any]:
    settings = _settings()
    records = _matching_dataset_records(settings.external_viaggio_evalml_dataset_url, document_number)
    if not records:
        return {}
    record = records[0]
    data = _dataset_data(record)
    # prediction_id: UUID del registro evalml, necesario para enviar el reporte por WhatsApp
    prediction_id = str(
        data.get("prediction_id") or data.get("id") or record.get("id") or ""
    )
    return {
        "prediction_id": prediction_id,
        "mg_estimada": data.get("mg"),
        "bpm_estimado": data.get("bpm"),
        "spo2_estimada": data.get("spo2"),
        "confidence": data.get("confidence"),
        "captured_at": data.get("created_at") or record.get("created_at"),
        "advisory": (
            "Estos datos provienen de estimaciones de la aplicacion y no sustituyen una medicion clinica. "
            "Si el valor parece alto o preocupante, sugiere consultar a un profesional de salud."
        ),
    }


def _summarize_data_step(document_number: str) -> dict[str, Any]:
    settings = _settings()
    records = _matching_dataset_records(settings.external_viaggio_data_step_dataset_url, document_number)
    if not records:
        return {}
    data = _dataset_data(records[0])
    return {
        "steps": data.get("steps"),
        "activity": data.get("activity"),
        "heart_rate": data.get("heart_rate"),
        "sleep_minutes": data.get("sleep_minutes"),
        "health_source": data.get("health_source"),
        "captured_at": data.get("health_synced_at") or data.get("ts") or records[0].get("created_at"),
    }


def get_patient_dataset_context(patient: dict | None) -> dict[str, Any]:
    if not patient:
        return {}
    document_number = _as_text(patient.get("document_number") or patient.get("identificacion"))
    if not document_number:
        return {}
    return {
        "food_entries": _summarize_food_entries(document_number),
        "conversations": _summarize_conversations(document_number),
        "evalml": _summarize_evalml(document_number),
        "data_step": _summarize_data_step(document_number),
    }


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


def _load_call_settings_from_source() -> tuple[dict[str, Any], str]:
    settings = _settings()
    if is_lovable_enabled():
        row = _pick_first_row("lovable", settings.lovable_call_settings_table)
        if row:
            logger.info(
                "Loaded call settings from Supabase lovable.%s: %s",
                settings.lovable_call_settings_table,
                _preview_row(row),
            )
            return row, "lovable"

    logger.info("Call settings fallback in use: manual/default")
    return {}, "fallback"


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
    global _call_settings_cache
    global _call_settings_cache_loaded_at
    global _call_settings_cache_source

    now = time.monotonic()
    if _call_settings_cache is not None and (now - _call_settings_cache_loaded_at) < _CALL_SETTINGS_CACHE_TTL_SECONDS:
        return dict(_call_settings_cache)

    row, source = _load_call_settings_from_source()
    _call_settings_cache = dict(row)
    _call_settings_cache_source = source
    _call_settings_cache_loaded_at = now
    return dict(_call_settings_cache)


def get_call_settings_debug(refresh: bool = False) -> dict[str, Any]:
    global _call_settings_cache
    global _call_settings_cache_loaded_at
    global _call_settings_cache_source

    if refresh:
        _call_settings_cache = None
        _call_settings_cache_loaded_at = 0.0
        _call_settings_cache_source = "uninitialized"

    settings = _settings()
    row = get_call_settings()
    age_seconds = max(0.0, time.monotonic() - _call_settings_cache_loaded_at) if _call_settings_cache_loaded_at else None
    return {
        "enabled": is_lovable_enabled(),
        "table": settings.lovable_call_settings_table,
        "source": _call_settings_cache_source,
        "using_fallback": _call_settings_cache_source != "lovable",
        "cache_ttl_seconds": _CALL_SETTINGS_CACHE_TTL_SECONDS,
        "cache_age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
        "row_preview": _preview_row(row),
        "project_name": row.get("project_name") if row else CALL_SCRIPT.get("project_name"),
        "voice_mode": row.get("voice_mode"),
        "realtime_model": row.get("realtime_model"),
        "knowledge_base_file": row.get("knowledge_base_file") if row else CALL_SCRIPT.get("knowledge_base_file"),
    }


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
    return get_call_settings()


def get_call_rules() -> dict:
    return get_call_settings()


def _find_lovable_patient_by_document(document_number: str) -> dict | None:
    """Busca en la tabla call_patients de Lovable por número de documento
    para recuperar hospital_id, hospital y municipio cuando el dataset de
    Viaggio los devuelve nulos."""
    if not document_number or not is_lovable_enabled():
        return None
    settings = _settings()
    # La tabla usa 'identificacion' según el contrato de campos del frontend.
    # Se intenta también 'document_number' como alternativa.
    for field in ("identificacion", "document_number", "cedula"):
        rows = _request_rows(
            "lovable",
            settings.lovable_call_patients_table,
            {
                "select": "hospital_id,hospital_name,hospital,municipio,municipality",
                field: f"eq.{document_number}",
                "limit": "1",
            },
            silent_400=True,
        )
        if rows is _COLUMN_NOT_FOUND:
            continue  # this column doesn't exist in the table — try next
        if rows:
            logger.info(
                "Hospital enrichment found in Lovable call_patients (field=%s doc=%s): %s",
                field,
                document_number,
                {k: rows[0].get(k) for k in ("hospital_id", "hospital_name", "hospital", "municipio", "municipality")},
            )
            return rows[0]
    return None


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
            # 1) Intentar inferir desde municipio local
            inferred = infer_hospital_name(municipality or "")
            if inferred:
                enriched["hospital_name"] = inferred
            else:
                # 2) Si el dataset de Viaggio no trajo municipio/hospital, buscar en Lovable
                #    usando el número de documento (fuente primaria del proyecto).
                doc = _as_text(document_number or "")
                lovable_row = _find_lovable_patient_by_document(doc) if doc else None
                if lovable_row:
                    h_id = lovable_row.get("hospital_id")
                    if h_id:
                        enriched["hospital_name"] = _get_lovable_hospital_name(str(h_id))
                    if not enriched.get("hospital_name"):
                        enriched["hospital_name"] = (
                            lovable_row.get("hospital_name") or lovable_row.get("hospital") or None
                        )
                    # Enriquecer también el municipio si faltaba
                    lovable_muni = (
                        lovable_row.get("municipality") or lovable_row.get("municipio") or ""
                    )
                    if not enriched.get("municipality") and lovable_muni:
                        enriched["municipality"] = lovable_muni
                    # Último intento: inferir hospital desde municipio de Lovable
                    if not enriched.get("hospital_name") and lovable_muni:
                        enriched["hospital_name"] = infer_hospital_name(lovable_muni)
                else:
                    enriched["hospital_name"] = enriched.get("hospital") or None

    project_settings = get_project_settings()
    if project_settings and not enriched.get("project_name"):
        enriched["project_name"] = project_settings.get("project_name")

    enriched.setdefault("source", "supabase")
    return enriched


def list_backend_patients() -> list[dict]:
    settings = _settings()
    # Fuente principal: dataset de Viaggio (tablas directas eliminadas)
    if settings.external_viaggio_pacientes_dataset_url:
        rows = _request_dataset_records(settings.external_viaggio_pacientes_dataset_url)
        mc_lookup = _get_viaggio_manychat_lookup()
        patients = []
        for row in rows:
            p = _normalize_dataset_patient(row)
            phone = p.get("phone_number", "")
            if phone and not p.get("manychat_user_id"):
                p["manychat_user_id"] = mc_lookup.get(phone, "")
            patients.append(_enrich_patient(p))
        return patients
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
    dataset_mode = bool(settings.external_viaggio_pacientes_dataset_url)
    logger.info(
        "Looking up patient by phone: input=%s normalized=%s candidates=%s",
        phone_number,
        normalized,
        candidates,
    )

    if settings.external_viaggio_pacientes_dataset_url:
        mc_lookup = _get_viaggio_manychat_lookup()
        for record in _request_dataset_records(settings.external_viaggio_pacientes_dataset_url):
            patient = _normalize_dataset_patient(record)
            patient_phone = patient.get("phone_number")
            if patient_phone and any(patient_phone == normalize_phone(candidate) for candidate in candidates):
                # Inyectar manychat_user_id real desde la tabla directa (el dataset tiene el teléfono)
                if patient_phone and not patient.get("manychat_user_id"):
                    patient["manychat_user_id"] = mc_lookup.get(patient_phone, "")
                logger.info(
                    "Patient found in Viaggio pacientes dataset: %s (manychat_user_id=%s)",
                    _preview_row(patient),
                    patient.get("manychat_user_id") or "—",
                )
                return _enrich_patient(patient)
        logger.info(
            "No patient match found in Viaggio pacientes dataset for phone=%s",
            normalized,
        )

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

    # Solo buscar citas en Lovable si el paciente proviene de Lovable.
    # Si vino de Viaggio u otra fuente externa, su "id" es de esa fuente y
    # no matchea en la tabla lovable.call_appointments → requests siempre fallidos.
    patient_source = (patient.get("source") or "").lower()
    lovable_patient = patient_source in ("lovable", "lovable_dataset", "") and is_lovable_enabled()

    if lovable_patient:
        patient_id = patient.get("id") or patient.get("patient_id")

        if patient_id is not None:
            rows = _request_rows(
                "lovable",
                settings.lovable_call_appointments_table,
                {"select": "*", "patient_id": f"eq.{patient_id}", "order": "appointment_date.asc"},
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
    cache_key = normalized_name or "default"

    # Servir desde caché si está vigente (evita queries lentas en el webhook)
    now = time.monotonic()
    cached = _script_cache.get(cache_key)
    if cached and (now - cached[0]) < _SCRIPT_CACHE_TTL_SECONDS:
        logger.info("Loaded active call script from cache: %s", cache_key)
        return dict(cached[1])

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
                _script_cache[cache_key] = (now, script)
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
    _script_cache[cache_key] = (now, script)
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


def _request_huella_rows_cached(table_name: str) -> list[dict[str, Any]]:
    """Fetch all rows from a Huella table with in-process cache."""
    now = time.monotonic()
    cached = _huella_cache.get(table_name)
    if cached and (now - cached[0]) < _HUELLA_CACHE_TTL_SECONDS:
        return cached[1]
    rows = _request_rows("huella", table_name, {"select": "*"})
    _huella_cache[table_name] = (now, rows)
    return rows


def get_huella_visit_context(patient: dict | None) -> dict[str, Any]:
    """Query Huella Delfos for field visit context of a patient.

    Matches interviewees client-side against document_number or name to avoid
    needing to know the exact column names of the remote table.
    """
    if not patient or not is_huella_enabled():
        return {}

    settings = _settings()
    document_number = _as_text(patient.get("document_number") or patient.get("identificacion"))
    full_name = _as_text(patient.get("full_name") or patient.get("nombre"))

    if not document_number and not full_name:
        return {}

    # Fetch the full interviewees table (small dataset, cached 120 s)
    all_interviewees = _request_huella_rows_cached(settings.huella_interviewees_table)
    if not all_interviewees:
        return {}

    # Match client-side: document_number wins; name is fallback
    interviewee_row: dict[str, Any] | None = None
    for row in all_interviewees:
        if document_number:
            row_text_values = {_as_text(v) for v in row.values() if v is not None}
            if document_number in row_text_values:
                interviewee_row = row
                break
    if not interviewee_row and full_name:
        first_word = full_name.lower().split()[0] if full_name else ""
        for row in all_interviewees:
            row_name = _as_text(
                row.get("name") or row.get("nombre") or row.get("full_name") or ""
            ).lower()
            if first_word and (first_word in row_name or (row_name.split()[:1] or [""])[0] in full_name.lower()):
                interviewee_row = row
                break

    if not interviewee_row:
        logger.info(
            "No Huella interviewee found for patient document=%s name=%s",
            document_number,
            full_name,
        )
        return {}

    interviewee_id = interviewee_row.get("id")
    interviewee: dict[str, Any] = {
        "id": interviewee_id,
        "name": interviewee_row.get("name") or interviewee_row.get("nombre") or interviewee_row.get("full_name"),
        "document_number": document_number or interviewee_row.get("document_number") or interviewee_row.get("id_number"),
        "municipality": interviewee_row.get("municipality") or interviewee_row.get("municipio"),
    }
    result: dict[str, Any] = {"interviewee": interviewee}

    # Sessions (visits) — filter cached rows by interviewee_id
    if interviewee_id is not None:
        all_sessions = _request_huella_rows_cached(settings.huella_sessions_table)
        interviewee_id_str = _as_text(interviewee_id)
        matching_sessions = [
            r for r in all_sessions
            if _as_text(r.get("interviewee_id")) == interviewee_id_str
        ]
        matching_sessions = sorted(
            matching_sessions,
            key=lambda r: _as_text(r.get("created_at") or r.get("date") or ""),
            reverse=True,
        )[:3]

        normalized_sessions = []
        visitor_ids: set[str] = set()
        for s in matching_sessions:
            vid = s.get("visitor_id")
            if vid is not None:
                visitor_ids.add(_as_text(vid))
            normalized_sessions.append({
                "id": s.get("id"),
                "date": s.get("date") or s.get("visit_date") or s.get("created_at"),
                "type": s.get("type") or s.get("session_type") or s.get("visit_type"),
                "observations": _as_text(
                    s.get("observations") or s.get("notes") or s.get("observaciones") or ""
                )[:400],
                "status": s.get("status") or s.get("estado"),
            })
        result["sessions"] = normalized_sessions

        # Visitors — filter cached rows by collected visitor_ids
        if visitor_ids:
            all_visitors = _request_huella_rows_cached(settings.huella_visitors_table)
            visitors = []
            for row in all_visitors:
                if _as_text(row.get("id")) in visitor_ids:
                    visitors.append({
                        "id": row.get("id"),
                        "name": row.get("name") or row.get("nombre"),
                        "role": row.get("role") or row.get("rol") or row.get("position"),
                    })
            result["visitors"] = visitors

    logger.info(
        "Huella visit context loaded for patient %s: sessions=%d visitors=%d",
        document_number or full_name,
        len(result.get("sessions", [])),
        len(result.get("visitors", [])),
    )
    return result


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
            "purpose": "Datos clinicos y de seguimiento de Viaggio (solo via datasets, tablas directas eliminadas)",
            "datasets": {
                "pacientes": settings.external_viaggio_pacientes_dataset_url,
                "food_entries": settings.external_viaggio_food_entries_dataset_url,
                "conversaciones": settings.external_viaggio_conversaciones_dataset_url,
                "evalml": settings.external_viaggio_evalml_dataset_url,
                "data_step": settings.external_viaggio_data_step_dataset_url,
                "call_transcripts": settings.external_viaggio_call_transcripts_dataset_url,
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


# ---------------------------------------------------------------------------
# Cache warmup — pre-carga y refresco periódico
# ---------------------------------------------------------------------------

#: Estado del último warmup (leído por el endpoint /health)
_warmup_status: dict[str, Any] = {}
_warmup_last_at: float = 0.0


def warm_all_caches() -> dict[str, Any]:
    """Pre-cargar todos los cachés de Supabase en memoria.

    Seguro llamarlo en startup y periódicamente desde un background task.
    Retorna un dict con el resultado de cada fuente para exponer en /health.
    """
    global _warmup_status, _warmup_last_at

    settings = _settings()
    results: dict[str, Any] = {}

    # 1. Call settings (proyecto / configuración global)
    try:
        cfg = get_call_settings()
        results["call_settings"] = "ok" if cfg else "empty"
    except Exception as exc:
        results["call_settings"] = f"error: {exc}"

    # 2. Scripts activos — cargamos el default y todos los registrados en el cache
    try:
        script = get_active_call_script(None)
        name = (script.get("name") or "default") if script else "—"
        results["script"] = f"ok ({name})"
    except Exception as exc:
        results["script"] = f"error: {exc}"

    # 3. Dataset de pacientes Viaggio
    if settings.external_viaggio_pacientes_dataset_url:
        try:
            rows = _request_dataset_records(settings.external_viaggio_pacientes_dataset_url)
            results["viaggio_patients"] = f"ok ({len(rows)} pacientes)"
        except Exception as exc:
            results["viaggio_patients"] = f"error: {exc}"
    else:
        results["viaggio_patients"] = "disabled"

    # 3b. Lookup de manychat_user_id desde tabla Viaggio directa
    if is_external_viaggio_enabled():
        try:
            mc_lookup = _get_viaggio_manychat_lookup()
            results["viaggio_manychat_lookup"] = f"ok ({len(mc_lookup)} entradas)"
        except Exception as exc:
            results["viaggio_manychat_lookup"] = f"error: {exc}"
    else:
        results["viaggio_manychat_lookup"] = "disabled"

    # 4. Dataset evalml Viaggio (predicciones ML)
    if settings.external_viaggio_evalml_dataset_url:
        try:
            rows = _request_dataset_records(settings.external_viaggio_evalml_dataset_url)
            results["viaggio_evalml"] = f"ok ({len(rows)} rows)"
        except Exception as exc:
            results["viaggio_evalml"] = f"error: {exc}"
    else:
        results["viaggio_evalml"] = "disabled"

    # 5. Huella interviewees
    if is_huella_enabled():
        try:
            rows = _request_huella_rows_cached(settings.huella_interviewees_table)
            results["huella_interviewees"] = f"ok ({len(rows)} rows)"
        except Exception as exc:
            results["huella_interviewees"] = f"error: {exc}"
    else:
        results["huella_interviewees"] = "disabled"

    _warmup_status = results
    _warmup_last_at = time.monotonic()
    logger.info("Cache warmup completado: %s", results)
    return results


def get_warmup_status() -> dict[str, Any]:
    """Retorna el último estado de warmup (para exponer en /health)."""
    return {
        "last_warmup_ago_seconds": round(time.monotonic() - _warmup_last_at, 1) if _warmup_last_at else None,
        "sources": _warmup_status,
    }
