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
import wave
from datetime import datetime
from pathlib import Path

import httpx

from app.config import get_settings


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
    ):
        self.call_sid = call_sid
        self.patient_name = patient_name or ""
        self.patient_id = patient_id or ""
        self.script_name = script_name or "default"
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

        self._user_wav = self._open_wave(self.user_wav_path)
        self._assistant_wav = self._open_wave(self.assistant_wav_path)
        self._transcript_lines: list[dict] = []

    @staticmethod
    def _slugify_patient_name(value: str) -> str:
        normalized = re.sub(r"\s+", "_", (value or "").strip())
        normalized = re.sub(r"[^A-Za-z0-9_]+", "", normalized)
        return normalized[:80]

    def _open_wave(self, path: Path):
        wav_file = wave.open(str(path), "wb")
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(8000)
        return wav_file

    def append_user_audio(self, payload_b64: str):
        pcm = self._decode_ulaw_payload(payload_b64)
        self._user_wav.writeframes(pcm)

    def append_assistant_audio(self, payload_b64: str):
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
        self._user_wav.close()
        self._assistant_wav.close()
        self._conversion_results["user_mp3"] = self._try_convert_to_mp3(self.user_wav_path, self.user_mp3_path)
        self._conversion_results["assistant_mp3"] = self._try_convert_to_mp3(
            self.assistant_wav_path,
            self.assistant_mp3_path,
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
            return {
                "status": "error",
                "path": relative_path,
                "error": str(exc),
                "details": details,
            }

    @staticmethod
    def _dataset_headers() -> dict[str, str]:
        key = settings.external_viaggio_dataset_api_key or settings.external_viaggio_service_role_key or settings.external_viaggio_anon_key
        return {
            "Content-Type": "application/json",
            "x-api-key": key,
        }

    def _sync_transcripts_to_table(self):
        if not self._transcript_lines:
            return

        endpoint = (settings.external_viaggio_call_transcripts_dataset_url or "").strip()
        key = settings.external_viaggio_dataset_api_key or settings.external_viaggio_service_role_key or settings.external_viaggio_anon_key
        if not (endpoint and key):
            return

        records = [
            {
                "patient_internal_id": self.patient_id or "",
                "data": {
                    "call_sid": self.call_sid,
                    "patient_id": self.patient_id or None,
                    "patient_name": self.patient_name or None,
                    "script_name": self.script_name or None,
                    "role": item.get("role"),
                    "text": item.get("text"),
                    "created_at": item.get("created_at"),
                },
                "source": settings.external_viaggio_call_transcripts_source or "sensor",
                "source_metadata": {
                    "device_id": settings.external_viaggio_call_transcripts_device_id or "CALL-BOT-001",
                },
            }
            for item in self._transcript_lines
            if item.get("text")
        ]
        if not records:
            return

        payload = {"records": records}
        try:
            with httpx.Client(timeout=20.0) as client:
                response = client.post(
                    endpoint,
                    headers=self._dataset_headers(),
                    content=json.dumps(payload, ensure_ascii=False),
                )
                response.raise_for_status()
            logger.info(
                "Synced %d transcript lines to Viaggio dataset for call %s",
                len(records),
                self.call_sid,
            )
        except Exception as exc:
            logger.warning(
                "Failed to sync transcript lines to Viaggio dataset for call %s: %s",
                self.call_sid,
                exc,
            )

    @staticmethod
    def _lovable_table_headers() -> dict[str, str]:
        key = (
            settings.lovable_cloud_service_role_key
            or settings.lovable_cloud_anon_key
        )
        return {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        }

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
                    "patient_id": self.patient_id or None,
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
        try:
            with httpx.Client(timeout=20.0) as client:
                response = client.post(
                    endpoint,
                    headers=self._lovable_table_headers(),
                    content=json.dumps(rows, ensure_ascii=False),
                )
                response.raise_for_status()
            logger.info(
                "Synced %d artifact rows to lovable table %s for call %s",
                len(rows),
                table,
                self.call_sid,
            )
        except Exception as exc:
            logger.warning(
                "Failed to sync artifacts to lovable table %s for call %s: %s",
                table,
                self.call_sid,
                exc,
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
        artifacts = [self.user_mp3_path, self.assistant_mp3_path, self.user_wav_path, self.assistant_wav_path]
        for artifact in artifacts:
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
