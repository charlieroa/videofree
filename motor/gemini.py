"""
Gemini: UNA clave (aistudio.google.com/apikey) para el guion, la voz y las imagenes.

La clave es de cada persona y se guarda solo en su equipo, en
secretos/<usuario>.json (fuera de git), como cualquier otro secreto. Nunca va
en config.json.

  texto()    el guion (modelo flash de texto; "auto" = el mas nuevo que liste la API)
  voz()      Gemini TTS: devuelve PCM 16 bit mono 24 kHz, aqui se pasa a mp3
  imagen()   Gemini imagen (tipo gemini-*-flash-image), con imagenes de referencia

Cuota: el plan gratis de Gemini tiene limites por minuto y por dia. Ante un 429
se espera lo que diga la API (o un poco mas cada vez) y se reintenta; si sigue
sin cupo se corta con un mensaje claro en vez de colgarse.
"""
import base64
import re
import tempfile
import threading
import time
from pathlib import Path

import requests

from . import medios, proyecto

BASE = "https://generativelanguage.googleapis.com/v1beta"
CLAVE_SECRETO = "gemini_clave"
REINTENTOS = 5

# Las tres voces de Gemini del catalogo (la cuarta, Jorge, es edge-tts y no necesita clave).
VOCES = {
    "gemini:Puck": {"nombre": "Puck", "pais": "Gemini", "genero": "hombre", "detalle": "animado"},
    "gemini:Charon": {"nombre": "Charon", "pais": "Gemini", "genero": "hombre", "detalle": "narrador"},
    "gemini:Kore": {"nombre": "Kore", "pais": "Gemini", "genero": "mujer", "detalle": "clara y cálida"},
}

# Prefijo CORTO que da el estilo de la voz. Medido: systemInstruction da error en
# los modelos TTS, y un prefijo largo hace que LEA las instrucciones en voz alta.
ESTILO_VOZ = {
    "": "Dilo en español latino, claro y ameno, como un divulgador: ",
    "humor": "Dilo en español latino, cálido y con humor, como un divulgador de YouTube: ",
    "documental": "Dilo en español latino, grave y épico, como un narrador de documental: ",
    "infantil": "Dilo en español latino, alegre y dulce, como contando un cuento a niños: ",
    "inspirador": "Dilo en español latino, sereno y cálido, con pausas, inspirando esperanza: ",
    "misterio": "Dilo en español latino, en voz baja e intrigante, creando suspenso: ",
}


class ErrorGemini(Exception):
    pass


class ErrorCuota(ErrorGemini):
    pass


# --------------------------------------------------------------- la clave

def clave():
    try:
        return (proyecto.secretos().get(CLAVE_SECRETO) or "").strip()
    except RuntimeError:            # sin usuario no hay clave
        return ""


def hay_clave():
    return bool(clave())


def guardar_clave(valor):
    proyecto.guardar_secreto(CLAVE_SECRETO, (valor or "").strip())


def olvidar_clave():
    proyecto.borrar_secretos(CLAVE_SECRETO)


def cfg():
    return proyecto.config().get("gemini") or {}


# ---------------------------------------------------------------- modelos

_modelos = {"hora": 0, "lista": None, "clave": None}
_cerrojo = threading.Lock()


def modelos(k=None):
    """Los modelos que ve esta clave (se piden una vez por hora)."""
    k = k or clave()
    with _cerrojo:
        if (_modelos["lista"] is not None and _modelos["clave"] == k
                and time.time() - _modelos["hora"] < 3600):
            return _modelos["lista"]
    r = requests.get(f"{BASE}/models", params={"pageSize": 1000},
                     headers={"x-goog-api-key": k}, timeout=30)
    if r.status_code >= 400:
        raise ErrorGemini(_mensaje_error(r))
    lista = [m["name"].split("/", 1)[1] for m in r.json().get("models", [])
             if "generateContent" in (m.get("supportedGenerationMethods") or [])]
    with _cerrojo:
        _modelos.update(hora=time.time(), lista=lista, clave=k)
    return lista


def _version(nombre):
    m = re.match(r"gemini-(\d+(?:\.\d+)?)-", nombre)
    return float(m.group(1)) if m else 0.0


