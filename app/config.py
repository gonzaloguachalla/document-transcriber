"""Configuración leída de variables de entorno."""
import os
from pathlib import Path

PUERTO = int(os.getenv("PORT", "8000"))
VOZ_PIPER = os.getenv("PIPER_VOICE", "kokoro-ef_dora")  # voz por defecto
DIR_VOCES = Path(os.getenv("PIPER_VOICES_DIR", "/opt/voces"))
DIR_KOKORO = Path(os.getenv("KOKORO_DIR", "/opt/kokoro"))
DIR_DATOS = Path(os.getenv("DATA_DIR", "/data"))
MAX_BYTES = int(float(os.getenv("MAX_UPLOAD_MB", "10")) * 1024 * 1024)
# Tamaño máximo descomprimido permitido dentro del .docx (protección contra zip bombs).
MAX_DESCOMPRIMIDO = MAX_BYTES * 20
MAX_ORACIONES = int(os.getenv("MAX_SENTENCES", "5000"))
# Horas que se conserva un documento (y su audio) antes de borrarlo.
TTL_HORAS = float(os.getenv("CACHE_TTL_HOURS", "24"))
