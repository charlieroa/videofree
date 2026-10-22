"""
Cloudflare Workers AI: imagenes GRATIS cada dia con FLUX.2 [klein] 4B.

Cada persona crea su cuenta gratis de Cloudflare (sin tarjeta) y un token de
Workers AI. El plan gratis da 10.000 «neuronas» al dia (se reinicia a las 00:00
UTC). FLUX.2 klein 4B cuesta 26,05 neuronas por cada trozo de 512x512 que sale y
5,37 por cada imagen de referencia: una imagen 1280x720 con referencias sale por
unas 110-180 neuronas, o sea 55-90 imagenes al dia. Gastado el cupo del dia, las
imagenes siguen con Pollinations.

Lo que lo hace bueno para un video: acepta hasta 4 IMAGENES DE REFERENCIA
(input_image_0..3, cada una menor de 512x512), asi que lleva la imagen de ejemplo
del estilo, la hoja de personajes y tus fotos, igual que Gemini.

API (changelog de Cloudflare, 2026-01-15): POST multipart a
  https://api.cloudflare.com/client/v4/accounts/<cuenta>/ai/run/@cf/black-forest-labs/flux-2-klein-4b
con prompt, width, height (256-1920), seed, guidance e input_image_N. Los pasos
van fijos en 4 (modelo destilado). Devuelve la imagen en base64.

Dos formas de conectar la cuenta:
  - «Entrar con Cloudflare»: la app lanza `wrangler login` (la herramienta oficial
    de Cloudflare, por npx; hace falta Node.js). Se abre el navegador, la persona
    entra (tambien con Google) y acepta. Aqui solo se guarda cf_modo=wrangler y el
    Account ID; el token lo da `wrangler auth token` (caduca a la hora y wrangler
    lo renueva solo), cacheado unos minutos.
  - A mano: Account ID + token de Workers AI (secretos cf_cuenta y cf_token).
"""
import base64
import io
import json
import shutil
import subprocess
import threading
import time

import requests
from PIL import Image

from . import proyecto

BASE = "https://api.cloudflare.com/client/v4/accounts"
MODELO = "@cf/black-forest-labs/flux-2-klein-4b"
MAX_REFERENCIAS = 4
LADO_REFERENCIA = 511           # «smaller than 512x512»


class ErrorCloudflare(Exception):
    pass


class ErrorCuota(ErrorCloudflare):
    pass


# --------------------------------------------------------------- la clave

def credenciales():
    try:
        s = proyecto.secretos()
    except RuntimeError:
        return None
    cuenta = (s.get("cf_cuenta") or "").strip()
    if not cuenta:
        return None
    if s.get("cf_modo") == "wrangler":
        token = token_wrangler()
        return (cuenta, token) if token else None
    token = (s.get("cf_token") or "").strip()
    return (cuenta, token) if token else None


def conectada():
    """¿Hay cuenta guardada? (sin pedir token: es lo que enseña la pantalla)."""
    try:
        s = proyecto.secretos()
    except RuntimeError:
        return False
    return bool((s.get("cf_cuenta") or "").strip()
                and (s.get("cf_modo") == "wrangler" or (s.get("cf_token") or "").strip()))


def hay_clave():
    return conectada()


def guardar(cuenta, token):
    proyecto.guardar_secreto("cf_cuenta", cuenta.strip())
    proyecto.guardar_secreto("cf_token", token.strip())
    proyecto.borrar_secretos("cf_modo")


def olvidar():
    proyecto.borrar_secretos("cf_cuenta", "cf_token", "cf_modo")


# ------------------------------------------- «Entrar con Cloudflare» (wrangler)

WRANGLER = "wrangler@4"
_token_cache = {"token": None, "hora": 0.0}
_login = {"proceso": None, "estado": "", "texto": "", "usuario": None}
_cerrojo = threading.Lock()


def hay_node():
    return bool(shutil.which("npx"))


