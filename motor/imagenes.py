"""
Paso 3: una imagen por escena, gratis.

Tres formas de conseguirla (config.json -> imagen.motor, o cada escena a mano):

  pollinations  Flux por la API publica de Pollinations: gratis, sin clave,
                una cada ~45 s por IP. Con una clave (enter.pollinations.ai)
                va sin marca de agua.
  manual        Las haces tu donde quieras (ChatGPT gratis, Gemini, Bing...)
                y las pegas en la escena. La pantalla te da el prompt listo
                para copiar.
  kaggle        En la GPU gratis de Kaggle de la persona, con FLUX.2 [klein] 4B:
                sin cupo, mejor calidad, y una hoja de personajes como imagen
                de referencia para que salgan iguales (motor/imagenes_gpu.py).
  prueba        Imagenes de prueba dibujadas aqui, para probar el montaje.

Como se parecen entre si: el prompt de cada imagen lleva SIEMPRE el mismo
estilo y la misma descripcion de cada personaje, y la misma semilla. Y las
escenas 'continua' no piden imagen: reusan la de la anterior y el montaje le
da otro movimiento de camara.
"""
import base64
import re
import time
import urllib.parse

import requests
from PIL import Image, ImageDraw, ImageFont

from . import proyecto

_ultima_llamada = [0.0]


class ErrorImagen(Exception):
    pass


# ---------------------------------------------------------------- prompts

def prompt_de(datos, e):
    b = datos.get("biblia") or {}
    partes = [e["visual"]]
    todos = {p.get("nombre"): p.get("descripcion_visual", "") for p in b.get("personajes", [])}
    pj = [f"{n}: {todos[n]}" for n in e.get("personajes", []) if n in todos]
    if pj:
        partes.append("Characters: " + "; ".join(pj))
    if b.get("estilo_visual"):
        partes.append(f"Style: {b['estilo_visual']}")
    partes.append("16:9 cinematic frame, no text, no letters, no watermark")
    return ". ".join(p.strip(". ") for p in partes)


# -------------------------------------------------------------- motores

def _pollinations(prompt, destino, n, avisar):
    cfg = proyecto.config()["imagen"]
    token = proyecto.secretos().get("pollinations_token", "")
    espera = 0 if token else cfg["espera_s"]
    params = {"width": cfg["ancho"], "height": cfg["alto"], "seed": cfg["semilla"],
              "model": cfg["modelo"], "nologo": "true"}
    if token:
        params["token"] = token
    url = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt[:1500])
           + "?" + urllib.parse.urlencode(params))
    for intento in range(5):
        falta = espera - (time.time() - _ultima_llamada[0])
        if falta > 0:
            time.sleep(falta)
        _ultima_llamada[0] = time.time()
        try:
            r = requests.get(url, timeout=180)
        except requests.RequestException as err:
            avisar(f"imagen {n}: {err}; reintento")
            time.sleep(10)
            continue
        if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/"):
            destino.write_bytes(r.content)
            return
        # El cupo gratis (1 imagen cada 45 s por IP) contesta 402 y dice cuanto falta.
        m = re.search(r"Retry after (\d+)", r.text)
        pausa = int(m.group(1)) + 2 if m else 20 * (intento + 1)
        avisar(f"imagen {n}: Pollinations pide esperar {pausa} s (cupo gratis)")
        time.sleep(pausa)
    raise ErrorImagen(f"Pollinations no ha devuelto la imagen de la escena {n}")


_COLORES = [(41, 50, 65), (92, 61, 46), (35, 70, 60), (70, 40, 80), (90, 75, 30)]


def _fuente(tam):
    for nombre in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(nombre, tam)
        except OSError:
            pass
    return ImageFont.load_default()


def _prueba(texto, destino, n):
    cfg = proyecto.config()["imagen"]
    w, h = cfg["ancho"], cfg["alto"]
    img = Image.new("RGB", (w, h), _COLORES[n % len(_COLORES)])
    d = ImageDraw.Draw(img)
    for i in range(0, w + h, 110):
        d.line([(i, 0), (i - h, h)], fill=(255, 255, 255), width=1)
    lineas, actual = [], ""
    for p in texto.split():
        if len(actual) + len(p) > 44:
            lineas.append(actual)
            actual = p
        else:
            actual = f"{actual} {p}".strip()
    lineas.append(actual)
    y = h // 2 - len(lineas[:7]) * 28
    for linea in lineas[:7]:
        d.text((110, y), linea, fill=(240, 240, 240), font=_fuente(40))
        y += 56
    d.text((110, 70), f"ESCENA {n}  ·  imagen de prueba", fill=(255, 210, 120), font=_fuente(32))
    img.save(destino)


