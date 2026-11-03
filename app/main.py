"""API FastAPI: sube un .docx, extrae el texto y sirve audio WAV generado con Piper."""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .almacen import Almacen
from .extraccion import DocumentoInvalido, DocumentoVacio, normalizar_para_voz, procesar_docx
from .tts import ErrorTTS, GestorVoces, unir_wavs

log = logging.getLogger("tts")
ESTATICOS = Path(__file__).parent / "static"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

almacen = Almacen(config.DIR_DATOS / "docs", config.TTL_HORAS)
estado: dict = {"voces": None, "error_tts": None}


async def _limpieza_periodica():
    while True:
        try:
            n = await asyncio.to_thread(almacen.limpiar_antiguos)
            if n:
                log.info("Documentos antiguos eliminados: %d", n)
        except Exception:
            log.exception("Fallo en la limpieza")
        await asyncio.sleep(3600)


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        gestor = GestorVoces(config.DIR_VOCES, config.DIR_KOKORO, config.VOZ_PIPER)
        await asyncio.to_thread(gestor.obtener, None)  # precarga la voz por defecto
        estado["voces"] = gestor
    except Exception as e:
        estado["error_tts"] = str(e)
        log.exception("No se pudo cargar la voz de Piper")
    tarea = asyncio.create_task(_limpieza_periodica())
    yield
    tarea.cancel()


app = FastAPI(title="Lector de documentos Word", lifespan=lifespan)


@app.get("/health")
def health():
    ok = estado["voces"] is not None
    return JSONResponse(
        {"estado": "ok" if ok else "error", "voz": estado["voces"].defecto if ok else config.VOZ_PIPER, "max_mb": config.MAX_BYTES / (1024 * 1024), "error": estado["error_tts"]},
        status_code=200 if ok else 503,
    )


@app.get("/api/voces")
def listar_voces():
    g = estado["voces"]
    if g is None:
        raise HTTPException(503, f"El motor de voz no está disponible: {estado['error_tts']}")
    return {"defecto": g.defecto, "voces": [{"id": v, "nombre": g.nombres[v]} for v in g.disponibles]}


@app.get("/")
def interfaz():
    return FileResponse(ESTATICOS / "index.html")


@app.post("/api/documento")
async def subir_documento(archivo: UploadFile = File(...)):
    nombre = (archivo.filename or "").strip().lower()
    if not nombre.endswith(".docx"):
        raise HTTPException(400, "Solo se admiten archivos Word con extensión .docx.")

    partes, total = [], 0
    while chunk := await archivo.read(1024 * 1024):
        total += len(chunk)
        if total > config.MAX_BYTES:
            raise HTTPException(413, f"El archivo supera el máximo de {config.MAX_BYTES // (1024 * 1024)} MB.")
        partes.append(chunk)
    contenido = b"".join(partes)
    if not contenido.startswith(b"PK"):
        raise HTTPException(400, "El archivo no es un documento .docx válido.")

    try:
        oraciones = await asyncio.to_thread(procesar_docx, contenido, config.MAX_DESCOMPRIMIDO)
    except DocumentoInvalido as e:
        raise HTTPException(400, str(e))
    except DocumentoVacio as e:
        raise HTTPException(422, str(e))
    if len(oraciones) > config.MAX_ORACIONES:
        raise HTTPException(413, f"El documento tiene demasiadas oraciones (máximo {config.MAX_ORACIONES}).")

    doc_id = await asyncio.to_thread(almacen.crear, oraciones)
    return {"id": doc_id, "oraciones": oraciones}


def _wav(ruta: Path, descarga: str | None = None):
    return FileResponse(ruta, media_type="audio/wav", filename=descarga,
                        headers={"Cache-Control": "private, max-age=3600"})


def _generar(doc_id: str, indice: int, voz: str | None) -> Path:
    oraciones = almacen.oraciones(doc_id)
    if oraciones is None:
        raise HTTPException(404, "Documento no encontrado o expirado. Súbelo de nuevo.")
    if not 0 <= indice < len(oraciones):
        raise HTTPException(404, "Oración fuera de rango.")
    if estado["voces"] is None:
        raise HTTPException(503, f"El motor de voz no está disponible: {estado['error_tts']}")
    voz = voz or estado["voces"].defecto
    if voz not in estado["voces"].disponibles:
        raise HTTPException(400, f"La voz '{voz}' no está disponible.")
    ruta = almacen.ruta_audio(doc_id, voz, str(indice))
    if ruta.is_file():
        return ruta
    ruta.parent.mkdir(parents=True, exist_ok=True)
    try:
        datos = estado["voces"].obtener(voz).sintetizar_wav(normalizar_para_voz(oraciones[indice]))
    except ErrorTTS as e:
        raise HTTPException(500, str(e))
    tmp = ruta.with_suffix(".tmp")
    tmp.write_bytes(datos)
    tmp.replace(ruta)
    return ruta


# Ruta fija declarada antes que la parametrizada.
@app.get("/api/audio/{doc_id}/completo")
def audio_completo(doc_id: str, voz: str | None = None):
    oraciones = almacen.oraciones(doc_id)
    if oraciones is None:
        raise HTTPException(404, "Documento no encontrado o expirado. Súbelo de nuevo.")
    rutas = [_generar(doc_id, i, voz) for i in range(len(oraciones))]
    destino = rutas[0].parent / "completo.wav"
    if not destino.is_file():
        unir_wavs(rutas, destino)
    return _wav(destino, "documento.wav")


@app.get("/api/audio/{doc_id}/{indice}")
def audio_oracion(doc_id: str, indice: int, voz: str | None = None):
    return _wav(_generar(doc_id, indice, voz))


app.mount("/static", StaticFiles(directory=ESTATICOS), name="static")
