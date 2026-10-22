"""
Paso 3: una imagen por escena.

Formas de conseguirla (config.json -> imagen.motor, o cada escena a mano):

  gemini        Gemini imagen (el modelo gemini-*-flash-image mas nuevo) con la
                clave de la persona. Lleva como referencia la IMAGEN DE EJEMPLO
                del estilo (si la subio) y la HOJA DE PERSONAJES del video, para
                que caras y ropa no cambien de una escena a otra. Sin clave, o si
                se acaba la cuota, sigue con Pollinations.
  openai        gpt-image con la clave de OpenAI de la persona (de pago, centimos
                por imagen). Mismas referencias que Gemini: imagen de ejemplo y
                hoja de personajes. Si hay clave de OpenAI se prefiere a Gemini,
                porque la capa gratis de Gemini no da cuota de imagenes.
  puter         Gemini imagen GRATIS con la cuenta de Puter de la persona: la genera
                su navegador (motor/navegador.py). Es lo que se usa sin ninguna
                clave. Mismas referencias que Gemini. Sin creditos o sin la pestaña
                abierta, sigue con Pollinations.
  pollinations  Flux por la API publica de Pollinations: gratis, sin clave,
                una cada ~45 s por IP. Con una clave (enter.pollinations.ai)
                va sin marca de agua.
  manual        Las haces tu donde quieras (ChatGPT gratis, Gemini, Bing...)
                y las pegas en la escena. La pantalla te da el prompt listo
                para copiar.
  prueba        Imagenes de prueba dibujadas aqui, para probar el montaje.

Y en cualquier escena, con cualquier motor, la persona puede subir o pegar SU
imagen: queda marcada como propia y «Imagenes» / «Hacer todo» no la pisan.

TUS FOTOS del video (imagenes/fotos/, las sube la persona de una vez):
  fotos_modo = "referencia"  la IA (Gemini u OpenAI) las ve en cada escena y
                             saca su producto, su cara o su local tal cual.
  fotos_modo = "escenas"     no se genera nada: las fotos SON las imagenes, en
                             orden y repartidas entre las escenas (varias escenas
                             seguidas comparten foto; el montaje les da otro
                             movimiento de camara).

Como se parecen entre si: el prompt de cada imagen lleva SIEMPRE el mismo
estilo y la misma descripcion de cada personaje (la «biblia» del guion), y con
Gemini ademas la hoja de personajes como imagen. Las escenas 'continua' no piden
imagen: reusan la de la anterior y el montaje le da otro movimiento de camara.
"""
import base64
import hashlib
import json
import re
import time
import urllib.parse

import requests
from PIL import Image, ImageDraw, ImageFont

from . import gemini, navegador, openai_img, proyecto

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


# ------------------------------------------------- hoja de personajes (Gemini)
# 1. Primero se genera una HOJA DE PERSONAJES del proyecto: todos los personajes
#    de la biblia, de cuerpo entero, de frente, en el estilo del video y sobre un
#    fondo liso (imagenes/hoja.jpg; se ve en «Estilo y personajes»).
# 2. Cada escena con personajes se genera pasando esa hoja como referencia.
# 3. Si la biblia (estilo o personajes) o la imagen de ejemplo cambian, la hoja
#    se rehace sola.

def _personajes(datos):
    return [p for p in ((datos.get("biblia") or {}).get("personajes") or [])
            if p.get("nombre") and p.get("descripcion_visual")]


def firma_hoja(datos):
    """Cambia si cambia lo que sale en la hoja: entonces hay que rehacerla."""
    b = datos.get("biblia") or {}
    base = json.dumps([b.get("estilo_visual", ""), _personajes(datos), datos.get("referencia")],
                      ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]


def prompt_hoja(datos):
    b = datos.get("biblia") or {}
    pj = _personajes(datos)
    lista = "; ".join(f"{p['nombre']}: {p['descripcion_visual']}" for p in pj)
    cuantos = "one character" if len(pj) == 1 else f"{len(pj)} characters side by side, clearly separated"
    texto = (f"Character reference sheet, {cuantos}, each one full body, standing, facing the "
             f"viewer, neutral friendly expression, whole figure visible from head to feet. "
             f"Characters: {lista}. Plain flat light grey background, nothing else in the image. ")
    if b.get("estilo_visual"):
        texto += f"Style: {b['estilo_visual']}. "
    texto += "No text, no labels, no letters, no watermark"
    return texto[:2000]


def usa_hoja(datos, e):
    nombres = {p["nombre"] for p in _personajes(datos)}
    return any(n in nombres for n in e.get("personajes") or [])