# ------------------------------------------------------------- el paso

def _carpeta(datos):
    c = proyecto.carpeta(datos["id"]) / "imagenes"
    c.mkdir(exist_ok=True)
    return c


def generar_una(datos, e, avisar, nota=""):
    motor = "prueba" if datos.get("simular") else proyecto.config()["imagen"]["motor"]
    destino = _carpeta(datos) / f"escena_{e['n']:03d}.jpg"
    if motor == "prueba":
        destino = destino.with_suffix(".png")
        _prueba(e["narracion"], destino, e["n"])
    elif motor == "pollinations":
        prompt = prompt_de(datos, e) + (f". {nota}" if nota else "")
        _pollinations(prompt, destino, e["n"], avisar)
    else:
        return False                    # manual: la pega la persona
    e["imagen"] = proyecto.relativa(datos, destino)
    proyecto.quitar_clip(e)
    datos["mp4"] = None
    proyecto.guardar(datos)
    return True


def pegar(datos, e, data_url):
    """Una imagen hecha fuera (ChatGPT...) pegada o subida desde la pantalla."""
    cabecera, _, cuerpo = data_url.partition(",")
    if not cabecera.startswith("data:image/"):
        raise ErrorImagen("eso no es una imagen")
    ext = cabecera.split("/")[1].split(";")[0].replace("jpeg", "jpg")
    destino = _carpeta(datos) / f"escena_{e['n']:03d}_propia.{ext}"
    destino.write_bytes(base64.b64decode(cuerpo))
    with Image.open(destino) as im:           # que de verdad se abra
        im.verify()
    e["imagen"] = proyecto.relativa(datos, destino)
    proyecto.quitar_clip(e)
    datos["mp4"] = None
    proyecto.guardar(datos)


def resolver_continuas(datos):
    """Las escenas 'continua' usan la imagen de la anterior."""
    previa = None
    for e in datos["escenas"]:
        if e["continua"] and previa:
            if e["imagen"] != previa:
                proyecto.quitar_clip(e)          # su clip se hizo con la imagen vieja
            e["imagen"] = previa
        previa = e["imagen"]


def ejecutar(datos, avisar, solo=None, nota="", ejecutor=None):
    motor = proyecto.config()["imagen"]["motor"]
    if datos.get("simular"):
        if motor == "kaggle" and ejecutor is None:
            # Modo prueba con el motor GPU: la tanda entera se simula en este PC
            # (mismo script, misma salida que Kaggle, imagenes dibujadas), como clips.
            from . import imagenes_gpu
            ejecutor = imagenes_gpu._simular_kaggle
        elif motor != "kaggle":
            motor = "prueba"
    propias = [e for e in datos["escenas"] if not e["continua"]]
    pendientes = [e for e in propias if (e["n"] in solo if solo else not e["imagen"])]
    if motor == "manual" and not solo:
        avisar(f"Motor manual: pega tus imagenes en las {len(pendientes)} escenas que faltan.")
    if motor == "kaggle":
        # Todas en UNA tanda de Kaggle (el arranque se paga una vez), con la hoja
        # de personajes como referencia. Ver motor/imagenes_gpu.py.
        from . import imagenes_gpu
        imagenes_gpu.ejecutar(datos, pendientes, avisar, nota if solo else "", ejecutor)
        pendientes = []
    for i, e in enumerate(pendientes, 1):
        if motor == "pollinations":
            avisar(f"Imagen escena {e['n']} ({i}/{len(pendientes)})")
        generar_una(datos, e, avisar, nota if solo else "")
    resolver_continuas(datos)
    proyecto.guardar(datos)
    avisar("Imagenes listas." if all(e["imagen"] for e in datos["escenas"])
           else "Faltan imagenes en algunas escenas.")


def estimar(datos):
    cfg = proyecto.config()["imagen"]
    faltan = sum(1 for e in datos["escenas"] if not e["continua"] and not e["imagen"])
    if not datos["escenas"]:
        n = max(3, round(datos["minutos"] * 60 / proyecto.config()["guion"]["segundos_por_escena"]))
        faltan = round(n * 0.7)
    por_imagen = 8 if proyecto.secretos().get("pollinations_token") else cfg["espera_s"]
    if cfg["motor"] == "kaggle":
        from . import imagenes_gpu
        minutos = imagenes_gpu.estimar_min(faltan)
    else:
        minutos = round(faltan * por_imagen / 60, 1)
    return {"imagenes": faltan,
            "minutos_imagenes": 0 if datos.get("simular") or cfg["motor"] == "manual"
            else minutos,
            "motor": "prueba" if datos.get("simular") else cfg["motor"],
            "simular": bool(datos.get("simular"))}
