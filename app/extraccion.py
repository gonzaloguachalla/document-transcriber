"""Extracción de texto de .docx, limpieza y división en oraciones."""
import io
import os
import re
import zipfile

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from num2words import num2words


class DocumentoInvalido(Exception):
    """El archivo no es un .docx válido o es demasiado grande al descomprimir."""


class DocumentoVacio(Exception):
    """El documento no contiene texto legible."""


def _iterar_bloques(doc):
    """Recorre párrafos y tablas en el orden en que aparecen en el documento."""
    for hijo in doc.element.body.iterchildren():
        if hijo.tag.endswith("}p"):
            yield Paragraph(hijo, doc)
        elif hijo.tag.endswith("}tbl"):
            yield Table(hijo, doc)


def _lineas_tabla(tabla):
    for fila in tabla.rows:
        vistas = set()
        celdas = []
        for celda in fila.cells:
            # Las celdas combinadas se repiten; se leen una sola vez.
            if id(celda._tc) in vistas:
                continue
            vistas.add(id(celda._tc))
            texto = " ".join(p.text for p in celda.paragraphs).strip()
            if texto:
                celdas.append(texto)
        if celdas:
            yield ". ".join(celdas)


def extraer_lineas(contenido: bytes, max_descomprimido: int) -> list[str]:
    try:
        with zipfile.ZipFile(io.BytesIO(contenido)) as z:
            if sum(i.file_size for i in z.infolist()) > max_descomprimido:
                raise DocumentoInvalido("El documento es demasiado grande al descomprimirse.")
            if "word/document.xml" not in z.namelist():
                raise DocumentoInvalido("El archivo no es un documento Word válido.")
        doc = Document(io.BytesIO(contenido))
    except DocumentoInvalido:
        raise
    except Exception as e:  # zip corrupto, XML roto, etc.
        raise DocumentoInvalido("No se pudo leer el archivo como documento Word (.docx).") from e

    lineas = []
    for bloque in _iterar_bloques(doc):
        if isinstance(bloque, Paragraph):
            lineas.extend(bloque.text.split("\n"))
        else:
            lineas.extend(_lineas_tabla(bloque))
    return lineas


def limpiar(linea: str) -> str:
    linea = linea.replace(" ", " ").replace("\t", " ")
    linea = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", linea)
    return re.sub(r" {2,}", " ", linea).strip()


_ABREVIATURAS = ("Sr", "Sra", "Srta", "Dr", "Dra", "Ud", "Uds", "Lic", "Ing", "Prof",
                 "etc", "pág", "págs", "núm", "art", "cap", "vs", "Av", "Gral", "EE")
_MARCA = "\u0001"
_RE_ABREV = re.compile(r"\b(" + "|".join(_ABREVIATURAS) + r")\.(?=\s)")
_RE_FIN = re.compile(r"(?<=[.!?…])[\"'»”)\]]*\s+(?=[\"'«“¿¡(\[]*[A-ZÁÉÍÓÚÑÜ0-9])")
# Las oraciones más largas se parten por comas para que el audio empiece rápido (más alto = lectura más fluida).
_MAX_LARGO = int(os.getenv("MAX_SENTENCE_CHARS", "600"))


def _partir_largas(oracion: str) -> list[str]:
    """Divide oraciones muy largas por comas/punto y coma para que el audio empiece rápido."""
    if len(oracion) <= _MAX_LARGO:
        return [oracion]
    trozos, actual = [], ""
    for parte in re.split(r"(?<=[,;:])\s+", oracion):
        if actual and len(actual) + len(parte) + 1 > _MAX_LARGO:
            trozos.append(actual)
            actual = parte
        else:
            actual = f"{actual} {parte}".strip()
    if actual:
        trozos.append(actual)
    final = []
    for t in trozos:  # último recurso: cortar por espacios
        while len(t) > _MAX_LARGO * 1.5:
            corte = t.rfind(" ", 0, _MAX_LARGO)
            corte = corte if corte > 0 else _MAX_LARGO
            final.append(t[:corte].strip())
            t = t[corte:].strip()
        if t:
            final.append(t)
    return final