def prompt_escena(datos, e, nota="", con_hoja=False, con_estilo=False):
    """El prompt de una escena para Gemini, diciendo para que sirve cada referencia."""
    base = prompt_de(datos, e)
    if con_estilo and con_hoja:
        guia = "Reference images: the first is the STYLE example, the second is the CHARACTER SHEET. "
    elif con_estilo:
        guia = "Reference image: the STYLE example. "
    elif con_hoja:
        guia = "Reference image: the CHARACTER SHEET. "
    else:
        guia = ""
    if con_estilo:
        guia += ("Copy only the visual style of the STYLE example (art technique, color palette, "
                 "lighting, line work, texture); do not copy its subject, characters or composition. ")
    base = guia + base
    if con_hoja:
        quienes = ", ".join(n for n in e.get("personajes") or [])
        base = (f"{base}. {quienes} must look exactly like in the CHARACTER SHEET: "
                f"same face, head shape, hair, beard and body, and the same clothes unless "
                f"this scene describes different clothes. Use the sheet only for the "
                f"characters' look, not for the background or the pose")
    if _personajes(datos):
        # Medido: sin esto, la gente del fondo sale con ropa moderna (polos, vaqueros)
        # aunque el protagonista vaya de romano.
        base += (". Everybody else in the scene wears clothing from the same time period and "
                 "culture as the main characters, no modern clothes")
    if nota:
        base += f". {nota}"
    return base[:2500]


def _carpeta(datos):
    c = proyecto.carpeta(datos["id"]) / "imagenes"
    c.mkdir(exist_ok=True)
    return c


def hoja_vale(datos):
    return bool(datos.get("hoja") and datos.get("hoja_firma") == firma_hoja(datos)
                and proyecto.absoluta(datos, datos["hoja"]).is_file())


def referencia(datos):
    """La imagen de ejemplo del estilo, si la persona subio una."""
    ruta = datos.get("referencia") and proyecto.absoluta(datos, datos["referencia"])
    return ruta if ruta and ruta.is_file() else None


def _asegurar_hoja(datos, avisar):
    """La hoja de personajes (se genera si falta o si cambio). None si no hay personajes."""
    if not _personajes(datos):
        return None
    if hoja_vale(datos):
        return proyecto.absoluta(datos, datos["hoja"])
    ref = referencia(datos)
    avisar(f"{_NOMBRE.get(motor_efectivo(datos), 'La IA')} dibuja la hoja de personajes" + (" (con tu imagen de ejemplo)" if ref else "") + "...")
    prompt = prompt_hoja(datos)
    if ref:
        prompt = ("Reference image: the STYLE example. Copy only its visual style (technique, "
                  "palette, lighting); do not copy its subject. " + prompt)
    destino = _carpeta(datos) / "hoja.jpg"
    _ia(motor_efectivo(datos), datos).imagen(prompt, destino, [ref] if ref else [], avisar)
    datos["hoja"] = proyecto.relativa(datos, destino)
    datos["hoja_firma"] = firma_hoja(datos)
    proyecto.guardar(datos)
    avisar("Hoja de personajes lista (imagenes/hoja.jpg).")
    return destino


_NOMBRE = {"gemini": "Gemini", "openai": "OpenAI", "puter": "Puter", "pollinations": "Pollinations"}
_ERRORES = (gemini.ErrorGemini, openai_img.ErrorOpenAI, navegador.ErrorNavegador)
_CUOTA = (gemini.ErrorCuota, openai_img.ErrorCuota, navegador.SinCreditos, navegador.SinRespuesta)
_IA = ("gemini", "openai", "puter")


def _ia(motor, datos):
    """Lo que dibuja: los tres tienen imagen(prompt, destino, referencias, avisar)."""
    if motor == "puter":
        return navegador.Imagenes(datos)
    return openai_img if motor == "openai" else gemini


def _con_ia(datos, e, destino, avisar, nota, hoja, motor):
    ref = referencia(datos)
    con_hoja = bool(hoja and usa_hoja(datos, e))
    refs = ([ref] if ref else []) + ([hoja] if con_hoja else [])
    prompt = prompt_escena(datos, e, nota, con_hoja, bool(ref))
    mias = fotos(datos)[:MAX_FOTOS_REFERENCIA] if datos.get("fotos_modo") != "escenas" else []
    if mias:
        orden = "after the other references" if refs else "attached"
        prompt = (f"The {len(mias)} photo(s) {orden} are the user's OWN PHOTOS (their product, "
                  f"person, place or brand). When the scene shows that subject, reproduce it "
                  f"faithfully from those photos (shape, colors, logo, face); adapt pose, angle "
                  f"and background to the scene. " + prompt)[:2500]
    _ia(motor, datos).imagen(prompt, destino, refs + mias, avisar)


