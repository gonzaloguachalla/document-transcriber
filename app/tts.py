"""Síntesis de voz con Piper, Kokoro y Supertonic. Genera WAV en memoria; el servidor nunca reproduce audio."""
import io
import threading
import wave
from pathlib import Path

from piper import PiperVoice


class ErrorTTS(Exception):
    pass


class Sintetizador:
    def __init__(self, nombre_voz: str, dir_voces: Path):
        modelo = dir_voces / f"{nombre_voz}.onnx"
        config = dir_voces / f"{nombre_voz}.onnx.json"
        if not modelo.is_file() or not config.is_file():
            raise ErrorTTS(f"No se encontró la voz '{nombre_voz}' en {dir_voces}.")
        self.nombre = nombre_voz
        self._voz = PiperVoice.load(modelo, config_path=config)
        # onnxruntime ya usa varios hilos por inferencia; se serializa para no saturar la CPU.
        self._lock = threading.Lock()

    def sintetizar_wav(self, texto: str) -> bytes:
        buf = io.BytesIO()
        try:
            with self._lock, wave.open(buf, "wb") as wav:
                self._voz.synthesize_wav(texto, wav)
        except Exception as e:
            raise ErrorTTS(f"Fallo al sintetizar el audio: {e}") from e
        return buf.getvalue()


# Voces de Kokoro: id -> (nombre, {voz base: peso}). Las mezclas promedian los vectores de estilo.
VOCES_KOKORO = {
    "kokoro-ef_dora": ("Dora (Kokoro)", {"ef_dora": 1.0}),
    "kokoro-em_alex": ("Alex (Kokoro)", {"em_alex": 1.0}),
    "kokoro-dora75-alex25": ("Dora 75 % + Alex 25 % (Kokoro)", {"ef_dora": 0.75, "em_alex": 0.25}),
    "kokoro-alex75-dora25": ("Alex 75 % + Dora 25 % (Kokoro)", {"em_alex": 0.75, "ef_dora": 0.25}),
}


class MotorKokoro:
    """Un único modelo Kokoro compartido por todas sus voces."""

    def __init__(self, dir_kokoro: Path):
        modelo, voces = dir_kokoro / "kokoro-v1.0.onnx", dir_kokoro / "voices-v1.0.bin"
        if not modelo.is_file() or not voces.is_file():
            raise ErrorTTS(f"No se encontró el modelo Kokoro en {dir_kokoro}.")
        from kokoro_onnx import Kokoro
        self._k = Kokoro(str(modelo), str(voces))
        self._lock = threading.Lock()

    def sintetizar_wav(self, texto: str, mezcla: dict[str, float]) -> bytes:
        import numpy as np
        try:
            estilo = sum(self._k.get_voice_style(v) * w for v, w in mezcla.items())
            with self._lock:
                audio, sr = self._k.create(texto, voice=estilo, speed=1.0, lang="es")
            pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(sr)
                wav.writeframes(pcm.tobytes())
            return buf.getvalue()
        except Exception as e:
            raise ErrorTTS(f"Fallo al sintetizar el audio: {e}") from e


# Voces de Supertonic 3 (ONNX, CPU): id -> (nombre, voz predefinida). El idioma es siempre español.
VOCES_SUPERTONIC = {
    **{f"supertonic-{v.lower()}": (f"{v} (Supertonic)", v) for v in ("F1", "F2", "F3", "M1", "M2", "M3")},
}


class MotorSupertonic:
    """Un único modelo Supertonic compartido por todas sus voces."""

    def __init__(self):
        try:
            from supertonic import TTS
            self._tts = TTS(auto_download=False)
        except Exception as e:
            raise ErrorTTS(f"No se pudo cargar Supertonic: {e}") from e
        self._estilos: dict[str, object] = {}
        self._lock = threading.Lock()

    def sintetizar_wav(self, texto: str, voz: str) -> bytes:
        import numpy as np
        try:
            with self._lock:
                if voz not in self._estilos:
                    self._estilos[voz] = self._tts.get_voice_style(voice_name=voz)
                audio, _ = self._tts.synthesize(texto, voice_style=self._estilos[voz], lang="es")
            pcm = (np.clip(np.asarray(audio, dtype=np.float32).reshape(-1), -1.0, 1.0) * 32767).astype(np.int16)
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(self._tts.sample_rate)
                wav.writeframes(pcm.tobytes())
            return buf.getvalue()
        except Exception as e:
            raise ErrorTTS(f"Fallo al sintetizar el audio: {e}") from e


