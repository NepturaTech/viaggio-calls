from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