def dividir_oraciones(lineas: list[str]) -> list[str]:
    oraciones = []
    for linea in lineas:
        linea = limpiar(linea)
        if not linea:
            continue
        protegida = _RE_ABREV.sub(lambda m: m.group(1) + _MARCA, linea)
        for parte in _RE_FIN.split(protegida):
            parte = parte.replace(_MARCA, ".").strip()
            # Descarta fragmentos sin ninguna letra o dígito (p. ej. "---").
            if parte and re.search(r"\w", parte):
                oraciones.extend(_partir_largas(parte))
    return oraciones


# Códigos de numeración (L2.1.1, 3.2.1, v1.2): las voces se saltan el punto entre números.
_RE_COD_LETRA = re.compile(r"(?<![\w.])[A-Za-zÁÉÍÓÚÑáéíóúñ]{1,3}\d+(?:\.\d+)+(?![\w])")
_RE_COD_NUM = re.compile(r"(?<![\w.])\d+(?:\.\d+){2,}(?![\w])")


def _es_numero_normal(codigo: str) -> bool:
    """Miles (1.000.000) o fechas (12.03.2024): se dejan tal cual."""
    grupos = codigo.split(".")
    return all(len(g) == 3 for g in grupos[1:]) or (len(grupos) == 3 and len(grupos[2]) == 4)


_LETRAS = dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ", (
    "a be ce de e efe ge hache i jota ka ele eme ene o pe cu erre ese te u uve doble-uve equis ye zeta").split()))
_LETRAS["Ñ"] = "eñe"
_DIGITOS = ("cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve")
# Siglas que se dicen como una palabra (no se deletrean). Añade aquí las que uses.
_SIGLAS_PALABRA = {"ONU", "OTAN", "UNESCO", "UNICEF", "NASA", "OPEP", "SIDA", "PYME", "SENAPI", "COVID", "FIFA", "ISO"}
_ROMANOS = {"II", "III", "IV", "VI", "VII", "VIII", "IX", "XI", "XII", "XIII", "XIV", "XV", "XVI", "XVII", "XVIII",
            "XIX", "XX"}
_GRUPOS_OK = ("PL", "PR", "BL", "BR", "CL", "CR", "DR", "FL", "FR", "GL", "GR", "TR")
_RE_SIGLA = re.compile(
    r"(?<![\w.])(?P<sigla>[A-ZÁÉÍÓÚÑ]{2,6})(?![\w]|\.[A-Z])(?:[ ]+(?P<num>\d{3,})(?!\d|\.\d))?")
_RE_VER = re.compile(r"\b[Vv]er\.?\s+(?=\d)")


def _se_deletrea(sigla: str) -> bool:
    if sigla in _SIGLAS_PALABRA or sigla in _ROMANOS:
        return False
    if len(sigla) == 2 or not re.search(r"[AEIOUÁÉÍÓÚ]", sigla):
        return True
    if re.search(r"[^AEIOUÁÉÍÓÚ]{3,}", sigla) or re.search(r"[^AEIOUÁÉÍÓÚ]{2}$", sigla):
        return True
    # empieza por dos consonantes que no forman un grupo válido en español (p. ej. «CP» en CPU)
    return bool(re.match(r"[^AEIOUÁÉÍÓÚ]{2}", sigla)) and sigla[:2] not in _GRUPOS_OK


def _sigla_a_voz(m: re.Match) -> str:
    sigla, num = m.group("sigla"), m.group("num")
    if not _se_deletrea(sigla):
        return m.group(0)
    texto = " ".join(_LETRAS.get(c, c.lower()) for c in sigla).replace("doble-uve", "doble uve")
    if num:  # número de norma (RFC 4949, ISO 9001): dígito a dígito
        return f"{texto}, " + " ".join(_DIGITOS[int(d)] for d in num)
    # pausa si lo siguiente es otra sigla o un número
    return texto + ("," if re.match(r"\s+[A-ZÁÉÍÓÚÑ0-9]", m.string[m.end():m.end() + 3]) else "")


