"""
Motor de imagenes "kaggle": las imagenes de las escenas se generan en la GPU
gratis de Kaggle de la propia persona (0 $, sin cupo por IP, mejor calidad).

Modelo: FLUX.2 [klein] 4B de Black Forest Labs (Apache 2.0, uso comercial
permitido), destilado a 4 pasos, y que acepta IMAGENES DE REFERENCIA: es lo que
da la consistencia de personajes.

Como se consigue que el personaje sea el mismo en todo el video:
  1. Primero se genera una HOJA DE PERSONAJES del proyecto: todos los personajes
     de la biblia, de cuerpo entero, de frente, en el estilo del video y sobre un
     fondo liso. Se guarda en proyectos/<id>/imagenes/hoja.png (y se ve en la
     pantalla, en "Estilo y personajes").
  2. Cada escena con personajes se genera pasando esa hoja como imagen de
     referencia (edicion multi-referencia de FLUX.2), con el mismo prompt de
     estilo y de personajes de siempre, y una semilla fija por escena.
  3. Si la biblia (estilo o personajes) cambia, la hoja se rehace sola.

Como clips_gpu, todo un proyecto es UNA tanda de Kaggle (o varias de
'max_por_tanda' escenas): el arranque (instalar, bajar el modelo, cargarlo) se
paga una vez. Con 2xT4 se reparten las escenas entre las dos GPU.

Precision: las T4 no tienen bf16 nativo, el modelo va en fp16. Si una imagen
sale negra o con NaN, el trabajador pasa a bf16 (emulado: mas lento, pero sin
desbordes) y la repite. El VAE va siempre en fp32 (es pequeno y asi no desborda).
"""
import base64
import hashlib
import io
import json
import math
import shutil
import time

from PIL import Image, ImageDraw

from . import gpu, imagenes, proyecto

LIMITE_EMBEBIDO = 600_000          # como clips_gpu: lo que va dentro del script


def cfg():
    return proyecto.config()["imagen_gpu"]


def gpus_de(c=None):
    c = c or cfg()
    por_maquina = 2 if c.get("machine_shape") == "NvidiaTeslaT4" else 1
    return max(1, min(por_maquina, c.get("gpus_max", 1)))


# ------------------------------------------------------------ prompts

def _personajes(datos):
    return [p for p in ((datos.get("biblia") or {}).get("personajes") or [])
            if p.get("nombre") and p.get("descripcion_visual")]


def firma_hoja(datos):
    """Cambia si cambia lo que sale en la hoja: entonces hay que rehacerla."""
    b = datos.get("biblia") or {}
    base = json.dumps([b.get("estilo_visual", ""), _personajes(datos)], ensure_ascii=False,
                      sort_keys=True)
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


def prompt_escena(datos, e, nota="", con_hoja=False):
    base = imagenes.prompt_de(datos, e)
    if con_hoja:
        quienes = ", ".join(n for n in e.get("personajes") or [])
        base = (f"{base}. {quienes} must look exactly like in the reference character sheet: "
                f"same face, head shape, hair, beard and body, and the same clothes unless "
                f"this scene describes different clothes. Use the reference only for the "
                f"characters' look, not for the background or the pose")
    if _personajes(datos):
        # Medido: sin esto, la gente del fondo sale con ropa moderna (polos, vaqueros)
        # aunque el protagonista vaya de romano.
        base += (". Everybody else in the scene wears clothing from the same time period and "
                 "culture as the main characters, no modern clothes")
    if nota:
        base += f". {nota}"
    return base[:2000]


# ------------------------------------------------------------- que escenas

def _hoja_ruta(datos):
    return proyecto.carpeta(datos["id"]) / "imagenes" / "hoja.png"


def hoja_vale(datos):
    return bool(datos.get("hoja") and datos.get("hoja_firma") == firma_hoja(datos)
                and _hoja_ruta(datos).is_file())


def estimar_min(n):
    """Minutos de GPU para n imagenes (lo medido si lo hay, si no lo estimado)."""
    c = cfg()
    med = c.get("medido") or {}
    por = med.get("min_por_imagen") or c["min_por_imagen_estimado"]
    arranque = med.get("min_arranque") or c["min_arranque_estimado"]
    tandas = math.ceil(n / c["max_por_tanda"]) if n else 0
    return round(tandas * arranque + n * por / gpus_de(c), 1)


