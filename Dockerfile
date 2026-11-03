FROM python:3.12-slim

ARG PIPER_VOICE=kokoro-ef_dora
ARG PIPER_VOICES="es_ES-davefx-medium es_MX-claude-high"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIPER_VOICE=${PIPER_VOICE} \
    PIPER_VOICES_DIR=/opt/voces \
    KOKORO_DIR=/opt/kokoro \
    SUPERTONIC_CACHE_DIR=/opt/supertonic \
    DATA_DIR=/data \
    PORT=8000

RUN useradd --system --uid 10001 --create-home app \
    && mkdir -p /data /opt/voces \
    && chown app:app /data

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# La voz se descarga en el build: en ejecución no se necesita internet.
RUN python -m piper.download_voices --download-dir /opt/voces ${PIPER_VOICES} \
    && chmod -R a+rX /opt/voces

# Modelo Kokoro v1.0 (fp32) y sus voces, con suma de verificación.
RUN mkdir -p /opt/kokoro && python - <<'PY'
import hashlib, urllib.request
base = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
for nombre, destino, sha in [
    ("kokoro-v1.0.onnx", "kokoro-v1.0.onnx", "7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5"),
    ("voices-v1.0.bin", "voices-v1.0.bin", "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d"),
]:
    ruta = "/opt/kokoro/" + destino
    urllib.request.urlretrieve(base + nombre, ruta)
    h = hashlib.sha256(open(ruta, "rb").read()).hexdigest()
    assert h == sha, f"SHA-256 inesperado para {nombre}: {h}"
PY
RUN chmod -R a+rX /opt/kokoro

# Supertonic 3 (pesos OpenRAIL): modelo ONNX descargado en el build; en ejecución no se usa internet.
RUN python -c "from supertonic import TTS; TTS(auto_download=True)" \
    && rm -rf /opt/supertonic/img /opt/supertonic/audio_samples \
    && chmod -R a+rX /opt/supertonic

COPY app ./app

USER app
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
  CMD python -c "import os,urllib.request as u; u.urlopen('http://127.0.0.1:%s/health' % os.environ['PORT'])"
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