def _supertonic_disponible() -> bool:
    import importlib.util
    return importlib.util.find_spec("supertonic") is not None


def _nombre_piper(v: str) -> str:
    """'es_MX-claude-high' -> 'Claude (México, calidad alta) (Piper)'."""
    try:
        loc, nombre, calidad = v.split("-", 2)
    except ValueError:
        return v
    pais = {"es_ES": "España", "es_MX": "México", "es_AR": "Argentina"}.get(loc, loc)
    cal = {"x_low": "muy baja", "low": "baja", "medium": "media", "high": "alta"}.get(calidad, calidad)
    return f"{nombre.capitalize()} ({pais}, calidad {cal}) (Piper)"


class _VozKokoro:
    """Adaptador con la misma interfaz que Sintetizador."""

    def __init__(self, motor: MotorKokoro, mezcla: dict[str, float]):
        self._motor, self._mezcla = motor, mezcla

    def sintetizar_wav(self, texto: str) -> bytes:
        return self._motor.sintetizar_wav(texto, self._mezcla)


class _VozSupertonic:
    """Adaptador con la misma interfaz que Sintetizador."""

    def __init__(self, motor: MotorSupertonic, voz: str):
        self._motor, self._voz = motor, voz

    def sintetizar_wav(self, texto: str) -> bytes:
        return self._motor.sintetizar_wav(texto, self._voz)


class GestorVoces:
    """Descubre las voces instaladas (Kokoro y Piper) y las carga bajo demanda."""

    def __init__(self, dir_piper: Path, dir_kokoro: Path, defecto: str):
        self.dir = dir_piper
        self.dir_kokoro = dir_kokoro
        self.nombres: dict[str, str] = {}
        if (dir_kokoro / "kokoro-v1.0.onnx").is_file() and (dir_kokoro / "voices-v1.0.bin").is_file():
            self.nombres.update({k: v[0] for k, v in VOCES_KOKORO.items()})
        if _supertonic_disponible():
            self.nombres.update({k: v[0] for k, v in VOCES_SUPERTONIC.items()})
        for p in sorted(dir_piper.glob("*.onnx")):
            nombre = p.name[: -len(".onnx")]
            if (dir_piper / f"{p.name}.json").is_file():
                self.nombres[nombre] = _nombre_piper(nombre)
        if not self.nombres:
            raise ErrorTTS("No hay voces instaladas.")
        self.disponibles = list(self.nombres)
        self.defecto = defecto if defecto in self.nombres else self.disponibles[0]
        self._cargadas: dict[str, object] = {}
        self._motor_kokoro: MotorKokoro | None = None
        self._motor_supertonic: MotorSupertonic | None = None
        self._lock = threading.Lock()

    def obtener(self, nombre: str | None):
        nombre = nombre or self.defecto
        if nombre not in self.nombres:
            raise ErrorTTS(f"La voz '{nombre}' no está instalada.")
        with self._lock:
            if nombre not in self._cargadas:
                if nombre in VOCES_SUPERTONIC:
                    if self._motor_supertonic is None:
                        self._motor_supertonic = MotorSupertonic()
                    self._cargadas[nombre] = _VozSupertonic(self._motor_supertonic, VOCES_SUPERTONIC[nombre][1])
                elif nombre in VOCES_KOKORO:
                    if self._motor_kokoro is None:
                        self._motor_kokoro = MotorKokoro(self.dir_kokoro)
                    self._cargadas[nombre] = _VozKokoro(self._motor_kokoro, VOCES_KOKORO[nombre][1])
                else:
                    self._cargadas[nombre] = Sintetizador(nombre, self.dir)
            return self._cargadas[nombre]


def unir_wavs(rutas: list[Path], destino: Path, silencio_ms: int = 250) -> None:
    """Concatena WAVs (mismo formato) con una pequeña pausa entre ellos."""
    tmp = destino.with_suffix(".tmp")
    with wave.open(str(tmp), "wb") as salida:
        for i, ruta in enumerate(rutas):
            with wave.open(str(ruta), "rb") as w:
                if i == 0:
                    salida.setparams(w.getparams())
                    marco = w.getsampwidth() * w.getnchannels()
                    pausa = b"\x00" * (int(w.getframerate() * silencio_ms / 1000) * marco)
                else:
                    salida.writeframes(pausa)
                salida.writeframes(w.readframes(w.getnframes()))
    tmp.replace(destino)
