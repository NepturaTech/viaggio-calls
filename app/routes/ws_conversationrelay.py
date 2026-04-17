import asyncio
import contextlib
import json
import logging
import re

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.db.repositories import CallRepository, CallScriptRepository
from app.services.call_log_service import append_transcript_line, finalize_call, log_call_event
from app.services.customer_service import get_customer_context
from app.services.openai_service import generate_response
from app.services.prompt_service import build_context_prompt
from app.services.audio_archive_service import CallAudioArchive
from app.services.realtime_service import connect_realtime, request_initial_greeting
from app.services.twilio_service import hangup_call

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


class ConversationSession:
    """Holds state for a single active call conversation."""

    def __init__(self):
        self.conversation_history: list[dict] = []
        self.system_prompt: str = ""
        self.call_id: int | None = None
        self.customer_phone: str | None = None
        self.script: dict | None = None
        self.direction: str | None = None
        self.customer_name: str | None = None
        self.patient_id: str | None = None
        self.call_sid: str | None = None
        self.pending_hangup: bool = False
        self.script_name: str = "default"

    def add_user_message(self, text: str):
        self.conversation_history.append({"role": "user", "content": text})

    def add_assistant_message(self, text: str):
        self.conversation_history.append({"role": "assistant", "content": text})


FAREWELL_PATTERN = re.compile(
    r"\b(adios|hasta luego|hasta pronto|chao|chau|bye|buen dia|buenas tardes|buenas noches|gracias igualmente|igualmente)\b",
    re.IGNORECASE,
)


def _should_end_call(text: str) -> bool:
    return bool(text and FAREWELL_PATTERN.search(text))


async def _hangup_after_response(call_sid: str | None):
    if not call_sid:
        return
    await asyncio.sleep(1.2)
    try:
        hangup_call(call_sid)
        logger.info("Call %s completed after farewell detection", call_sid)
    except Exception:
        logger.exception("Failed to complete call %s after farewell detection", call_sid)


def _load_call_record(call_sid: str) -> tuple[dict | None, int | None]:
    call_repo = CallRepository()
    call = call_repo.find_by_sid(call_sid)
    if not call:
        return None, None
    return call, call["id"]


def _load_session_context(session: ConversationSession):
    customer, appointments = get_customer_context(session.customer_phone or "")
    session.customer_name = customer["full_name"] if customer else None
    session.patient_id = str(customer.get("document_number") or "") if customer else None

    script_repo = CallScriptRepository()
    session.script = script_repo.get_active_script(session.script_name or "default")
    session.system_prompt = build_context_prompt(customer, appointments, session.script)
    return customer, appointments


@router.websocket("/conversation")
async def conversation_relay_ws(websocket: WebSocket):
    """WebSocket endpoint for Twilio ConversationRelay."""
    await websocket.accept()
    session = ConversationSession()

    logger.info("ConversationRelay WebSocket connected")

    try:
        while True:
            raw = await websocket.receive_text()
            event = json.loads(raw)
            event_type = event.get("type", "unknown")

            logger.debug("WS event: %s", event_type)

            if event_type == "setup":
                call_sid = event.get("callSid", "")
                session.call_sid = call_sid
                session.direction = event.get("direction", "")
                from_number = event.get("from", "")
                to_number = event.get("to", "")
                session.customer_phone = to_number if session.direction == "outbound" else from_number

                _, session.call_id = _load_call_record(call_sid)
                _load_session_context(session)

                if session.call_id:
                    log_call_event(session.call_id, "setup", event)

                logger.info(
                    "Session setup: call_sid=%s, direction=%s, phone=%s, script=%s",
                    call_sid,
                    session.direction,
                    session.customer_phone,
                    session.script.get("name") if session.script else "default",
                )

            elif event_type == "prompt":
                user_text = event.get("voicePrompt", "")
                if not user_text.strip():
                    continue

                logger.info("User said: %s", user_text)
                session.add_user_message(user_text)

                if session.call_id:
                    log_call_event(session.call_id, "user_speech", {"text": user_text})

                session.pending_hangup = _should_end_call(user_text)
                ai_response = await generate_response(
                    session.system_prompt,
                    session.conversation_history[:-1],
                    user_text,
                )

                session.add_assistant_message(ai_response)

                if session.call_id:
                    log_call_event(session.call_id, "ai_response", {"text": ai_response})

                response_payload = json.dumps({
                    "type": "text",
                    "token": ai_response,
                    "last": True,
                    "lang": "es-US",
                })
                await websocket.send_text(response_payload)
                if session.pending_hangup:
                    await _hangup_after_response(session.call_sid)

            elif event_type == "interrupt":
                logger.info("User interrupted the agent")
                if session.call_id:
                    log_call_event(session.call_id, "interrupt", event)

            elif event_type == "dtmf":
                digit = event.get("digit", "")
                logger.info("DTMF received: %s", digit)
                if session.call_id:
                    log_call_event(session.call_id, "dtmf", {"digit": digit})

            elif event_type == "error":
                logger.error("ConversationRelay error: %s", event)
                if session.call_id:
                    log_call_event(session.call_id, "error", event)

            else:
                logger.warning("Unknown event type: %s", event_type)

    except WebSocketDisconnect:
        logger.info("ConversationRelay WebSocket disconnected")
        if session.call_id:
            summary = " | ".join(
                f"{m['role']}: {m['content'][:100]}"
                for m in session.conversation_history[-6:]
            )
            finalize_call(session.call_id, "completed", summary=summary)

    except Exception as e:
        logger.error("WebSocket error: %s", e, exc_info=True)
        if session.call_id:
            finalize_call(session.call_id, "failed", summary=str(e))


