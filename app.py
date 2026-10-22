"""
Video Simple: de un texto a un video narrado con imagenes animadas. Gratis.

    python app.py            ->  http://127.0.0.1:8031/

Los pasos (motor/): guion -> voz -> imagenes -> montaje. Con la clave de Gemini
de la persona (motor/gemini.py) salen solos a partir del tema y la linea grafica
(texto y/o una imagen de ejemplo). Cada paso se puede lanzar por separado, y cada
escena se puede rehacer sola o recibir una imagen propia (subida o pegada).
"""
import argparse
from pathlib import Path
import json
import shutil
import subprocess
import threading
import time
import traceback
from http.cookies import SimpleCookie

import requests
import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from motor import canal, gemini, guion, imagenes, montaje, navegador, nichos, openai_img, proyecto, usuarios, voz

app = FastAPI(title="Video Simple")
WEB = proyecto.RAIZ / "web"
proyecto.PROYECTOS.mkdir(exist_ok=True)


class Sesion:
    """Pone en usuarios.ACTUAL quien hace cada peticion (por su cookie de sesion).

    Middleware ASGI a pelo y no BaseHTTPMiddleware: asi la variable de contexto
    llega tal cual a los endpoints, que corren en otro hilo.
    """

    def __init__(self, siguiente):
        self.siguiente = siguiente

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            crudo = dict(scope.get("headers") or []).get(b"cookie", b"").decode("latin-1")
            galleta = SimpleCookie()
            try:
                galleta.load(crudo)
            except Exception:
                pass
            token = galleta[usuarios.COOKIE].value if usuarios.COOKIE in galleta else None
            nombre = usuarios.de_sesion(token)
            local = usuarios.es_local(scope)
            if not nombre and local:              # desde este PC se entra sin cuenta
                nombre = usuarios.por_defecto()
            scope.setdefault("state", {})["local"] = local
            usuarios.ACTUAL.set(nombre)
        await self.siguiente(scope, receive, send)


app.add_middleware(Sesion)
# El video de muestra que ve quien abre la herramienta por primera vez. Va en el
# repositorio (web/ejemplo/ejemplo.mp4), comprimido a 720p para que pese poco.
(WEB / "ejemplo").mkdir(exist_ok=True)
app.mount("/ejemplo", StaticFiles(directory=WEB / "ejemplo"), name="ejemplo")

_hilos = {}

PASOS = ("guion", "voz", "imagenes", "montaje", "todo")


# ------------------------------------------------------------- trabajos

def _yo():
    nombre = usuarios.ACTUAL.get()
    if not nombre:
        raise HTTPException(401, "Entra con tu usuario.")
    return nombre


def _mio(pid):
    """El proyecto, solo si es de quien lo pide (si no, como si no existiera)."""
    yo = _yo()
    try:
        datos = proyecto.leer(pid)
    except (FileNotFoundError, OSError):
        raise HTTPException(404, "No existe ese proyecto.")
    if datos.get("dueno") != yo:
        raise HTTPException(404, "No existe ese proyecto.")
    return datos


def _correr(pid, paso, solo, nota):
    datos = proyecto.leer(pid)
    usuarios.ACTUAL.set(datos.get("dueno"))      # el hilo trabaja con las claves del dueno

    def avisar(texto):
        proyecto.anotar(datos, texto)

    try:
        orden = ["guion", "voz", "imagenes", "montaje"] if paso == "todo" else [paso]
        for p in orden:
            datos["trabajo"]["paso"] = p
            proyecto.guardar(datos)
            if p == "guion":
                if paso == "todo" and datos["escenas"]:
                    continue
                guion.ejecutar(datos, avisar)
                if paso == "todo" and not datos["escenas"]:
                    avisar("Falta el guion: pégalo y vuelve a pulsar «Hacer todo».")
                    break
            elif p == "voz":
                voz.ejecutar(datos, avisar, solo)
            elif p == "imagenes":
                imagenes.ejecutar(datos, avisar, solo, nota)
                if paso == "todo" and not all(e["imagen"] for e in datos["escenas"]):
                    avisar("Faltan imagenes por pegar: el montaje espera.")
                    break
            elif p == "montaje":
                montaje.ejecutar(datos, avisar)
            proyecto.guardar(datos)
        avisar(f"Terminado: {paso}.")
    except Exception as err:
        traceback.print_exc()
        avisar(f"ERROR en {paso}: {err}")
    finally:
        datos["trabajo"] = None
        proyecto.guardar(datos)
        _hilos.pop(pid, None)


