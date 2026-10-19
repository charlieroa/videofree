"""
Voz natural en la GPU gratis de Kaggle: Chatterbox Multilingual (Resemble AI, MIT).

Es la alternativa abierta a ElevenLabs: habla español con entonación natural y
puede CLONAR una voz con 10-20 s de audio. Como la clonación solo se hace con la
voz de la propia persona (o una que tenga permiso de usar), la muestra la sube
ella en la pantalla y se guarda en secretos/<usuario>_voz.mp3, junto a sus claves.

Va igual que los clips: UN trabajo de Kaggle con todas las frases del video.
  1. Aquí se preparan los textos de cada escena (y la muestra de voz, si se clona).
  2. Todo viaja dentro del propio script en base64: los textos pesan poco y la
     muestra va en mp3 (unos 200 KB).
  3. El kernel instala Chatterbox sin tocar el torch de Kaggle; si así no carga,
     hace la instalación completa (con su torch) y lo reintenta.
  4. Genera escena a escena (partiendo los textos largos por frases, que es como
     mejor suena) y deja escena_NNN.wav + resultado.json.
  5. Aquí se pasan a mp3 y cada escena guarda 'audio' y 'duracion'.

Ids de voz: "chatterbox:base" (la voz que trae el modelo) y "chatterbox:clon"
(la muestra subida por la persona).
"""
import base64
import json
import threading
import time

from . import gpu, medios, proyecto

VOCES = ("chatterbox:base", "chatterbox:clon")
MAX_MUESTRA_S = 25


def es_suya(voz_id):
    return voz_id in VOCES


def cfg():
    return proyecto.config().get("voz_gpu") or {}


# ------------------------------------------------------ la muestra de voz

def ruta_muestra():
    """La muestra de voz de la persona (para clonar). Una por cuenta."""
    nombre = proyecto.usuarios.ACTUAL.get()
    if not nombre:
        raise RuntimeError("No hay usuario.")
    proyecto.SECRETOS_DIR.mkdir(exist_ok=True)
    return proyecto.SECRETOS_DIR / f"{nombre}_voz.mp3"


def guardar_muestra(origen):
    """Deja la grabación en mp3 mono 24 kHz, sin silencios al inicio y con 25 s como mucho."""
    destino = ruta_muestra()
    medios.ffmpeg("-i", origen, "-af", "silenceremove=start_periods=1:start_threshold=-45dB,"
                  "loudnorm=I=-18:TP=-2", "-t", MAX_MUESTRA_S, "-ac", 1, "-ar", 24000,
                  "-b:a", "96k", destino)
    segundos = medios.duracion(destino)
    if segundos < 5:
        destino.unlink(missing_ok=True)
        raise ValueError("La grabación es muy corta: hacen falta al menos 8-10 segundos hablando.")
    return round(segundos, 1)


def ruta_prueba(voz_id):
    """Lo que dijo Chatterbox en la última prueba: la base es común, la clonada es de cada cuenta."""
    if voz_id == "chatterbox:base":
        carpeta = proyecto.RAIZ / "voces_muestra"
        carpeta.mkdir(exist_ok=True)
        return carpeta / "chatterbox-base.mp3"
    return ruta_muestra().with_name(ruta_muestra().stem + "_prueba.mp3")


def hay_muestra():
    try:
        return ruta_muestra().exists()
    except RuntimeError:
        return False


# ------------------------------------------------- probar antes de elegir

FRASE_PRUEBA = ("Hola, así va a sonar la narración de tu video. "
                "¿Te gusta cómo suena? Si quieres, la cambiamos.")
_pruebas, _cerrojo = {}, threading.Lock()


def estado_prueba():
    with _cerrojo:
        return dict(_pruebas.get(proyecto.usuarios.ACTUAL.get(), {"fase": "nada", "detalle": ""}))


def _poner(yo, fase, detalle):
    with _cerrojo:
        _pruebas[yo] = {"fase": fase, "detalle": detalle}


