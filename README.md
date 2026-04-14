# AI Voice Calls Backend

FastAPI backend for outbound and inbound healthcare follow-up calls using:
- Twilio Voice
- OpenAI
- optional Twilio ConversationRelay / Realtime-style flows

This repository is focused on the backend only. It is prepared to be deployed cleanly and later connected to an admin frontend.

## What It Does

- starts outbound calls through Twilio
- handles Twilio voice webhooks
- generates conversational responses with OpenAI
- supports call scripts and greetings
- records in-memory call logs for QA/debugging
- stores local audio/transcript artifacts when enabled in runtime flows
- supports voicemail detection and early hangup

## Current State

The project currently runs in a manual/local mode:
- call script content comes from [manual_data.py](C:/Users/DAVIDE/Documents/calls/plain_calls/app/manual_data.py)
- runtime configuration comes from environment variables via [config.py](C:/Users/DAVIDE/Documents/calls/plain_calls/app/config.py)
- call logs are stored in memory

The repository was cleaned for backend deployment, so local auxiliary data sources such as CSV seeds were removed.

## Main Routes

Health:
- `GET /health`

Calls:
- `GET /calls`
- `GET /calls/{call_sid}`

Patients:
- `GET /patients`
- `GET /patients/{phone_number}`
- `POST /patients/{phone_number}/call`
- `POST /patients/call-batch`

Scripts:
- `GET /scripts`
- `GET /scripts/active`

Twilio:
- `POST /twilio/voice`
- `POST /twilio/status`
- `POST /twilio/amd`
- `POST /twilio/outbound`

WebSockets:
- `/ws/conversation`
- `/ws/realtime-media`

## Project Structure

- [app/main.py](C:/Users/DAVIDE/Documents/calls/plain_calls/app/main.py): FastAPI app entrypoint
- [app/config.py](C:/Users/DAVIDE/Documents/calls/plain_calls/app/config.py): environment-driven settings
- [app/manual_data.py](C:/Users/DAVIDE/Documents/calls/plain_calls/app/manual_data.py): current local script/customer data
- [app/routes](C:/Users/DAVIDE/Documents/calls/plain_calls/app/routes): HTTP and WebSocket endpoints
- [app/services](C:/Users/DAVIDE/Documents/calls/plain_calls/app/services): Twilio, OpenAI, prompts, call archive, etc.
- [app/db](C:/Users/DAVIDE/Documents/calls/plain_calls/app/db): in-memory/manual repositories

## Requirements

- Python 3.11 recommended
- Twilio account and phone number
- OpenAI API key
- public HTTPS base URL for Twilio callbacks

Dependencies are listed in [requirements.txt](C:/Users/DAVIDE/Documents/calls/plain_calls/requirements.txt).

## Local Setup

1. Create and activate a virtual environment.
2. Install dependencies.
3. Copy `.env.example` to `.env`.
4. Fill the required environment variables.
5. Run the app.

Example:

```powershell
python -m venv .venv311
.venv311\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app.main
```

## Required Environment Variables

Minimum:
- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `TWILIO_PHONE_NUMBER`
- `OPENAI_API_KEY`
- `BASE_URL`

Important optional settings:
- `TWILIO_VOICE_MODE`
- `TWILIO_TTS_PROVIDER`
- `TWILIO_TTS_VOICE`
- `TWILIO_TTS_MODEL`
- `TWILIO_MACHINE_DETECTION`
- `TWILIO_MACHINE_DETECTION_TIMEOUT`
- `TWILIO_ASYNC_AMD`
- `FFMPEG_PATH`

See [.env.example](C:/Users/DAVIDE/Documents/calls/plain_calls/.env.example).

## Run

Development:

```powershell
python -m app.main
```

Production-style:

```powershell
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Deployment

This backend is ready to deploy to services such as:
- Azure App Service
- AWS App Runner / ECS / EC2
- Render
- Railway
- Fly.io

There is a [Procfile](C:/Users/DAVIDE/Documents/calls/plain_calls/Procfile) included for simple platform startup.

See [DEPLOYMENT.md](C:/Users/DAVIDE/Documents/calls/plain_calls/DEPLOYMENT.md) for backend deployment notes.

## Production Notes

- do not store secrets in code
- use environment variables or a secrets manager
- keep `BASE_URL` public and reachable by Twilio
- local folders like `audios/` and `logs/` are ignored for deployment
- for production persistence, replace manual/in-memory storage with a real database

## Recommended Next Step

The next recommended evolution is:
- move patients, appointments, scripts, and settings to a database
- keep secrets in server-side configuration
- connect a TypeScript admin frontend to this backend