def _ocupado(pid):
    h = _hilos.get(pid)
    return h is not None and h.is_alive()


# --------------------------------------------------------------- rutas

class Nuevo(BaseModel):
    titulo: str
    texto: str
    minutos: float = 2
    estilo: str = ""
    tono: str = ""
    simular: bool = False
    voz: str = ""
    movimiento: bool = False
    referencia: str = ""        # imagen de ejemplo del estilo (data URL), opcional
    fotos: list[str] = []       # TUS fotos (data URLs): referencia para la IA o las imagenes mismas
    fotos_modo: str = "referencia"
    auto: bool = True           # lanzar «Hacer todo» al crear


class Paso(BaseModel):
    paso: str
    solo: list[int] | None = None
    nota: str = ""


class Escena(BaseModel):
    narracion: str | None = None
    visual: str | None = None
    continua: bool | None = None
    video_ia: bool | None = None


class Pegada(BaseModel):
    imagen: str


class Ajustes(BaseModel):
    simular: bool | None = None
    voz: str | None = None
    movimiento: bool | None = None
    motor_imagen: str | None = None
    motor_guion: str | None = None
    token_pollinations: str | None = None
    asistente_hecho: bool | None = None


class GuionPegado(BaseModel):
    texto: str


class ClaveGemini(BaseModel):
    clave: str


class Credenciales(BaseModel):
    usuario: str
    clave: str


@app.get("/")
def inicio():
    # Sin cache: tras actualizar la app, recargar basta para ver la pantalla nueva.
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})


def _es_local(peticion):
    return bool(peticion.scope.get("state", {}).get("local"))


@app.get("/api/sesion")
def sesion(peticion: Request):
    local = _es_local(peticion)
    return {"usuario": usuarios.ACTUAL.get(), "hay_usuarios": usuarios.hay_usuarios(),
            "local": local, "usuarios": usuarios.nombres() if local else []}


class Cambio(BaseModel):
    usuario: str


@app.post("/api/usar")
def usar(c: Cambio, peticion: Request, respuesta: Response):
    """Cambiar de usuario sin contrasena: solo desde este mismo PC."""
    if not _es_local(peticion):
        raise HTTPException(403, "Desde otra máquina hay que entrar con contraseña.")
    nombre = (c.usuario or "").strip().lower()
    if nombre not in usuarios.nombres():
        raise HTTPException(404, "No existe ese usuario.")
    return _con_sesion(respuesta, nombre)


def _con_sesion(respuesta, nombre):
    respuesta.set_cookie(usuarios.COOKIE, usuarios.abrir_sesion(nombre), httponly=True,
                         samesite="lax", max_age=usuarios.DURACION_SESION)
    return {"usuario": nombre}


@app.post("/api/entrar")
def entrar(c: Credenciales, respuesta: Response):
    nombre = usuarios.comprobar(c.usuario, c.clave)
    if not nombre:
        raise HTTPException(401, "Usuario o contraseña incorrectos.")
    return _con_sesion(respuesta, nombre)


@app.post("/api/registro")
def registro(c: Credenciales, respuesta: Response):
    try:
        nombre = usuarios.crear(c.usuario, c.clave)
    except usuarios.ErrorUsuario as err:
        raise HTTPException(400, str(err))
    return _con_sesion(respuesta, nombre)


@app.post("/api/salir")
def salir(peticion: Request, respuesta: Response):
    usuarios.cerrar_sesion(peticion.cookies.get(usuarios.COOKIE))
    respuesta.delete_cookie(usuarios.COOKIE)
    return {"ok": True}


