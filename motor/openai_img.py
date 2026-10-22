"""
OpenAI imagenes (gpt-image) y guion con la clave de la persona (platform.openai.com/api-keys).

Es de PAGO (cada imagen cuesta unos centavos de dolar en la cuenta de la persona),
por eso nunca es el motor por defecto: se elige en el Asistente o en Ajustes.
La clave se guarda como las demas, en secretos/<usuario>.json (fuera de git).

  imagen()   genera una imagen 16:9. Con referencias (la imagen de ejemplo del
             estilo, la hoja de personajes o las fotos de la persona) va por
             /images/edits, que las recibe como imagenes de entrada; sin ellas,
             por /images/generations.
  texto()    el guion (chat completions en modo JSON; 'auto' = el gpt-N-mini mas
             nuevo, que sobra para un guion y cuesta centimos). Ve tambien las
             imagenes de referencia.
  probar()   valida la clave listando modelos: no gasta nada.

gpt-image no hace 16:9 exacto: se pide 1536x1024 (3:2) y se recorta al centro.
"""
import base64
import io
import re
import threading
import time

import requests
from PIL import Image

from . import proyecto

BASE = "https://api.openai.com/v1"
CLAVE_SECRETO = "openai_clave"
REINTENTOS = 4
TAMANO = "1536x1024"
MAX_REFERENCIAS = 4


class ErrorOpenAI(Exception):
    pass


class ErrorCuota(ErrorOpenAI):
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
    return proyecto.config().get("openai") or {}


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
    r = requests.get(f"{BASE}/models", headers={"Authorization": f"Bearer {k}"}, timeout=30)
    if r.status_code >= 400:
        raise ErrorOpenAI(_mensaje_error(r))
    lista = [m["id"] for m in r.json().get("data", []) if m.get("id")]
    with _cerrojo:
        _modelos.update(hora=time.time(), lista=lista, clave=k)
    return lista


def _version(nombre):
    m = re.match(r"gpt-image-(\d+(?:\.\d+)?)", nombre)
    return float(m.group(1)) if m else 0.0


def modelo_imagen():
    """'auto' = el gpt-image de version mas alta (sin las variantes mini, salvo que no haya otra)."""
    elegido = cfg().get("modelo_imagen") or "auto"
    if elegido != "auto":
        return elegido
    try:
        lista = [n for n in modelos() if re.fullmatch(r"gpt-image-\d+(?:\.\d+)?(?:-mini)?", n)]
    except Exception:
        lista = []
    if not lista:
        return "gpt-image-1"
    return max(lista, key=lambda n: (_version(n), "mini" not in n))


def modelo_texto():
    """'auto' = el gpt-N-mini de version mas alta (sin fecha ni sufijos raros)."""
    elegido = cfg().get("modelo_texto") or "auto"
    if elegido != "auto":
        return elegido
    try:
        lista = [n for n in modelos() if re.fullmatch(r"gpt-\d+(?:\.\d+)?-mini", n)]
    except Exception:
        lista = []
    if not lista:
        return "gpt-4o-mini"
    return max(lista, key=lambda n: float(re.match(r"gpt-(\d+(?:\.\d+)?)", n).group(1)))


def calidad():
    return cfg().get("calidad") or "medium"


# --------------------------------------------------------------- llamadas

def _mensaje_error(r):
    try:
        err = r.json().get("error", {}) or {}
        texto, codigo = err.get("message") or r.text, err.get("code") or ""
    except ValueError:
        texto, codigo = r.text, ""
    if r.status_code == 401:
        return "OpenAI no acepta esa clave. Crea una en platform.openai.com/api-keys y pégala en el Asistente."
    if codigo == "insufficient_quota" or "billing" in texto.lower():
        return "Tu cuenta de OpenAI no tiene saldo: carga crédito en platform.openai.com/settings/organization/billing."
    if r.status_code == 403 and "verif" in texto.lower():
        return ("OpenAI pide verificar tu organización para usar gpt-image "
                "(platform.openai.com/settings/organization/general).")
    if codigo == "moderation_blocked" or "safety" in texto.lower():
        return "OpenAI ha rechazado esa imagen por su filtro de contenido. Cambia la descripción de la escena."
    return f"OpenAI ({r.status_code}): {texto[:400]}"


