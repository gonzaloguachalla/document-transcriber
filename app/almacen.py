"""Almacenamiento en disco de documentos (oraciones) y caché de audio, con limpieza por antigüedad."""
import json
import re
import shutil
import time
import uuid
from pathlib import Path

_RE_ID = re.compile(r"^[0-9a-f]{32}$")


class Almacen:
    def __init__(self, raiz: Path, ttl_horas: float):
        self.raiz = raiz
        self.ttl = ttl_horas * 3600
        self.raiz.mkdir(parents=True, exist_ok=True)

    def _dir(self, doc_id: str) -> Path | None:
        if not _RE_ID.match(doc_id):
            return None
        return self.raiz / doc_id

    def crear(self, oraciones: list[str]) -> str:
        """Guarda las oraciones bajo un id aleatorio; el nombre original nunca se usa en disco."""
        doc_id = uuid.uuid4().hex
        d = self.raiz / doc_id
        (d / "audio").mkdir(parents=True)
        (d / "oraciones.json").write_text(json.dumps(oraciones, ensure_ascii=False), encoding="utf-8")
        return doc_id

    def oraciones(self, doc_id: str) -> list[str] | None:
        d = self._dir(doc_id)
        if d is None or not (d / "oraciones.json").is_file():
            return None
        d_json = d / "oraciones.json"
        d_json.touch()  # marca uso reciente para el TTL
        return json.loads(d_json.read_text(encoding="utf-8"))

    def ruta_audio(self, doc_id: str, voz: str, nombre: str) -> Path:
        # 'voz' ya fue validada contra la lista de voces instaladas.
        return self.raiz / doc_id / "audio" / voz / f"{nombre}.wav"

    def limpiar_antiguos(self) -> int:
        limite = time.time() - self.ttl
        borrados = 0
        for d in self.raiz.iterdir():
            try:
                if d.is_dir() and d.stat().st_mtime < limite and \
                        (d / "oraciones.json").stat().st_mtime < limite:
                    shutil.rmtree(d, ignore_errors=True)
                    borrados += 1
            except OSError:
                continue
        return borrados