def probar_en_segundo_plano(voz_id):
    """Una frase de muestra con Chatterbox en la GPU de Kaggle (unos minutos)."""
    yo = proyecto.usuarios.ACTUAL.get()
    if estado_prueba()["fase"] == "probando":
        return
    if not gpu.credenciales():
        raise RuntimeError("Conecta primero tu GPU de Kaggle (Asistente).")
    if voz_id == "chatterbox:clon" and not hay_muestra():
        raise RuntimeError("Primero sube o graba 10-20 segundos de tu voz.")
    destino = ruta_prueba(voz_id)

    def correr():
        proyecto.usuarios.ACTUAL.set(yo)
        try:
            _poner(yo, "probando", "Mandando la prueba a tu GPU de Kaggle (tarda 5-10 minutos)...")
            datos = {"id": "prueba-voz", "escenas": []}
            salida = _generar(datos, [{"n": 1, "narracion": FRASE_PRUEBA}], voz_id,
                              lambda t: _poner(yo, "probando", t))
            wav = salida / "escena_001.wav"
            if not wav.is_file():
                res = json.loads((salida / "resultado.json").read_text(encoding="utf-8"))
                raise RuntimeError((res.get("fatal") or json.dumps(res.get("escenas")))[-600:])
            medios.ffmpeg("-i", wav, "-ac", 1, "-ar", 44100, "-b:a", "128k", destino)
            _poner(yo, "ok", "✓ Lista: pulsa ▶ Escuchar.")
        except Exception as err:
            _poner(yo, "error", f"✗ {err}"[:700])

    threading.Thread(target=correr, daemon=True).start()


# ------------------------------------------------------------- el paso

def _frases(texto, tope=260):
    """Chatterbox suena mejor con trozos cortos: se parte por frases (y por comas si hace falta)."""
    import re
    trozos, actual = [], ""
    for frase in re.split(r"(?<=[.!?¿¡…;:])\s+", texto.strip()):
        if len(frase) > tope:                         # una frase larguísima: por comas
            partes = re.split(r"(?<=,)\s+", frase)
        else:
            partes = [frase]
        for p in partes:
            if actual and len(actual) + len(p) + 1 > tope:
                trozos.append(actual)
                actual = p
            else:
                actual = f"{actual} {p}".strip()
    if actual:
        trozos.append(actual)
    return trozos or [texto]


def _b64(obj):
    return base64.b64encode(json.dumps(obj, ensure_ascii=False).encode("utf-8")).decode("ascii")


def script_kernel(tanda, muestra_b64, limite_s):
    return (KERNEL.replace("__TANDA__", _b64(tanda))
                  .replace("__MUESTRA__", muestra_b64 or "")
                  .replace("__LIMITE_S__", str(int(limite_s))))


def ejecutar(datos, avisar, escenas, voz_id, ejecutor=None):
    """Narra 'escenas' con Chatterbox en la GPU de Kaggle de la persona."""
    salida, tanda = _generar(datos, escenas, voz_id, avisar, ejecutor, con_tanda=True)
    _registrar(datos, salida, tanda, avisar)


def _generar(datos, escenas, voz_id, avisar, ejecutor=None, con_tanda=False):
    """Manda las frases a Kaggle y devuelve la carpeta con escena_NNN.wav + resultado.json."""
    if not gpu.credenciales() and ejecutor is None:
        raise RuntimeError("La voz Chatterbox va en tu GPU de Kaggle y no está conectada: "
                           "abre el Asistente y conéctala, o elige una voz normal.")
    muestra = None
    if voz_id == "chatterbox:clon":
        if not hay_muestra():
            raise RuntimeError("Para clonar tu voz primero sube una grabación tuya de 10-20 s "
                               "(en el panel de la izquierda, junto a la voz).")
        muestra = base64.b64encode(ruta_muestra().read_bytes()).decode("ascii")
    c = cfg()
    tanda = {"id": f"{datos['id']}-{time.strftime('%H%M%S')}",
             "pip_ligero": c.get("pip_ligero", []), "pip_completo": c.get("pip_completo", []),
             "idioma": "es", "emocion": c.get("emocion", 0.5), "cfg": c.get("cfg", 0.5),
             "temperatura": c.get("temperatura", 0.8), "semilla": c.get("semilla", 1234),
             "escenas": [{"n": e["n"], "frases": _frases(e["narracion"])} for e in escenas]}
    palabras = sum(len(e["narracion"].split()) for e in escenas)
    # Tope de la sesión: instalar y cargar (~15 min) + 4 veces lo que dura leerlo.
    limite = int(min(max(15 * 60 + palabras / 2.2 * 4, 3600), 11.5 * 3600))
    avisar(f"Voz Chatterbox: {len(escenas)} escenas ({palabras} palabras) a tu GPU de Kaggle"
           + (" con tu voz clonada" if muestra else ""))
    salida = (ejecutor or gpu.ejecutar_script)(
        f"voz-{datos['id'][:24]}", script_kernel(tanda, muestra, limite), avisar,
        limite_s=limite, maquina=c.get("machine_shape") or None)
    return (salida, tanda) if con_tanda else salida