def _post(ruta, avisar, **kwargs):
    k = clave()
    if not k:
        raise ErrorOpenAI("Falta la clave de OpenAI: pégala en el Asistente.")
    for intento in range(REINTENTOS):
        try:
            r = requests.post(f"{BASE}/{ruta}", headers={"Authorization": f"Bearer {k}"},
                              timeout=300, **kwargs)
        except requests.RequestException as err:
            if intento == REINTENTOS - 1:
                raise ErrorOpenAI(f"Sin conexión con OpenAI: {err}")
            time.sleep(5 * (intento + 1))
            continue
        if r.status_code == 200:
            return r.json()
        if r.status_code == 429:
            try:
                sin_saldo = (r.json().get("error") or {}).get("code") == "insufficient_quota"
            except ValueError:
                sin_saldo = False
            if sin_saldo:
                raise ErrorCuota(_mensaje_error(r))
        if r.status_code in (429, 500, 502, 503) and intento < REINTENTOS - 1:
            pausa = int(r.headers.get("retry-after") or 0) or 15 * (intento + 1)
            if avisar:
                avisar(f"OpenAI pide esperar: reintento en {pausa} s")
            time.sleep(pausa)
            continue
        if r.status_code == 429:
            raise ErrorCuota(_mensaje_error(r))
        raise ErrorOpenAI(_mensaje_error(r))
    raise ErrorOpenAI("OpenAI no ha respondido.")


def _png(ruta, lado=1024):
    """Una referencia, reducida, como PNG en memoria (lo que admite /images/edits)."""
    with Image.open(ruta) as im:
        im = im.convert("RGB")
        im.thumbnail((lado, lado), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "PNG")
    return buf.getvalue()


def _a_16_9(crudo, destino):
    with Image.open(io.BytesIO(crudo)) as im:
        im = im.convert("RGB")
        alto = round(im.width * 9 / 16)
        if alto < im.height:
            y = (im.height - alto) // 2
            im = im.crop((0, y, im.width, y + alto))
        im.save(destino, "JPEG", quality=92)


def imagen(prompt, destino, referencias=(), avisar=None):
    """Genera una imagen 16:9 en destino; referencias = rutas que la IA ve como entrada."""
    refs = list(referencias)[:MAX_REFERENCIAS]
    comun = {"model": modelo_imagen(), "prompt": prompt[:30000], "size": TAMANO,
             "quality": calidad(), "n": 1}
    if refs:
        archivos = [("image[]", (f"ref{i}.png", _png(r), "image/png")) for i, r in enumerate(refs)]
        resp = _post("images/edits", avisar,
                     data={k: str(v) for k, v in comun.items()}, files=archivos)
    else:
        resp = _post("images/generations", avisar, json=comun)
    dato = ((resp.get("data") or [{}])[0]).get("b64_json")
    if not dato:
        raise ErrorOpenAI("OpenAI no ha devuelto imagen.")
    _a_16_9(base64.b64decode(dato), destino)
    return destino


# ------------------------------------------------------------------ texto

def _data_url(ruta, lado=768):
    with Image.open(ruta) as im:
        im = im.convert("RGB")
        im.thumbnail((lado, lado), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def texto(prompt, avisar=None, como_json=True, imagenes=()):
    """Texto (el guion). 'imagenes': rutas que el modelo ve junto al prompt."""
    contenido = [{"type": "image_url", "image_url": {"url": _data_url(r)}} for r in imagenes]
    contenido.append({"type": "text", "text": prompt})
    cuerpo = {"model": modelo_texto(), "messages": [{"role": "user", "content": contenido}]}
    if como_json:
        cuerpo["response_format"] = {"type": "json_object"}
    resp = _post("chat/completions", avisar, json=cuerpo)
    try:
        return resp["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError):
        raise ErrorOpenAI("OpenAI no ha devuelto texto.")


# ------------------------------------------------------------------ probar

def probar(k):
    """¿Sirve esta clave? Solo lista modelos: no gasta saldo."""
    try:
        lista = modelos(k)
    except ErrorOpenAI as err:
        return False, str(err)
    except requests.RequestException:
        return False, "Sin conexión con OpenAI. Revisa tu internet."
    if not any(n.startswith("gpt-image") for n in lista):
        return False, "La clave vale pero tu cuenta no ve ningún modelo gpt-image (¿organización sin verificar?)."
    return True, "Clave válida."
