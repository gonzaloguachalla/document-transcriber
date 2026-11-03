# Lector de documentos Word (.docx) con voz en español

Aplicación web local: subes un `.docx`, ves el texto por oraciones y lo escuchas con voces neuronales de
[Kokoro](https://github.com/thewh1teagle/kokoro-onnx) y [Piper](https://github.com/OHF-Voice/piper1-gpl). 100 % offline una vez construida la imagen.

El contenedor no tiene salida de audio: el servidor genera WAV y el navegador lo reproduce con `<audio>`.

## Estructura

```
.
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── requirements.txt
└── app/
    ├── main.py        # FastAPI: endpoints, validación, caché
    ├── config.py      # variables de entorno
    ├── extraccion.py  # python-docx, limpieza, división en oraciones
    ├── tts.py         # Kokoro + Piper, gestor de voces, unión de WAV
    ├── almacen.py     # documentos/audio en disco y limpieza por antigüedad
    └── static/        # index.html, estilos.css, app.js
```

## Construir y ejecutar

```bash
docker compose up --build
```

Abre <http://localhost:8000>. La primera construcción descarga los modelos (~0,5 GB en total) desde Hugging Face;
después no se necesita internet. Para segundo plano: `docker compose up -d --build`; para detener: `docker compose down`
(añade `-v` para borrar también la caché de audio).

## Variables de entorno

Se pueden definir en un archivo `.env` (copia `.env.example`) o en el entorno.

| Variable | Defecto | Descripción |
|---|---|---|
| `PORT` | `8000` | Puerto (interno y publicado) |
| `PIPER_VOICE` | `kokoro-ef_dora` | Voz por defecto |
| `PIPER_VOICES` | las 4 de Piper | Voces de Piper a instalar (se descargan **al construir**) |
| `MAX_UPLOAD_MB` | `10` | Tamaño máximo del .docx |
| `CACHE_TTL_HOURS` | `24` | Horas antes de borrar un documento y su audio |

## Voces disponibles

La interfaz incluye un selector de **Voz** (se recuerda en el navegador; al cambiarla durante la lectura, continúa con la nueva voz).
El audio se cachea por voz. La imagen instala tres motores, todos locales:

**Kokoro** ([kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx), modelo v1.0 fp32, licencia Apache-2.0) — voz por defecto: `kokoro-ef_dora`

| ID | Descripción |
|---|---|
| `kokoro-ef_dora` | Dora (voz femenina de Kokoro) |
| `kokoro-em_alex` | Alex (voz masculina de Kokoro) |
| `kokoro-dora75-alex25` | Mezcla: 75 % Dora + 25 % Alex |
| `kokoro-alex75-dora25` | Mezcla: 75 % Alex + 25 % Dora |

Kokoro solo trae tres voces en español (`ef_dora`, `em_alex`, `em_santa`); las mezclas se calculan promediando los vectores de estilo
y no son voces oficiales del modelo. `em_santa` y sus mezclas no se incluyeron. No está confirmado si su español es latino o de España.

**Supertonic 3** ([Supertone/supertonic-3](https://huggingface.co/Supertone/supertonic-3), ~99 M parámetros, ONNX en CPU; SDK MIT, pesos bajo licencia **OpenRAIL** con restricciones de uso: léela antes de redistribuir)

| ID | Descripción |
|---|---|
| `supertonic-f1`, `-f2`, `-f3`, `-m1`, `-m2`, `-m3` | Voces predefinidas de Supertonic, en español |

Supertonic solo tiene voces predefinidas (F1–F5, M1–M5) y el idioma `es`; no permite elegir acento (México, Argentina…). Para añadir otra (F4, F5, M4, M5),
agrégala a `VOCES_SUPERTONIC` en `app/tts.py`. El modelo (~380 MB) se descarga al construir; en ejecución no usa internet.

**Piper** (voces del catálogo oficial `rhasspy/piper-voices`)

| ID | Descripción |
|---|---|
| `es_ES-davefx-medium` | España, calidad media |
| `es_MX-claude-high` | México, calidad alta |

La lista que ve la app es la de los archivos presentes en la imagen (`GET /api/voces`).

### Cambiar o añadir voces

- **Piper:** `PIPER_VOICES` (lista separada por espacios) define las instaladas; se descargan al construir, así que hay que reconstruir:
  `PIPER_VOICES="es_ES-davefx-medium es_MX-claude-high" docker compose up --build`. Catálogo:
  <https://huggingface.co/rhasspy/piper-voices/tree/main/es> (también existe `es_AR-daniela-high`, ~114 MB, no incluida).
- **Kokoro:** el modelo se descarga en el build con suma SHA-256 verificada (ver `Dockerfile`, ~310 MB). Las voces se definen en `VOCES_KOKORO` de `app/tts.py`.
- `PIPER_VOICE` fija la voz por defecto (puede ser una de Kokoro o de Piper).

## Endpoints

- `GET /` interfaz · `GET /health` estado (503 si la voz no cargó)
- `POST /api/documento` (campo `archivo`) → `{id, oraciones}`
- `GET /api/voces` → voces instaladas y voz por defecto
- `GET /api/audio/{id}/{indice}?voz=ID` → WAV de una oración
- `GET /api/audio/{id}/completo?voz=ID` → WAV completo (genera lo que falte)

`voz` es opcional (usa la voz por defecto).

## Decisiones de diseño

- Un audio por oración (las oraciones de más de ~300 caracteres se parten por comas); el navegador precarga las 2 siguientes.
- La velocidad (0.75x–2x) se aplica en el navegador (`playbackRate`), por lo que no regenera audio.
- El `.docx` se procesa en memoria y **no se guarda**; en disco solo hay un id aleatorio, las oraciones y los WAV (volumen `/data`).
- Validaciones: extensión, tamaño (lectura por bloques), firma ZIP, tamaño descomprimido, estructura del docx.
- El contenedor corre como usuario no root (uid 10001).

## Solución de problemas

- **El build falla al descargar la voz**: requiere internet solo en el build; revisa proxy/firewall y reintenta.
- **`/health` devuelve 503**: la voz no cargó; mira `docker compose logs`. Suele ser un `PIPER_VOICE` mal escrito (el build ya falla en ese caso).
- **Puerto ocupado**: `PORT=8080 docker compose up --build`.
- **Primera oración lenta**: la primera síntesis carga el modelo en CPU; las siguientes son rápidas y quedan en caché.
- **«Documento no encontrado o expirado»**: pasó el TTL o se borró el volumen; sube el archivo de nuevo.
- **El .doc antiguo no funciona**: solo se admite `.docx` (guárdalo como .docx desde Word).
- **No se lee texto en cuadros de texto, encabezados, pies, notas ni imágenes**: solo se extraen párrafos y tablas del cuerpo.
- **Permisos en volumen bind-mount**: usa el volumen con nombre del compose; si montas una carpeta, debe ser escribible por el uid 10001.

## Qué se verificó y qué no

Verificado: API de `piper-tts==1.8.0` y `kokoro-onnx==0.6.1` (`PiperVoice.load`, `synthesize_wav`, `python -m piper.download_voices`);
build de la imagen; `/health`; subida de un .docx con párrafos y tabla; audio por oración y completo con las 4 voces de Kokoro y con Piper (Piper 22050 Hz, Kokoro 24000 Hz, mono); oración de ~280 caracteres; síntesis con `--network none`;
rechazo de extensión inválida y de archivo corrupto; ejecución como uid 10001.
**No verificado**: el comportamiento del frontend en navegadores (no se probó con un navegador real), el funcionamiento
completamente sin red en ejecución (la app no hace llamadas externas, pero no se aisló la red), el selector de voz en navegador,
la calidad/naturalidad y el acento de las voces (no se escucharon), y la política de licencias de cada voz (revisa la tarjeta de la voz elegida). Piper 1.x (`piper-tts`) se distribuye bajo GPL-3.0; revisa también la licencia de cada modelo.

## Pruebas manuales

1. `docker compose up --build` termina y <http://localhost:8000/health> responde `{"estado":"ok",...}`.
2. Sube un .docx con párrafos y una tabla: aparece el texto, una oración por bloque (incluida la tabla).
3. «Reproducir»: suena en menos de unos segundos y se resalta la oración actual; avanza sola a la siguiente.
4. «Pausar» / «Continuar» / «Detener» funcionan; la barra de progreso avanza.
5. Cambia de voz en el selector durante la lectura: la oración actual se relee con la nueva voz y suena distinta.
5b. Cambia la velocidad a 2x y 0.75x durante la lectura: cambia al instante.
6. Haz clic en una oración del medio: la lectura empieza ahí.
7. «Descargar audio (WAV)» descarga un archivo que se reproduce completo.
8. Errores: sube un `.txt`, un `.docx` vacío, un archivo >10 MB y un archivo renombrado a .docx: cada uno muestra un mensaje claro.
9. `docker compose restart` y reproducir una oración ya leída (sigue en la caché, sin regenerar); reabre desde otra pestaña con el mismo id vía `/api/audio/{id}/0`.
10. `docker compose exec lector id -u` devuelve `10001`.