def _registrar(datos, salida, tanda, avisar):
    ruta = salida / "resultado.json"
    if not ruta.exists():
        raise RuntimeError("Kaggle no ha devuelto resultado.json (mira el log del kernel).")
    res = json.loads(ruta.read_text(encoding="utf-8"))
    escenas = res.get("escenas", {})
    if res.get("fatal") and not any(r.get("ok") for r in escenas.values()):
        raise RuntimeError(res["fatal"][-800:])
    carpeta = proyecto.carpeta(datos["id"]) / "voz"
    carpeta.mkdir(exist_ok=True)
    buenas = 0
    for esc in tanda["escenas"]:
        r = escenas.get(str(esc["n"])) or {"ok": False, "error": "sin resultado"}
        e = next((x for x in datos["escenas"] if x["n"] == esc["n"]), None)
        origen = salida / (r.get("archivo") or "")
        if not (e and r.get("ok") and origen.is_file()):
            avisar(f"Voz escena {esc['n']}: falló ({str(r.get('error', 'no llegó'))[-200:]})")
            continue
        destino = carpeta / f"escena_{esc['n']:03d}.mp3"
        medios.ffmpeg("-i", origen, "-ac", 1, "-ar", 44100, "-b:a", "128k", destino)
        e["audio"] = proyecto.relativa(datos, destino)
        e["duracion"] = round(medios.duracion(destino), 2)
        buenas += 1
    datos["mp4"] = None
    proyecto.guardar(datos)
    total = sum(e["duracion"] or 0 for e in datos["escenas"])
    avisar(f"Voz Chatterbox: {buenas}/{len(tanda['escenas'])} escenas ({res.get('gpu')}, "
           f"modelo cargado en {res.get('s_arranque')} s, {res.get('instalacion')}). "
           f"Total {total / 60:.1f} min de narración.")
    if res.get("fatal"):
        avisar(f"Aviso del kernel: {res['fatal'][-300:]}")
    if buenas < len(tanda["escenas"]):
        raise RuntimeError("Faltan escenas por narrar: pulsa otra vez «2 · Voz» para reintentarlas.")


# ===================================================== el script de Kaggle
#
# Corre en el kernel de Kaggle. La generación va en un subproceso: si hay que
# reinstalar torch para Chatterbox, el proceso principal ya lo tiene importado y
# solo un proceso nuevo ve la versión buena.

