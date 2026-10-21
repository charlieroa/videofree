"""
Video Simple: de un texto a un video narrado con imagenes animadas. Gratis.

    python app.py            ->  http://127.0.0.1:8031/

Los pasos (motor/): guion -> voz -> imagenes -> montaje. Cada uno se puede
lanzar por separado desde la pantalla, y cada escena se puede rehacer sola o
recibir una imagen pegada a mano (ChatGPT, Gemini...).
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

from motor import canal, clips_gpu, gpu, guion, imagenes, montaje, proyecto, usuarios, voz, voz_gpu

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

PASOS = ("guion", "voz", "imagenes", "clips", "montaje", "todo")
VOCES = ["es-MX-JorgeNeural", "es-MX-DaliaNeural", "es-ES-AlvaroNeural", "es-ES-ElviraNeural",
         "es-ES-XimenaNeural", "es-CO-GonzaloNeural", "es-CO-SalomeNeural", "es-US-AlonsoNeural",
         "es-US-PalomaNeural", "es-AR-TomasNeural", "es-AR-ElenaNeural"]


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


def _juntar_voz_e_imagenes(datos):
    """En «Hacer todo», ¿van voz e imagenes a Kaggle? Entonces se hacen en UN trabajo."""
    if datos.get("simular") or not gpu.credenciales():
        return False
    cfg = proyecto.config()
    voz_kaggle = voz_gpu.es_suya(datos.get("voz") or cfg["voz"]["voz"])
    faltan_voz = any(not e.get("audio") for e in datos["escenas"])
    faltan_img = any(not e.get("imagen") for e in datos["escenas"] if not e.get("continua"))
    return voz_kaggle and faltan_voz and cfg["imagen"]["motor"] == "kaggle" and faltan_img


def _voz_e_imagenes_juntas(datos, avisar):
    """Voz e imagenes en hilos, con un Agrupador: hacen cola en Kaggle una sola vez."""
    dueno = datos.get("dueno")
    maquina = proyecto.config().get("imagen_gpu", {}).get("machine_shape")
    agrupador = gpu.Agrupador({"voz", "imagenes"}, avisar, maquina)
    errores = {}

    def correr(paso, hacer):
        usuarios.ACTUAL.set(dueno)               # el hilo no hereda el usuario
        try:
            hacer()
        except Exception as err:
            traceback.print_exc()
            errores[paso] = err
        finally:
            agrupador.terminado(paso)

    hilos = [threading.Thread(target=correr, args=("voz", lambda: voz.ejecutar(
                 datos, avisar, None, agrupador.ejecutor_de("voz")))),
             threading.Thread(target=correr, args=("imagenes", lambda: imagenes.ejecutar(
                 datos, avisar, None, "", agrupador.ejecutor_de("imagenes"))))]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    if errores:
        paso, err = next(iter(errores.items()))
        raise RuntimeError(f"{paso}: {err}")


def _correr(pid, paso, solo, nota):
    datos = proyecto.leer(pid)
    usuarios.ACTUAL.set(datos.get("dueno"))      # el hilo trabaja con las claves del dueno

    def avisar(texto):
        proyecto.anotar(datos, texto)

    try:
        orden = ["guion", "voz", "imagenes", "movimiento", "montaje"] if paso == "todo" else [paso]
        juntas = False
        for p in orden:
            if paso == "todo" and p == "voz" and _juntar_voz_e_imagenes(datos):
                datos["trabajo"]["paso"] = "voz + imagenes"
                proyecto.guardar(datos)
                _voz_e_imagenes_juntas(datos, avisar)
                juntas = True
                continue
            if juntas and p == "imagenes":
                if not all(e["imagen"] for e in datos["escenas"]):
                    avisar("Faltan imagenes: el montaje espera.")
                    break
                continue
            datos["trabajo"]["paso"] = p
            proyecto.guardar(datos)
            if p == "guion":
                if paso == "todo" and datos["escenas"]:
                    continue
                guion.ejecutar(datos, avisar)
            elif p == "voz":
                voz.ejecutar(datos, avisar, solo)
            elif p == "imagenes":
                imagenes.ejecutar(datos, avisar, solo, nota)
                if paso == "todo" and not all(e["imagen"] for e in datos["escenas"]):
                    avisar("Faltan imagenes por pegar: el montaje espera.")
                    break
            elif p == "clips":
                clips_gpu.ejecutar(datos, avisar, solo)
            elif p == "movimiento":
                # «Movimiento IA en todas las escenas»: todas pasan por la GPU.
                if not datos.get("movimiento"):
                    continue
                for e in datos["escenas"]:
                    e["video_ia"] = True
                proyecto.guardar(datos)
                clips_gpu.ejecutar(datos, avisar)
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


class Kaggle(BaseModel):
    usuario: str
    token: str


class MuestraVoz(BaseModel):
    audio: str              # data URL (lo que da FileReader o el grabador del navegador)
    permiso: bool = False


class Credenciales(BaseModel):
    usuario: str
    clave: str


@app.get("/")
def inicio():
    return FileResponse(WEB / "index.html")


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
        return canal.guardar(tipo, crudo)
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
    dentro = bool(usuarios.ACTUAL.get())
    natural = [{"id": "chatterbox:clon", "nombre": "Tu voz clonada", "pais": "Voz natural · GPU Kaggle",
                "genero": "", "gpu": True, "lista": dentro and voz_gpu.hay_muestra(),
                "prueba": dentro and voz_gpu.hay_muestra() and voz_gpu.ruta_prueba("chatterbox:clon").exists()},
               {"id": "chatterbox:base", "nombre": "Chatterbox", "pais": "Voz natural · GPU Kaggle",
                "genero": "", "gpu": True, "lista": True,
                "prueba": voz_gpu.ruta_prueba("chatterbox:base").exists()}]
    return natural + voz.catalogo(VOCES)


class ProbarVoz(BaseModel):
    voz: str


@app.post("/api/voz/probar")
def probar_voz(b: ProbarVoz):
    """Una frase de muestra con Chatterbox en la GPU de Kaggle, para oírla antes de usarla."""
    _yo()
    if not voz_gpu.es_suya(b.voz):
        raise HTTPException(400, "Esa voz ya se puede escuchar directamente.")
    try:
        voz_gpu.probar_en_segundo_plano(b.voz)
    except RuntimeError as err:
        raise HTTPException(400, str(err))
    return voz_gpu.estado_prueba()


@app.get("/api/voz/probar")
def estado_probar_voz():
    _yo()
    return voz_gpu.estado_prueba()


@app.post("/api/voz/muestra")
def subir_muestra(m: MuestraVoz):
    """La grabación de la persona para clonar SU voz (10-25 s)."""
    _yo()
    if not m.permiso:
        raise HTTPException(400, "Confirma que es tu voz o que tienes permiso para usarla.")
    import base64
    import tempfile
    try:
        crudo = base64.b64decode(m.audio.split(",", 1)[-1], validate=False)
    except Exception:
        raise HTTPException(400, "No he podido leer ese audio.")
    if len(crudo) > 15 * 1024 * 1024:
        raise HTTPException(400, "El audio pesa demasiado: con 20 segundos basta.")
    with tempfile.TemporaryDirectory() as tmp:
        origen = Path(tmp) / "entrada"
        origen.write_bytes(crudo)
        try:
            segundos = voz_gpu.guardar_muestra(origen)
        except ValueError as err:
            raise HTTPException(400, str(err))
        except Exception:
            raise HTTPException(400, "No he podido leer ese audio. Prueba con un mp3, wav o m4a.")
    return {"ok": True, "segundos": segundos}


@app.get("/api/voces/{voz_id}/muestra")
def muestra_voz(voz_id: str):
    _yo()
    try:
        return FileResponse(voz.muestra(voz_id), media_type="audio/mpeg")
    except ValueError as err:
        raise HTTPException(404, str(err))
    except Exception:
        raise HTTPException(502, "No se pudo generar la muestra; revisa tu conexión.")


@app.get("/api/config")
def ver_config():
    cfg = proyecto.config()
    yo = usuarios.ACTUAL.get()
    return {"voz": cfg["voz"]["voz"], "voces": VOCES,
            "motor_imagen": cfg["imagen"]["motor"], "motor_guion": cfg["guion"]["motor"],
            "token_pollinations": bool(yo and proyecto.secretos().get("pollinations_token")),
            "asistente_hecho": bool(yo and proyecto.secretos().get("asistente_hecho")),
            "gpu_conectada": bool(yo and gpu.credenciales())}


@app.post("/api/config")
def guardar_config(a: Ajustes):
    _yo()
    cfg = proyecto.config()
    if a.voz:
        cfg["voz"]["voz"] = _voz_valida(a.voz)
    if a.motor_imagen in ("pollinations", "manual", "kaggle"):
        cfg["imagen"]["motor"] = a.motor_imagen
    if a.motor_guion in ("claude", "ollama", "manual"):
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
    return datos


@app.get("/api/proyectos/{pid}")
def ver(pid: str):
    datos = _mio(pid)
    datos["ocupado"] = _ocupado(pid)
    if not datos["ocupado"] and datos.get("trabajo"):
        datos["trabajo"] = None            # quedo a medias al cerrar el programa
    datos["estimacion"] = imagenes.estimar(datos)
    datos["prompts"] = {e["n"]: imagenes.prompt_de(datos, e) for e in datos["escenas"]}
    datos["video_ia"] = clips_gpu.estimar(datos)
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


@app.post("/api/proyectos/{pid}/paso")
def lanzar(pid: str, p: Paso):
    _mio(pid)
    if p.paso not in PASOS:
        raise HTTPException(400, f"Paso desconocido: {p.paso}")
    if _ocupado(pid):
        raise HTTPException(409, "Ya hay un trabajo en marcha en este video.")
    datos = _mio(pid)
    usa_gpu = p.paso == "clips" or (p.paso in ("imagenes", "todo")
                                    and proyecto.config()["imagen"]["motor"] == "kaggle")
    if usa_gpu and not datos.get("simular") and not gpu.credenciales():
        raise HTTPException(400, "La GPU no está conectada. Abre el Asistente (paso 5) y "
                                 "conecta tu cuenta de Kaggle.")
    datos["trabajo"] = {"paso": p.paso, "inicio": time.strftime("%H:%M:%S")}
    proyecto.guardar(datos)
    h = threading.Thread(target=_correr, args=(pid, p.paso, p.solo, p.nota), daemon=True)
    _hilos[pid] = h
    h.start()
    return {"ok": True}


# ------------------------------------------------------- el asistente

@app.get("/api/diagnostico")
def diagnostico():
    """Lo que hay en esta maquina, para que el asistente proponga lo que funciona."""
    _yo()
    from motor import medios
    res = {"ffmpeg": bool(medios.FFMPEG)}
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
            v = proyecto.config()["voz"]["voz"]
            asyncio.run(edge_tts.Communicate("Hola", VOCES[0] if voz_gpu.es_suya(v) else v).save(f"{tmp}/p.mp3"))
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


@app.post("/api/gpu/conectar")
def gpu_conectar(k: Kaggle):
    _yo()
    if not k.usuario.strip() or not k.token.strip():
        raise HTTPException(400, "Pon tu usuario y tu token de Kaggle.")
    antes = gpu.credenciales()
    gpu.guardar(k.usuario, k.token)
    ok, texto = gpu.verificar()
    if not ok:
        # Lo que no sirve no se queda guardado: se vuelve a lo que habia.
        if antes:
            gpu.guardar(antes["kaggle_usuario"], antes["kaggle_token"])
        else:
            gpu.olvidar()
        raise HTTPException(400, "Kaggle no acepta ese usuario o token. Genera uno nuevo en "
                                 "kaggle.com/settings/api (Generate New Token) y pégalo entero.")
    return {"ok": True, "texto": texto}


@app.post("/api/gpu/probar")
def gpu_probar():
    _yo()
    if not gpu.credenciales():
        raise HTTPException(400, "Primero conecta tu cuenta de Kaggle.")
    gpu.probar_en_segundo_plano()
    return gpu.estado_prueba()


@app.get("/api/gpu/estado")
def gpu_estado():
    _yo()
    return {**gpu.estado_prueba(), "conectada": bool(gpu.credenciales())}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--puerto", type=int, default=8031)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    if a.host not in ("127.0.0.1", "localhost", "::1"):
        print(f"Aviso: escuchando en {a.host}. Desde este PC se entra sin cuenta; "
              "desde otras maquinas se pide usuario y contraseña.")
    uvicorn.run(app, host=a.host, port=a.puerto)