@app.get("/archivos/{pid}/{ruta:path}")
def archivo(pid: str, ruta: str):
    """Los ficheros de un proyecto (imagenes, voz, video), solo para su dueno."""
    _mio(pid)
    base = proyecto.carpeta(pid).resolve()
    destino = (base / ruta).resolve()
    if base not in destino.parents or not destino.is_file():
        raise HTTPException(404, "No existe ese fichero.")
    return FileResponse(destino)


# ------------------------------------------------------------ el canal

class ImagenCanal(BaseModel):
    imagen: str             # data URL (lo que da FileReader)
    recorte: dict | None = None     # {x, y, w, h} en fracciones de la foto: el encuadre a mano


@app.get("/api/canal")
def ver_canal():
    _yo()
    return {"hechas": canal.estado(),
            "medidas": {"perfil": canal.PERFIL, "banner": canal.BANNER,
                        "escritorio": canal.ESCRITORIO, "segura": canal.SEGURA}}


@app.post("/api/canal/{tipo}")
def subir_canal(tipo: str, b: ImagenCanal):
    """Una foto cualquiera -> foto de perfil o banner con las medidas de YouTube."""
    _yo()
    if tipo not in canal.ARCHIVO:
        raise HTTPException(404, "Solo hay perfil y banner.")
    import base64
    try:
        crudo = base64.b64decode(b.imagen.split(",", 1)[-1], validate=False)
    except Exception:
        raise HTTPException(400, "No he podido leer esa imagen.")
    if len(crudo) > 25 * 1024 * 1024:
        raise HTTPException(400, "La imagen pesa más de 25 MB.")
    try:
        return canal.guardar(tipo, crudo, b.recorte)
    except ValueError as err:
        raise HTTPException(400, str(err))


@app.get("/canal/{tipo}")
def archivo_canal(tipo: str):
    _yo()
    ruta = canal.carpeta() / canal.ARCHIVO.get(tipo, "-")
    if not ruta.is_file():
        raise HTTPException(404, "Todavía no está hecha.")
    return FileResponse(ruta, headers={"Cache-Control": "no-store"},
                        filename=f"youtube-{canal.ARCHIVO[tipo]}")


def _voz_valida(v):
    if not voz.valida(v):
        raise HTTPException(400, "Esa voz no existe.")
    return v


@app.get("/api/voces")
def voces():
    _yo()
    return voz.catalogo()


@app.get("/api/voces/{voz_id}/muestra")
def muestra_voz(voz_id: str):
    _yo()
    try:
        return FileResponse(voz.muestra(voz_id), media_type="audio/mpeg")
    except ValueError as err:
        raise HTTPException(404, str(err))
    except gemini.ErrorGemini as err:
        raise HTTPException(502, str(err))
    except Exception:
        raise HTTPException(502, "No se pudo generar la muestra; revisa tu conexión.")


@app.get("/api/config")
def ver_config():
    cfg = proyecto.config()
    yo = usuarios.ACTUAL.get()
    return {"voz": cfg["voz"]["voz"],
            "motor_imagen": cfg["imagen"]["motor"], "motor_guion": cfg["guion"]["motor"],
            # lo que de verdad se usa (Gemini sin clave: guion a mano e imagenes de Pollinations)
            "guion_efectivo": guion.motor_efectivo() if yo else cfg["guion"]["motor"],
            "imagen_efectivo": imagenes.motor_efectivo() if yo else cfg["imagen"]["motor"],
            "token_pollinations": bool(yo and proyecto.secretos().get("pollinations_token")),
            "asistente_hecho": bool(yo and proyecto.secretos().get("asistente_hecho")),
            "gemini": bool(yo and gemini.hay_clave()),
            "openai": bool(yo and openai_img.hay_clave())}


