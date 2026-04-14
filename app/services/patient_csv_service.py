import csv
import io
from functools import lru_cache
from pathlib import Path


PATIENT_CSV_PATH = Path("app/pacientes/pacientes.csv")


def _normalize_text(value: str) -> str:
    return (value or "").strip().lower()


def infer_hospital_name(municipality: str) -> str | None:
    normalized = _normalize_text(municipality)
    if "honda" in normalized:
        return "Hospital San Juan de Dios"
    if "guacar" in normalized:
        return "Hospital San Roque"
    return None


def normalize_phone(phone_number: str) -> str:
    digits = "".join(ch for ch in phone_number if ch.isdigit())
    if not digits:
        return ""
    if phone_number.strip().startswith("+"):
        return f"+{digits}"
    if digits.startswith("57") and len(digits) >= 10:
        return f"+{digits}"
    return f"+{digits}"


def _clean_value(value: str) -> str:
    return (value or "").strip().strip('"').strip()


@lru_cache
def load_patient_rows() -> list[dict]:
    if not PATIENT_CSV_PATH.exists():
        return []

    rows: list[dict] = []
    text = PATIENT_CSV_PATH.read_text(encoding="utf-8-sig")
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return rows

    headers = next(csv.reader([lines[0]]))

    for idx, raw_line in enumerate(lines[1:], start=1):
        normalized_line = raw_line
        if raw_line.startswith('"'):
            normalized_line = raw_line[1:].replace('""', '"')

        parsed = next(csv.reader(io.StringIO(normalized_line)))
        row = dict(zip(headers, parsed))

        full_name = _clean_value(row.get("Nombre", ""))
        phone_number = normalize_phone(_clean_value(row.get("Teléfono", "")))
        if not full_name or not phone_number:
            continue

        rows.append({
            "id": 10000 + idx,
            "phone_number": phone_number,
            "full_name": full_name,
            "document_number": _clean_value(row.get("Identificación", "")),
            "status": "active",
            "preferred_language": "es",
            "age": _clean_value(row.get("Edad", "")),
            "sex": _clean_value(row.get("Sexo", "")),
            "municipality": _clean_value(row.get("Municipio", "")),
            "imc": _clean_value(row.get("IMC", "")),
            "diet": _clean_value(row.get("Dieta", "")),
            "findrisc": _clean_value(row.get("FINDRISC", "")),
            "hospital_name": infer_hospital_name(_clean_value(row.get("Municipio", ""))),
            "project_name": "proyecto de diabetes mellitus tipo 2",
            "source": "csv",
        })
    return rows


def find_patient_by_phone(phone_number: str) -> dict | None:
    normalized = normalize_phone(phone_number)
    for row in load_patient_rows():
        if row["phone_number"] == normalized:
            return row
    return None


def list_patients() -> list[dict]:
    return load_patient_rows()
