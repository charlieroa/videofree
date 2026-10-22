"""
Donde vive cada video y su estado.

Un proyecto es una carpeta en proyectos/<id>/ con un proyecto.json y los
ficheros que van saliendo (voz/, imagenes/, montaje/). Todo lo que
la pantalla ensena sale de ese json: si se cierra el programa a medias, al
volver se sigue donde se quedo.
"""
import json
import re
import threading
import time
import unicodedata
from pathlib import Path

from . import usuarios

RAIZ = Path(__file__).resolve().parent.parent
PROYECTOS = RAIZ / "proyectos"
CONFIG = RAIZ / "config.json"
# Claves de cada persona (Gemini, Pollinations): un fichero por usuario en
# secretos/<usuario>.json. Nunca en config.json: la carpeta esta en .gitignore
# y no se sube al repositorio.
SECRETOS_DIR = RAIZ / "secretos"

_cerrojo = threading.Lock()


def config():
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def _fichero_secretos():
    nombre = usuarios.ACTUAL.get()
    if not nombre:
        raise RuntimeError("No hay usuario: las claves son de cada cuenta.")
    SECRETOS_DIR.mkdir(exist_ok=True)
    return SECRETOS_DIR / f"{nombre}.json"


def secretos():
    ruta = _fichero_secretos()
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else {}


def guardar_secreto(clave, valor):
    datos = secretos()
    datos[clave] = valor
    _fichero_secretos().write_text(json.dumps(datos, indent=2), encoding="utf-8")


def borrar_secretos(*claves):
    datos = secretos()
    for clave in claves:
        datos.pop(clave, None)
    _fichero_secretos().write_text(json.dumps(datos, indent=2), encoding="utf-8")


# --------------------------------------------------------------- proyectos

def _slug(texto):
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    texto = re.sub(r"[^a-zA-Z0-9]+", "-", texto).strip("-").lower()
    return texto[:40] or "video"


def carpeta(pid):
    return PROYECTOS / pid


def crear(titulo, texto, minutos, estilo, dueno):
    PROYECTOS.mkdir(exist_ok=True)
    pid = f"{time.strftime('%Y%m%d-%H%M%S')}-{_slug(titulo)}"
    datos = {
        "id": pid,
        "dueno": dueno,
        "titulo": titulo,
        "texto": texto,
        "minutos": float(minutos),
        "estilo": estilo,
        "creado": time.strftime("%Y-%m-%d %H:%M:%S"),
        "biblia": None,
        "escenas": [],
        "mp4": None,
        "trabajo": None,
        "registro": [],
    }
    carpeta(pid).mkdir(parents=True)
    guardar(datos)
    return datos


def leer(pid):
    return json.loads((carpeta(pid) / "proyecto.json").read_text(encoding="utf-8"))


def guardar(datos):
    with _cerrojo:
        ruta = carpeta(datos["id"]) / "proyecto.json"
        tmp = ruta.with_suffix(".tmp")
        tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(ruta)


def listar(dueno):
    if not PROYECTOS.exists():
        return []
    salida = []
    for d in sorted(PROYECTOS.iterdir(), reverse=True):
        if (d / "proyecto.json").exists():
            p = leer(d.name)
            if p.get("dueno") != dueno:
                continue
            salida.append(resumen(p))
    return salida


def estado(p):
    """En qué punto va el video, para el tablero: lo primero que falte."""
    if p.get("publicado"):
        return "publicado"
    if p.get("mp4"):
        return "listo"
    esc = p["escenas"]
    if not esc:
        return "guion"
    if not all(e.get("audio") for e in esc):
        return "voz"
    if not all(e.get("imagen") for e in esc):
        return "imagenes"
    return "montaje"


def resumen(p):
    """Lo que enseña cada tarjeta del tablero."""
    esc = p["escenas"]
    portada = next((e["imagen"] for e in esc if e.get("imagen")), None)
    return {"id": p["id"], "titulo": (p.get("biblia") or {}).get("titulo") or p["titulo"],
            "creado": p["creado"], "escenas": len(esc), "mp4": p["mp4"], "portada": portada,
            "segundos": round(sum(e.get("duracion") or 0 for e in esc)), "minutos": p.get("minutos"),
            "voz": p.get("voz"), "estilo": p.get("estilo", ""), "tono": p.get("tono", ""),
            "clips": sum(1 for e in esc if e.get("clip")), "estado": estado(p),
            "publicado": p.get("publicado"), "simular": bool(p.get("simular"))}


def anotar(datos, texto):
    """Una linea en el registro del proyecto (lo que la pantalla ensena abajo)."""
    datos["registro"].append(f"{time.strftime('%H:%M:%S')}  {texto}")
    datos["registro"] = datos["registro"][-200:]
    guardar(datos)


def relativa(datos, ruta):
    """Ruta dentro de la carpeta del proyecto, para guardar en el json."""
    return Path(ruta).resolve().relative_to(carpeta(datos["id"]).resolve()).as_posix()


def absoluta(datos, rel):
    return carpeta(datos["id"]) / rel


def quitar_clip(e):
    """La escena cambia de imagen o de 'que se ve': su clip de video IA ya no vale.

    El fichero se queda en clips/ (se sobrescribe al rehacerlo); solo se olvida.
    """
    e["clip"], e["clip_s"] = None, None
