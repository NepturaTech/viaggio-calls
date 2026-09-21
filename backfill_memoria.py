"""Backfill de `call_logs.memoria` desde los transcript.txt de Storage.

    python backfill_memoria.py rutas.txt           # ENSAYO: imprime las notas, no escribe
    python backfill_memoria.py rutas.txt --write   # escribe en call_logs por call_sid

`rutas.txt`: una ruta del bucket por linea (`Paciente/CAxxxx/transcript.txt`).
Se sacan por SQL de `storage.objects` cruzado con `call_logs`, asi el script no
tiene que recorrer el bucket (la conexion se corta hacia los ~140 archivos).
"""
import asyncio
import sys

import httpx

from app.config import get_settings
from app.services import call_memory_service as cms


async def main(paths_file: str, write: bool) -> None:
    s = get_settings()
    base = f"{s.external_viaggio_url.rstrip('/')}/storage/v1/object/{s.audio_storage_bucket}"
    headers = {"Authorization": f"Bearer {s.supabase_service_role_key}", "apikey": s.supabase_service_role_key}
    paths = [l.strip() for l in open(paths_file, encoding="utf-8") if l.strip()]
    saved = skipped = failed = 0
    with httpx.Client(timeout=20.0, headers=headers) as http:
        for path in paths:
            call_sid = path.split("/")[1]
            try:
                resp = http.get(f"{base}/{path}")
                resp.raise_for_status()
                history = cms.parse_transcript(resp.content.decode("utf-8", errors="replace"))
                memoria = await cms.summarize_call(history, None)
            except Exception as exc:  # una ruta mala no tumba el lote
                failed += 1
                print(f"!! {call_sid}: {exc}")
                continue
            if not memoria:
                skipped += 1
                print(f"-- {call_sid}: sin contenido util ({len(history)} turnos)")
                continue
            print(f"\n== {call_sid} ({len(history)} turnos)\n{memoria}")
            try:
                if write and not cms._patch_memoria(call_sid, memoria):
                    raise RuntimeError("el PATCH no devolvio ninguna fila")
                saved += 1
            except Exception as exc:
                failed += 1
                print(f"!! {call_sid}: no se escribio: {exc}")
    print(f"\n{'ESCRITAS' if write else 'ENSAYO, nada escrito'}: notas={saved} sin_contenido={skipped} fallos={failed}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], "--write" in sys.argv))