def _wrangler(*args, timeout=180):
    npx = shutil.which("npx")
    if not npx:
        raise ErrorCloudflare("Falta Node.js (nodejs.org) para entrar con Cloudflare. "
                              "O pega tu Account ID y tu token a mano.")
    r = subprocess.run([npx, "-y", WRANGLER, *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout, cwd=proyecto.RAIZ)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def token_wrangler():
    """El token OAuth de wrangler (lo renueva el propio wrangler). Cache de 10 min."""
    with _cerrojo:
        if _token_cache["token"] and time.time() - _token_cache["hora"] < 600:
            return _token_cache["token"]
    try:
        codigo, salida, _ = _wrangler("auth", "token", "--json", timeout=120)
    except (ErrorCloudflare, subprocess.TimeoutExpired):
        return None
    if codigo != 0 or not salida:
        return None
    token = None
    try:
        d = json.loads(salida[salida.index("{"):])
        token = d.get("token") or d.get("value") or d.get("access_token") or d.get("apiToken")
    except ValueError:
        token = salida.splitlines()[-1].strip()
    with _cerrojo:
        _token_cache.update(token=token, hora=time.time())
    return token


def _cuentas(token):
    r = requests.get(BASE, params={"per_page": 50}, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    if r.status_code != 200:
        raise _mensaje(r)
    return r.json().get("result") or []


def empezar_login(usuario):
    """Lanza `wrangler login` (abre el navegador). El estado se mira con estado_login()."""
    with _cerrojo:
        p = _login["proceso"]
        if p and p.poll() is None:
            return
        npx = shutil.which("npx")
        if not npx:
            raise ErrorCloudflare("Falta Node.js (nodejs.org) para entrar con Cloudflare. "
                                  "O pega tu Account ID y tu token a mano.")
        _token_cache.update(token=None, hora=0)
        _login.update(estado="esperando", texto="Se abrió Cloudflare en tu navegador: entra (puedes "
                      "usar Google) y pulsa «Allow».", usuario=usuario,
                      proceso=subprocess.Popen([npx, "-y", WRANGLER, "login"], cwd=proyecto.RAIZ,
                                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))


def estado_login():
    """esperando | listo | error. Al terminar el login guarda la cuenta de la persona."""
    with _cerrojo:
        p, estado = _login["proceso"], _login["estado"]
    if estado != "esperando" or not p or p.poll() is None:
        return {"estado": estado or "nada", "texto": _login["texto"]}
    token = token_wrangler()
    if not token:
        _login.update(estado="error", texto="No se completó la entrada en Cloudflare. Vuelve a intentarlo.")
        return {"estado": "error", "texto": _login["texto"]}
    try:
        cuentas = _cuentas(token)
    except ErrorCloudflare as err:
        _login.update(estado="error", texto=str(err))
        return {"estado": "error", "texto": _login["texto"]}
    if not cuentas:
        _login.update(estado="error", texto="Tu usuario de Cloudflare no tiene ninguna cuenta.")
        return {"estado": "error", "texto": _login["texto"]}
    proyecto.guardar_secreto("cf_cuenta", cuentas[0]["id"])
    proyecto.guardar_secreto("cf_modo", "wrangler")
    proyecto.borrar_secretos("cf_token")
    _login.update(estado="listo", texto=f"✓ Conectado a Cloudflare ({cuentas[0].get('name', '')}). "
                                        f"Imágenes FLUX.2 gratis cada día.")
    return {"estado": "listo", "texto": _login["texto"]}


def cfg():
    return proyecto.config().get("cloudflare") or {}


# --------------------------------------------------------------- llamadas

def _errores(r):
    try:
        cuerpo = r.json()
        errs = cuerpo.get("errors") or []
        texto = "; ".join(f"{e.get('code', '')} {e.get('message', '')}".strip() for e in errs) or r.text
    except ValueError:
        texto = r.text
    return texto[:400]


def _mensaje(r):
    texto = _errores(r)
    bajo = texto.lower()
    if r.status_code in (401, 403) or "authentication" in bajo or "10000" in texto:
        return ErrorCloudflare("Cloudflare no acepta ese token o ese Account ID. Crea el token en "
                               "dash.cloudflare.com → AI → Workers AI → «Use REST API».")
    if "7003" in texto or "object identifier" in bajo:
        return ErrorCloudflare("Ese Account ID no es válido: cópialo de dash.cloudflare.com → AI → "
                               "Workers AI → «Use REST API» (son 32 letras y números).")
    if r.status_code == 429 or "4006" in texto or "neuron" in bajo or "allocation" in bajo or "quota" in bajo:
        return ErrorCuota("Se acabó el cupo gratis de hoy de Cloudflare (10.000 neuronas; vuelve a "
                          "las 00:00 UTC).")
    if "3030" in texto or "flagged" in bajo:
        return ErrorCloudflare("Cloudflare rechazó esa imagen por su filtro de contenido. "
                               "Cambia la descripción de la escena.")
    return ErrorCloudflare(f"Cloudflare ({r.status_code}): {texto}")


def _png(ruta):
    with Image.open(ruta) as im:
        im = im.convert("RGB")
        im.thumbnail((LADO_REFERENCIA, LADO_REFERENCIA), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "PNG")
    return buf.getvalue()


def imagen(prompt, destino, referencias=(), avisar=None):
    """Genera una imagen 16:9 en destino; referencias = rutas que el modelo ve (hasta 4)."""
    cred = credenciales()
    if not cred:
        raise ErrorCloudflare("Faltan tu Account ID y tu token de Cloudflare: pégalos en el Asistente.")
    cuenta, token = cred
    c = cfg()
    campos = {"prompt": (None, prompt[:2048]),
              "width": (None, str(c.get("ancho", 1280))),
              "height": (None, str(c.get("alto", 720))),
              "seed": (None, str(c.get("semilla", 1234)))}
    for i, ruta in enumerate(list(referencias)[:MAX_REFERENCIAS]):
        campos[f"input_image_{i}"] = (f"ref{i}.png", _png(ruta), "image/png")
    url = f"{BASE}/{cuenta}/ai/run/{MODELO}"
    for intento in range(4):
        try:
            # requests arma el multipart con su boundary: NO poner Content-Type a mano
            r = requests.post(url, headers={"Authorization": f"Bearer {token}"}, files=campos, timeout=180)
        except requests.RequestException as err:
            if intento == 3:
                raise ErrorCloudflare(f"Sin conexión con Cloudflare: {err}")
            time.sleep(5 * (intento + 1))
            continue
        if r.status_code == 200:
            break
        err = _mensaje(r)
        if r.status_code >= 500 and intento < 3:
            if avisar:
                avisar(f"Cloudflare falló ({r.status_code}); reintento")
            time.sleep(8 * (intento + 1))
            continue
        raise err
    try:
        cuerpo = r.json()
        dato = (cuerpo.get("result") or {}).get("image") or cuerpo.get("image")
    except ValueError:
        dato = None
        if r.headers.get("content-type", "").startswith("image/"):
            dato = base64.b64encode(r.content).decode()
    if not dato:
        raise ErrorCloudflare("Cloudflare no ha devuelto imagen.")
    with Image.open(io.BytesIO(base64.b64decode(dato.split(",", 1)[-1]))) as im:
        im.convert("RGB").save(destino, "JPEG", quality=92)
    return destino


# ------------------------------------------------------------------ probar

def probar(cuenta, token):
    """¿Sirven? Lista un modelo de Workers AI de esa cuenta: no gasta neuronas."""
    try:
        r = requests.get(f"{BASE}/{cuenta.strip()}/ai/models/search",
                         params={"per_page": 1, "search": "flux-2-klein-4b"},
                         headers={"Authorization": f"Bearer {token.strip()}"}, timeout=30)
    except requests.RequestException:
        return False, "Sin conexión con Cloudflare. Revisa tu internet."
    if r.status_code == 200 and (r.json() or {}).get("success"):
        return True, "Cuenta y token válidos."
    return False, str(_mensaje(r))