@app.post("/api/config")
def guardar_config(a: Ajustes):
    _yo()
    cfg = proyecto.config()
    if a.voz:
        cfg["voz"]["voz"] = _voz_valida(a.voz)
    if a.motor_imagen in ("gemini", "openai", "puter", "pollinations", "manual"):
        cfg["imagen"]["motor"] = a.motor_imagen
    if a.motor_guion in ("gemini", "openai", "puter", "claude", "ollama", "manual"):
        cfg["guion"]["motor"] = a.motor_guion
    if a.token_pollinations is not None:
        proyecto.guardar_secreto("pollinations_token", a.token_pollinations.strip())
    if a.asistente_hecho is not None:
        proyecto.guardar_secreto("asistente_hecho", a.asistente_hecho)
    proyecto.CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return ver_config()


class Publicado(BaseModel):
    publicado: bool
    url: str = ""


@app.get("/api/proyectos")
def lista():
    salida = proyecto.listar(_yo())
    for p in salida:
        p["ocupado"] = _ocupado(p["id"])
    return salida


@app.post("/api/proyectos/{pid}/publicado")
def marcar_publicado(pid: str, b: Publicado):
    """El tablero separa lo publicado: se marca a mano, con el enlace de YouTube si se tiene."""
    datos = _mio(pid)
    if _ocupado(pid):
        raise HTTPException(409, "Espera a que termine el trabajo en marcha.")
    url = b.url.strip()
    if url and not url.startswith(("https://", "http://")):
        raise HTTPException(400, "El enlace tiene que empezar por https://")
    datos["publicado"] = {"url": url, "fecha": time.strftime("%Y-%m-%d")} if b.publicado else None
    proyecto.guardar(datos)
    return proyecto.resumen(datos)


@app.post("/api/proyectos")
def nuevo(n: Nuevo):
    _yo()
    if not n.texto.strip():
        raise HTTPException(400, "Escribe el material del video.")
    datos = proyecto.crear(n.titulo.strip() or "Video", n.texto, n.minutos, n.estilo, _yo())
    datos["simular"] = n.simular
    datos["tono"] = n.tono.strip()
    if n.voz:
        datos["voz"] = _voz_valida(n.voz)
    datos["movimiento"] = n.movimiento
    proyecto.guardar(datos)
    if n.referencia:
        try:
            imagenes.poner_referencia(datos, n.referencia)
        except Exception as err:
            raise HTTPException(400, f"No he podido usar la imagen de ejemplo: {err}")
    if n.fotos:
        try:
            imagenes.agregar_fotos(datos, n.fotos)
            imagenes.modo_fotos(datos, n.fotos_modo)
        except Exception as err:
            raise HTTPException(400, f"No he podido usar tus fotos: {err}")
    # Flujo automatico: si el guion lo escribe una IA, se lanza todo de una vez.
    if n.auto and guion.motor_efectivo(datos) != "manual":
        _arrancar(datos["id"], "todo")
    return datos


@app.get("/api/proyectos/{pid}")
def ver(pid: str):
    datos = _mio(pid)
    datos["ocupado"] = _ocupado(pid)
    if not datos["ocupado"] and datos.get("trabajo"):
        datos["trabajo"] = None            # quedo a medias al cerrar el programa
        datos["voz_navegador"] = None
    datos["pedido_navegador"] = navegador.pendiente(pid) if datos["ocupado"] else None
    datos["estimacion"] = imagenes.estimar(datos)
    datos["prompts"] = {e["n"]: imagenes.prompt_de(datos, e) for e in datos["escenas"]}
    datos["sello"] = time.time()
    return datos


@app.post("/api/proyectos/{pid}/ajustes")
def ajustes(pid: str, a: Ajustes):
    _mio(pid)
    if _ocupado(pid):
        raise HTTPException(409, "Hay un trabajo en marcha.")
    datos = _mio(pid)
    if a.simular is not None:
        datos["simular"] = a.simular
    if a.movimiento is not None and a.movimiento != bool(datos.get("movimiento")):
        datos["movimiento"] = a.movimiento
        for e in datos["escenas"]:              # los clips se hicieron con otro movimiento
            proyecto.quitar_clip(e)
        datos["mp4"] = None
    if a.voz and a.voz != datos.get("voz"):
        datos["voz"] = _voz_valida(a.voz)
        for e in datos["escenas"]:              # otra voz: hay que volver a narrar
            e["audio"], e["duracion"] = None, None
        datos["mp4"] = None
    proyecto.guardar(datos)
    return ver(pid)