# ------------------------------------------------------------- el paso

def motor_efectivo(datos=None):
    """El motor que de verdad se usa. Con «gemini» (el de serie) y clave de OpenAI,
    OpenAI: la capa gratis de Gemini da cuota 0 de imagenes. Sin ninguna clave,
    Puter (gratis, en el navegador)."""
    if datos and datos.get("simular"):
        return "prueba"
    motor = proyecto.config()["imagen"]["motor"]
    if motor in ("gemini", "openai"):
        if openai_img.hay_clave():
            return "openai"
        if motor == "gemini" and gemini.hay_clave():
            return "gemini"
        return "puter"
    return motor


def generar_una(datos, e, avisar, nota="", motor=None, hoja=None):
    motor = motor or motor_efectivo(datos)
    destino = _carpeta(datos) / f"escena_{e['n']:03d}.jpg"
    if motor == "prueba":
        destino = destino.with_suffix(".png")
        _prueba(e["narracion"], destino, e["n"])
    elif motor in _IA:
        _con_ia(datos, e, destino, avisar, nota, hoja, motor)
    elif motor == "pollinations":
        prompt = prompt_de(datos, e) + (f". {nota}" if nota else "")
        _pollinations(prompt, destino, e["n"], avisar)
    else:
        return False                    # manual: la pega la persona
    e["imagen"] = proyecto.relativa(datos, destino)
    e["propia"] = False
    proyecto.quitar_clip(e)
    datos["mp4"] = None
    proyecto.guardar(datos)
    return True


def _guardar_data_url(data_url, destino_sin_ext):
    cabecera, _, cuerpo = data_url.partition(",")
    if not cabecera.startswith("data:image/"):
        raise ErrorImagen("eso no es una imagen")
    ext = cabecera.split("/")[1].split(";")[0].replace("jpeg", "jpg")
    if ext not in ("jpg", "png", "webp", "gif", "bmp"):
        raise ErrorImagen(f"formato {ext} no soportado (usa JPG, PNG o WEBP)")
    crudo = base64.b64decode(cuerpo)
    if len(crudo) > 25 * 1024 * 1024:
        raise ErrorImagen("la imagen pesa más de 25 MB")
    destino = destino_sin_ext.with_name(f"{destino_sin_ext.name}.{ext}")
    destino.write_bytes(crudo)
    try:
        with Image.open(destino) as im:           # que de verdad se abra
            im.verify()
    except Exception:
        destino.unlink(missing_ok=True)
        raise ErrorImagen("no se puede abrir como imagen")
    return destino


def pegar(datos, e, data_url):
    """Una imagen de la persona (hecha fuera, o una foto suya) para una escena."""
    destino = _guardar_data_url(data_url, _carpeta(datos) / f"escena_{e['n']:03d}_propia")
    e["imagen"] = proyecto.relativa(datos, destino)
    e["propia"] = True
    proyecto.quitar_clip(e)
    datos["mp4"] = None
    proyecto.guardar(datos)


# ----------------------------------------------------------- tus fotos

MAX_FOTOS = 30
MAX_FOTOS_REFERENCIA = 2       # con la de estilo y la hoja suman 4 (el tope de OpenAI)


def _carpeta_fotos(datos):
    c = _carpeta(datos) / "fotos"
    c.mkdir(exist_ok=True)
    return c


def fotos(datos):
    return [r for r in (proyecto.absoluta(datos, f) for f in datos.get("fotos") or []) if r.is_file()]


def agregar_fotos(datos, data_urls):
    lista = list(datos.get("fotos") or [])
    if len(lista) + len(data_urls) > MAX_FOTOS:
        raise ErrorImagen(f"como mucho {MAX_FOTOS} fotos por vídeo")
    base = int(time.time() * 1000)
    for i, url in enumerate(data_urls):
        destino = _guardar_data_url(url, _carpeta_fotos(datos) / f"foto_{base}_{i:02d}")
        lista.append(proyecto.relativa(datos, destino))
    datos["fotos"] = lista
    datos["fotos_modo"] = datos.get("fotos_modo") or "referencia"
    proyecto.guardar(datos)