# ---------------------------------------------------------- preparar tanda

def _jpg_b64(ruta, lado=1024):
    with Image.open(ruta) as im:
        im = im.convert("RGB")
        im.thumbnail((lado, lado), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=92)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def preparar(datos, escenas, nota="", c=None):
    """La tanda: modelo, tamano, hoja (generar o reusar) y el prompt de cada escena."""
    c = c or cfg()
    pj = _personajes(datos)
    flux = c["modelo"].get("familia", "flux2_klein") == "flux2_klein"   # Z-Image: sin refs
    hay_refs = (flux and c.get("referencias", True) and pj
                and any(usa_hoja(datos, e) for e in escenas))
    hoja = {"generar": False, "b64": None}
    if hay_refs:
        if hoja_vale(datos):
            hoja["b64"] = _jpg_b64(_hoja_ruta(datos), c.get("ref_lado", 1024))
        else:
            hoja["generar"] = True
            hoja["prompt"] = prompt_hoja(datos)
    tanda = {
        "id": f"{datos['id']}-{time.strftime('%H%M%S')}",
        "ancho": c["ancho"], "alto": c["alto"], "modelo": c["modelo"],
        "precision": c.get("precision", "auto"), "semilla": c["semilla"],
        "gpus_max": c.get("gpus_max", 1), "pip": c["pip"], "ref_lado": c.get("ref_lado", 1024),
        "hoja": hoja, "escenas": [],
    }
    for e in escenas:
        con = bool(hay_refs and usa_hoja(datos, e))
        tanda["escenas"].append({"n": e["n"], "ref": con,
                                 "prompt": prompt_escena(datos, e, nota, con)})
    return tanda


def _b64(obj):
    return base64.b64encode(json.dumps(obj, ensure_ascii=False).encode("utf-8")).decode("ascii")


def script_kernel(tanda, limite_s=3 * 3600):
    return (KERNEL.replace("__TANDA__", _b64(tanda))
            .replace("__LIMITE_S__", str(int(limite_s))))


# ---------------------------------------------------------------- simular

