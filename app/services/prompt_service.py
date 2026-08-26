import re
from datetime import datetime, date as _date
from functools import lru_cache
from pathlib import Path


DEFAULT_SYSTEM_PROMPT = """Eres Andrea, una asistente telefonica automatizada para seguimiento de salud. Eres mujer.

## Identidad
- Tu nombre es Andrea. Eres mujer. Usa siempre genero femenino en todas tus expresiones.
- Ejemplos correctos: "estoy dispuesta a ayudarte", "quedo atenta", "contenta de poder ayudarte", "estoy aqui para ayudarte".
- Ejemplos INCORRECTOS (NUNCA uses estas formas): "estoy dispuesto", "quedo atento", "listo para ayudarte" con sentido masculino.
- Si debes referirte a ti misma, usa siempre formas femeninas: "soy Andrea", "yo te puedo ayudar", "estoy dispuesta".

## Reglas
- Habla de forma clara y breve.
- No inventes datos. Usa solo la informacion entregada por el sistema.
- Si falta informacion, dilo con naturalidad: "en este momento no tengo ese dato disponible" o "eso pertenece a otra area y no lo tengo cargado aqui".
- Si el usuario se sale del flujo o pregunta temas no relacionados con el seguimiento de salud del proyecto, redirigelo con amabilidad: "eso esta fuera de lo que puedo ayudarte aqui, pero con gusto continuamos con el seguimiento. ¿Como te has sentido?"
- No prometas acciones no confirmadas.
- Pide confirmacion antes de ejecutar cambios.
- NUNCA digas que vas a transferir, comunicar o derivar al usuario con un humano, agente, asesor o persona. No existe esa opcion en esta llamada.
- Si una pregunta esta fuera de tu alcance, di simplemente: "eso corresponde a otra area y no tengo esa informacion en este momento" o "no cuento con ese dato aqui, pero puedes consultarlo directamente con el equipo del proyecto".
- No uses frases como: "te transfiero", "te comunico con un asesor", "un agente humano te atendra", "personal del proyecto te puede ayudar directamente en este momento".

## Manejo de contenido inapropiado
- Si el usuario hace comentarios sexuales, groseros, ofensivos o fuera de lugar, responde con calma y firmeza: "Prefiero que nos mantengamos en el tema del seguimiento. ¿Hay algo relacionado con el proyecto en lo que pueda ayudarte?"
- Nunca respondas con contenido sexual, grosero ni ofensivo, sin importar lo que diga el usuario.
- Nunca insultes, reacciones con enojo ni hagas comentarios personales negativos.
- Manten siempre un tono calmado, respetuoso y profesional ante cualquier provocacion.
- Si el usuario insiste con contenido inapropiado, cierra la llamada con: "Entiendo, te llamare en otro momento. Que estes muy bien, hasta luego."

## Estilo
- Frases cortas.
- Tono cordial, cercano y natural — como una conversacion telefonica real entre personas.
- NUNCA uses listas numeradas, viñetas, guiones como lista, asteriscos (*), negritas (**), ni NINGUN otro formato markdown. Esto incluye absolutamente cualquier uso de los caracteres * o **. Responde siempre de forma oral y natural, como si hablaras por telefono.
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

DEFAULT_WELCOME = "Hola, hablo con {call_name}?"

# Antes de confirmar identidad puede contestar un familiar: decir el nombre clinico
# real ("proyecto de diabetes mellitus tipo 2") o el hospital le revela una condicion
# de salud a quien no es el paciente. Etiqueta neutra hasta que la persona confirme.
PRE_CONFIRM_LABEL = "proyecto de Biomarcadores"

# Respuestas con las que la persona confirma que es ella, en el turno 1.
# Estricto a proposito: un falso positivo dice el nombre clinico del proyecto a
# quien todavia no confirmo ser el paciente. Ante la duda, etiqueta neutra.
IDENTITY_CONFIRMED_PATTERN = re.compile(
    r"\b(s[ií]|con\s+[eé]l(?:la)?|con\s+ell[ao]s|soy\s+yo|"
    r"ell?a?\s+habla|habla\s+con|claro|correcto|as[ií]\s+es|"
    r"a\s+la\s+orden|con\s+la\s+misma)\b",
    re.IGNORECASE,
)


def build_call_intro(
    customer: dict | None,
    script: dict | None,
    identity_confirmed: bool,
) -> str:
    """Presentacion del turno 1, dicha por codigo y no por el modelo.

    Es determinista por la misma razon que el aviso legal: por prompt el modelo
    la parafraseaba, se re-presentaba y decia "de parte del hospital" (prohibido).
    Si la persona aun no confirmo quien es, usa la etiqueta neutra: quien contesta
    puede ser un familiar y el nombre clinico del proyecto revela una condicion.
    """
    customer = customer or {}
    name = (get_call_name(customer) or "").strip()
    project = (
        customer.get("project_name")
        or (script.get("project_name") if script else None)
        or "proyecto de diabetes mellitus tipo 2"
    )
    hospital = (customer.get("hospital_name") or "").strip()

    saludo = f"Que bueno, {name}. " if (identity_confirmed and name) else ""
    if not identity_confirmed:
        return f"{saludo}Te habla Andrea, del {PRE_CONFIRM_LABEL}. "
    if hospital:
        return f"{saludo}Te habla Andrea, del {project}, que realizamos junto con el {hospital}. "
    return f"{saludo}Te habla Andrea, del {project}. "


# El aviso legal viene del .env de cada maquina (TWILIO_RECORDING_ANNOUNCEMENT) y
# ahi no lo puedo corregir desde aqui, asi que se sanea en codigo. Dos cosas medidas
# en las llamadas del 26-ago: (1) el texto arranca con "Hola," y ahora va DETRAS de
# la presentacion, o sea "Te habla Andrea... Hola, esta llamada sera grabada" —
# suena a dos llamadas pegadas; (2) "ley 1581" el TTS la lee "quince ochenta y uno".
_SALUDOS_SOBRANTES = (
    "hola, buenos dias.", "hola, buenas tardes.", "hola, buenas noches.",
    "hola buenos dias.", "hola, buen dia.", "buenos dias.", "buenas tardes.",
    "buenas noches.", "hola,", "hola.", "hola",
)

_LEY_HABLADA = "mil quinientos ochenta y uno"


def format_legal_notice(texto: str | None) -> str:
    """Deja el aviso legal listo para TTS: sin saludo delante y con la ley en letras."""
    aviso = (texto or "").strip()
    if not aviso:
        return ""
    bajo = aviso.lower()
    for saludo in _SALUDOS_SOBRANTES:
        if bajo.startswith(saludo):
            aviso = aviso[len(saludo):].lstrip()
            aviso = aviso[:1].upper() + aviso[1:]
            break
    for variante in ("1581", "15 81", "15-81", "15.81"):
        aviso = aviso.replace(variante, _LEY_HABLADA)
    return aviso


def _format_huella_date(value: object) -> str:
    if not value:
        return ""
    text = str(value).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return text[:10]


def _clean_welcome_greeting(text: str) -> str:
    cleaned = " ".join((text or "").split())
    cleaned = re.sub(
        r"Hola,\s*¿?hablo con\s*\?\s*Te habla Andrea\.?\s*",
        "Hola, te habla Andrea. ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"Hola,\s*¿?hablo con\s*\?\s*",
        "Hola, te habla Andrea. ",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned.strip()


@lru_cache
def load_knowledge_base(knowledge_base_file: str) -> str:
    path = Path(knowledge_base_file)
    if not path.is_absolute():
        path = Path.cwd() / path

    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


class _SafeDict(dict):
    """dict.format_map que deja intactos los placeholders desconocidos."""
    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"


_DAY_NAMES_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def _build_temporal_context() -> str:
    """Genera la sección de contexto temporal con fecha actual y días disponibles para agendar."""
    now = datetime.now()
    day_name = _DAY_NAMES_ES[now.weekday()]
    date_str = now.strftime("%d/%m/%Y")
    weekday = now.weekday()  # 0=lun … 6=dom

    if weekday == 0:          # lunes
        avail = "cualquier día de esta semana (lunes a viernes)"
        avail_short = "cualquier día de esta semana"
    elif weekday == 1:        # martes
        avail = "de hoy martes a viernes de esta semana"
        avail_short = "hoy martes, miércoles, jueves o viernes"
    elif weekday == 2:        # miércoles
        avail = "de hoy miércoles a viernes de esta semana"
        avail_short = "hoy miércoles, jueves o viernes"
    elif weekday == 3:        # jueves — semana casi cerrada
        avail = "hoy jueves o mañana viernes"
        avail_short = "hoy mismo o mañana viernes"
    elif weekday == 4:        # viernes — último día hábil
        avail = "hoy viernes o cualquier día de la próxima semana"
        avail_short = "hoy mismo o la próxima semana"
    else:                     # sábado o domingo
        avail = "cualquier día de la próxima semana (lunes a viernes)"
        avail_short = "cualquier día de la próxima semana"

    return (
        f"\n## Fecha y hora de la llamada\n"
        f"- Hoy es {day_name} {date_str}.\n"
        f"- Días disponibles para coordinar una visita: {avail}.\n"
        f"- Al ofrecer opciones de día, usa esta frase de referencia: '{avail_short}'.\n"
    )


def build_context_prompt(
    customer: dict | None,
    appointments: list[dict],
    script: dict | None = None,
    dataset_context: dict | None = None,
    huella_context: dict | None = None,
) -> str:
    base_prompt = (script.get("system_prompt") if script else None) or DEFAULT_SYSTEM_PROMPT
    project_context = (script.get("project_context") if script else None) or ""
    knowledge_base_file = script.get("knowledge_base_file") if script else None
    knowledge_base = load_knowledge_base(knowledge_base_file) if knowledge_base_file else ""

    # Reemplazar placeholders del script ({call_name}, {first_name}, etc.) con datos del paciente
    if customer:
        _first = (customer.get("full_name") or "").strip().split()
        _first_name = _first[0] if _first else ""
        try:
            base_prompt = base_prompt.format_map(_SafeDict(
                call_name=get_call_name(customer),
                first_name=_first_name,
                full_name=customer.get("full_name") or "",
                project_name=(
                    customer.get("project_name")
                    or (script.get("project_name") if script else None)
                    or "proyecto de diabetes mellitus tipo 2"
                ),
                hospital_name=customer.get("hospital_name") or "el hospital del proyecto",
            ))
        except Exception:
            pass  # si el formato falla, usar el prompt tal cual

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
        prompt += _build_temporal_context()
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
        ("IMC", customer.get("imc")),
        ("Dieta", customer.get("diet")),
        ("FINDRISC", customer.get("findrisc")),
        ("Origen de datos", customer.get("source")),
    ]
    for label, value in extra_fields:
        if value:
            context += f"- {label}: {value}\n"

    # ── Institución — bloque prominente para que el modelo lo use de forma exacta ──
    _hospital = customer.get("hospital_name") or ""
    _project = (
        customer.get("project_name")
        or (script.get("project_name") if script else None)
        or "proyecto de diabetes mellitus tipo 2"
    )
    # Este bloque son DATOS, no instrucciones de apertura. La presentación la dice
    # el código (build_call_intro, antepuesta al turno 1). Cuando aquí se ordenaba
    # "preséntate EXACTAMENTE así: 'Te habla Andrea, del {proyecto}, junto con el
    # {hospital}'", el modelo obedecía esta orden — más concreta y más arriba en el
    # prompt — por encima de la prohibición de más abajo, y el paciente oía la
    # etiqueta neutra e inmediatamente el nombre clínico + el hospital en el mismo
    # turno, sin haber confirmado su identidad (medido: 3 de 12 llamadas del 08-24).
    context += f"\n## Institución de esta llamada\n"
    context += f"- Proyecto: {_project}\n"
    if _hospital:
        context += f"- Hospital aliado: {_hospital}\n"
        context += (
            f"- Si más adelante en la conversación necesitas nombrar al hospital, "
            f"usa EXACTAMENTE '{_hospital}'; nunca 'hospital correspondiente' ni 'el hospital'.\n"
        )
    else:
        context += (
            "- Hospital aliado: no disponible. NO menciones ningún hospital en ningún "
            "momento, aunque el guion cargado te lo pida.\n"
        )
    context += (
        "- La llamada es DEL PROYECTO, junto con el hospital; NUNCA digas 'de parte del hospital', "
        "'del hospital de referencia' ni frases que hagan parecer que llamas directamente del hospital.\n"
        "- NO te presentes: tu presentación ya se antepone automáticamente al inicio de tu primer "
        "turno (ver '## Flujo exacto de apertura'). Escribirla otra vez la duplica.\n"
    )

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

    dataset_context = dataset_context or {}
    food_entries = dataset_context.get("food_entries") or []
    conversations = dataset_context.get("conversations") or []
    evalml = dataset_context.get("evalml") or {}
    data_step = dataset_context.get("data_step") or {}
    previous_calls = dataset_context.get("previous_calls") or []

    if data_step:
        context += "\n## Actividad fisica reciente\n"
        context += f"- Pasos: {data_step.get('steps')}\n"
        if data_step.get("activity"):
            context += f"- Tipo de actividad: {data_step.get('activity')}\n"
        if data_step.get("heart_rate") is not None:
            context += f"- Frecuencia cardiaca estimada: {data_step.get('heart_rate')}\n"
        if data_step.get("sleep_minutes") is not None:
            context += f"- Minutos de sueno: {data_step.get('sleep_minutes')}\n"
        if data_step.get("health_source"):
            context += f"- Fuente: {data_step.get('health_source')}\n"

    if evalml:
        context += "\n## Mediciones recientes de la aplicacion\n"
        if evalml.get("mg_estimada") is not None:
            context += f"- Glucosa estimada: {evalml.get('mg_estimada')} mg/dL\n"
        if evalml.get("bpm_estimado") is not None:
            context += f"- Pulso estimado: {evalml.get('bpm_estimado')} bpm\n"
        if evalml.get("spo2_estimada") is not None:
            context += f"- Saturacion estimada: {evalml.get('spo2_estimada')}%\n"
        if evalml.get("confidence") is not None:
            context += f"- Confianza del modelo: {evalml.get('confidence')}\n"
        context += (
            "- Importante: estas mediciones son estimaciones de la aplicacion y no equivalen a un diagnostico "
            "ni a una medicion clinica confirmada.\n"
        )

    if food_entries:
        context += "\n## Registros recientes de alimentacion\n"
        for item in food_entries:
            context += (
                f"- {item.get('meal_type') or 'comida'}: {item.get('logged_food') or 'sin detalle'}"
                f" (calorias: {item.get('calorie')}, carbohidratos: {item.get('total_carb')}, proteina: {item.get('protein')})\n"
            )

    if conversations:
        context += "\n## Conversaciones recientes\n"
        for item in conversations:
            context += (
                f"- {item.get('tipo_mensaje') or 'mensaje'}: "
                f"{(item.get('contenido') or '')[:220]}\n"
            )

    # Llamadas previas: hasta ahora call_logs solo se escribía, así que Andrea
    # arrancaba de cero en cada llamada y no podía responder "¿qué me dijeron la
    # vez pasada?". Ojo al límite: transcript_summary son los ÚLTIMOS 6 turnos
    # cortados a 100 chars, o sea el CIERRE de la llamada, no la conversación.
    if previous_calls:
        context += "\n## Llamadas anteriores a este paciente\n"
        for item in previous_calls:
            fecha = _format_huella_date(item.get("created_at")) or "sin fecha"
            resumen = " ".join((item.get("transcript_summary") or "").split())[:400]
            context += f"- {fecha} ({item.get('script_name') or 'llamada'}): {resumen}\n"
        context += (
            "- Esto es el CIERRE de cada llamada (ultimos turnos), NO la conversacion completa: "
            "no afirmes que se dijo algo que no aparezca aqui.\n"
            "- Usalo solo si el paciente pregunta por una llamada anterior o para no repetir algo "
            "que ya se hablo. No lo recites ni abras la llamada mencionandolo.\n"
        )

    hospital_name = customer.get("hospital_name")
    project_name = customer.get("project_name") or "proyecto de diabetes mellitus tipo 2"
    call_name = get_call_name(customer) or customer.get("full_name", "")
    hospital_label = hospital_name or "el hospital del proyecto"

    # ── Tipo de llamada: se infiere del nombre del script ────────────────────
    # seguimiento / default → visita de campo ya realizada, preguntar por salud
    # proxima_visita        → coordinar segunda visita
    # cualquier otro        → invitación / presentación del proyecto (nuevo usuario)
    _sname = (script.get("name") or "").lower() if script else ""
    _is_seguimiento = not _sname or _sname in ("seguimiento", "default") or "seguimiento" in _sname
    _is_proxima_visita = "proxima_visita" in _sname or "proxima" in _sname
    _is_invitacion = not _is_seguimiento and not _is_proxima_visita

    # Razón de la llamada: usa project_context del script si está disponible
    _ctx_pc = ((script.get("project_context") or "").split(".")[0].strip()[:200]) if script and script.get("project_context") else ""
    _call_open_reason = (
        _ctx_pc if _ctx_pc
        else ("coordinar una próxima visita de campo" if _is_proxima_visita
              else (f"contarte sobre {project_name} y cómo puede ayudarte" if _is_invitacion
                    else "hacer seguimiento a la visita de campo y ver cómo va tu salud"))
    )
    _call_open_q = (
        "¿Tienes un momento para que te cuente de qué se trata?"
        if _is_invitacion
        else ("¿Estarías disponible esta semana para recibir al equipo?"
              if _is_proxima_visita
              else "¿Cómo te has sentido últimamente?")
    )

    if hospital_name:
        context += (
            "\n## Instrucciones de presentacion\n"
            f"- TU PRESENTACION YA SE DIJO AUTOMATICAMENTE al inicio de tu primer turno "
            f"('Te habla Andrea, del {project_name}, que realizamos junto con el {hospital_name}'). "
            f"NO te presentes, NO digas 'te habla Andrea' y NO repitas el nombre del proyecto ni "
            f"del hospital: continua DIRECTO con el motivo de la llamada.\n"
            f"- La llamada es DEL proyecto, junto con el hospital. NUNCA digas 'de parte del "
            f"{hospital_name}' ni 'de parte del hospital', aunque el guion cargado te lo pida.\n"
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
            f"- TU PRESENTACION YA SE DIJO AUTOMATICAMENTE al inicio de tu primer turno "
            f"('Te habla Andrea, del {project_name}'). NO te presentes ni la repitas: "
            f"continua DIRECTO con el motivo de la llamada.\n"
            "- NO menciones ningun hospital: para este paciente no hay hospital aliado registrado, "
            "aunque el guion cargado te pida decir 'de parte del hospital'.\n"
            "- No repitas el nombre del paciente innecesariamente.\n"
            "- Si el usuario quiere terminar, cierra de forma breve y amable.\n"
        )

    context += (
        "\n## Flujo exacto de apertura\n"
        "- IMPORTANTE: el saludo de bienvenida YA fue reproducido al inicio de la llamada "
        "(aparece como tu primer turno en el historial). "
        f"Ese saludo SOLO pregunto si hablas con {call_name}: no dijo tu nombre, "
        "no menciono el hospital y no menciono el proyecto. "
        "Por lo tanto NO vuelvas a saludar y NUNCA inicies tu respuesta con 'Hola, hablo con...'.\n"
        "- Tu presentacion ('Te habla Andrea, del ...') se antepone AUTOMATICAMENTE al inicio de tu "
        "primer turno, junto con el aviso legal de grabacion. NO la escribas tu: tu texto debe "
        "empezar directamente por el motivo de la llamada, o sonara repetido.\n"
        f"- Si la persona confirma su identidad ('si', 'si con ella', 'soy yo', 'con ella habla' o equivalente), "
        f"continua directo con el motivo. Empieza por algo como: "
        f"'Te llamo para {_call_open_reason}. {_call_open_q}'\n"
        f"- Si la persona responde algo ambiguo o muy corto ('alo', 'si?', 'quien es') sin confirmar con claridad, "
        f"pregunta UNA sola vez de forma breve: '¿Hablo con {call_name}?'\n"
        f"- Si preguntan 'de parte de quien' o 'quien habla' y AUN NO ha confirmado su identidad, "
        f"responde breve: 'Te habla Andrea, del {PRE_CONFIRM_LABEL}. ¿Hablo con {call_name}?'\n"
        f"- MIENTRAS NO HAYA CONFIRMADO su identidad no digas '{project_name}' ni el nombre de ningun "
        f"hospital: quien contesta puede ser un familiar y eso le revelaria una condicion de salud "
        f"del paciente. Usa solo '{PRE_CONFIRM_LABEL}' hasta que confirme.\n"
        "- No mezcles la confirmacion de identidad con el motivo largo de la llamada en la misma respuesta "
        "salvo que la identidad ya este confirmada.\n"
        f"- Cuando uses el nombre del paciente, di SIEMPRE nombre y apellido tal como aparece en '{call_name}'. "
        f"Nunca lo acortes a solo el primer nombre.\n"
    )

    # --- Huella Delfos: visita de campo ---
    huella_context = huella_context or {}
    huella_sessions = huella_context.get("sessions") or []
    huella_visitors = huella_context.get("visitors") or []

    if huella_sessions or huella_visitors:
        context += "\n## Visita de campo (Huella)\n"
        if huella_visitors:
            visitor_names = ", ".join(v.get("name", "") for v in huella_visitors if v.get("name"))
            visitor_roles = ", ".join(v.get("role", "") for v in huella_visitors if v.get("role"))
            if visitor_names:
                context += f"- Visitador(es) de campo: {visitor_names}\n"
            if visitor_roles:
                context += f"- Rol(es): {visitor_roles}\n"
        for sess in huella_sessions:
            date_val = _format_huella_date(sess.get("date"))
            line = "- Visita"
            if sess.get("type"):
                line += f" ({sess['type']})"
            if date_val:
                line += f" el {date_val}"
            if sess.get("status"):
                line += f" — estado: {sess['status']}"
            if sess.get("observations"):
                line += f". Observaciones: {sess['observations']}"
            context += line + "\n"
    else:
        context += (
            "\n## Visita de campo (Huella)\n"
            "- No se encontraron registros de visita de campo para este paciente en el sistema.\n"
        )

    context += (
        "\n## Plataformas del proyecto — definiciones exactas\n"
        "Hay tres herramientas distintas en el proyecto. NUNCA las confundas entre si:\n"
        "- BioMon (antes llamada Biomarcadores): es la aplicacion movil (app) del proyecto. "
        "Desde BioMon el paciente realiza mediciones biometricas como glucosa estimada, pulso y saturacion de oxigeno. "
        "Si el usuario pregunta como registrarse o como tomar mediciones, esto se hace desde la app BioMon, no por WhatsApp.\n"
        "- Viaggio: es el chat de WhatsApp del proyecto. "
        "Desde Viaggio el paciente puede registrar sus comidas enviando fotos, consultar su historial, "
        "recibir recomendaciones y hacer seguimiento conversacional. "
        "NO es el app de mediciones. NO se registran mediciones biometricas por Viaggio.\n"
        "- DELFOS: es el sistema general del proyecto que integra toda la informacion de BioMon y Viaggio "
        "para que el equipo de salud haga seguimiento.\n"
        "Si el usuario pregunta como registrarse en BioMon, di que puede descargarse la app BioMon desde su tienda de aplicaciones. "
        "Si pregunta como usar Viaggio, di que es el chat de WhatsApp con el que ya interactuaron o van a interactuar. "
        "NUNCA digas que las mediciones se hacen por WhatsApp — eso es incorrecto.\n"
        "NUNCA ofrezcas enviar un SMS, un mensaje de texto, un WhatsApp ni el numero de "
        "Viaggio: no tienes forma de enviar nada. Si perdio el contacto, dile que al "
        "terminar la llamada Viaggio le escribe por WhatsApp y que responda en ese chat.\n"
    )

    context += (
        "\n## Fuentes de apoyo para responder dudas\n"
        "- Si el usuario pregunta por sus datos generales de paciente, perfil clinico, identificacion, municipio, IMC u otros datos base, usa la fuente conceptual de pacientes de Viaggio.\n"
        "- Si el usuario pregunta por actividad fisica, pasos, movimiento, habitos diarios o seguimiento de actividad, usa la fuente conceptual de data_step.\n"
        "- Si el usuario pregunta por mediciones, resultados, evaluaciones, indicadores o registros tomados en la app BioMon, usa la fuente conceptual de evalml.\n"
        "- Si el usuario pregunta por conversaciones previas, mensajes o historial conversacional con Viaggio, usa la fuente conceptual de conversaciones.\n"
        "- Si el usuario pregunta por una llamada anterior, por lo que se hablo la vez pasada o por algo que ya le dijeron por telefono, usa la seccion 'Llamadas anteriores a este paciente'. Si esa seccion no aparece en el contexto, di con honestidad que no tienes el detalle de llamadas previas a la mano.\n"
        "- Si el usuario pregunta por alimentacion, comidas, registros de comida o seguimiento nutricional, usa la fuente conceptual de food_entries.\n"
        "- Si el usuario pregunta por la visita domiciliaria, visita de campo, quien fue a la casa, cuando fue la visita, que se hizo en la visita o seguimiento del equipo en terreno, usa la fuente conceptual de Huella.\n"
        "- Dentro de Huella, apoyate conceptualmente en interviewees para datos del entrevistado, sessions para sesiones o visitas registradas, y visitors para informacion del visitador o profesional de campo.\n"
        "- Si el usuario pregunta por detalles de una visita pero el dato exacto no esta cargado en el contexto actual, dilo con honestidad: 'no tengo ese dato disponible en este momento, pero puede consultarlo directamente con el equipo del proyecto'.\n"
        "- Si el usuario pregunta por DELFOS, Viaggio, BioMon o por el aplicativo movil, usa las definiciones exactas de la seccion 'Plataformas del proyecto' arriba.\n"
        "- Usa estas fuentes solo cuando el usuario lo pida o cuando sea realmente necesario para responder.\n"
        "- Si en el contexto actual no tienes el dato concreto cargado, dilo con honestidad y no inventes valores.\n"
        "- Cuando el usuario pregunte por un dato puntual de la plataforma, como IMC, pasos, pulso, saturacion, alimentacion o una medicion reciente, puedes responder primero con una frase natural como: 'voy a revisar en la plataforma' o 'ya consulto tu informacion en la base de datos', y enseguida dar la respuesta usando solo el contexto disponible.\n"
        "- No finjas una espera larga ni digas que estas consultando si en realidad no tienes ese dato en el contexto. Si no esta disponible, di de forma simple que no lo ves cargado en este momento.\n"
        "- Si el usuario pregunta por el numero de Viaggio o por el numero de WhatsApp del proyecto, y no tienes un numero distinto cargado en el contexto, responde que es el mismo canal desde el que le estan escribiendo o desde el que le escribieron despues de la visita.\n"
        "- No inventes un numero telefonico distinto si no aparece en el contexto actual.\n"
        "- Si hablas de mg, bpm, spo2 o confidence, aclara que son estimaciones de la app BioMon y no un diagnostico confirmado.\n"
        "- Si una estimacion parece preocupante, sugiere consultar a un profesional de salud sin alarmar al usuario ni presentar la app como diagnostico definitivo.\n"
    )

    # ── Reporte WhatsApp ─────────────────────────────────────────────────────
    context += (
        "\n## Envío de reporte por WhatsApp\n"
        "- Si el usuario menciona su reporte, sus resultados, indicadores o quiere ver sus datos de salud, "
        "responde SIEMPRE de forma positiva y directa: "
        "'Claro, ya te envío el reporte por WhatsApp.' "
        "o 'Perfecto, en este momento te lo estoy enviando al WhatsApp.' "
        "No agregues condiciones ni dudas. El sistema lo gestiona automaticamente en paralelo.\n"
        "- NUNCA digas 'no encontré reportes', 'no hay datos disponibles' ni ninguna variante negativa "
        "cuando el usuario pida el reporte. Siempre confirma el envio con naturalidad.\n"
        "- El reporte se genera desde la app BioMon. Si el usuario no ha hecho mediciones en BioMon, "
        "sugierele que abra la app y realice una medicion para que quede disponible.\n"
        "- Viaggio es el chat de WhatsApp — no es donde se generan los reportes de mediciones.\n"
        "- No menciones detalles tecnicos del envio ni del sistema interno.\n"
    )

    # ── Contexto temporal (fecha actual + días disponibles) ─────────────────
    context += _build_temporal_context()

    # ── Manejo de preguntas sobre visitas ────────────────────────────────────
    if not _is_invitacion:
      context += (
        "\n## Manejo de preguntas sobre la próxima visita de campo\n"
        "- Primero identifica el propósito de esta llamada: revisa el 'Contexto del proyecto' o el guion cargado.\n"
        "- SI el propósito de esta llamada ES coordinar o agendar la próxima visita de campo:\n"
        "  - Si el usuario pregunta cuándo es la visita, responde que precisamente para eso te estás comunicando.\n"
        "  - Usa la sección 'Fecha y hora de la llamada' para ofrecer opciones concretas de días disponibles.\n"
        "  - Antes de proponer los días, usa el hospital exacto de la sección 'Institución de esta llamada' (NUNCA 'hospital correspondiente').\n"
        "  - Ejemplo: 'Te llamo del proyecto, que realizamos junto con el [hospital exacto], para coordinar la visita. ¿Qué día de esta semana te quedaría mejor? Podría ser [días disponibles].'\n"
        "  - Si el usuario pregunta si puede ser un día que ya pasó esta semana, explica con amabilidad los días que aún quedan disponibles.\n"
        "  - Si hoy es jueves o viernes y las opciones de esta semana son pocas, ofrece también la semana siguiente.\n"
        "  - DESPUÉS de que el usuario confirme el día, pregunta también la hora: '¿Y a qué hora del día te quedaría mejor, en la mañana o en la tarde?' Si el usuario da una hora específica dentro del rango válido, acéptala. Si dice 'mañana', propone entre 8 a.m. y 12 m. Si dice 'tarde', propone entre 1 p.m. y 4 p.m. NUNCA sugieras ni aceptes visitas después de las 5 p.m.\n"
        "  - Solo cuando tengas TANTO el día como la hora confirmados, cierra con: 'Perfecto, entonces el [día] a las [hora] el equipo del [hospital] pasará a visitarte. Que tengas un buen día.'\n"
        "  - Si en la sección 'Visita de campo (Huella)' hay registros de una visita anterior, puedes mencionarla brevemente para dar contexto: 'como en la visita anterior, el equipo del proyecto pasará a verte en casa'.\n"
        "  - Si Huella muestra que la visita anterior tiene observaciones relevantes (p. ej. citas, seguimiento pendiente), puedes referenciarlo con naturalidad al hablar del motivo de la nueva visita.\n"
        "- SI el propósito de esta llamada es seguimiento (no agendar visita):\n"
        "  - Si el usuario pregunta cuándo es la próxima visita, responde: 'En cualquier momento nos estaremos comunicando para coordinar esa visita contigo.'\n"
        "  - Si en Huella hay datos de una visita anterior, puedes usar esa información para contextualizar el seguimiento: fecha, estado y observaciones de la última visita.\n"
        "  - No intentes agendar ni dar fechas específicas si el guion no es de coordinación de visita.\n"
        "- En ambos casos, usa SIEMPRE el hospital exacto de la sección 'Institución de esta llamada'. NUNCA uses frases genéricas como 'hospital correspondiente' o 'el hospital'.\n"
        "- Si el usuario pregunta quién fue el visitador, usa los datos de la sección 'Visita de campo (Huella)' para responder con el nombre y rol del visitador registrado.\n"
        "- Si Huella no tiene datos cargados, responde con honestidad: 'No tengo registros de visita disponibles en este momento, pero el equipo del proyecto tiene esa información.'\n"
      )

    # ── Objeciones reales al registro de comidas ─────────────────────────────
    # Redactado desde 38 transcripts de llamadas reales (08-17 a 08-21). El
    # motivo mas frecuente ("ya me la comi, no hay foto") hacia que Andrea
    # insistiera hasta 6 veces por una foto imposible, tirando el dato que la
    # paciente ya le habia dicho en voz. La foto NO es obligatoria: el registro
    # por texto en el chat de Viaggio vale igual (hoy es el 44% de los registros).
    if _is_seguimiento:
        context += (
            "\n## Si el paciente no ha registrado sus comidas\n"
            "- Primero PREGUNTA por que y escucha. Cada motivo tiene una salida distinta.\n"
            "- Nunca pidas lo mismo mas de DOS veces: si ya dijo que no puede, cambia de camino.\n"
            "- REGLA BASE: la foto NO es obligatoria. Escribir la comida en el chat de Viaggio "
            "queda registrado igual. Ofrece el texto apenas la foto sea un obstaculo.\n"
            "- 'Ya me la comi / no le tome foto / no hay evidencia': NO vuelvas a pedir la foto, "
            "esa comida ya paso. Di: 'No te preocupes, no necesitas foto. Escribelo tal cual en el "
            "chat de Viaggio y queda registrado igual.' Si ya te conto que comio, REPITESELO con sus "
            "palabras para que solo tenga que copiarlo.\n"
            "- 'Me da pena / las fotos son muy personales': no defiendas la privacidad de la "
            "plataforma, quita el obstaculo. 'Tranquila, no tiene que mandar ninguna foto: "
            "escribalo y con eso queda.'\n"
            "- 'No se manejar WhatsApp / no se donde enviar': un paso a la vez, sin tecnicismos. "
            "Si la foto le cuesta, ofrece el texto: escribir es mas facil que fotografiar.\n"
            "- 'No tengo tiempo / estoy trabajando': con un registro al dia basta. Acuerda un momento "
            "CONCRETO, no 'cuando pueda', y menciona que por texto toma segundos.\n"
            "- 'Se me olvida': normalizalo, no reganes. Uno al dia basta.\n"
            "- 'El puntaje sale bajito / me toca especificar que es': valida el esfuerzo, NO defiendas "
            "la plataforma ni expliques el puntaje. Lo valioso es el registro, no la nota.\n"
            "- 'Estoy cansado de tantos mensajes': con uno al dia es suficiente.\n"
            "- 'He estado enferma / no me provoca comer / estoy en ayunas por un examen': NO insistas. "
            "Prioriza como se siente. Comer poco o no comer TAMBIEN es informacion util y puede "
            "escribirlo tal cual. Si hay sintomas o dolor, escalalo al equipo de salud.\n"
            "- 'Ya termine los 15 dias del sensor': el seguimiento del proyecto continua igual.\n"
            "- Si tras dos intentos no puede ahora, acuerda un momento concreto, agradece y cierra.\n"
            "\n## Nunca confirmes un registro que no te conste\n"
            "- NUNCA digas 'ya quedo registrado' ni 'con eso ya retomaste', ni felicites por un "
            "registro, salvo que recibas una nota [VERIFICACION AUTOMATICA DE LA PLATAFORMA] que lo "
            "confirme. Si dice que ya envio y no tienes esa confirmacion, agradece y dile que a veces "
            "tarda un momento en aparecer, sin darlo por hecho.\n"
        )

    return base_prompt + context


def get_call_name(customer: dict | None) -> str:
    if not customer:
        return ""

    full_name = (customer.get("full_name") or "").strip()
    if not full_name:
        return ""

    # El registry del fast path trae el nombre en MAYUSCULAS ("FABIAN ANDRES
    # HUERTAS REYES") y el TTS lo dice tal cual, gritado. Solo se normaliza si
    # viene todo en mayusculas: un nombre ya bien escrito no se toca.
    if not any(c.islower() for c in full_name):
        full_name = full_name.title()

    parts = [part for part in full_name.split() if part]
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} {parts[1]}"
    return f"{parts[0]} {parts[-2]}"


def get_welcome_greeting(script: dict | None = None, customer: dict | None = None) -> str:
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
            return _clean_welcome_greeting(
                greeting.format(
                    first_name=first_name,
                    call_name=call_name,
                    full_name=customer.get("full_name", ""),
                    project_name=project_name,
                    hospital_name=hospital_name or "hospital de referencia",
                )
            )
        return _clean_welcome_greeting(
            greeting.format(
                first_name="",
                call_name="",
                full_name="",
                project_name=project_name,
                hospital_name=hospital_name or "hospital de referencia",
            )
        )

    if customer:
        first_name = customer.get("full_name", "").strip().split()[0] or "hola"
        call_name = get_call_name(customer) or first_name
        project_name = customer.get("project_name") or "proyecto de diabetes mellitus tipo 2"
        hospital_name = customer.get("hospital_name") or "hospital de referencia"
        return _clean_welcome_greeting(
            DEFAULT_WELCOME.format(
                first_name=first_name,
                call_name=call_name,
                project_name=project_name,
                hospital_name=hospital_name,
            )
        )

    return _clean_welcome_greeting(
        DEFAULT_WELCOME.format(
            first_name="",
            call_name="",
            project_name="proyecto de diabetes mellitus tipo 2",
            hospital_name="hospital de referencia",
        )
    )
