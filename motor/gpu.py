"""
La GPU gratis: Kaggle (30 horas a la semana de una GPU de 16 GB).

Kaggle no da una maquina a la que conectarse: da «notebooks» que se ejecutan en
su GPU. Asi que el trabajo se manda como un script, Kaggle lo ejecuta, y
despues se descargan los ficheros que haya escrito. Todo con su herramienta
oficial (paquete 'kaggle'), autenticando con el token de la cuenta de cada
persona: la GPU es SUYA, no del autor del programa.

Lo que necesita la persona, una vez:
  1. Cuenta en kaggle.com.
  2. Verificar el telefono (Settings > Phone verification): sin eso Kaggle no
     deja usar la GPU.
  3. Generar un token (kaggle.com/settings/api > Generate New Token) y pegarlo
     en el asistente junto con su nombre de usuario.

Las credenciales se guardan en secretos.json, junto al programa, y ese fichero
no se sube nunca al repositorio (.gitignore).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import sysconfig
import threading
import time
from pathlib import Path

from . import proyecto, usuarios

TRABAJOS = proyecto.RAIZ / "gpu_trabajos"
# El kaggle del mismo Python que corre la app (venv en Windows o Mac/Linux).
_BIN = Path(sysconfig.get_path("scripts"))
KAGGLE = next((p for p in (_BIN / "kaggle.exe", _BIN / "kaggle",
                           proyecto.RAIZ / ".venv" / "Scripts" / "kaggle.exe",
                           proyecto.RAIZ / ".venv" / "bin" / "kaggle") if p.exists()),
              proyecto.RAIZ / ".venv" / "Scripts" / "kaggle.exe")

# Si la GPU pedida lleva este rato en cola, se pide la otra: Kaggle reparte sus
# T4 y sus P100 por filas distintas, y en horas pico una se atasca y la otra no.
COLA_MAX_S = 600
OTRA_GPU = {"NvidiaTeslaT4": "NvidiaTeslaP100", "NvidiaTeslaP100": "NvidiaTeslaT4"}
# Kaggle deja como mucho 2 trabajos de GPU por cuenta, y los que esperan en cola
# cuentan. Con el cupo lleno, se espera turno en vez de fallar.
ESPERA_CUPO_S = 45 * 60

# El estado de la prueba de GPU, por usuario: cada cuenta prueba su Kaggle.
_estados = {}
_cerrojo = threading.Lock()


# ------------------------------------------------------------ credenciales

def credenciales():
    datos = proyecto.secretos()
    if datos.get("kaggle_usuario") and datos.get("kaggle_token"):
        return datos
    return None


def guardar(usuario, token):
    proyecto.guardar_secreto("kaggle_usuario", usuario.strip().lower())
    proyecto.guardar_secreto("kaggle_token", token.strip())


def olvidar():
    proyecto.borrar_secretos("kaggle_usuario", "kaggle_token")


def _kaggle(*args, timeout=120):
    c = credenciales()
    if not c:
        raise RuntimeError("Falta conectar la cuenta de Kaggle.")
    exe = str(KAGGLE) if KAGGLE.exists() else (shutil.which("kaggle") or "kaggle")
    config = proyecto.RAIZ / ".kaggle"           # no se toca el ~/.kaggle de nadie
    config.mkdir(exist_ok=True)
    entorno = {**os.environ, "KAGGLE_API_TOKEN": c["kaggle_token"],
               "KAGGLE_USERNAME": c["kaggle_usuario"], "KAGGLE_CONFIG_DIR": str(config),
               "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    r = subprocess.run([exe, *map(str, args)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=entorno, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr).strip()


def verificar():
    """Que el token sirve: listar los notebooks propios."""
    codigo, salida = _kaggle("kernels", "list", "--mine", "--page-size", "1")
    if codigo != 0:
        return False, salida[-400:]
    return True, "Cuenta de Kaggle conectada."


# ------------------------------------------------------------- ejecutar

def preparar_trabajo(nombre, codigo_python, datasets=None, maquina=None, usuario=None):
    """La carpeta que se manda con 'kernels push': script.py + kernel-metadata.json.

    Ojo: 'kernels push' solo sube el code_file; cualquier otro fichero de la
    carpeta NO llega a Kaggle. Por eso los datos van en un dataset (o dentro
    del propio script). Devuelve (carpeta, id del kernel).
    """
    usuario = usuario or credenciales()["kaggle_usuario"]
    slug = re.sub(r"[^a-z0-9-]", "-", f"video-simple-{nombre}".lower())[:50].strip("-")
    carpeta = TRABAJOS / slug
    if carpeta.exists():
        shutil.rmtree(carpeta)
    (carpeta / "salida").mkdir(parents=True)
    (carpeta / "script.py").write_text(codigo_python, encoding="utf-8")
    meta = {
        "id": f"{usuario}/{slug}",
        "title": slug,
        "code_file": "script.py",
        "language": "python",
        "kernel_type": "script",
        "is_private": "true",
        "enable_gpu": "true",
        "enable_internet": "true",
        "dataset_sources": list(datasets or []), "competition_sources": [],
        "kernel_sources": [], "model_sources": [],
    }
    if maquina:                     # sin clave, Kaggle usa su GPU por defecto
        meta["machine_shape"] = maquina
    (carpeta / "kernel-metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return carpeta, meta["id"]


def ejecutar_script(nombre, codigo_python, avisar, archivos=None, limite_s=3 * 3600,
                    datasets=None, maquina=None):
    """Manda un script a la GPU de Kaggle, espera a que acabe y baja su salida.

    Devuelve la carpeta local con lo que el script haya escrito en /kaggle/working.

    datasets: lista de "usuario/slug" que el kernel ve montados en /kaggle/input
    (asi le llegan las imagenes de los clips). maquina: el 'machine_shape' de
    Kaggle (p.ej. "NvidiaTeslaT4" = 2xT4); vacio = lo que Kaggle de por defecto.
    limite_s tambien se manda a Kaggle como tope de la sesion: si algo se cuelga,
    Kaggle la corta y no se come la cuota semanal de GPU.
    """
    carpeta, kernel = preparar_trabajo(nombre, codigo_python, datasets, maquina)
    for nombre_archivo, contenido in (archivos or {}).items():
        (carpeta / nombre_archivo).write_bytes(contenido)

    avisar("Mandando el trabajo a la GPU de Kaggle...")
    _empujar(carpeta, limite_s, maquina, avisar)

    encolado, corriendo, ultimo, cambiada = time.time(), None, "", False
    fallos, latido = 0, time.time()
    while True:
        time.sleep(15)
        codigo, estado = _kaggle("kernels", "status", kernel)
        if codigo != 0 or "status" not in estado.lower():
            # Antes esto se tomaba por una "fase" y el trabajo parecia quieto para siempre.
            if "authentication" in estado.lower():
                raise RuntimeError("Kaggle ya no acepta tu token (lo regeneraste o caducó): "
                                   "crea uno nuevo en kaggle.com/settings y pégalo en el asistente.")
            fallos += 1
            if fallos >= 8:
                raise RuntimeError(f"Kaggle no responde al consultar el trabajo: {estado[-300:]}")
            continue
        fallos = 0
        if time.time() - latido > 300:           # que se vea que sigue vivo
            avisar(f"GPU de Kaggle: sigue {ultimo or 'en marcha'} "
                   f"({int((time.time() - encolado) // 60)} min)")
            latido = time.time()
        m = re.search(r'status "?([A-Za-z_.]+)', estado)
        fase = (m.group(1) if m else estado).split(".")[-1].lower()
        if fase != ultimo:
            avisar(f"GPU de Kaggle: {fase}")
            ultimo = fase
        if "running" in fase and corriendo is None:
            corriendo = time.time()
        if "complete" in fase:
            break
        otra = OTRA_GPU.get(maquina or "")
        if "queued" in fase and otra and not cambiada and time.time() - encolado > COLA_MAX_S:
            # Mandar una version nueva del mismo kernel reemplaza la que espera:
            # no ocupa un hueco mas del cupo de Kaggle.
            avisar(f"Kaggle no da {maquina} desde hace {COLA_MAX_S // 60} min: pido {otra}.")
            meta = json.loads((carpeta / "kernel-metadata.json").read_text(encoding="utf-8"))
            meta["machine_shape"] = otra
            (carpeta / "kernel-metadata.json").write_text(json.dumps(meta, indent=2),
                                                          encoding="utf-8")
            try:
                _empujar(carpeta, limite_s, otra, avisar, espera_s=0)
                maquina, ultimo = otra, ""
            except RuntimeError as err:
                avisar(f"No he podido cambiar de GPU ({str(err)[-160:]}); sigo esperando.")
            cambiada = True
        if "error" in fase or "cancel" in fase:
            _kaggle("kernels", "output", kernel, "-p", carpeta / "salida",
                    timeout=600)
            log = next((carpeta / "salida").glob("*.log"), None)
            detalle = log.read_text(encoding="utf-8", errors="replace")[-1500:] if log else estado
            raise RuntimeError(f"El trabajo fallo en Kaggle: {detalle}")
        # El tope cuenta desde que arranca: la cola no se come la cuota de GPU.
        if corriendo and time.time() - corriendo > limite_s + 600:
            raise RuntimeError("El trabajo de Kaggle no ha terminado a tiempo.")
        if time.time() - encolado > limite_s + 6 * 3600:
            raise RuntimeError("Kaggle lleva horas sin dar GPU: prueba más tarde.")

    avisar("Descargando el resultado de Kaggle...")
    codigo, salida = _kaggle("kernels", "output", kernel,
                             "-p", carpeta / "salida", timeout=1800)
    # El CLI de Kaggle puede acabar con error DESPUES de bajar todo (en Windows,
    # al imprimir una ruta con caracteres que la consola no sabe pintar): lo que
    # manda es si los ficheros estan, no el codigo de salida.
    bajados = [p for p in (carpeta / "salida").iterdir() if p.suffix != ".log"]
    if codigo != 0 and not bajados:
        raise RuntimeError(f"No he podido bajar la salida: {salida[-400:]}")
    return carpeta / "salida"


def _empujar(carpeta, limite_s, maquina, avisar, espera_s=ESPERA_CUPO_S):
    """kernels push, esperando turno si la cuenta ya tiene 2 trabajos de GPU."""
    # El machine_shape va en los metadatos Y como --accelerator: asi es como
    # Kaggle ha dado de verdad las 2xT4 (probado con una cuenta real).
    extra = ["--accelerator", maquina] if maquina else []
    inicio, avisado = time.time(), False
    while True:
        codigo, salida = _kaggle("kernels", "push", "-p", carpeta, "-t", int(limite_s), *extra,
                                 timeout=300)
        if codigo == 0 and "error" not in salida.lower():
            return
        if "session count" not in salida.lower() or time.time() - inicio > espera_s:
            raise RuntimeError(f"Kaggle no ha aceptado el trabajo: {salida[-500:]}")
        if not avisado:
            avisar("Tu Kaggle ya tiene 2 trabajos de GPU (su máximo): espero a que acabe uno.")
            avisado = True
        time.sleep(60)


# ------------------------------------------------- varios pasos, una cola

# Un trabajo que lleva dentro otros: cada uno corre en su subproceso y escribe en
# su subcarpeta de /kaggle/working. Asi voz e imagenes hacen cola UNA vez.
VARIOS = r'''
import base64, json, os, subprocess, sys, time
from pathlib import Path
PARTES = json.loads(base64.b64decode("__PARTES__").decode("utf-8"))
for p in PARTES:
    destino = Path("/kaggle/working") / p["nombre"]
    destino.mkdir(parents=True, exist_ok=True)
    codigo = base64.b64decode(p["codigo"]).decode("utf-8")
    codigo = codigo.replace('Path("/kaggle/working")', f'Path("{destino}")')
    ruta = Path(f"/tmp/parte_{p['nombre']}.py")
    ruta.write_text(codigo, encoding="utf-8")
    print(f"===== {p['nombre']} =====", flush=True)
    t = time.time()
    r = subprocess.run([sys.executable, str(ruta)])
    print(f"===== {p['nombre']}: codigo {r.returncode} en {time.time() - t:.0f} s =====", flush=True)
'''


def ejecutar_varios(nombre, partes, avisar, maquina=None):
    """Manda varios scripts en UN trabajo de Kaggle. partes: [(nombre, codigo, limite_s)].

    Devuelve {nombre: carpeta local con su salida}.
    """
    import base64
    datos = [{"nombre": n, "codigo": base64.b64encode(c.encode("utf-8")).decode("ascii")}
             for n, c, _ in partes]
    codigo = VARIOS.replace("__PARTES__", base64.b64encode(
        json.dumps(datos).encode("utf-8")).decode("ascii"))
    limite = int(min(sum(l for _, _, l in partes), 11.5 * 3600))
    salida = ejecutar_script(nombre, codigo, avisar, limite_s=limite, maquina=maquina)
    return {n: salida / n for n, _, _ in partes}


class Agrupador:
    """Junta en un solo trabajo de Kaggle los pasos que corren a la vez en hilos.

    Cada paso recibe agrupador.ejecutor como 'ejecutor': en vez de mandar su
    script, lo deja aqui y espera. Cuando todos los pasos han dejado el suyo (o
    han terminado sin necesitar GPU), se manda UN trabajo, y cada paso recibe su
    subcarpeta y sigue (de uno en uno, para que no pisen el proyecto a la vez).
    """

    def __init__(self, pasos, avisar, maquina):
        self.pendientes = set(pasos)
        self.avisar, self.maquina = avisar, maquina
        self.partes, self.salidas, self.error = {}, None, None
        self.cerrojo = threading.Condition()
        self.turno = threading.Lock()

    def ejecutor_de(self, paso):
        def ejecutor(nombre, codigo, avisar, limite_s=3600, maquina=None, **extra):
            if self.salidas is not None or self.error:
                # Una segunda tanda del mismo paso (videos muy largos): va sola.
                return ejecutar_script(nombre, codigo, avisar, limite_s=limite_s,
                                       maquina=maquina, **extra)
            with self.cerrojo:
                self.partes[paso] = (paso, codigo, limite_s)
                self.pendientes.discard(paso)
                self.cerrojo.notify_all()
            self._lanzar_si_toca()
            with self.cerrojo:
                self.cerrojo.wait_for(lambda: self.salidas is not None or self.error)
            if self.error:
                raise RuntimeError(self.error)
            self.turno.acquire()            # se suelta en terminado()
            self.con_turno = paso
            return self.salidas[paso]
        return ejecutor

    def terminado(self, paso):
        """El paso acabo (con o sin GPU): ya no hay que esperarlo."""
        with self.cerrojo:
            self.pendientes.discard(paso)
            self.cerrojo.notify_all()
        if getattr(self, "con_turno", None) == paso:
            self.con_turno = None
            self.turno.release()
        self._lanzar_si_toca()

    def _lanzar_si_toca(self):
        with self.cerrojo:
            if self.pendientes or self.salidas is not None or self.error or not self.partes \
                    or getattr(self, "_lanzado", False):
                return
            self._lanzado = True
            partes = list(self.partes.values())
        try:
            nombres = " + ".join(n for n, _, _ in partes)
            self.avisar(f"Un solo trabajo de Kaggle para: {nombres}")
            salidas = ejecutar_varios(f"todo-{int(time.time()) % 100000}", partes, self.avisar,
                                      self.maquina)
            with self.cerrojo:
                self.salidas = salidas
                self.cerrojo.notify_all()
        except Exception as err:
            with self.cerrojo:
                self.error = str(err)
                self.cerrojo.notify_all()


# ------------------------------------------------------------ datasets

def metadatos_dataset(carpeta, slug, titulo, usuario):
    """dataset-metadata.json segun la doc oficial (title 6-50, id, una licencia)."""
    ident = f"{usuario}/{slug}"
    (Path(carpeta) / "dataset-metadata.json").write_text(json.dumps({
        "title": titulo[:50].ljust(6, "-"),
        "id": ident,
        "licenses": [{"name": "CC0-1.0"}],
    }, indent=2), encoding="utf-8")
    return ident


def subir_dataset(slug, titulo, carpeta, avisar, espera_s=900):
    """Sube una carpeta como dataset PRIVADO de la cuenta (o una version nueva).

    Es la forma robusta de pasarle ficheros grandes a un kernel: el script de
    Kaggle no admite muchos MB de texto, y el dataset se monta tal cual en
    /kaggle/input. Se reusa el mismo slug (una version nueva cada vez, borrando
    las viejas) para no llenar la cuenta de la persona de datasets sueltos.
    Devuelve el id "usuario/slug" para ponerlo en dataset_sources.
    """
    c = credenciales()
    if not c:
        raise RuntimeError("Falta conectar la cuenta de Kaggle.")
    ident = metadatos_dataset(carpeta, slug, titulo, c["kaggle_usuario"])

    codigo, estado = _kaggle("datasets", "status", ident)
    if codigo == 0 and "ready" in estado.lower():
        avisar("Subiendo las imagenes a Kaggle (version nueva del dataset privado)...")
        codigo, salida = _kaggle("datasets", "version", "-p", carpeta, "-m", "imagenes de la tanda",
                                 "-r", "skip", "-d", timeout=1800)
    else:
        avisar("Subiendo las imagenes a Kaggle (dataset privado nuevo)...")
        codigo, salida = _kaggle("datasets", "create", "-p", carpeta, "-r", "skip", timeout=1800)
    if codigo != 0 or "error" in salida.lower():
        raise RuntimeError(f"Kaggle no ha aceptado el dataset: {salida[-500:]}")

    # Kaggle procesa el dataset unos segundos/minutos antes de poder usarlo.
    inicio = time.time()
    while time.time() - inicio < espera_s:
        time.sleep(10)
        _, estado = _kaggle("datasets", "status", ident)
        if "ready" in estado.lower():
            return ident
        if "error" in estado.lower():
            raise RuntimeError(f"Kaggle no ha podido procesar el dataset: {estado[-300:]}")
    raise RuntimeError("El dataset de Kaggle no ha quedado listo a tiempo.")


# ------------------------------------------------------- prueba de la GPU

PRUEBA = r'''
import json, subprocess
info = {}
try:
    info["nvidia_smi"] = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total",
        "--format=csv,noheader"], capture_output=True, text=True).stdout.strip()
except Exception as e:
    info["nvidia_smi"] = f"sin nvidia-smi: {e}"
try:
    import torch
    info["cuda"] = torch.cuda.is_available()
    info["gpu"] = torch.cuda.get_device_name(0) if info["cuda"] else ""
except Exception as e:
    info["cuda"] = False
    info["error"] = str(e)
open("/kaggle/working/gpu.json", "w").write(json.dumps(info))
print(json.dumps(info))
'''


def estado_prueba():
    with _cerrojo:
        return dict(_estados.get(usuarios.ACTUAL.get(),
                                 {"fase": "sin_probar", "detalle": "", "salida": ""}))


def _poner(fase, detalle="", salida=""):
    with _cerrojo:
        _estados[usuarios.ACTUAL.get()] = {"fase": fase, "detalle": detalle, "salida": salida}


def probar_en_segundo_plano():
    if estado_prueba()["fase"] == "probando":
        return
    yo = usuarios.ACTUAL.get()

    def correr():
        usuarios.ACTUAL.set(yo)              # el hilo no hereda el usuario de la peticion
        try:
            _poner("probando", "Mandando una prueba a la GPU (tarda 1-3 minutos)...")
            carpeta = ejecutar_script("prueba-gpu", PRUEBA,
                                      lambda t: _poner("probando", t))
            info = json.loads((carpeta / "gpu.json").read_text(encoding="utf-8"))
            if info.get("cuda"):
                _poner("ok", f"GPU funcionando: {info.get('gpu') or info.get('nvidia_smi')}",
                       json.dumps(info))
            else:
                _poner("sin_gpu", "El trabajo corrio, pero sin GPU. Suele ser que falta "
                                  "verificar el telefono en Kaggle.", json.dumps(info))
        except Exception as err:
            _poner("error", str(err))

    threading.Thread(target=correr, daemon=True).start()
