from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    lovable_call_logs_table: str = "call_logs"
    lovable_call_artifacts_table: str = "call_artifacts"
    lovable_call_appointments_table: str = "call_appointments"
    lovable_call_hospitals_table: str = "call_hospitals"
    lovable_call_scripts_table: str = "call_scripts"
    lovable_call_settings_table: str = "call_settings"
    lovable_visitas_campo_table: str = "visitas_campo"

    # External Supabase - Viaggio
    external_viaggio_url: str = ""
    external_viaggio_anon_key: str = ""
    external_viaggio_service_role_key: str = ""
    external_viaggio_pacientes_table: str = "pacientes"
    external_viaggio_food_entries_table: str = "food_entries"
    external_viaggio_conversaciones_table: str = "conversaciones"
    external_viaggio_meal_patterns_table: str = "meal_patterns"
    external_viaggio_evalml_table: str = "evalml"
    external_viaggio_data_step_table: str = "data_step"

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
    twilio_tts_voice: str = "Andrea"
    twilio_tts_model: str = "eleven_flash_v2_5"
    twilio_tts_speed: str = "0.95"
    twilio_tts_stability: str = "0.50"
    twilio_tts_similarity_boost: str = "0.70"
    twilio_transcription_provider: str = "Google"
    twilio_speech_model: str = "telephony"

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    openai_realtime_model: str = "gpt-realtime"
    openai_realtime_voice: str = "alloy"
    openai_realtime_speaking_style: str = (
        "Habla en espanol latinoamericano neutro. "
        "Evita acento rioplatense, voseo y modismos argentinos. "
        "No prolongues demasiado las vocales ni uses una entonacion cantada. "
        "Prefiere un tono claro, calido y natural, cercano a servicio telefonico en Colombia. "
        "Habla con pausas breves, seguridad y ritmo conversacional."
    )
    ffmpeg_path: str = ""

    # App
    app_env: str = "production"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    base_url: str = ""
    twilio_voice_mode: str = "conversation_relay"
    cors_allow_origins: str = "*"

    # Vercel runtime helpers
    vercel_url: str = ""
    vercel_env: str = ""
    vercel_project_production_url: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @model_validator(mode="after")
    def apply_runtime_fallbacks(self):
        if not self.base_url:
            candidate = self.vercel_project_production_url or self.vercel_url
            if candidate:
                self.base_url = candidate if candidate.startswith(("http://", "https://")) else f"https://{candidate}"
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