# Palabras que la voz pronuncia mal: se reescriben como suenan. Añade aquí las que necesites.
_PRONUNCIACION = {"OWASP": "Ouasp"}
_RE_PRONUNCIACION = re.compile(r"(?<![\w.])(" + "|".join(_PRONUNCIACION) + r")(?!\w)")
_RE_EEUU = re.compile(r"(?<![\w.])EE\.?\s?UU\b(\.?)")
# Código de siglas pegadas a su número: FN-123, A5, FP/007.
_RE_CODIGO = re.compile(r"(?<![\w.])([A-ZÑ]{1,4})[-/]?(\d+)(?![\w])")
# Enteros con miles (1.250.000) o decimales con coma (3,5).
_RE_NUMERO = re.compile(r"(?<![\w.,])(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d+))?(?!\w|\.\d)")


def _leer_cifras(cifras: str) -> str:
    """Número en palabras; con ceros a la izquierda (007) se lee dígito a dígito."""
    if len(cifras) > 1 and cifras.startswith("0"):
        return " ".join(_DIGITOS[int(c)] for c in cifras)
    return num2words(int(cifras), lang="es")


def _numero_a_voz(m: re.Match) -> str:
    entero, _, decimales = m.group(0).partition(",")
    texto = _leer_cifras(entero.replace(".", ""))
    return f"{texto} coma {_leer_cifras(decimales)}" if decimales else texto


def _codigo_a_voz(m: re.Match) -> str:
    letras = " ".join(_LETRAS[c] for c in m.group(1)).replace("doble-uve", "doble uve")
    return f"{letras}, {_leer_cifras(m.group(2))}"


def normalizar_para_voz(texto: str) -> str:
    """Texto que se envía a la voz; el que se muestra en pantalla no cambia."""
    # «EE.UU.» -> «Estados Unidos»; el punto final solo se conserva si cierra la oración.
    texto = _RE_EEUU.sub(lambda m: "Estados Unidos" + ("." if m.group(1) and not m.string[m.end():].strip() else ""), texto)
    texto = _RE_PRONUNCIACION.sub(lambda m: _PRONUNCIACION[m.group(1)], texto)
    texto = _RE_COD_LETRA.sub(lambda m: m.group(0).replace(".", " punto "), texto)
    texto = _RE_COD_NUM.sub(
        lambda m: m.group(0) if _es_numero_normal(m.group(0)) else m.group(0).replace(".", " punto "), texto)
    texto = _RE_CODIGO.sub(_codigo_a_voz, texto)
    texto = _RE_SIGLA.sub(_sigla_a_voz, texto)
    texto = _RE_NUMERO.sub(_numero_a_voz, texto)
    texto = _RE_VER.sub(", versión ", texto)
    texto = re.sub(r"\s*[(\[]\s*", ", ", texto)          # los paréntesis se leen como una pausa
    texto = re.sub(r"\s*[)\]]", ",", texto)
    texto = re.sub(r"\s+,", ",", texto)
    texto = re.sub(r"([:;])\s*,", r"\1", texto)           # «Fuente: ,» -> «Fuente:»
    texto = re.sub(r",(\s*,)+", ",", texto)
    texto = re.sub(r",\s*([.!?…])", r"\1", texto)
    return texto.strip(" ,") or texto


def procesar_docx(contenido: bytes, max_descomprimido: int) -> list[str]:
    oraciones = dividir_oraciones(extraer_lineas(contenido, max_descomprimido))
    if not oraciones:
        raise DocumentoVacio("El documento no contiene texto para leer.")
    return oraciones