def _mas_nuevo(lista, patron):
    """El de version mas alta que case con el patron; los estables antes que los preview."""
    candidatos = [n for n in lista if re.fullmatch(patron, n)]
    if not candidatos:
        return None
    return max(candidatos, key=lambda n: (_version(n), "preview" not in n))


def modelo_texto():
    elegido = cfg().get("modelo_texto") or "auto"
    if elegido != "auto":
        return elegido
    try:
        return _mas_nuevo(modelos(), r"gemini-\d+(?:\.\d+)?-flash") or "gemini-flash-latest"
    except Exception:
        return "gemini-flash-latest"


def modelo_imagen():
    elegido = cfg().get("modelo_imagen") or "auto"
    if elegido != "auto":
        return elegido
    try:
        return (_mas_nuevo(modelos(), r"gemini-\d+(?:\.\d+)?-flash-image(?:-preview)?")
                or "gemini-2.5-flash-image")
    except Exception:
        return "gemini-2.5-flash-image"


def modelo_voz():
    return cfg().get("modelo_voz") or "gemini-3.1-flash-tts-preview"


# --------------------------------------------------------------- llamadas

def _mensaje_error(r):
    try:
        err = r.json().get("error", {})
        texto = err.get("message") or r.text
    except ValueError:
        texto = r.text
    if r.status_code in (400, 403) and re.search(r"API key|API_KEY|permission", texto, re.I):
        return "Gemini no acepta esa clave. Crea una en aistudio.google.com/apikey y pégala en el Asistente."
    return f"Gemini ({r.status_code}): {texto[:400]}"


def _espera_pedida(r):
    """Lo que la API dice que hay que esperar (RetryInfo), en segundos."""
    try:
        for d in r.json().get("error", {}).get("details", []):
            if d.get("@type", "").endswith("RetryInfo"):
                return float(str(d.get("retryDelay", "0")).rstrip("s") or 0)
    except (ValueError, AttributeError):
        pass
    return 0.0


def _post(modelo, cuerpo, avisar=None, k=None, timeout=300):
    k = k or clave()
    if not k:
        raise ErrorGemini("Falta la clave de Gemini: pégala en el Asistente (es gratis).")
    url = f"{BASE}/models/{modelo}:generateContent"
    for intento in range(REINTENTOS):
        try:
            r = requests.post(url, json=cuerpo, headers={"x-goog-api-key": k}, timeout=timeout)
        except requests.RequestException as err:
            if intento == REINTENTOS - 1:
                raise ErrorGemini(f"Sin conexión con Gemini: {err}")
            time.sleep(5 * (intento + 1))
            continue
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 503):
            pedida = _espera_pedida(r)
            if r.status_code == 429 and "limit: 0" in r.text:
                # Medido (2026-10-22): en el plan gratis Google da 0 imagenes al dia a
                # todos los gemini-*-image. Esperar no sirve de nada.
                raise ErrorCuota(f"Tu clave de Gemini no tiene cuota gratis para {modelo} "
                                 f"(Google la deja en 0 en el plan gratis; con facturación "
                                 f"activada en aistudio.google.com sí funciona).")
            if r.status_code == 429 and pedida > 120:
                raise ErrorCuota(_texto_cuota(modelo))     # cupo del dia agotado
            pausa = max(pedida + 1, 10 * (intento + 1))
            if intento < REINTENTOS - 1:
                if avisar:
                    avisar(f"Gemini pide esperar ({'cuota' if r.status_code == 429 else 'saturado'}): "
                           f"reintento en {int(pausa)} s")
                time.sleep(pausa)
                continue
            if r.status_code == 429:
                raise ErrorCuota(_texto_cuota(modelo))
        raise ErrorGemini(_mensaje_error(r))
    raise ErrorGemini("Gemini no ha respondido.")


def _texto_cuota(modelo):
    return (f"Se acabó la cuota gratis de Gemini para {modelo} por ahora. Espera un rato "
            f"(el cupo por minuto se libera solo; el diario, mañana) o sigue con la voz Jorge "
            f"y las imágenes de Pollinations, que no la usan.")


def _partes(resp):
    cands = resp.get("candidates") or []
    if not cands:
        motivo = (resp.get("promptFeedback") or {}).get("blockReason")
        raise ErrorGemini(f"Gemini no ha devuelto nada{f' (bloqueado: {motivo})' if motivo else ''}.")
    return (cands[0].get("content") or {}).get("parts") or []