def _escena(datos, n):
    e = next((x for x in datos["escenas"] if x["n"] == n), None)
    if not e:
        raise HTTPException(404, "No existe esa escena.")
    return e


@app.patch("/api/proyectos/{pid}/escena/{n}")
def editar_escena(pid: str, n: int, cambio: Escena):
    _mio(pid)
    if _ocupado(pid):
        raise HTTPException(409, "Hay un trabajo en marcha.")
    datos = _mio(pid)
    e = _escena(datos, n)
    if cambio.narracion is not None and cambio.narracion != e["narracion"]:
        e["narracion"], e["audio"], e["duracion"] = cambio.narracion, None, None
    if cambio.visual is not None and cambio.visual != e["visual"]:
        e["visual"], e["imagen"] = cambio.visual, None
        proyecto.quitar_clip(e)
    if cambio.continua is not None and n > 1 and cambio.continua != e["continua"]:
        e["continua"], e["imagen"] = cambio.continua, None
        proyecto.quitar_clip(e)
        imagenes.resolver_continuas(datos)
    if cambio.video_ia is not None:
        e["video_ia"] = cambio.video_ia
    datos["mp4"] = None
    proyecto.guardar(datos)
    return ver(pid)


class RespuestaNavegador(BaseModel):
    id: str
    resultado: str | None = None    # el texto, o la imagen en data URL
    error: str = ""


@app.post("/api/proyectos/{pid}/navegador")
def respuesta_navegador(pid: str, r: RespuestaNavegador):
    """La pestaña contesta un pedido de Puter (guion o imagen) del paso en marcha."""
    _mio(pid)
    if not navegador.responder(pid, r.id, r.resultado, r.error):
        raise HTTPException(409, "Ese pedido ya no está pendiente.")
    return {"ok": True}


class AudioEscena(BaseModel):
    audio: str              # data URL del audio que hizo el navegador con Puter


@app.post("/api/proyectos/{pid}/escena/{n}/audio")
def subir_audio(pid: str, n: int, a: AudioEscena):
    """La narracion de una escena hecha en el navegador (voz de Gemini sin clave, via Puter).
    Solo mientras el paso de voz la espera: es lo unico que puede escribir con un trabajo en marcha."""
    datos = _mio(pid)
    if not datos.get("voz_navegador") or not _ocupado(pid):
        raise HTTPException(409, "Este vídeo no está esperando voz del navegador.")
    import base64
    try:
        crudo = base64.b64decode(a.audio.split(",", 1)[-1], validate=False)
    except Exception:
        raise HTTPException(400, "No he podido leer ese audio.")
    if not crudo or len(crudo) > 20 * 1024 * 1024:
        raise HTTPException(400, "Audio vacío o demasiado grande.")
    e = _escena(datos, n)
    try:
        voz.guardar_audio(datos, e, crudo)
    except Exception as err:
        raise HTTPException(400, f"No he podido usar ese audio: {err}")
    return {"ok": True, "duracion": e["duracion"]}


@app.post("/api/proyectos/{pid}/escena/{n}/imagen")
def pegar_imagen(pid: str, n: int, p: Pegada):
    _mio(pid)
    if _ocupado(pid):
        raise HTTPException(409, "Hay un trabajo en marcha.")
    datos = _mio(pid)
    e = _escena(datos, n)
    e["continua"] = False                   # con imagen propia deja de reusar la anterior
    try:
        imagenes.pegar(datos, e, p.imagen)
    except Exception as err:
        raise HTTPException(400, f"No he podido usar esa imagen: {err}")
    imagenes.resolver_continuas(datos)
    proyecto.guardar(datos)
    return ver(pid)


class Referencia(BaseModel):
    imagen: str = ""        # data URL; vacio = quitarla