def _simular_kaggle(nombre, codigo_python, avisar, limite_s=0, datasets=None, maquina=None, **_):
    """Modo prueba: la misma carpeta y el mismo resultado.json que Kaggle, sin IA."""
    carpeta, _ = gpu.preparar_trabajo(nombre, codigo_python, datasets, maquina,
                                      usuario="simulado")
    compile(codigo_python, "script.py", "exec")
    marca = "TANDA = json.loads(base64.b64decode(\""
    ini = codigo_python.index(marca) + len(marca)
    tanda = json.loads(base64.b64decode(codigo_python[ini:codigo_python.index('"', ini)]))
    salida = carpeta / "salida"
    res = {"ok": True, "gpu": "simulada", "dtype": "-", "modelo": "simulado",
           "s_arranque": 0, "hoja": None, "escenas": {}, "fatal": None}

    def dibujar(texto, ruta, color):
        im = Image.new("RGB", (tanda["ancho"], tanda["alto"]), color)
        ImageDraw.Draw(im).text((40, 40), texto[:120], fill=(255, 255, 255))
        im.save(ruta)

    if tanda["hoja"].get("generar"):
        dibujar("HOJA " + tanda["hoja"]["prompt"], salida / "hoja.png", (90, 90, 90))
        res["hoja"] = {"ok": True, "archivo": "hoja.png", "s": 0.0}
        avisar("(simulado) hoja de personajes")
    for i, esc in enumerate(tanda["escenas"]):
        archivo = f"escena_{esc['n']:03d}.jpg"
        dibujar(f"ESCENA {esc['n']} ref={esc['ref']} " + esc["prompt"], salida / archivo,
                (40 + 30 * (i % 5), 60, 90))
        res["escenas"][str(esc["n"])] = {"ok": True, "archivo": archivo, "s": 0.0}
    (salida / "resultado.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    return salida


# ---------------------------------------------------------------- el paso

def _registrar(datos, salida, tanda, avisar, simulado):
    ruta = salida / "resultado.json"
    if not ruta.exists():
        raise RuntimeError("Kaggle no ha devuelto resultado.json (mira el log del kernel).")
    res = json.loads(ruta.read_text(encoding="utf-8"))
    escenas = res.get("escenas", {})
    if res.get("fatal") and not any(r.get("ok") for r in escenas.values()):
        raise RuntimeError(res["fatal"][-600:])

    carpeta = proyecto.carpeta(datos["id"]) / "imagenes"
    carpeta.mkdir(exist_ok=True)
    h = res.get("hoja") or {}
    if h.get("ok") and (salida / h["archivo"]).is_file():
        shutil.copyfile(salida / h["archivo"], carpeta / "hoja.png")
        datos["hoja"] = proyecto.relativa(datos, carpeta / "hoja.png")
        datos["hoja_firma"] = firma_hoja(datos)
        avisar("Hoja de personajes lista (imagenes/hoja.png).")
    elif tanda["hoja"].get("generar"):
        avisar(f"La hoja de personajes ha fallado ({str(h.get('error', 'no llego'))[-200:]}); "
               f"las escenas van sin referencia.")

    buenos, tiempos = 0, []
    for esc in tanda["escenas"]:
        r = escenas.get(str(esc["n"])) or {"ok": False, "error": "sin resultado"}
        e = next((x for x in datos["escenas"] if x["n"] == esc["n"]), None)
        origen = salida / (r.get("archivo") or "")
        if not (e and r.get("ok") and origen.is_file()):
            avisar(f"Imagen escena {esc['n']}: fallo ({str(r.get('error', 'no llego'))[-200:]})")
            continue
        final = carpeta / f"escena_{esc['n']:03d}.jpg"
        shutil.copyfile(origen, final)
        e["imagen"] = proyecto.relativa(datos, final)
        proyecto.quitar_clip(e)
        buenos += 1
        if r.get("s"):
            tiempos.append(r["s"])
    datos["mp4"] = None
    proyecto.guardar(datos)
    avisar(f"Imagenes GPU: {buenos}/{len(tanda['escenas'])} listas"
           + (f" ({res.get('gpu')}, {res.get('dtype')})" if not simulado else " (simuladas)"))

    if not simulado and tiempos:
        total = proyecto.config()
        total["imagen_gpu"]["medido"] = {
            "min_por_imagen": round(sum(tiempos) / len(tiempos) / 60, 2),
            "min_arranque": round((res.get("s_arranque") or 0) / 60, 1),
            "gpu": res.get("gpu"), "dtype": res.get("dtype"),
            "fecha": time.strftime("%Y-%m-%d %H:%M")}
        proyecto.CONFIG.write_text(json.dumps(total, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
    if res.get("fatal"):
        avisar(f"Aviso del kernel: {res['fatal'][-300:]}")
    return res


def ejecutar(datos, escenas, avisar, nota="", ejecutor=None):
    """Genera en Kaggle las imagenes de 'escenas' (no 'continua'); la hoja si hace falta."""
    c = cfg()
    if not escenas:
        avisar("Imagenes GPU: no hay escenas sin imagen.")
        return
    simulado = ejecutor is _simular_kaggle
    if ejecutor is None and not gpu.credenciales():
        raise RuntimeError("La GPU no esta conectada: abre el Asistente (paso 5) y conecta "
                           "tu cuenta de Kaggle (o elige otro motor de imagenes en Ajustes).")
    ejecutor = ejecutor or gpu.ejecutar_script
    paso = c["max_por_tanda"]
    tandas = [escenas[i:i + paso] for i in range(0, len(escenas), paso)]
    for k, lote in enumerate(tandas, 1):
        tanda = preparar(datos, lote, nota, c)
        avisar(f"Imagenes GPU, tanda {k}/{len(tandas)}: {len(lote)} escenas"
               + (" + hoja de personajes" if tanda["hoja"]["generar"] else "")
               + (" (con la hoja como referencia)" if any(x["ref"] for x in tanda["escenas"]) else "")
               + f", ~{estimar_min(len(lote))} min de GPU")
        limite = (c["min_arranque_estimado"] * 2
                  + (len(lote) + 1) * c["min_por_imagen_estimado"] * 3 / gpus_de(c)) * 60
        limite = int(min(max(limite, 3600), 11.5 * 3600))
        codigo = script_kernel(tanda, limite)
        if len(codigo) > LIMITE_EMBEBIDO + 200_000:
            raise RuntimeError("La tanda no cabe en el script de Kaggle: baja max_por_tanda.")
        salida = ejecutor(f"imagenes-{datos['id'][:22]}", codigo, avisar, limite_s=limite,
                          maquina=c.get("machine_shape") or None)
        _registrar(datos, salida, tanda, avisar, simulado)


# ===================================================== el script de Kaggle
#
# Corre en el kernel de Kaggle (Python 3.13, torch ya instalado). Fases:
#   0. Sin GPU -> resultado.json con el error claro y fuera.
#   1. pip install (versiones fijadas en config) y bajar el modelo UNA vez.
#   2. El codificador de texto (Qwen3 4B, 8 GB) se carga en la GPU 0, codifica
#      la hoja y todas las escenas y se libera: asi cada trabajador solo carga
#      el transformer (4B) y el VAE, y caben dos (uno por T4).
#   3. Un trabajador por GPU. El de la GPU 0 hace primero la hoja; las escenas
#      que la usan como referencia la esperan. Una escena que falla no para las demas.
#   4. resultado.json en /kaggle/working con la hoja, las escenas y los tiempos.

KERNEL = r'''
import base64, json, os, subprocess, sys, time, traceback
from pathlib import Path

INICIO = time.time()
TANDA = json.loads(base64.b64decode("__TANDA__").decode("utf-8"))
LIMITE_S = __LIMITE_S__
SALIDA = Path("/kaggle/working")
TMP = Path("/tmp/video_simple_img")
TMP.mkdir(parents=True, exist_ok=True)
MODELO = TANDA["modelo"]

resultado = {"ok": False, "tanda": TANDA["id"], "gpu": "", "dtype": "", "modelo": MODELO["repo"],
             "s_arranque": None, "s_modelo": None, "hoja": None, "escenas": {}, "fatal": None}


def guardar():
    (SALIDA / "resultado.json").write_text(json.dumps(resultado, indent=2))


def log(texto):
    print(f"[{time.time() - INICIO:7.1f}s] {texto}", flush=True)


def ver_gpu():
    try:
        import torch
        if not torch.cuda.is_available():
            return 0, ""
        n = torch.cuda.device_count()
        return n, ", ".join(torch.cuda.get_device_name(i) for i in range(n))
    except Exception as err:
        log(f"torch no responde: {err}")
        return 0, ""


def instalar():
    log("Instalando: " + " ".join(TANDA["pip"]))
    r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", *TANDA["pip"]],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("pip install fallo: " + (r.stderr or r.stdout)[-1500:])


def bajar_modelo():
    from huggingface_hub import snapshot_download
    log(f"Bajando {MODELO['repo']}")
    t = time.time()
    # Solo las carpetas de diffusers (el repo trae ademas el modelo en un unico fichero).
    ruta = snapshot_download(MODELO["repo"], allow_patterns=[
        "model_index.json", "scheduler/*", "text_encoder/*", "tokenizer/*", "transformer/*",
        "vae/*"])
    log(f"Modelo bajado en {time.time() - t:.0f} s")
    return ruta


CODIFICADOR = r"""
import json, sys, time
from pathlib import Path
import torch
from transformers import AutoTokenizer, Qwen3ForCausalLM
from diffusers import Flux2KleinPipeline

a = json.loads(Path(sys.argv[1]).read_text())
TMP = Path(a["tmp"])
tok = AutoTokenizer.from_pretrained(a["ruta"], subfolder="tokenizer")
enc = Qwen3ForCausalLM.from_pretrained(a["ruta"], subfolder="text_encoder",
                                       torch_dtype=torch.float16).to("cuda")
enc.eval()
capas = tuple(a["capas"])


def uno(texto):
    with torch.no_grad():
        return Flux2KleinPipeline._get_qwen3_prompt_embeds(
            text_encoder=enc, tokenizer=tok, prompt=texto, dtype=torch.float32,
            device="cuda", max_sequence_length=512, hidden_states_layers=capas)


for clave, texto in a["textos"]:
    emb = uno(texto)
    if not torch.isfinite(emb).all():
        print(f"texto {clave}: NaN/inf en fp16 -> repito en bf16", flush=True)
        enc.to(torch.bfloat16)
        emb = uno(texto)
        enc.to(torch.float16)
        if not torch.isfinite(emb).all():
            raise RuntimeError("el codificador de texto da NaN tambien en bf16")
    torch.save(emb.cpu(), TMP / f"emb_{clave}.pt")
"""


def codificar_textos(ruta):
    """Qwen3 (8 GB) en la GPU 0, en un SUBPROCESO: al acabar, la GPU queda libre del
    todo para el trabajador (en el mismo proceso, 'del' no soltaba los 7 GB: medido)."""
    textos = [("hoja", TANDA["hoja"]["prompt"])] if TANDA["hoja"].get("generar") else []
    textos += [(f"{e['n']:03d}", e["prompt"]) for e in TANDA["escenas"]]
    (TMP / "codificador.py").write_text(CODIFICADOR)
    (TMP / "codificar.json").write_text(json.dumps({
        "ruta": ruta, "tmp": str(TMP), "textos": textos,
        "capas": MODELO.get("capas_texto") or [9, 18, 27]}))
    log("Codificando los prompts (Qwen3, GPU 0)")
    r = subprocess.run([sys.executable, str(TMP / "codificador.py"), str(TMP / "codificar.json")],
                       env={**os.environ, "CUDA_VISIBLE_DEVICES": "0"},
                       capture_output=True, text=True)
    print(r.stdout[-3000:], flush=True)
    if r.returncode != 0:
        raise RuntimeError("el codificador de texto fallo: " + r.stderr[-1500:])
    log(f"{len(textos)} prompts codificados.")


TRABAJADOR = r"""
import base64, io, json, sys, time, traceback
from pathlib import Path
import numpy as np
import torch
from PIL import Image

trabajo = json.loads(Path(sys.argv[1]).read_text())
T = trabajo["tanda"]
M = T["modelo"]
TMP = Path(trabajo["tmp"])
SALIDA = Path(trabajo["salida"])
FIN = trabajo["fin"]
HOJA = TMP / "hoja_ref.png"
HOJA_MAL = TMP / "hoja_fallo"
res = {"_dtype": "", "_cargado_s": None}
salida_res = TMP / f"resultado_{trabajo['gpu']}.json"


def guardar():
    salida_res.write_text(json.dumps(res, indent=2))


def log(t):
    print(f"[gpu{trabajo['gpu']} {time.time() - trabajo['inicio']:7.1f}s] {t}", flush=True)


def elegir_dtype():
    p = T["precision"]
    if p in ("fp32", "bf16", "fp16"):
        return {"fp32": torch.float32, "bf16": torch.bfloat16, "fp16": torch.float16}[p]
    return torch.bfloat16 if torch.cuda.get_device_capability(0)[0] >= 8 else torch.float16


def cargar(dtype):
    if M.get("familia", "flux2_klein") == "flux2_klein":
        from diffusers import Flux2KleinPipeline
        pipe = Flux2KleinPipeline.from_pretrained(trabajo["ruta"], text_encoder=None,
                                                  tokenizer=None, torch_dtype=dtype)
        pipe.vae.to(torch.float32)              # el VAE en fp32: pequeno y sin desbordes
        pipe.to("cuda")
    else:                                       # plan B: Z-Image-Turbo, sin referencias
        from diffusers import ZImagePipeline
        pipe = ZImagePipeline.from_pretrained(trabajo["ruta"], torch_dtype=dtype)
        pipe.enable_model_cpu_offload()
    pipe.set_progress_bar_config(disable=True)
    return pipe


def a_imagen(arr):
    return Image.fromarray((np.clip(np.nan_to_num(arr), 0, 1) * 255).round().astype(np.uint8))


def malo(arr):
    return (not np.isfinite(arr).all()) or arr.mean() < 0.02 or arr.std() < 0.01


def generar(pipe, dtype, clave, semilla, ref=None, prompt=None):
    g = torch.Generator("cuda").manual_seed(semilla)
    args = dict(height=T["alto"], width=T["ancho"], num_inference_steps=M["pasos"],
                guidance_scale=M["guia"], generator=g)
    if M.get("familia", "flux2_klein") != "flux2_klein":
        img = pipe(prompt=prompt, output_type="np", **args).images[0]
        return img
    emb = torch.load(TMP / f"emb_{clave}.pt").to("cuda", dtype)
    if ref is not None:
        args["image"] = [ref]
    with torch.no_grad():
        lat = pipe(prompt_embeds=emb, output_type="latent", **args).images
        img = pipe.vae.decode(lat.to(torch.float32), return_dict=False)[0]
        if not torch.isfinite(img).all():
            return np.full((T["alto"], T["ancho"], 3), np.nan, dtype=np.float32)
        return pipe.image_processor.postprocess(img, output_type="np")[0]


def con_precision(pipe, estado, fn):
    # fp16 desborda -> imagen negra/NaN: se pasa a bf16 (emulado en T4) y se repite.
    arr = fn(estado["dtype"])
    if malo(arr) and estado["dtype"] == torch.float16:
        log("salida negra/NaN en fp16 -> paso a bf16 y repito")
        estado["dtype"] = torch.bfloat16
        pipe.transformer.to(torch.bfloat16)
        arr = fn(estado["dtype"])
    if malo(arr):
        raise RuntimeError("la imagen sale negra o con NaN")
    return arr


def esperar_hoja():
    while time.time() < FIN:
        if HOJA.exists():
            return Image.open(HOJA).convert("RGB")
        if HOJA_MAL.exists():
            return None
        time.sleep(3)
    return None


def main():
    t0 = time.time()
    estado = {"dtype": elegir_dtype()}
    pipe = cargar(estado["dtype"])
    res["_cargado_s"] = round(time.time() - t0, 1)
    log(f"Modelo listo en {res['_cargado_s']} s ({estado['dtype']})")

    if trabajo["hacer_hoja"]:
        t = time.time()
        try:
            arr = con_precision(pipe, estado, lambda d: generar(pipe, d, "hoja", T["semilla"]))
            img = a_imagen(arr)
            img.save(SALIDA / "hoja.png")
            ref = img.copy()
            ref.thumbnail((T["ref_lado"], T["ref_lado"]), Image.LANCZOS)
            ref.save(TMP / "hoja_tmp.png")
            (TMP / "hoja_tmp.png").rename(HOJA)
            res["_hoja"] = {"ok": True, "archivo": "hoja.png", "s": round(time.time() - t, 1)}
            log(f"hoja en {time.time() - t:.0f} s")
        except Exception as err:
            log("hoja falla:\n" + traceback.format_exc()[-1500:])
            res["_hoja"] = {"ok": False, "error": f"{type(err).__name__}: {err}"[-800:]}
            HOJA_MAL.write_text("x")
            torch.cuda.empty_cache()
        guardar()

    ref = None
    for esc in trabajo["escenas"]:
        if time.time() > FIN:
            res[str(esc["n"])] = {"ok": False, "error": "sin tiempo en la sesion de Kaggle"}
            guardar()
            continue
        if esc["ref"] and ref is None:
            ref = esperar_hoja()
            if ref is None:
                log("sin hoja: la escena va sin referencia")
        t = time.time()
        try:
            r = ref if esc["ref"] else None
            semilla = T["semilla"] + esc["n"]
            arr = con_precision(pipe, estado, lambda d: generar(
                pipe, d, f"{esc['n']:03d}", semilla, r, esc["prompt"]))
            archivo = f"escena_{esc['n']:03d}.jpg"
            a_imagen(arr).save(SALIDA / archivo, quality=93)
            res[str(esc["n"])] = {"ok": True, "archivo": archivo, "s": round(time.time() - t, 1),
                                  "ref": r is not None,
                                  "dtype": str(estado["dtype"]).replace("torch.", "")}
            log(f"escena {esc['n']} en {time.time() - t:.0f} s (ref={r is not None})")
        except Exception as err:
            log(f"escena {esc['n']} falla:\n" + traceback.format_exc()[-1500:])
            res[str(esc["n"])] = {"ok": False, "error": f"{type(err).__name__}: {err}"[-800:]}
            torch.cuda.empty_cache()
        res["_dtype"] = str(estado["dtype"]).replace("torch.", "")
        guardar()


try:
    main()
except Exception:
    res["_fatal"] = traceback.format_exc()[-2000:]
    log(res["_fatal"])
    if trabajo["hacer_hoja"] and not HOJA.exists():
        HOJA_MAL.write_text("x")
guardar()
"""


def lanzar_trabajadores(n_gpus, ruta):
    escenas = TANDA["escenas"]
    flux = MODELO.get("familia", "flux2_klein") == "flux2_klein"
    n = max(1, min(n_gpus, TANDA.get("gpus_max", 1), len(escenas) + 1))
    if not flux:
        n = 1                       # Z-Image con offload: uno, por la RAM de Kaggle
        for esc in escenas:         # y sin referencias: misma semilla y mismo prompt fijo
            esc["ref"] = False
    hoja = TANDA["hoja"]
    if hoja.get("b64"):
        (TMP / "hoja_ref.png").write_bytes(base64.b64decode(hoja["b64"]))
    (TMP / "trabajador.py").write_text(TRABAJADOR)
    # La GPU 0 hace la hoja: se le da una escena menos, y primero las que no la usan.
    orden = sorted(escenas, key=lambda e: e["ref"])
    partes = [[] for _ in range(n)]
    for i, esc in enumerate(orden):
        partes[(i + (1 if hoja.get("generar") and n > 1 else 0)) % n].append(esc)
    procesos = []
    for i in range(n):
        trabajo = {"gpu": i, "tanda": TANDA, "escenas": partes[i], "tmp": str(TMP),
                   "salida": str(SALIDA), "ruta": ruta, "inicio": INICIO,
                   "hacer_hoja": bool(i == 0 and hoja.get("generar") and flux),
                   "fin": INICIO + LIMITE_S - 600}
        ruta_t = TMP / f"trabajo_{i}.json"
        ruta_t.write_text(json.dumps(trabajo))
        entorno = {**os.environ, "CUDA_VISIBLE_DEVICES": str(i),
                   "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True"}
        procesos.append((i, subprocess.Popen([sys.executable, str(TMP / "trabajador.py"),
                                              str(ruta_t)], env=entorno)))
    log(f"{n} trabajador(es) en marcha")
    cargas = []
    for i, p in procesos:
        codigo = p.wait()
        ruta_r = TMP / f"resultado_{i}.json"
        parcial = json.loads(ruta_r.read_text()) if ruta_r.exists() else {}
        for clave, valor in parcial.items():
            if not clave.startswith("_"):
                resultado["escenas"][clave] = valor
        if parcial.get("_hoja"):
            resultado["hoja"] = parcial["_hoja"]
        resultado["dtype"] = resultado["dtype"] or parcial.get("_dtype", "")
        if parcial.get("_cargado_s"):
            cargas.append(parcial["_cargado_s"])
        if parcial.get("_fatal"):
            resultado["fatal"] = (resultado["fatal"] or "") + f"\n[gpu{i}] " + parcial["_fatal"]
        for esc in partes[i]:
            if str(esc["n"]) not in resultado["escenas"]:
                resultado["escenas"][str(esc["n"])] = {
                    "ok": False, "error": f"el trabajador de la GPU {i} se cayo (codigo {codigo})"}
    return cargas


def main():
    n_gpus, nombres = ver_gpu()
    resultado["gpu"] = nombres
    if not n_gpus:
        resultado["fatal"] = ("sin GPU: verifica el telefono en kaggle.com/settings "
                              "(sin eso Kaggle no da GPU) y que la cuota semanal no este agotada")
        log(resultado["fatal"])
        return
    log(f"GPU: {nombres}")
    instalar()
    ruta = bajar_modelo()
    if MODELO.get("familia", "flux2_klein") == "flux2_klein":
        codificar_textos(ruta)
    antes = time.time() - INICIO
    cargas = lanzar_trabajadores(n_gpus, ruta)
    resultado["s_modelo"] = max(cargas) if cargas else None
    resultado["s_arranque"] = round(antes + (max(cargas) if cargas else 0), 1)
    resultado["ok"] = any(r.get("ok") for r in resultado["escenas"].values())


try:
    main()
except Exception:
    resultado["fatal"] = traceback.format_exc()[-2000:]
    log(resultado["fatal"])
finally:
    guardar()
    log("Fin.")
'''
