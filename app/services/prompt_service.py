import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path

DEFAULT_SYSTEM_PROMPT = """Eres un asistente telefonico automatizado para seguimiento de salud.

## Reglas
- Habla de forma clara y breve.
- No inventes datos. Usa solo la informacion entregada por el sistema.
- Si falta informacion, dilo.
- Si el usuario se sale del flujo, redirigelo amablemente.
- Si hay duda, ofrece transferencia a un humano.
- No prometas acciones no confirmadas.
- Pide confirmacion antes de ejecutar cambios.

## Estilo
- Frases cortas.
- Tono cordial, cercano y natural.
- Una pregunta a la vez.
- Confirmar datos sensibles antes de continuar.
- Evita sonar mecanico o demasiado formal.
- No repitas el nombre de la organizacion en cada turno.
- No repitas el nombre del paciente salvo al inicio o cuando sea realmente util.
- Evita formulas institucionales repetitivas o despedidas demasiado solemnes.
- Valida al usuario de forma breve y humana: "claro", "entiendo", "perfecto", "que bueno".
- Si el usuario ya quiere terminar, no abras un tema nuevo.
- Cierra en una sola frase simple cuando la llamada ya deba terminar.
- Evita agradecer o confirmar en exceso.
- Despues de presentarte, usa expresiones como "el proyecto", "el seguimiento" o "la visita".
"""

DEFAULT_WELCOME = (
    "Hola, hablo con {call_name}?"
)


def _clean_welcome_greeting(text: str) -> str:
    cleaned = " ".join((text or "").split())
    cleaned = re.sub(
        r"Hola,\s*hablo con\s*\?\s*Te habla Andrea\.?\s*",
        "Hola, te habla Andrea. ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"Hola,\s*hablo con\s*\?\s*",
        "Hola, te habla Andrea. ",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned.strip()


@lru_cache
def load_knowledge_base(knowledge_base_file: str) -> str:
    """Load a local markdown knowledge base for project-related questions."""
    path = Path(knowledge_base_file)
    if not path.is_absolute():
        path = Path.cwd() / path

    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


def build_context_prompt(
    customer: dict | None,
    appointments: list[dict],
    script: dict | None = None,
) -> str:
    """Build the full system prompt using the call script + customer data."""
    base_prompt = (script.get("system_prompt") if script else None) or DEFAULT_SYSTEM_PROMPT
    project_context = (script.get("project_context") if script else None) or ""
    knowledge_base_file = script.get("knowledge_base_file") if script else None
    knowledge_base = load_knowledge_base(knowledge_base_file) if knowledge_base_file else ""

    if not customer:
        prompt = (
            base_prompt
            + "\n\n## Contexto\nNo se encontro informacion del cliente. "
            "Pide al usuario que se identifique con su nombre o numero de documento."
        )
        if project_context:
            prompt += f"\n\n## Contexto del proyecto\n{project_context}"
        if knowledge_base:
            prompt += f"\n\n## Guia del proyecto\n{knowledge_base}"
        return prompt

    context = f"""

## Datos del cliente
- Nombre: {customer['full_name']}
- Nombre para trato en llamada: {get_call_name(customer)}
- Telefono: {customer['phone_number']}
- Idioma preferido: {customer.get('preferred_language', 'es')}
"""

    extra_fields = [
        ("Documento", customer.get("document_number")),
        ("Edad", customer.get("age")),
        ("Sexo", customer.get("sex")),
        ("Municipio", customer.get("municipality")),
        ("Hospital de referencia", customer.get("hospital_name")),
        ("IMC", customer.get("imc")),
        ("Dieta", customer.get("diet")),
        ("FINDRISC", customer.get("findrisc")),
        ("Origen de datos", customer.get("source")),
    ]
    for label, value in extra_fields:
        if value:
            context += f"- {label}: {value}\n"

    if appointments:
        context += "\n## Citas proximas\n"
        for apt in appointments:
            apt_date = apt["appointment_date"]
            if isinstance(apt_date, str):
                try:
                    apt_date = datetime.fromisoformat(apt_date).strftime("%d/%m/%Y a las %H:%M")
                except ValueError:
                    pass
            context += (
                f"- Cita #{apt['id']}: {apt['appointment_type']} "
                f"el {apt_date} "
                f"en {apt.get('location') or 'ubicacion no especificada'} "
                f"(estado: {apt['status']})\n"
            )
    else:
        context += "\n## Citas proximas\nNo hay citas programadas proximas.\n"

    if project_context:
        context += f"\n## Contexto del proyecto\n{project_context}\n"

    if knowledge_base:
        context += f"\n## Guia del proyecto\n{knowledge_base}\n"

    hospital_name = customer.get("hospital_name")
    project_name = customer.get("project_name") or "proyecto de diabetes mellitus tipo 2"
    call_name = get_call_name(customer) or customer.get("full_name", "")
    if hospital_name:
        context += (
            "\n## Instrucciones de presentacion\n"
            f"- Presentate una sola vez al inicio.\n"
            f"- Explica que llamas por el {project_name}.\n"
            f"- Di que te comunicas de parte del {hospital_name}.\n"
            f"- Si la persona confirma que si es ella, en tu siguiente respuesta vuelve a mencionar con claridad que llamas de parte del {hospital_name} antes de pasar a la siguiente pregunta.\n"
            f"- Despues de confirmar identidad, usa una frase parecida a: 'mucho gusto, te habla Andrea. Me comunico de parte del {hospital_name} por el {project_name}'.\n"
            "- No menciones Biomarcadores repetidamente.\n"
            "- No repitas el nombre del paciente innecesariamente.\n"
            "- Evita despedidas exageradas o demasiado afectuosas.\n"
            "- Evita repetir 'del hospital' o 'del proyecto' al despedirte si ya lo dijiste antes.\n"
            "- Si el usuario dice que no necesita nada mas o quiere terminar, responde breve y cierra la llamada.\n"
            "- No abras nuevas preguntas cuando el usuario ya este cerrando.\n"
            "- Despues de presentarte, usa 'el proyecto' o 'el seguimiento'.\n"
        )
    else:
        context += (
            "\n## Instrucciones de presentacion\n"
            f"- Presentate una sola vez al inicio por el {project_name}.\n"
            "- Di que te comunicas de parte del hospital correspondiente.\n"
            "- Si la persona confirma que si es ella, vuelve a mencionar de forma breve que llamas de parte del hospital antes de seguir.\n"
            "- No menciones Biomarcadores repetidamente.\n"
            "- No repitas el nombre del paciente innecesariamente.\n"
            "- Si el usuario quiere terminar, cierra de forma breve y amable.\n"
        )

    context += (
        "\n## Flujo exacto de apertura\n"
        f"- Primera intervencion exacta: 'Hola, hablo con {call_name}?'\n"
        f"- Si la persona responde algo ambiguo como 'alo', 'si', 'quien habla', 'de parte de quien' o similar, todavia no asumas que ya confirmo identidad.\n"
        f"- Si preguntan 'de parte de quien' o 'quien habla', responde: 'Hola, mucho gusto, te habla Andrea. Me comunico de parte del {hospital_name or 'hospital correspondiente'} por el {project_name}. ¿Hablo con {call_name}?'\n"
        f"- Si la persona responde de forma ambigua como 'alo' o no se entiende, repite solo la confirmacion de identidad: 'Hola, hablo con {call_name}?'\n"
        f"- Si la persona confirma claramente con frases como 'si', 'si con el', 'soy yo', 'con el habla' o equivalente, no vuelvas a preguntar '¿Hablo con {call_name}?'.\n"
        f"- Cuando ya quede confirmada la identidad, continua con una frase natural como: 'Que bueno, {call_name}. Me alegra saludarte. Te comento que esta llamada es para hacer seguimiento a la visita de campo y ver como va tu salud en el marco del proyecto. ¿Como te has sentido ultimamente?'\n"
        "- No mezcles la confirmacion de identidad con el motivo largo de la llamada en la misma primera respuesta salvo que la identidad ya este confirmada.\n"
    )

    return base_prompt + context


def get_call_name(customer: dict | None) -> str:
    """Return a natural spoken name, preferring first name + surname."""
    if not customer:
        return ""

    full_name = (customer.get("full_name") or "").strip()
    if not full_name:
        return ""

    parts = [part for part in full_name.split() if part]
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} {parts[1]}"
    return f"{parts[0]} {parts[-2]}"