@app.post("/api/proyectos/{pid}/referencia")
def poner_referencia(pid: str, r: Referencia):
    """La imagen de ejemplo del estilo. Cambiarla rehace la hoja de personajes."""
    _mio(pid)
    if _ocupado(pid):
        raise HTTPException(409, "Hay un trabajo en marcha.")
    datos = _mio(pid)
    try:
        imagenes.poner_referencia(datos, r.imagen)
    except Exception as err:
        raise HTTPException(400, f"No he podido usar esa imagen: {err}")
    return ver(pid)


class Fotos(BaseModel):
    imagenes: list[str] = []    # data URLs para añadir
    modo: str = ""              # "referencia" | "escenas"


@app.post("/api/proyectos/{pid}/fotos")
def poner_fotos(pid: str, f: Fotos):
    """Añadir fotos tuyas al vídeo y/o cambiar cómo se usan."""
    _mio(pid)
    if _ocupado(pid):
        raise HTTPException(409, "Hay un trabajo en marcha.")
    datos = _mio(pid)
    try:
        if f.imagenes:
            imagenes.agregar_fotos(datos, f.imagenes)
        if f.modo:
            imagenes.modo_fotos(datos, f.modo)
    except Exception as err:
        raise HTTPException(400, f"No he podido usar esas fotos: {err}")
    return ver(pid)


@app.delete("/api/proyectos/{pid}/fotos/{i}")
def quitar_foto(pid: str, i: int):
    _mio(pid)
    if _ocupado(pid):
        raise HTTPException(409, "Hay un trabajo en marcha.")
    datos = _mio(pid)
    try:
        imagenes.quitar_foto(datos, i)
    except Exception as err:
        raise HTTPException(400, str(err))
    return ver(pid)


def _arrancar(pid, paso, solo=None, nota=""):
    datos = proyecto.leer(pid)
    datos["trabajo"] = {"paso": paso, "inicio": time.strftime("%H:%M:%S")}
    proyecto.guardar(datos)
    h = threading.Thread(target=_correr, args=(pid, paso, solo, nota), daemon=True)
    _hilos[pid] = h
    h.start()


@app.post("/api/proyectos/{pid}/paso")
def lanzar(pid: str, p: Paso):
    _mio(pid)
    if p.paso not in PASOS:
        raise HTTPException(400, f"Paso desconocido: {p.paso}")
    if _ocupado(pid):
        raise HTTPException(409, "Ya hay un trabajo en marcha en este video.")
    _arrancar(pid, p.paso, p.solo, p.nota)
    return {"ok": True}


# ------------------------------------------------------- el asistente

@app.get("/api/diagnostico")
def diagnostico():
    """Lo que hay en esta maquina, para que el asistente proponga lo que funciona."""
    _yo()
    from motor import medios
    res = {"ffmpeg": bool(medios.FFMPEG), "gemini": gemini.hay_clave(),
           "openai": openai_img.hay_clave()}
    exe = shutil.which("claude")
    res["claude"] = False
    if exe:
        try:
            r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=20)
            res["claude"] = r.returncode == 0
        except Exception:
            pass
    try:
        r = requests.get("http://127.0.0.1:11434/api/tags", timeout=3)
        res["ollama"] = [m["name"] for m in r.json().get("models", [])]
    except Exception:
        res["ollama"] = None
    try:
        res["internet"] = requests.get("https://image.pollinations.ai/", timeout=10).status_code < 500
    except Exception:
        res["internet"] = False
    try:
        import asyncio
        import tempfile
        import edge_tts
        with tempfile.TemporaryDirectory() as tmp:
            asyncio.run(edge_tts.Communicate("Hola", voz.JORGE).save(f"{tmp}/p.mp3"))
        res["voz"] = True
    except Exception:
        res["voz"] = False
    return res


@app.get("/api/proyectos/{pid}/guion_prompt")
def guion_prompt(pid: str):
    return {"prompt": guion.prompt_manual(_mio(pid))}