def quitar_foto(datos, i):
    lista = list(datos.get("fotos") or [])
    if not 0 <= i < len(lista):
        raise ErrorImagen("esa foto no existe")
    rel = lista.pop(i)
    proyecto.absoluta(datos, rel).unlink(missing_ok=True)
    for e in datos["escenas"]:                 # las escenas que la usaban vuelven a quedar sin imagen
        if e.get("imagen") == rel:
            e["imagen"], e["propia"] = None, False
            proyecto.quitar_clip(e)
            datos["mp4"] = None
    datos["fotos"] = lista
    proyecto.guardar(datos)


def modo_fotos(datos, modo):
    if modo not in ("referencia", "escenas"):
        raise ErrorImagen("modo de fotos desconocido")
    datos["fotos_modo"] = modo
    proyecto.guardar(datos)


def _repartir_fotos(datos, pendientes, avisar):
    """Modo «escenas»: cada escena pendiente recibe una de TUS fotos, en orden."""
    mias = datos.get("fotos") or []
    propias = [e for e in datos["escenas"] if not e["continua"]]
    for e in pendientes:
        i = propias.index(e) * len(mias) // len(propias)      # reparto parejo y en orden
        e["imagen"] = mias[i]
        e["propia"] = True
        proyecto.quitar_clip(e)
    datos["mp4"] = None
    avisar(f"Tus {len(mias)} fotos repartidas en {len(pendientes)} escenas.")


def poner_referencia(datos, data_url):
    """La IMAGEN DE EJEMPLO del estilo (o quitarla con data_url vacio)."""
    for viejo in _carpeta(datos).glob("referencia.*"):
        viejo.unlink(missing_ok=True)
    datos["referencia"] = (proyecto.relativa(datos, _guardar_data_url(data_url, _carpeta(datos) / "referencia"))
                           if data_url else None)
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


def ejecutar(datos, avisar, solo=None, nota=""):
    elegido = proyecto.config()["imagen"]["motor"]
    motor = motor_efectivo(datos)
    if elegido in ("gemini", "openai") and motor == "pollinations":
        avisar("Sin clave de Gemini ni de OpenAI: las imágenes salen de Pollinations (gratis). "
               "Pega tu clave en el Asistente para usar la IA.")
    propias = [e for e in datos["escenas"] if not e["continua"]]
    # Sin 'solo' se hacen las que faltan: las que subio la persona no se tocan.
    pendientes = [e for e in propias if (e["n"] in solo if solo else not e["imagen"])]
    if motor == "manual" and not solo:
        avisar(f"Motor manual: pega tus imagenes en las {len(pendientes)} escenas que faltan.")
    nota = nota if solo else ""
    if datos.get("fotos_modo") == "escenas" and fotos(datos):
        _repartir_fotos(datos, pendientes, avisar)
        resolver_continuas(datos)
        proyecto.guardar(datos)
        avisar("Imagenes listas." if all(e["imagen"] for e in datos["escenas"])
               else "Faltan imagenes en algunas escenas.")
        return
    hoja = None
    if motor in _IA and any(usa_hoja(datos, e) for e in pendientes):
        try:
            hoja = _asegurar_hoja(datos, avisar)
        except _CUOTA as err:
            avisar(f"{err} Sigo con Pollinations.")
            motor = "pollinations"
        except _ERRORES as err:
            avisar(f"La hoja de personajes ha fallado ({err}); las escenas van sin ella.")
    for i, e in enumerate(pendientes, 1):
        if motor in _NOMBRE:
            avisar(f"Imagen escena {e['n']} ({i}/{len(pendientes)}) con {_NOMBRE[motor]}")
        try:
            generar_una(datos, e, avisar, nota, motor, hoja)
        except _CUOTA as err:
            avisar(f"{err} Sigo con Pollinations.")
            motor = "pollinations"
            generar_una(datos, e, avisar, nota, motor)
        except _ERRORES as err:
            avisar(f"{_NOMBRE[motor]} no pudo con la escena {e['n']} ({err}); la hago con Pollinations.")
            generar_una(datos, e, avisar, nota, "pollinations")
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
    motor = motor_efectivo(datos)
    if datos.get("fotos_modo") == "escenas" and datos.get("fotos"):
        return {"imagenes": faltan, "minutos_imagenes": 0, "motor": "fotos",
                "simular": bool(datos.get("simular"))}
    if motor in _IA:
        por_imagen = {"gemini": 15, "openai": 30, "puter": 20}[motor]
    else:
        por_imagen = 8 if proyecto.secretos().get("pollinations_token") else cfg["espera_s"]
    return {"imagenes": faltan,
            "minutos_imagenes": 0 if motor in ("prueba", "manual") else round(faltan * por_imagen / 60, 1),
            "motor": motor,
            "simular": bool(datos.get("simular"))}
