"""
Puter: la IA gratis que corre en el NAVEGADOR de la persona (puter.com).

Puter.js solo funciona dentro de una pagina web: cada persona entra una vez con
su cuenta gratis de Puter y lo que gasta va a esa cuenta, sin claves. El servidor
no puede llamarlo, asi que cuando un paso necesita Puter hace un PEDIDO y espera:

  1. pedir() deja el pedido del proyecto en memoria (uno a la vez por video) y
     bloquea el hilo del paso.
  2. GET /api/proyectos/<id> lo devuelve como 'pedido_navegador'; la pestaña
     abierta lo ve, llama a Puter y contesta en POST /api/proyectos/<id>/navegador.
  3. responder() despierta al hilo con el resultado (o con el error de Puter).

Tipos de pedido:
  texto    el guion: puter.ai.chat (un modelo Gemini) -> texto
  imagen   puter.ai.txt2img (Gemini imagen) con referencias -> imagen en data URL

Si la pestaña no contesta en ESPERA_S, el paso sigue sin Puter (las imagenes con
Pollinations) o se corta con un mensaje claro (el guion).

La voz con Puter va por su propio camino (motor/voz.py), que ya existia.
"""
import base64
import io
import threading
import uuid

from PIL import Image

from . import proyecto

ESPERA_S = 10 * 60

_pedidos = {}            # pid -> pedido pendiente
_cerrojo = threading.Lock()


class ErrorNavegador(Exception):
    pass


class SinRespuesta(ErrorNavegador):
    """La pestaña no contesto a tiempo (cerrada, o Puter sin conectar)."""


class SinCreditos(ErrorNavegador):
    """Puter dice que la cuenta no tiene saldo para eso."""


def pendiente(pid):
    """Lo que la pestaña tiene que hacer ahora para este video (sin el evento interno)."""
    with _cerrojo:
        p = _pedidos.get(pid)
        return {k: v for k, v in p.items() if not k.startswith("_")} if p else None


def responder(pid, rid, resultado=None, error=""):
    with _cerrojo:
        p = _pedidos.get(pid)
        if not p or p["id"] != rid:
            return False
        p["_resultado"], p["_error"] = resultado, error
        p["_listo"].set()
        return True


def _pedir(datos, tipo, carga, avisar, espera=ESPERA_S):
    pid = datos["id"]
    pedido = {"id": uuid.uuid4().hex[:12], "tipo": tipo, **carga,
              "_listo": threading.Event(), "_resultado": None, "_error": ""}
    with _cerrojo:
        _pedidos[pid] = pedido
    try:
        if not pedido["_listo"].wait(espera):
            raise SinRespuesta("Tu navegador no ha contestado: deja abierta la pestaña del vídeo "
                               "y pulsa «Conectar Puter» si te lo pide.")
    finally:
        with _cerrojo:
            if _pedidos.get(pid) is pedido:
                del _pedidos[pid]
    if pedido["_error"]:
        err = pedido["_error"]
        if "insufficient" in err.lower() or "402" in err or "saldo" in err.lower():
            raise SinCreditos(f"Se acabaron los créditos gratis de tu cuenta de Puter ({err[:200]}).")
        raise ErrorNavegador(f"Puter: {err[:300]}")
    return pedido["_resultado"]


def _relativas(datos, rutas):
    return [proyecto.relativa(datos, r) for r in rutas if r]


# ------------------------------------------------------------------ texto

def texto(datos, prompt, avisar=None, imagenes=()):
    """El guion con la IA de Puter. 'imagenes': rutas del proyecto que el modelo ve."""
    r = _pedir(datos, "texto", {"prompt": prompt, "imagenes": _relativas(datos, imagenes)}, avisar)
    if not isinstance(r, str) or not r.strip():
        raise ErrorNavegador("Puter no ha devuelto texto.")
    return r


# ---------------------------------------------------------------- imagenes

class Imagenes:
    """Mismo uso que gemini/openai_img: imagen(prompt, destino, referencias, avisar)."""

    def __init__(self, datos):
        self.datos = datos

    def imagen(self, prompt, destino, referencias=(), avisar=None):
        r = _pedir(self.datos, "imagen",
                   {"prompt": prompt, "referencias": _relativas(self.datos, referencias)}, avisar)
        cabecera, _, cuerpo = (r or "").partition(",")
        if not cabecera.startswith("data:image/"):
            raise ErrorNavegador("Puter no ha devuelto una imagen.")
        with Image.open(io.BytesIO(base64.b64decode(cuerpo))) as im:
            im = im.convert("RGB")
            alto = round(im.width * 9 / 16)
            if abs(im.height - alto) > 4:                  # por si no vino en 16:9
                if alto < im.height:
                    y = (im.height - alto) // 2
                    im = im.crop((0, y, im.width, y + alto))
                else:
                    ancho = round(im.height * 16 / 9)
                    x = (im.width - ancho) // 2
                    im = im.crop((x, 0, x + ancho, im.height))
            im.save(destino, "JPEG", quality=92)
        return destino