@app.post("/api/proyectos/{pid}/guion_pegado")
def guion_pegado(pid: str, g: GuionPegado):
    _mio(pid)
    if _ocupado(pid):
        raise HTTPException(409, "Hay un trabajo en marcha.")
    datos = _mio(pid)
    try:
        guion.pegar(datos, g.texto)
    except Exception as err:
        raise HTTPException(400, str(err))
    proyecto.anotar(datos, f"Guion pegado: {len(datos['escenas'])} escenas.")
    return ver(pid)


@app.get("/api/gemini")
def gemini_estado():
    _yo()
    return {"conectada": gemini.hay_clave()}


@app.post("/api/gemini")
def gemini_guardar(c: ClaveGemini):
    """Probar la clave (sin gastar cuota: solo lista modelos) y, si vale, guardarla."""
    _yo()
    k = c.clave.strip()
    if not k:
        raise HTTPException(400, "Pega tu clave de Gemini (aistudio.google.com/apikey).")
    ok, texto = gemini.probar(k)
    if not ok:
        raise HTTPException(400, texto)       # lo que no sirve no se guarda
    gemini.guardar_clave(k)
    return {"ok": True, "texto": texto, "modelos": gemini.resumen_modelos()}


@app.delete("/api/gemini")
def gemini_olvidar():
    _yo()
    gemini.olvidar_clave()
    return {"ok": True}


# ----------------------------------------------------------- nichos de YouTube

def _nichos(hacer):
    _yo()
    try:
        return hacer()
    except nichos.ErrorNichos as err:
        raise HTTPException(400, str(err))


@app.get("/api/nichos")
def ver_nichos():
    return _nichos(lambda: {"clave": bool(nichos.clave()), "propia": nichos.tiene_clave_propia(),
                            "nichos": nichos.catalogo()})


@app.get("/api/nichos/{nid}")
def ver_nicho(nid: str, forzar: bool = False):
    return _nichos(lambda: nichos.nicho(nid, forzar))


class Busqueda(BaseModel):
    consulta: str
    forzar: bool = False


@app.post("/api/nichos/buscar")
def buscar_nicho(b: Busqueda):
    return _nichos(lambda: nichos.analizar(b.consulta, forzar=b.forzar))


@app.get("/api/tendencias")
def ver_tendencias(region: str = "CO", forzar: bool = False):
    return _nichos(lambda: nichos.tendencias(region, forzar))


@app.post("/api/youtube")
def youtube_guardar(c: ClaveGemini):
    """La clave de la YouTube Data API (se prueba con una llamada de 1 unidad)."""
    _yo()
    k = c.clave.strip()
    if not k:
        raise HTTPException(400, "Pega tu clave de YouTube Data API.")
    ok, texto = nichos.probar(k)
    if not ok:
        raise HTTPException(400, texto)
    nichos.guardar_clave(k)
    return {"ok": True, "texto": texto}


@app.get("/api/openai")
def openai_estado():
    _yo()
    return {"conectada": openai_img.hay_clave()}


@app.post("/api/openai")
def openai_guardar(c: ClaveGemini):
    """Probar la clave de OpenAI (solo lista modelos: no gasta saldo) y, si vale, guardarla."""
    _yo()
    k = c.clave.strip()
    if not k:
        raise HTTPException(400, "Pega tu clave de OpenAI (platform.openai.com/api-keys).")
    ok, texto = openai_img.probar(k)
    if not ok:
        raise HTTPException(400, texto)       # lo que no sirve no se guarda
    openai_img.guardar_clave(k)
    return {"ok": True, "texto": texto,
            "modelos": {"texto": openai_img.modelo_texto(), "imagen": openai_img.modelo_imagen()}}


@app.delete("/api/openai")
def openai_olvidar():
    _yo()
    openai_img.olvidar_clave()
    return {"ok": True}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--puerto", type=int, default=8031)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    if a.host not in ("127.0.0.1", "localhost", "::1"):
        print(f"Aviso: escuchando en {a.host}. Desde este PC se entra sin cuenta; "
              "desde otras maquinas se pide usuario y contraseña.")
    uvicorn.run(app, host=a.host, port=a.puerto)