KERNEL = r'''
import base64, json, os, subprocess, sys, time, traceback
from pathlib import Path

INICIO = time.time()
TANDA = json.loads(base64.b64decode("__TANDA__").decode("utf-8"))
MUESTRA = "__MUESTRA__"
LIMITE_S = __LIMITE_S__
SALIDA = Path("/kaggle/working")
TMP = Path("/tmp/voz")
TMP.mkdir(parents=True, exist_ok=True)
resultado = {"ok": False, "tanda": TANDA["id"], "gpu": "", "instalacion": "",
             "s_arranque": None, "escenas": {}, "fatal": None}


def guardar():
    (SALIDA / "resultado.json").write_text(json.dumps(resultado, indent=2, ensure_ascii=False))


def log(t):
    print(f"[{time.time() - INICIO:7.1f}s] {t}", flush=True)


def pip(*paquetes, sin_deps=False):
    if not paquetes:
        return True
    orden = [sys.executable, "-m", "pip", "install", "-q", *(["--no-deps"] if sin_deps else []), *paquetes]
    log("pip " + " ".join(orden[4:]))
    r = subprocess.run(orden, capture_output=True, text=True)
    if r.returncode != 0:
        log("pip fallo: " + (r.stderr or r.stdout)[-1500:])
    return r.returncode == 0


def carga():
    r = subprocess.run([sys.executable, "-c", "from chatterbox.mtl_tts import ChatterboxMultilingualTTS"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        log("Chatterbox no carga: " + r.stderr[-1500:])
    return r.returncode == 0


TRABAJADOR = r"""
import json, random, sys, time, traceback
from pathlib import Path
import numpy as np
import torch, torchaudio
from chatterbox.mtl_tts import ChatterboxMultilingualTTS

T = json.loads(Path(sys.argv[1]).read_text())
muestra = sys.argv[2] or None
salida = Path(sys.argv[3])
res = {"escenas": {}, "s_arranque": None, "gpu": torch.cuda.get_device_name(0)}
t0 = time.time()
modelo = ChatterboxMultilingualTTS.from_pretrained(device="cuda")
res["s_arranque"] = round(time.time() - t0, 1)
pausa = torch.zeros(1, int(modelo.sr * 0.18))
for esc in T["escenas"]:
    t = time.time()
    try:
        trozos = []
        for i, frase in enumerate(esc["frases"]):
            semilla = T["semilla"] + esc["n"] * 100 + i
            random.seed(semilla); np.random.seed(semilla); torch.manual_seed(semilla)
            wav = modelo.generate(frase, language_id=T["idioma"], audio_prompt_path=muestra,
                                  exaggeration=T["emocion"], cfg_weight=T["cfg"],
                                  temperature=T["temperatura"])
            trozos += [wav.cpu(), pausa]
        audio = torch.cat(trozos[:-1], dim=1)
        nombre = f"escena_{esc['n']:03d}.wav"
        torchaudio.save(str(salida / nombre), audio, modelo.sr)
        res["escenas"][str(esc["n"])] = {"ok": True, "archivo": nombre, "s": round(time.time() - t, 1),
                                         "segundos_audio": round(audio.shape[1] / modelo.sr, 2)}
        print(f"escena {esc['n']}: {audio.shape[1] / modelo.sr:.1f} s de voz en {time.time() - t:.1f} s", flush=True)
    except Exception:
        res["escenas"][str(esc["n"])] = {"ok": False, "error": traceback.format_exc()[-800:]}
        print(traceback.format_exc(), flush=True)
    Path(sys.argv[4]).write_text(json.dumps(res))
"""


try:
    try:
        import torch
        if not torch.cuda.is_available():
            raise RuntimeError("Kaggle no ha dado GPU (¿falta verificar el teléfono?)")
        resultado["gpu"] = torch.cuda.get_device_name(0)
        log(f"GPU: {resultado['gpu']} · torch {torch.__version__} · Python {sys.version.split()[0]}")
    except ImportError:
        pass
    # 1) Chatterbox sin tocar el torch de Kaggle (rápido).
    pip(*TANDA["pip_ligero"])
    pip("chatterbox-tts==0.1.7", sin_deps=True)
    resultado["instalacion"] = "ligera"
    if not carga():
        # 2) La instalación completa, con el torch que pide Chatterbox.
        pip(*TANDA["pip_completo"])
        resultado["instalacion"] = "completa"
        if not carga():
            raise RuntimeError("No consigo cargar Chatterbox ni con la instalación completa (mira el log).")
    ruta_muestra = ""
    if MUESTRA:
        ruta_muestra = str(TMP / "muestra.mp3")
        Path(ruta_muestra).write_bytes(base64.b64decode(MUESTRA))
    (TMP / "tanda.json").write_text(json.dumps(TANDA, ensure_ascii=False))
    (TMP / "trabajador.py").write_text(TRABAJADOR)
    parcial = TMP / "res.json"
    log(f"Generando {len(TANDA['escenas'])} escenas...")
    p = subprocess.run([sys.executable, str(TMP / "trabajador.py"), str(TMP / "tanda.json"),
                        ruta_muestra, str(SALIDA), str(parcial)],
                       timeout=max(600, LIMITE_S - (time.time() - INICIO) - 300))
    if parcial.exists():
        r = json.loads(parcial.read_text())
        resultado["escenas"] = r["escenas"]
        resultado["s_arranque"] = r["s_arranque"]
        resultado["gpu"] = r["gpu"]
    if p.returncode != 0 and not resultado["escenas"]:
        raise RuntimeError(f"El generador terminó con código {p.returncode} (mira el log).")
    resultado["ok"] = any(x.get("ok") for x in resultado["escenas"].values())
except Exception:
    resultado["fatal"] = traceback.format_exc()[-2000:]
    log(resultado["fatal"])
guardar()
log("Fin.")
'''
