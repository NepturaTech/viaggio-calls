import audioop
import base64
import contextlib
import json
import logging
import mimetypes
import os
import re
import shutil
import subprocess
import time
import unicodedata
import wave
from datetime import datetime
from pathlib import Path
from copy import deepcopy

import httpx

from app.config import get_settings
from app.services.error_log_service import log_error_event


settings = get_settings()
logger = logging.getLogger(__name__)


class CallAudioArchive:
    """Persist call audio and transcript artifacts locally for QA."""

    def __init__(
        self,
        call_sid: str,
        patient_name: str | None = None,
        patient_id: str | None = None,
        script_name: str | None = None,
        mode: str = "realtime",
    ):
        self.call_sid = call_sid
        self.patient_name = patient_name or ""
        self.patient_id = patient_id or ""
        self.script_name = script_name or "default"
        # "realtime"             → raw audio bytes available → open WAV files
        # "conversation_relay"   → Twilio handles audio internally → skip WAVs
        self.mode = mode
        slug = self._slugify_patient_name(self.patient_name)
        patient_folder = slug or "sin_nombre"
        self.base_dir = Path("audios") / patient_folder / call_sid
        self.base_dir.mkdir(parents=True, exist_ok=True)

        self.user_wav_path = self.base_dir / "user.wav"
        self.assistant_wav_path = self.base_dir / "assistant.wav"
        self.user_mp3_path = self.base_dir / "user.mp3"
        self.assistant_mp3_path = self.base_dir / "assistant.mp3"
        self.call_json_path = self.base_dir / "call.json"
        self.transcript_json_path = self.base_dir / "transcript.json"
        self.transcript_txt_path = self.base_dir / "transcript.txt"
        self.archive_meta_path = self.base_dir / "archive_meta.json"
        self._conversion_results: dict[str, dict] = {}
        self._remote_artifacts: dict[str, dict] = {}

        # WAV files only make sense in realtime mode where we receive raw µ-law audio.
        # In conversation_relay mode Twilio handles audio; bytes never arrive here.
        if self.mode == "realtime":
            self._user_wav = self._open_wave(self.user_wav_path)
            self._assistant_wav = self._open_wave(self.assistant_wav_path)
        else:
            self._user_wav = None
            self._assistant_wav = None
        self._transcript_lines: list[dict] = []
        self._closed = False

    @staticmethod
    def _slugify_patient_name(value: str) -> str:
        """Convierte un nombre de paciente a slug de máximo 2 tokens (nombre + primer apellido).

        - Elimina iniciales sueltas (p. ej. "A." en "Gustavo A. Cajiao Juri").
        - Normaliza tildes y caracteres especiales.
        - Resultado: "Gustavo_Cajiao" en lugar de "Gustavo_A_Cajiao_Juri".
        """
        raw = (value or "").strip()
        # Normalizar tildes: é→e, ñ→n, ü→u, etc.
        raw = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
        # Dividir y filtrar tokens que sean sólo una letra (iniciales como "A.", "J.")
        parts = [tok.rstrip(".") for tok in raw.split() if len(tok.rstrip(".")) > 1]
        # Tomar primer nombre + primer apellido (máx 2 tokens).
        # Para nombres compuestos (≥3 tokens), parts[-2] es el primer apellido:
        #   "Edwin Mauricio Arias Lopez"  → parts[0]="Edwin"  parts[-2]="Arias"  ✓
        #   "Gustavo Cajiao Juri"         → parts[0]="Gustavo" parts[-2]="Cajiao" ✓
        #   "Gustavo Cajiao"              → parts[:2]          (sin cambio)       ✓
        selected = [parts[0], parts[-2]] if len(parts) >= 3 else parts[:2]
        result = "_".join(selected)
        result = re.sub(r"[^A-Za-z0-9_]+", "", result)
        return result[:80]

    def _open_wave(self, path: Path):
        wav_file = wave.open(str(path), "wb")
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(8000)
        return wav_file

    def append_user_audio(self, payload_b64: str):
        if self._closed or self._user_wav is None:
            return
        pcm = self._decode_ulaw_payload(payload_b64)
        self._user_wav.writeframes(pcm)

    def append_assistant_audio(self, payload_b64: str):
        if self._closed or self._assistant_wav is None:
            return
        pcm = self._decode_ulaw_payload(payload_b64)
        self._assistant_wav.writeframes(pcm)

    def append_transcript(self, role: str, text: str):
        line = {
            "role": role,
            "text": text,
            "created_at": datetime.utcnow().isoformat(),
        }
        self._transcript_lines.append(line)
        self.transcript_json_path.write_text(
            json.dumps(self._transcript_lines, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.transcript_txt_path.write_text(
            "\n".join(f"[{item['role']}] {item['text']}" for item in self._transcript_lines),
            encoding="utf-8",
        )

    def close(self):
        if self._closed:
            return
        self._closed = True

        # Close WAV writers if they were opened (realtime mode only)
        if self._user_wav is not None:
            self._user_wav.close()
            self._user_wav = None
        if self._assistant_wav is not None:
            self._assistant_wav.close()
            self._assistant_wav = None

        # WAV→MP3 conversion only applies in realtime mode
        if self.mode == "realtime":
            self._conversion_results["user_mp3"] = self._try_convert_to_mp3(
                self.user_wav_path, self.user_mp3_path
            )
            self._conversion_results["assistant_mp3"] = self._try_convert_to_mp3(
                self.assistant_wav_path, self.assistant_mp3_path
            )
            self._delete_wav_if_mp3_exists(self.user_wav_path, self.user_mp3_path)
            self._delete_wav_if_mp3_exists(self.assistant_wav_path, self.assistant_mp3_path)

        if self._should_discard_archive():
            shutil.rmtree(self.base_dir, ignore_errors=True)
            logger.info("Discarded empty local archive for %s", self.call_sid)
            return
        self._remote_artifacts = self._upload_artifacts_to_storage()
        self._sync_artifacts_to_table()
        self._sync_transcripts_to_table()
        self._write_call_json()
        self._write_archive_meta()

    @staticmethod
    def _decode_ulaw_payload(payload_b64: str) -> bytes:
        ulaw_bytes = base64.b64decode(payload_b64)
        return audioop.ulaw2lin(ulaw_bytes, 2)

    def _write_archive_meta(self):
        ffmpeg_path = self._resolve_ffmpeg_path()
        meta = {
            "ffmpeg_available": bool(ffmpeg_path),
            "ffmpeg_path": ffmpeg_path,
            "call_sid": self.call_sid,
            "transcript_lines": len(self._transcript_lines),
            "conversion_results": self._conversion_results,
            "artifacts": {
                "user_wav": str(self.user_wav_path),
                "assistant_wav": str(self.assistant_wav_path),
                "user_mp3": str(self.user_mp3_path),
                "assistant_mp3": str(self.assistant_mp3_path),
                "call_json": str(self.call_json_path),
                "transcript_json": str(self.transcript_json_path),
                "transcript_txt": str(self.transcript_txt_path),
            },
            "remote_artifacts": self._remote_artifacts,
        }
        self.archive_meta_path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _write_call_json(self):
        payload = {
            "call_sid": self.call_sid,
            "patient_name": self.patient_name,
            "patient_id": self.patient_id,
            "script_name": self.script_name,
            "created_at": datetime.utcnow().isoformat(),
            "transcript_lines": self._transcript_lines,
            "artifacts": {
                "user_wav": str(self.user_wav_path),
                "assistant_wav": str(self.assistant_wav_path),
                "user_mp3": str(self.user_mp3_path if self.user_mp3_path.exists() else ""),
                "assistant_mp3": str(self.assistant_mp3_path if self.assistant_mp3_path.exists() else ""),
            },
            "remote_artifacts": self._remote_artifacts,
        }
        self.call_json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _storage_config() -> dict[str, str]:
        url = (settings.audio_storage_url or settings.lovable_cloud_url or "").rstrip("/")
        key = (
            settings.audio_storage_service_role_key
            or settings.supabase_service_role_key
            or settings.audio_storage_anon_key
            or settings.lovable_cloud_service_role_key
            or settings.lovable_cloud_anon_key
        )
        bucket = (settings.audio_storage_bucket or settings.lovable_storage_bucket or "audio-recordings").strip()
        return {"url": url, "key": key, "bucket": bucket}

    @classmethod
    def _storage_enabled(cls) -> bool:
        config = cls._storage_config()
        return bool(settings.audio_storage_enabled and config["url"] and config["key"] and config["bucket"])

    def _storage_headers(self, content_type: str) -> dict[str, str]:
        config = self._storage_config()
        key = config["key"]
        return {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": content_type,
            "x-upsert": "true",
        }

    def _upload_artifacts_to_storage(self) -> dict[str, dict]:
        if not self._storage_enabled():
            logger.info(
                "Audio storage disabled for call %s: enabled=%s url_set=%s key_set=%s bucket=%s",
                self.call_sid,
                settings.audio_storage_enabled,
                bool((settings.audio_storage_url or settings.lovable_cloud_url or "").strip()),
                bool(self._storage_config()["key"]),
                self._storage_config()["bucket"],
            )
            return {}

        uploads: dict[str, dict] = {}
        for label, path in {
            "user_mp3": self.user_mp3_path,
            "assistant_mp3": self.assistant_mp3_path,
            "transcript_json": self.transcript_json_path,
            "transcript_txt": self.transcript_txt_path,
            "call_json": self.call_json_path,
        }.items():
            if not path.exists() or path.stat().st_size == 0:
                continue
            uploads[label] = self._upload_single_artifact(path)
        return uploads

    def _upload_single_artifact(self, path: Path) -> dict:
        config = self._storage_config()
        relative_path = "/".join(
            [
                self.base_dir.parent.name,
                self.call_sid,
                path.name,
            ]
        )
        endpoint = f"{config['url']}/storage/v1/object/{config['bucket']}/{relative_path}"
        content_type, _ = mimetypes.guess_type(str(path))
        content_type = content_type or "application/octet-stream"

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    endpoint,
                    headers=self._storage_headers(content_type),
                    content=path.read_bytes(),
                )
                response.raise_for_status()
            public_url = (
                f"{config['url']}/storage/v1/object/public/{config['bucket']}/{relative_path}"
            )
            logger.info("Uploaded call artifact to Supabase Storage: %s", public_url)
            return {
                "status": "ok",
                "path": relative_path,
                "public_url": public_url,
                "size_bytes": path.stat().st_size,
            }
        except Exception as exc:
            details = ""
            if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
                details = exc.response.text[:500]
            logger.warning(
                "Failed to upload %s to Supabase Storage: %s | details=%s",
                path.name,
                exc,
                details,
            )
            log_error_event(
                source="backend",
                severity="warning",
                error_type="storage_upload_failed",
                message=f"Failed to upload {path.name} to Supabase Storage",
                call_sid=self.call_sid,
                patient_id=self.patient_id or None,
                details=details or str(exc),
                context={
                    "artifact": path.name,
                    "storage_path": relative_path,
                    "bucket": config["bucket"],
                },
            )
            return {
                "status": "error",
                "path": relative_path,
                "error": str(exc),
                "details": details,
            }

    @staticmethod
    def _dataset_headers() -> dict[str, str]:
        key = (
            settings.external_viaggio_dataset_api_key
            or settings.external_viaggio_service_role_key
            or settings.external_viaggio_anon_key
        )
        return {
            "Content-Type": "application/json",
            "x-api-key": key,
        }

    def _sync_transcripts_to_table(self):
        if not self._transcript_lines:
            return

        endpoint = (
            settings.external_viaggio_call_transcripts_dataset_url
        ).strip()
        key = (
            settings.external_viaggio_dataset_api_key
            or settings.external_viaggio_service_role_key
            or settings.external_viaggio_anon_key
        )
        if not (endpoint and key):
            logger.info(
                "Transcript dataset sync disabled for call %s: endpoint_set=%s key_set=%s",
                self.call_sid,
                bool(endpoint),
                bool(key),
            )
            return

        messages = [
            {
                "role": item.get("role"),
                "text": item.get("text"),
                "created_at": item.get("created_at"),
                "script_name": self.script_name or None,
            }
            for item in self._transcript_lines
            if item.get("text")
        ]
        records = [
            {
                "patient_internal_id": self.patient_id or "",
                "data": {
                    "call_sid": self.call_sid,
                    "paciente": self.patient_name or None,
                    "patient_id": self.patient_id or None,
                    "patient_name": self.patient_name or None,
                    "script_name": self.script_name or None,
                    "last_message_at": messages[-1].get("created_at") if messages else None,
                    "messages": messages,
                },
                "source": settings.external_viaggio_call_transcripts_source or "sensor",
                "source_metadata": {
                    "device_id": settings.external_viaggio_call_transcripts_device_id or "CALL-BOT-001",
                },
            }
        ]
        if not records:
            return

        payload = {"records": records}
        max_attempts = 4
        backoff = 2.0  # segundos iniciales; se duplica en cada reintento
        last_exc: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                with httpx.Client(timeout=20.0) as client:
                    response = client.post(
                        endpoint,
                        headers=self._dataset_headers(),
                        content=json.dumps(payload, ensure_ascii=False),
                    )
                    if response.status_code == 429:
                        # Rate-limit: esperar y reintentar
                        retry_after = float(response.headers.get("Retry-After", backoff))
                        wait = max(retry_after, backoff)
                        logger.warning(
                            "Transcript dataset 429 (attempt %d/%d) for call %s — waiting %.1fs",
                            attempt, max_attempts, self.call_sid, wait,
                        )
                        time.sleep(wait)
                        backoff *= 2
                        last_exc = httpx.HTTPStatusError(
                            f"429 Too Many Requests", request=response.request, response=response
                        )
                        continue
                    response.raise_for_status()
                logger.info(
                    "Synced %d transcript lines to Viaggio dataset for call %s (attempt %d)",
                    len(records), self.call_sid, attempt,
                )
                return  # éxito
            except httpx.HTTPStatusError as exc:
                if exc.response is not None and exc.response.status_code == 429:
                    last_exc = exc
                    continue
                last_exc = exc
                break
            except Exception as exc:
                last_exc = exc
                break

        logger.warning(
            "Failed to sync transcript lines to Viaggio dataset for call %s after %d attempts: %s",
            self.call_sid, max_attempts, last_exc,
        )
        log_error_event(
            source="backend",
            severity="warning",
            error_type="transcript_dataset_sync_failed",
            message="Failed to sync transcript lines to Viaggio dataset",
            call_sid=self.call_sid,
            patient_id=self.patient_id or None,
            details=str(last_exc),
            context={
                "endpoint": endpoint,
                "records_count": len(records),
                "script_name": self.script_name,
            },
        )

    @staticmethod
    def _lovable_table_headers() -> dict[str, str]:
        # Preferir service role key para evitar bloqueos de RLS.
        # SUPABASE_SERVICE_ROLE_KEY (sb_secret_...) es el service role de Lovable Cloud.
        key = (
            settings.lovable_cloud_service_role_key
            or settings.supabase_service_role_key
            or settings.lovable_cloud_anon_key
        )
        return {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        }

    @staticmethod
    def _extract_missing_column(details: str) -> str | None:
        if not details:
            return None
        match = re.search(r"Could not find the '([^']+)' column", details)
        if match:
            return match.group(1)
        return None

    @staticmethod
    def _extract_invalid_type_column(details: str, rows: list[dict]) -> str | None:
        """Detecta errores de tipo (p. ej. uuid inválido) e identifica qué columna enviar como null.

        PostgREST devuelve un cuerpo JSON como:
            {"code":"22P02","details":null,"message":"invalid input syntax for type uuid: \"VALUE\""}

        El valor problemático está dentro de una cadena JSON, por lo que las comillas están
        escapadas como \\". Parseamos el JSON primero y ejecutamos el regex sobre el campo
        `message` ya desescapado — de lo contrario el regex nunca hace match.
        """
        if not details:
            return None

        bad_value: str | None = None

        # ── Intento 1: parsear como JSON (respuesta normal de PostgREST) ──────
        try:
            err = json.loads(details)
            if err.get("code") != "22P02":
                return None
            message = err.get("message") or ""
            vm = re.search(r'invalid input syntax for type \w+: "([^"]+)"', message)
            if vm:
                bad_value = vm.group(1)
        except (json.JSONDecodeError, ValueError, AttributeError):
            # ── Fallback: buscar en texto crudo (comillas escapadas o no) ─────
            if '"22P02"' not in details and "22P02" not in details:
                return None
            # Probar primero con comillas escapadas (\\") y luego sin escapar
            vm = re.search(r'invalid input syntax for type \w+: \\"([^\\"]+)\\"', details)
            if not vm:
                vm = re.search(r'invalid input syntax for type \w+: "([^"]+)"', details)
            if vm:
                bad_value = vm.group(1)

        if not bad_value:
            return None

        # Buscar qué columna de los rows contiene ese valor exacto
        for row in rows:
            for col, val in row.items():
                if val is not None and str(val) == bad_value:
                    return col
        return None

    @classmethod
    def _drop_column_from_rows(cls, rows: list[dict], column: str) -> list[dict]:
        trimmed_rows = deepcopy(rows)
        for row in trimmed_rows:
            row.pop(column, None)
        return trimmed_rows

    def _post_artifact_rows(self, endpoint: str, rows: list[dict]) -> tuple[bool, str]:
        try:
            with httpx.Client(timeout=20.0) as client:
                response = client.post(
                    endpoint,
                    headers=self._lovable_table_headers(),
                    content=json.dumps(rows, ensure_ascii=False),
                )
                response.raise_for_status()
            return True, ""
        except Exception as exc:
            details = ""
            if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
                details = exc.response.text[:1000]
            logger.warning(
                "Failed to sync artifacts to lovable table %s for call %s: %s",
                settings.lovable_call_artifacts_table,
                self.call_sid,
                exc,
            )
            if details:
                logger.warning("call_artifacts response details: %s", details)
            return False, details or str(exc)

    def _sync_artifacts_to_table(self):
        if not self._remote_artifacts:
            return

        base_url = (settings.lovable_cloud_url or "").rstrip("/")
        table = (settings.lovable_call_artifacts_table or "").strip()
        key = (
            settings.lovable_cloud_service_role_key
            or settings.lovable_cloud_anon_key
        )
        if not (base_url and table and key):
            return

        rows = []
        for artifact_type, artifact in self._remote_artifacts.items():
            if artifact.get("status") != "ok":
                continue
            public_url = artifact.get("public_url", "")
            content_type, _ = mimetypes.guess_type(public_url)
            rows.append(
                {
                    "call_sid": self.call_sid,
                    "patient_document_number": self.patient_id or None,
                    "patient_name": self.patient_name or None,
                    "script_name": self.script_name or None,
                    "artifact_type": artifact_type,
                    "storage_path": artifact.get("path"),
                    "public_url": public_url,
                    "content_type": content_type or "application/octet-stream",
                    "size_bytes": artifact.get("size_bytes"),
                    "created_at": datetime.utcnow().isoformat(),
                }
            )

        if not rows:
            return

        endpoint = f"{base_url}/rest/v1/{table}"
        rows_to_send = rows
        dropped_columns: list[str] = []
        nulled_columns: list[str] = []
        details = ""

        for _ in range(6):
            ok, details = self._post_artifact_rows(endpoint, rows_to_send)
            if ok:
                logger.info(
                    "Synced %d artifact rows to lovable table %s for call %s%s",
                    len(rows_to_send),
                    table,
                    self.call_sid,
                    f" (dropped={dropped_columns} nulled={nulled_columns})" if (dropped_columns or nulled_columns) else "",
                )
                return

            # ── Columna desconocida → eliminarla ─────────────────────────────
            missing_column = self._extract_missing_column(details)
            if missing_column and missing_column not in dropped_columns:
                dropped_columns.append(missing_column)
                rows_to_send = self._drop_column_from_rows(rows_to_send, missing_column)
                logger.warning("Retrying call_artifacts without missing column '%s'", missing_column)
                continue

            # ── Columna con tipo incompatible (p. ej. uuid) → enviar null ────
            invalid_col = self._extract_invalid_type_column(details, rows_to_send)
            if invalid_col and invalid_col not in nulled_columns and invalid_col not in dropped_columns:
                nulled_columns.append(invalid_col)
                rows_to_send = self._drop_column_from_rows(rows_to_send, invalid_col)
                logger.warning(
                    "Retrying call_artifacts: nulling column '%s' (UUID/type mismatch)", invalid_col
                )
                continue

            break

        log_error_event(
            source="backend",
            severity="warning",
            error_type="artifact_table_sync_failed",
            message=f"Failed to sync artifacts to lovable table {table}",
            call_sid=self.call_sid,
            patient_id=self.patient_id or None,
            details=details,
            context={
                "table": table,
                "rows_count": len(rows_to_send),
                "script_name": self.script_name,
                "dropped_columns": dropped_columns,
                "nulled_columns": nulled_columns,
            },
        )

    @staticmethod
    def _resolve_ffmpeg_path() -> str | None:
        configured = (settings.ffmpeg_path or "").strip()
        if configured and Path(configured).exists():
            return configured

        for candidate in ("ffmpeg", "ffmpeg.exe"):
            resolved = shutil.which(candidate)
            if resolved:
                return resolved

        env_path = os.environ.get("FFMPEG_PATH", "").strip()
        if env_path and Path(env_path).exists():
            return env_path

        common_candidates = [
            Path.home() / "ffmpeg" / "bin" / "ffmpeg.exe",
            Path("C:/ffmpeg/bin/ffmpeg.exe"),
            Path("C:/Program Files/ffmpeg/bin/ffmpeg.exe"),
        ]
        for candidate in common_candidates:
            if candidate.exists():
                return str(candidate)
        return None

    @classmethod
    def _try_convert_to_mp3(cls, source: Path, target: Path):
        ffmpeg_path = cls._resolve_ffmpeg_path()
        if not ffmpeg_path:
            return {"status": "skipped", "reason": "ffmpeg_not_found"}
        if not source.exists() or source.stat().st_size <= 44:
            return {"status": "skipped", "reason": "source_empty"}

        result = subprocess.run(
            [
                ffmpeg_path,
                "-y",
                "-i",
                str(source),
                "-codec:a",
                "libmp3lame",
                "-q:a",
                "5",
                str(target),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and target.exists():
            return {
                "status": "ok",
                "output": str(target),
                "size_bytes": target.stat().st_size,
            }
        return {
            "status": "error",
            "returncode": result.returncode,
            "stderr": result.stderr[-500:],
        }

    @staticmethod
    def _delete_wav_if_mp3_exists(source: Path, target: Path):
        if source.exists() and target.exists() and target.stat().st_size > 0:
            with contextlib.suppress(Exception):
                source.unlink()

    def _should_discard_archive(self) -> bool:
        if self._transcript_lines:
            return False
        # In realtime mode check for leftover audio files
        if self.mode == "realtime":
            for artifact in [self.user_mp3_path, self.assistant_mp3_path,
                              self.user_wav_path, self.assistant_wav_path]:
                if artifact.exists() and artifact.stat().st_size > 256:
                    return False
        return True


def find_call_archive_dir(call_sid: str) -> Path | None:
    root = Path("audios")
    if not root.exists():
        return None

    direct = root / call_sid
    if direct.exists():
        return direct

    for path in root.glob(f"**/{call_sid}"):
        if path.is_dir():
            return path
    for path in root.glob(f"*__{call_sid}"):
        if path.is_dir():
            return path
    return None


def delete_call_archive(call_sid: str):
    archive_dir = find_call_archive_dir(call_sid)
    if archive_dir and archive_dir.exists():
        shutil.rmtree(archive_dir, ignore_errors=True)
        logger.info("Deleted local call archive for %s", call_sid)


def _read_call_json_meta(archive_dir: Path) -> dict:
    """Lee call.json del directorio del archive para recuperar metadatos del paciente."""
    call_json = archive_dir / "call.json"
    if call_json.exists():
        with contextlib.suppress(Exception):
            return json.loads(call_json.read_text(encoding="utf-8"))
    return {}


def _upload_recording_to_supabase(
    archive_dir: Path,
    call_sid: str,
    recording_path: Path,
    recording_sid: str | None,
) -> dict:
    """Sube el MP3 de grabación de Twilio a Supabase Storage y registra en call_artifacts."""
    # Obtener config de storage
    url = (settings.audio_storage_url or settings.lovable_cloud_url or "").rstrip("/")
    key = (
        settings.audio_storage_service_role_key
        or settings.supabase_service_role_key
        or settings.audio_storage_anon_key
        or settings.lovable_cloud_service_role_key
        or settings.lovable_cloud_anon_key
    )
    bucket = (settings.audio_storage_bucket or settings.lovable_storage_bucket or "audio-recordings").strip()

    if not (settings.audio_storage_enabled and url and key and bucket):
        logger.info("Supabase storage disabled — skipping recording upload for call %s", call_sid)
        return {}

    # Leer metadatos: primero call.json, luego el registro en memoria, luego el nombre de la carpeta
    from app.db.repositories import get_call_patient  # import tardío
    meta = _read_call_json_meta(archive_dir)
    registry = get_call_patient(call_sid) or {}
    patient_name = (
        meta.get("patient_name")
        or registry.get("patient_name")
        or (archive_dir.parent.name if archive_dir.parent.name != "sin_nombre" else None)
        or ""
    )
    patient_id = meta.get("patient_id") or registry.get("patient_id") or ""
    script_name = meta.get("script_name") or registry.get("script_name") or "default"

    # Ruta en el bucket: <patient_folder>/<call_sid>/twilio_recording.mp3
    relative_path = f"{archive_dir.parent.name}/{call_sid}/{recording_path.name}"
    endpoint = f"{url}/storage/v1/object/{bucket}/{relative_path}"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "audio/mpeg",
        "x-upsert": "true",
    }

    # 1. Subir MP3 a Supabase Storage
    public_url = ""
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(endpoint, headers=headers, content=recording_path.read_bytes())
            resp.raise_for_status()
        public_url = f"{url}/storage/v1/object/public/{bucket}/{relative_path}"
        logger.info("Twilio recording uploaded to Supabase Storage: %s", public_url)
    except Exception as exc:
        details = ""
        if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
            details = exc.response.text[:500]
        logger.warning("Failed to upload Twilio recording to Supabase for call %s: %s | %s", call_sid, exc, details)
        log_error_event(
            source="backend",
            severity="warning",
            error_type="twilio_recording_upload_failed",
            message="Failed to upload Twilio recording to Supabase Storage",
            call_sid=call_sid,
            details=details or str(exc),
            context={"recording_path": str(recording_path), "bucket": bucket},
        )
        return {"status": "error", "error": str(exc)}

    # 2. Registrar en call_artifacts (Lovable)
    lovable_url = (settings.lovable_cloud_url or "").rstrip("/")
    table = (settings.lovable_call_artifacts_table or "").strip()
    lovable_key = (
        settings.lovable_cloud_service_role_key
        or settings.supabase_service_role_key
        or settings.lovable_cloud_anon_key
    )
    if lovable_url and table and lovable_key:
        artifact_row = {
            "call_sid": call_sid,
            "patient_document_number": patient_id or None,
            "patient_name": patient_name or None,
            "script_name": script_name or None,
            "artifact_type": "twilio_recording_mp3",
            "storage_path": relative_path,
            "public_url": public_url,
            "content_type": "audio/mpeg",
            "size_bytes": recording_path.stat().st_size,
            "created_at": datetime.utcnow().isoformat(),
        }
        table_headers = {
            "apikey": lovable_key,
            "Authorization": f"Bearer {lovable_key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        }
        # Retry loop: elimina columnas desconocidas o nullifica columnas con tipo
        # incompatible (p. ej. patient_document_number esperado como uuid).
        rows_to_send = [artifact_row]
        dropped_columns: list[str] = []
        nulled_columns: list[str] = []
        for attempt in range(5):
            try:
                with httpx.Client(timeout=20.0) as client:
                    resp = client.post(
                        f"{lovable_url}/rest/v1/{table}",
                        headers=table_headers,
                        content=json.dumps(rows_to_send, ensure_ascii=False),
                    )
                if resp.status_code in (200, 201):
                    logger.info("Twilio recording artifact registered in Lovable for call %s", call_sid)
                    break
                details = resp.text[:500]
                # Columna desconocida → eliminarla y reintentar
                missing = CallAudioArchive._extract_missing_column(details)
                if missing and missing not in dropped_columns:
                    dropped_columns.append(missing)
                    rows_to_send = [{k: v for k, v in row.items() if k not in dropped_columns}
                                    for row in rows_to_send]
                    logger.warning(
                        "Retrying call_artifacts (Twilio rec) without column '%s' (call=%s)",
                        missing, call_sid,
                    )
                    continue
                # Tipo incompatible (UUID) → nullificar la columna y reintentar
                invalid_col = CallAudioArchive._extract_invalid_type_column(details, rows_to_send)
                if invalid_col and invalid_col not in nulled_columns and invalid_col not in dropped_columns:
                    nulled_columns.append(invalid_col)
                    rows_to_send = CallAudioArchive._drop_column_from_rows(rows_to_send, invalid_col)
                    logger.warning(
                        "Retrying call_artifacts (Twilio rec) nulling column '%s' (UUID/type mismatch, call=%s)",
                        invalid_col, call_sid,
                    )
                    continue
                logger.warning(
                    "Failed to sync Twilio recording artifact to Lovable for call %s (attempt %d): %s",
                    call_sid, attempt, details,
                )
                break
            except Exception as exc:
                exc_details = ""
                if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
                    exc_details = exc.response.text[:500]
                logger.warning(
                    "Failed to sync Twilio recording artifact to Lovable for call %s: %s | %s",
                    call_sid, exc, exc_details,
                )
                break

    return {"status": "ok", "public_url": public_url, "path": relative_path}


def store_twilio_recording(
    call_sid: str,
    recording_url: str,
    recording_sid: str | None = None,
    recording_status: str | None = None,
):
    if not call_sid or not recording_url:
        return None

    archive_dir = find_call_archive_dir(call_sid)
    if archive_dir is None:
        # Intentar obtener el nombre del paciente desde el registro (poblado en /voice o /outbound)
        from app.db.repositories import get_call_patient  # import tardío para evitar circular
        registry = get_call_patient(call_sid)
        if registry and registry.get("patient_name"):
            slug = CallAudioArchive._slugify_patient_name(registry["patient_name"])
            folder = slug or "sin_nombre"
        else:
            folder = "sin_nombre"
        archive_dir = Path("audios") / folder / call_sid
        archive_dir.mkdir(parents=True, exist_ok=True)

    target_path = archive_dir / "twilio_recording.mp3"
    download_url = recording_url if recording_url.endswith(".mp3") else f"{recording_url}.mp3"
    auth = (settings.twilio_account_sid, settings.twilio_auth_token)

    try:
        with httpx.Client(timeout=60.0, auth=auth) as client:
            response = client.get(download_url)
            response.raise_for_status()
        target_path.write_bytes(response.content)

        meta_path = archive_dir / "twilio_recording_meta.json"
        meta_path.write_text(
            json.dumps(
                {
                    "call_sid": call_sid,
                    "recording_sid": recording_sid,
                    "recording_status": recording_status,
                    "recording_url": download_url,
                    "saved_at": datetime.utcnow().isoformat(),
                    "size_bytes": target_path.stat().st_size,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        logger.info("Downloaded Twilio recording for call %s to %s", call_sid, target_path)

        # Subir MP3 a Supabase Storage y registrar en call_artifacts
        upload_result = _upload_recording_to_supabase(archive_dir, call_sid, target_path, recording_sid)
        if upload_result.get("status") == "ok":
            # Actualizar el meta con la URL pública
            meta_path.write_text(
                json.dumps(
                    {
                        "call_sid": call_sid,
                        "recording_sid": recording_sid,
                        "recording_status": recording_status,
                        "recording_url": download_url,
                        "saved_at": datetime.utcnow().isoformat(),
                        "size_bytes": target_path.stat().st_size,
                        "public_url": upload_result.get("public_url"),
                        "storage_path": upload_result.get("path"),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

        return str(target_path)
    except Exception as exc:
        logger.warning("Failed to download Twilio recording for call %s: %s", call_sid, exc)
        log_error_event(
            source="backend",
            severity="warning",
            error_type="twilio_recording_download_failed",
            message="Failed to download Twilio recording",
            call_sid=call_sid,
            details=str(exc),
            context={
                "recording_sid": recording_sid,
                "recording_status": recording_status,
                "recording_url": download_url,
            },
        )
        return None