# ------------------------------------------------------------------ texto

def texto(prompt, avisar=None, como_json=True, imagenes=()):
    """Texto (el guion). 'imagenes': rutas que el modelo ve junto al prompt."""
    partes = [{"inlineData": {"mimeType": "image/jpeg", "data": jpg_b64(r, 768)}} for r in imagenes]
    cuerpo = {"contents": [{"role": "user", "parts": partes + [{"text": prompt}]}]}
    if como_json:
        cuerpo["generationConfig"] = {"responseMimeType": "application/json"}
    resp = _post(modelo_texto(), cuerpo, avisar, timeout=600)
    return "".join(p.get("text", "") for p in _partes(resp) if not p.get("thought"))


# -------------------------------------------------------------------- voz

def es_suya(voz_id):
    return voz_id in VOCES


def prefijo(tono):
    return ESTILO_VOZ.get((tono or "").strip().lower(), ESTILO_VOZ[""])


def voz(texto_leer, voz_id, destino, tono="", avisar=None):
    """Narra texto_leer con una voz de Gemini y lo deja en destino (mp3)."""
    nombre = voz_id.split(":", 1)[1]
    cuerpo = {"contents": [{"parts": [{"text": prefijo(tono) + texto_leer}]}],
              "generationConfig": {"responseModalities": ["AUDIO"],
                                   "speechConfig": {"voiceConfig": {
                                       "prebuiltVoiceConfig": {"voiceName": nombre}}}}}
    resp = _post(modelo_voz(), cuerpo, avisar)
    audio = next((p["inlineData"] for p in _partes(resp) if p.get("inlineData")), None)
    if not audio:
        raise ErrorGemini("Gemini no ha devuelto audio.")
    pcm = base64.b64decode(audio["data"])
    tasa = 24000
    m = re.search(r"rate=(\d+)", audio.get("mimeType", ""))
    if m:
        tasa = int(m.group(1))
    with tempfile.TemporaryDirectory() as tmp:
        crudo = Path(tmp) / "voz.pcm"
        crudo.write_bytes(pcm)
        medios.ffmpeg("-f", "s16le", "-ar", tasa, "-ac", 1, "-i", crudo,
                      "-b:a", "128k", destino)
    return destino


# ---------------------------------------------------------------- imagenes

def jpg_b64(ruta, lado=1024):
    """Una imagen de referencia, reducida, en base64 (para inlineData)."""
    from PIL import Image
    import io
    with Image.open(ruta) as im:
        im = im.convert("RGB")
        im.thumbnail((lado, lado), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def imagen(prompt, destino, referencias=(), avisar=None, aspecto="16:9"):
    """Genera una imagen; referencias = rutas de imagenes que se pasan antes del texto."""
    partes = [{"inlineData": {"mimeType": "image/jpeg", "data": jpg_b64(r)}} for r in referencias]
    partes.append({"text": prompt})
    cuerpo = {"contents": [{"role": "user", "parts": partes}],
              "generationConfig": {"responseModalities": ["IMAGE"],
                                   "imageConfig": {"aspectRatio": aspecto}}}
    resp = _post(modelo_imagen(), cuerpo, avisar)
    dato = next((p["inlineData"] for p in _partes(resp)
                 if p.get("inlineData", {}).get("mimeType", "").startswith("image/")), None)
    if not dato:
        motivo = " ".join(p.get("text", "") for p in _partes(resp))[:200]
        raise ErrorGemini(f"Gemini no ha devuelto imagen{': ' + motivo if motivo else ''}.")
    from PIL import Image
    import io
    with Image.open(io.BytesIO(base64.b64decode(dato["data"]))) as im:
        im.convert("RGB").save(destino, "JPEG", quality=92)
    return destino


# ------------------------------------------------------------------ probar

def probar(k):
    """¿Sirve esta clave? Solo lista modelos: no gasta cuota."""
    try:
        lista = modelos(k)
    except ErrorGemini as err:
        return False, str(err)
    except requests.RequestException:
        return False, "Sin conexión con Gemini. Revisa tu internet."
    if not lista:
        return False, "La clave responde pero no ve ningún modelo."
    return True, "Clave válida."


def resumen_modelos():
    return {"texto": modelo_texto(), "voz": modelo_voz(), "imagen": modelo_imagen()}