def get_welcome_greeting(script: dict | None = None, customer: dict | None = None) -> str:
    """Get the welcome greeting from the script or use default."""
    if script and script.get("welcome_greeting"):
        greeting = script["welcome_greeting"]
        hospital_name = customer.get("hospital_name") if customer else ""
        project_name = (
            (customer.get("project_name") if customer else None)
            or script.get("project_name", "el proyecto")
        )
        if customer:
            first_name = customer.get("full_name", "").strip().split()[0] or "hola"
            call_name = get_call_name(customer) or first_name
            return _clean_welcome_greeting(greeting.format(
                first_name=first_name,
                call_name=call_name,
                full_name=customer.get("full_name", ""),
                project_name=project_name,
                hospital_name=hospital_name or "hospital de referencia",
            ))
        return _clean_welcome_greeting(greeting.format(
            first_name="",
            call_name="",
            full_name="",
            project_name=project_name,
            hospital_name=hospital_name or "hospital de referencia",
        ))
    if customer:
        first_name = customer.get("full_name", "").strip().split()[0] or "hola"
        call_name = get_call_name(customer) or first_name
        project_name = customer.get("project_name") or "proyecto de diabetes mellitus tipo 2"
        hospital_name = customer.get("hospital_name") or "hospital de referencia"
        return _clean_welcome_greeting(DEFAULT_WELCOME.format(
            first_name=first_name,
            call_name=call_name,
            project_name=project_name,
            hospital_name=hospital_name,
        ))
    return _clean_welcome_greeting(DEFAULT_WELCOME.format(
        first_name="",
        call_name="",
        project_name="proyecto de diabetes mellitus tipo 2",
        hospital_name="hospital de referencia",
    ))
