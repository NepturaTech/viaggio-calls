# Deployment Notes

## Backend only

This project is ready to deploy as a FastAPI backend.

Recommended deployment targets:
- Azure App Service
- AWS App Runner / ECS / EC2
- Render / Railway / Fly.io

## Required environment variables

Use `.env.example` as the reference.

Minimum required:
- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `TWILIO_PHONE_NUMBER`
- `OPENAI_API_KEY`
- `BASE_URL`

Recommended:
- `TWILIO_MACHINE_DETECTION`
- `TWILIO_MACHINE_DETECTION_TIMEOUT`
- `TWILIO_ASYNC_AMD`
- `TWILIO_TTS_PROVIDER`
- `TWILIO_TTS_VOICE`
- `TWILIO_TTS_MODEL`
- `OPENAI_MODEL`
- `APP_ENV=production`
- `TWILIO_VOICE_MODE=conversation_relay`

## Startup command

The project includes a `Procfile` with:

```txt
web: python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

Equivalent startup command:

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Files not intended for deployment

These local directories should not be deployed:
- `audios/`
- `logs/`
- `.venv/`
- `.venv311/`
- `env/`

They are already ignored in `.gitignore` and `.dockerignore`.

## Production recommendation

For production, keep these in environment variables or a secrets manager:
- Twilio credentials
- OpenAI API key
- ElevenLabs / other provider secrets

Do not hardcode secrets in `app/config.py`.
