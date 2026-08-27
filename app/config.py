from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Data source
    data_source_mode: str = "manual"

    # Lovable Cloud (primary app database)
    lovable_cloud_url: str = ""
    lovable_cloud_anon_key: str = ""
    lovable_cloud_service_role_key: str = ""
    lovable_whitelist_table: str = "whitelist"
    lovable_user_roles_table: str = "user_roles"
    lovable_call_patients_table: str = "call_patients"
    lovable_call_patients_phone_fields: str = "phone_number"
    lovable_call_logs_table: str = "call_logs"
    lovable_call_artifacts_table: str = "call_artifacts"
    lovable_error_logs_table: str = "error_logs"
    lovable_call_appointments_table: str = "call_appointments"
    lovable_call_hospitals_table: str = "call_hospitals"
    lovable_call_scripts_table: str = "call_scripts"
    lovable_call_settings_table: str = "call_settings"
    lovable_visitas_campo_table: str = "visitas_campo"
    lovable_storage_bucket: str = "audio-recordings"

    # External Supabase - Viaggio (solo datasets, las tablas directas fueron eliminadas)
    external_viaggio_url: str = ""
    external_viaggio_anon_key: str = ""
    external_viaggio_service_role_key: str = ""
    external_viaggio_dataset_api_key: str = ""
    external_viaggio_pacientes_table: str = "pacientes"  # tabla directa para manychat_user_id
    external_viaggio_pacientes_dataset_url: str = ""
    external_viaggio_food_entries_dataset_url: str = ""
    external_viaggio_conversaciones_dataset_url: str = ""
    external_viaggio_evalml_dataset_url: str = ""
    external_viaggio_data_step_dataset_url: str = ""
    external_viaggio_call_transcripts_dataset_url: str = ""
    external_viaggio_call_transcripts_source: str = "sensor"
    external_viaggio_call_transcripts_device_id: str = "CALL-BOT-001"

    # Huella Delfos
    huella_supabase_url: str = ""
    huella_supabase_anon_key: str = ""
    huella_supabase_service_role_key: str = ""
    huella_interviewees_table: str = "interviewees"
    huella_sessions_table: str = "sessions"
    huella_visitors_table: str = "visitors"

    # Twilio
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""
    twilio_machine_detection: str = "Enable"
    twilio_machine_detection_timeout: int = 20
    twilio_async_amd: bool = True
    twilio_conversation_language: str = "es-US"
    twilio_tts_provider: str = "ElevenLabs"
    twilio_tts_voice: str = "b2htR0pMe28pYwCY9gnP"
    twilio_tts_model: str = "eleven_flash_v2_5"
    twilio_tts_speed: str = "0.95"
    twilio_tts_stability: str = "0.50"
    twilio_tts_similarity_boost: str = "0.70"
    twilio_transcription_provider: str = "Google"
    twilio_speech_model: str = "telephony"
    twilio_speech_timeout: int = 3
    twilio_speech_hints: str = ""
    twilio_action_on_empty_result: bool = True
    twilio_profanity_filter: bool = False
    twilio_recording_enabled: bool = False
    twilio_recording_channels: str = "dual"
    twilio_recording_status_callback_events: str = "completed"
    twilio_recording_announcement: str = (
        "Hola, buenos dias. Le informamos que esta llamada sera grabada con fines de calidad y seguridad. "
        "Al continuar en la linea, usted acepta la grabacion y el tratamiento de sus datos personales conforme "
        "a nuestra politica de proteccion de datos."
    )

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-4-5"

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    openai_realtime_model: str = "gpt-realtime"
    openai_realtime_voice: str = "alloy"
    # Silencio (ms) que espera el VAD antes de que Andrea responda. Knob de
    # calibracion: subir si corta a pacientes que hablan pausado.
    openai_realtime_silence_ms: int = 500
    # Umbral del VAD (0-1): mas alto = menos disparos por ruido/eco de linea.
    # Llamadas 08-10: con 0.7 el eco en altavoz cortaba las frases de Andrea.
    openai_realtime_vad_threshold: float = 0.85
    # "server_vad" (por silencio) o "semantic_vad" (por contenido; mas natural
    # con muletillas/ruido, algo mas de latencia). Cambiar por .env sin deploy.
    openai_realtime_turn_detection: str = "server_vad"
    # Voz del modo Realtime: "openai" = voz nativa GPT; "elevenlabs" = hibrido
    # (GPT Realtime pasa a modo texto y ElevenLabs sintetiza con la voz clonada
    # de Andrea, ulaw_8000 directo a Twilio). Requiere ELEVENLABS_API_KEY.
    realtime_tts_provider: str = "openai"
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "b2htR0pMe28pYwCY9gnP"  # voz Andrea (la misma de CR)
    elevenlabs_tts_model: str = "eleven_flash_v2_5"
    openai_realtime_speaking_style: str = (
        "Habla con acento COLOMBIANO (bogotano/andino): entonacion suave y melodica, "
        "seseo latinoamericano, tuteo respetuoso. "
        "PROHIBIDO el acento de Espana: nada de zeta/ce castellana (di 'gracias' como 'grasias', "
        "no 'grathias'), nada de vosotros. "
        "Evita tambien acento rioplatense, voseo, modismos argentinos y acento mexicano marcado. "
        "No prolongues demasiado las vocales ni uses una entonacion cantada. "
        "Tono claro, calido y natural, como una asistente telefonica de salud en Colombia. "
        "Habla con pausas breves, seguridad y ritmo conversacional."
    )
    ffmpeg_path: str = ""

    # WhatsApp report
    whatsapp_report_api_key: str = ""
    whatsapp_report_url: str = "https://xibrxuqiybcalkrtycpi.supabase.co/functions/v1/send-report-by-document"

    # Tope de llamadas simultaneas. Rechaza con 429 en /outbound antes de
    # marcar en Twilio, para no saturar la VM ni las lecturas de Supabase.
    max_concurrent_calls: int = 5

    # ManyChat — automatización cuando no se contesta la llamada
    manychat_api_key: str = ""
    manychat_no_answer_flow_ns: str = ""   # Flow NS del flow a disparar
    # Flow a disparar al terminar una llamada de reactivación (override por env)
    manychat_reactivation_flow_ns: str = "content20260620113511_304633"
    # Flow que le recuerda el numero de Viaggio — se dispara EN MEDIO de la
    # llamada cuando el paciente dice que perdio el chat/el numero.
    manychat_lost_contact_flow_ns: str = "content20260827141001_938175"

    # Audio storage
    audio_storage_enabled: bool = False
    audio_storage_url: str = ""
    audio_storage_anon_key: str = ""
    audio_storage_service_role_key: str = Field(default="", validation_alias=AliasChoices("AUDIO_STORAGE_SERVICE_ROLE_KEY"))
    supabase_service_role_key: str = ""
    audio_storage_bucket: str = "audio-recordings"

    # App
    app_env: str = "production"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    base_url: str = ""
    twilio_voice_mode: str = "conversation_relay"
    cors_allow_origins: str = "*"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