@router.websocket("/realtime-media")
async def realtime_media_ws(websocket: WebSocket):
    """Bridge Twilio bidirectional Media Streams with OpenAI Realtime API."""
    await websocket.accept()
    session = ConversationSession()
    stream_sid: str | None = None
    openai_ws = None
    archive: CallAudioArchive | None = None
    archive_finalized = False

    logger.info("Realtime media WebSocket connected")

    def finalize_archive_once():
        nonlocal archive_finalized, archive
        if archive is None or archive_finalized:
            return
        try:
            archive.close()
            archive_finalized = True
            logger.info("Audio archive finalized for call %s", session.call_sid)
        except Exception as exc:
            logger.error("Failed to finalize local audio archive: %s", exc, exc_info=True)

    async def twilio_to_openai():
        nonlocal stream_sid, openai_ws, archive

        while True:
            raw = await websocket.receive_text()
            event = json.loads(raw)
            event_type = event.get("event", "unknown")

            if event_type == "connected":
                logger.info("Twilio media stream connected")

            elif event_type == "start":
                start = event.get("start", {})
                custom_parameters = start.get("customParameters", {})
                call_sid = start.get("callSid", "")
                session.call_sid = call_sid
                stream_sid = start.get("streamSid")

                session.call_id = _load_call_record(call_sid)[1]
                session.customer_phone = custom_parameters.get("customer_phone", "")
                session.customer_name = custom_parameters.get("customer_name", "")
                session.direction = custom_parameters.get("direction", "")
                session.script_name = custom_parameters.get("script_name", "default")
                _load_session_context(session)
                archive = CallAudioArchive(
                    call_sid,
                    session.customer_name,
                    session.patient_id,
                    session.script_name,
                )
                openai_ws = await connect_realtime(session.system_prompt)
                logger.info(
                    "Realtime custom parameters received: %s",
                    {
                        "customer_phone": session.customer_phone,
                        "customer_name": session.customer_name,
                        "patient_id": session.patient_id,
                        "direction": session.direction,
                        "script_name": session.script_name,
                        "welcome_greeting": custom_parameters.get("welcome_greeting", ""),
                    },
                )
                await request_initial_greeting(
                    openai_ws,
                    custom_parameters.get("welcome_greeting", ""),
                )

                if session.call_id:
                    log_call_event(session.call_id, "realtime_start", start)

                logger.info(
                    "Realtime session setup: call_sid=%s, stream_sid=%s, phone=%s, direction=%s",
                    call_sid,
                    stream_sid,
                    session.customer_phone,
                    session.direction,
                )

            elif event_type == "media":
                if openai_ws is None:
                    continue
                if archive is not None:
                    archive.append_user_audio(event["media"]["payload"])
                await openai_ws.send(json.dumps({
                    "type": "input_audio_buffer.append",
                    "audio": event["media"]["payload"],
                }))

            elif event_type == "dtmf":
                logger.info("DTMF received during realtime call: %s", event)
                if session.call_id:
                    log_call_event(session.call_id, "dtmf", event)

            elif event_type == "stop":
                logger.info("Twilio media stream stopped")
                if session.call_id:
                    log_call_event(session.call_id, "realtime_stop", event)
                finalize_archive_once()
                if openai_ws is not None:
                    with contextlib.suppress(Exception):
                        await openai_ws.close()
                break

            else:
                logger.debug("Unhandled Twilio media event: %s", event_type)

    async def openai_to_twilio():
        nonlocal openai_ws

        while openai_ws is None:
            await asyncio.sleep(0.05)

        async for raw in openai_ws:
            event = json.loads(raw)
            event_type = event.get("type", "unknown")

            if event_type == "response.created":
                logger.info("OpenAI started a realtime response")

            elif event_type in {"response.audio.delta", "response.output_audio.delta"} and stream_sid:
                if archive is not None:
                    archive.append_assistant_audio(event["delta"])
                await websocket.send_text(json.dumps({
                    "event": "media",
                    "streamSid": stream_sid,
                    "media": {"payload": event["delta"]},
                }))
                logger.debug("Forwarded audio delta to Twilio stream")

            elif event_type in {
                "response.audio_transcript.delta",
                "response.output_audio_transcript.delta",
            }:
                logger.debug("Assistant transcript delta: %s", event.get("delta", ""))

            elif event_type in {
                "response.audio_transcript.done",
                "response.output_audio_transcript.done",
            }:
                transcript = event.get("transcript", "")
                if transcript:
                    logger.info("Assistant said: %s", transcript)
                    session.add_assistant_message(transcript)
                    if session.call_id:
                        log_call_event(session.call_id, "ai_response", {"text": transcript})
                        append_transcript_line(session.call_id, "assistant", transcript)
                    if archive is not None:
                        archive.append_transcript("assistant", transcript)

            elif event_type in {"response.audio.done", "response.output_audio.done"}:
                logger.debug("Assistant audio stream completed")

            elif event_type in {"response.text.delta", "response.output_text.delta"}:
                logger.debug("Assistant text delta: %s", event.get("delta", ""))

            elif event_type == "conversation.item.input_audio_transcription.completed":
                transcript = event.get("transcript", "")
                if transcript:
                    logger.info("User said: %s", transcript)
                    session.add_user_message(transcript)
                    session.pending_hangup = _should_end_call(transcript)
                    if session.call_id:
                        log_call_event(session.call_id, "user_speech", {"text": transcript})
                        append_transcript_line(session.call_id, "user", transcript)
                    if archive is not None:
                        archive.append_transcript("user", transcript)

            elif event_type == "session.updated":
                logger.info("Realtime session updated successfully")

            elif event_type == "response.done":
                logger.info("OpenAI completed a realtime response")
                if session.pending_hangup:
                    session.pending_hangup = False
                    await _hangup_after_response(session.call_sid)

            elif event_type == "input_audio_buffer.speech_started" and stream_sid:
                await websocket.send_text(json.dumps({
                    "event": "clear",
                    "streamSid": stream_sid,
                }))
                logger.info("Caller speech detected; cleared pending Twilio audio buffer")

            elif event_type == "error":
                logger.error("OpenAI realtime error: %s", event)
                if session.call_id:
                    log_call_event(session.call_id, "error", event)

            else:
                logger.debug("Unhandled OpenAI realtime event: %s", event_type)

    try:
        await asyncio.gather(twilio_to_openai(), openai_to_twilio())
    except WebSocketDisconnect:
        logger.info("Realtime media WebSocket disconnected")
    except Exception as exc:
        logger.error("Realtime media bridge failed: %s", exc, exc_info=True)
        if session.call_id:
            finalize_call(session.call_id, "failed", summary=str(exc))
    finally:
        logger.info("Finalizing realtime media session for call %s", session.call_sid)
        if openai_ws is not None:
            with contextlib.suppress(Exception):
                await openai_ws.close()
        finalize_archive_once()

        if session.call_id:
            summary = " | ".join(
                f"{m['role']}: {m['content'][:100]}"
                for m in session.conversation_history[-6:]
            )
            finalize_call(session.call_id, "completed", summary=summary or "Realtime session ended")
