"""
Paso opcional: clips de video IA en la GPU gratis de Kaggle (0 $).

Las escenas marcadas como 'Video IA' dejan de ser una foto con zoom: su imagen
se anima con un modelo abierto de imagen->video (LTX-Video 2B distilled, de
Lightricks) en la GPU de Kaggle de la propia persona, y el montaje usa ese clip.

Como Kaggle no da una maquina sino «notebooks» que se ejecutan solos, cada tanda
de escenas es UN trabajo:

  1. Aqui se prepara la tanda: la imagen de cada escena (ya recortada al tamano
     del modelo), un prompt de movimiento (lo que se ve + el estilo de la biblia
     + un movimiento de camara) y cuantos fotogramas hacen falta.
  2. Las imagenes viajan a Kaggle: si son pocas van dentro del propio script
     (base64, sin pasos extra: lo tipico al rehacer un clip); si son muchas se
     suben como dataset PRIVADO de la cuenta y el kernel lo monta.
  3. El script del kernel instala diffusers, baja el modelo de Hugging Face UNA
     vez y genera todos los clips de la tanda seguidos (la carga del modelo se
     paga una sola vez). Si una escena falla, sigue con las demas. Con 2xT4
     reparte las escenas entre las dos GPU.
  4. Se baja la salida, se copian los clips a proyectos/<id>/clips/ y cada
     escena guarda 'clip' y 'clip_s'.

Las T4/P100 de Kaggle no tienen bf16 de verdad: el modelo va en fp16 y, si un
clip sale negro o con NaN, el kernel pasa solo a fp32 y lo repite.
"""
import base64
import io
import json
import math
import shutil
import time

from PIL import Image

from . import gpu, imagenes, medios, proyecto
from .montaje import RESPIRO

# Hasta este tamano (base64) las imagenes van dentro del script; mas, en un
# dataset. Kaggle no documenta un tope para el codigo de un kernel, asi que se
# es prudente: ~5 imagenes de 832x480.
LIMITE_EMBEBIDO = 600_000

# Movimientos de camara alternos, como en el montaje: dos clips seguidos no se
# mueven igual.
MOVIMIENTOS = ("Slow cinematic camera push-in", "Slow camera pan to the right",
               "Slow camera pull-back", "Slow camera pan to the left")
NEGATIVO = ("worst quality, inconsistent motion, blurry, jittery, distorted, morphing, "
            "deformed faces, text, watermark")


def cfg():
    return proyecto.config()["video_gpu"]


# ------------------------------------------------------------- que escenas

def marcadas(datos):
    return [e for e in datos["escenas"] if e.get("video_ia")]


def pendientes(datos, solo=None):
    """Las escenas a generar: las pedidas a mano (rehacer) o las marcadas sin clip."""
    if solo:
        return [e for e in datos["escenas"] if e["n"] in solo and e.get("imagen")]
    return [e for e in marcadas(datos) if e.get("imagen") and not e.get("clip")]


def segundos_objetivo(e, c=None):
    """Lo que dura la escena en el video (voz + respiro), con el tope del modelo.

    Si el clip queda corto, el montaje lo ralentiza (hasta 1.4x) y congela el
    ultimo fotograma: no hace falta generar mas segundos de los que el modelo
    hace bien.
    """
    c = c or cfg()
    voz = e.get("duracion") or proyecto.config()["guion"]["segundos_por_escena"]
    return min(voz + RESPIRO, c["tope_s"])


def fotogramas(segundos, fps):
    """LTX-Video quiere 8*k+1 fotogramas."""
    k = max(3, round(segundos * fps / 8))
    return 8 * k + 1


LEVE = ("Static camera, no zoom, no pan. The characters move subtly and naturally: breathing, "
        "blinking, small head and hand gestures, mouth moving as if talking. Gentle ambient motion "
        "where it fits: smoke or steam rising, dust in the light, leaves, flickering light, water")


def prompt_movimiento(datos, e):
    """El prompt del clip: movimiento de camara + lo que se ve + estilo de la biblia.

    Se reusa el prompt de la imagen (mismos personajes y estilo) para que el
    modelo no 'reinterprete' la escena, y se le pide movimiento suave: lo que
    mejor sale en 5 s y lo que menos deforma caras.
    """
    base = imagenes.prompt_de(datos, e)
    if datos.get("movimiento"):
        # «Movimiento IA en todas las escenas»: lo que se mueve es la escena, no la
        # camara, y el montaje repite el clip en bucle de ida y vuelta.
        texto = (f"{LEVE}. {base}. Same art style and colors as the first frame, smooth, "
                 f"stable, seamless, high quality")
        return texto[:1200]
    mov = MOVIMIENTOS[(e["n"] - 1) % len(MOVIMIENTOS)]
    texto = (f"{mov}. {base}. Subtle natural motion in the scene, smooth and stable, "
             f"consistent with the first frame, high quality")
    return texto[:1200]


# -------------------------------------------------------------- estimacion

def gpus_de(c=None):
    c = c or cfg()
    por_maquina = 2 if c.get("machine_shape") == "NvidiaTeslaT4" else 1   # T4 = 2xT4
    return max(1, min(por_maquina, c.get("gpus_max", 1)))


def estimar(datos):
    """Cuantas escenas llevan video IA y cuantas horas de GPU costarian las que faltan.

    Usa lo medido en la ultima tanda real si lo hay (config video_gpu.medido);
    si no, la estimacion del README.
    """
    c = cfg()
    marc = marcadas(datos)
    faltan = [e for e in marc if not e.get("clip")]
    med = c.get("medido") or {}
    min_clip = med.get("min_por_clip") or c["min_por_clip_estimado"]
    arranque = med.get("min_arranque") or c["min_arranque_estimado"]
    tandas = math.ceil(len(faltan) / c["max_escenas_por_tanda"]) if faltan else 0
    minutos = tandas * arranque + len(faltan) * min_clip / gpus_de(c)
    return {"marcadas": len(marc), "con_clip": len(marc) - len(faltan), "faltan": len(faltan),
            "sin_imagen": sum(1 for e in faltan if not e.get("imagen")),
            "horas": round(minutos / 60, 2), "horas_semana": c.get("horas_semana_kaggle", 30),
            "medido": bool(med)}


# ---------------------------------------------------------- preparar tanda

def _encuadrar(ruta, ancho, alto):
    """Recorta al centro a la proporcion del modelo y escala: menos bytes que subir."""
    with Image.open(ruta) as im:
        im = im.convert("RGB")
        w, h = im.size
        if w / h > ancho / alto:
            nw = round(h * ancho / alto)
            im = im.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
        else:
            nh = round(w * alto / ancho)
            im = im.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
        im = im.resize((ancho, alto), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=92)
        return buf.getvalue()


def preparar(datos, escenas, carpeta, c=None):
    """Imagenes (escena_NNN.jpg) + tanda.json en 'carpeta'. Devuelve la tanda."""
    c = c or cfg()
    if carpeta.exists():
        shutil.rmtree(carpeta)
    carpeta.mkdir(parents=True)
    tanda = {
        "id": f"{datos['id']}-{time.strftime('%H%M%S')}",
        "ancho": c["ancho"], "alto": c["alto"], "fps": c["fps"],
        "modelo": c["modelo"], "plan_b": c.get("plan_b"), "precision": c["precision"],
        "semilla": c["semilla"], "gpus_max": c.get("gpus_max", 1), "pip": c["pip"],
        "negativo": NEGATIVO,
        "escenas": [],
    }
    for e in escenas:
        nombre = f"escena_{e['n']:03d}.jpg"
        (carpeta / nombre).write_bytes(
            _encuadrar(proyecto.absoluta(datos, e["imagen"]), c["ancho"], c["alto"]))
        seg = segundos_objetivo(e, c)
        tanda["escenas"].append({"n": e["n"], "imagen": nombre,
                                 "prompt": prompt_movimiento(datos, e),
                                 "segundos": round(seg, 2),
                                 "frames": fotogramas(seg, c["fps"])})
    (carpeta / "tanda.json").write_text(json.dumps(tanda, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    return tanda


def _b64(obj):
    return base64.b64encode(json.dumps(obj, ensure_ascii=False).encode("utf-8")).decode("ascii")


def script_kernel(tanda, embebidas=None, limite_s=11 * 3600):
    """El script que corre en Kaggle, con la tanda (y quiza las imagenes) dentro.

    Todo va en base64 para que ningun prompt pueda romper el codigo Python.
    """
    return (KERNEL
            .replace("__TANDA__", _b64(tanda))
            .replace("__IMAGENES__", _b64(embebidas or {}))
            .replace("__LIMITE_S__", str(int(limite_s))))


# ---------------------------------------------------------------- el paso

def _simular_kaggle(nombre, codigo_python, avisar, limite_s=0, datasets=None, maquina=None,
                    **_):
    """Modo prueba: hace lo mismo que Kaggle pero en este PC y sin IA.

    Prepara la carpeta del trabajo igual que la de verdad (script.py +
    kernel-metadata.json), comprueba que el script compila, y fabrica la salida
    con ffmpeg: clips de 3 y 9 s alternos (para probar que el montaje alarga y
    recorta) y un resultado.json con el mismo formato que el del kernel.
    """
    carpeta, _ = gpu.preparar_trabajo(nombre, codigo_python, datasets, maquina,
                                      usuario="simulado")
    compile(codigo_python, "script.py", "exec")
    marca = "TANDA = json.loads(base64.b64decode(\""
    ini = codigo_python.index(marca) + len(marca)
    tanda = json.loads(base64.b64decode(codigo_python[ini:codigo_python.index('"', ini)]))
    salida = carpeta / "salida"
    res = {"ok": True, "gpu": "simulada", "dtype": "-", "modelo": "simulado",
           "s_arranque": 0, "escenas": {}, "fatal": None}
    for i, esc in enumerate(tanda["escenas"]):
        dur = 3 if i % 2 == 0 else 9
        archivo = f"escena_{esc['n']:03d}.mp4"
        avisar(f"(simulado) clip escena {esc['n']}: {dur} s")
        medios.ffmpeg("-f", "lavfi", "-i",
                      f"testsrc2=size={tanda['ancho']}x{tanda['alto']}:rate={tanda['fps']}",
                      "-t", dur, "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                      salida / archivo)
        res["escenas"][str(esc["n"])] = {"ok": True, "archivo": archivo, "s": 0.0,
                                         "frames": dur * tanda["fps"], "segundos_clip": dur}
    (salida / "resultado.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    return salida


def _registrar(datos, salida, tanda, avisar, simulado):
    """Copia los clips buenos al proyecto y apunta en cada escena 'clip' y 'clip_s'."""
    ruta = salida / "resultado.json"
    if not ruta.exists():
        raise RuntimeError("Kaggle no ha devuelto resultado.json (mira el log del kernel).")
    res = json.loads(ruta.read_text(encoding="utf-8"))
    escenas = res.get("escenas", {})
    if res.get("fatal") and not any(r.get("ok") for r in escenas.values()):
        raise RuntimeError(res["fatal"][-600:])

    destino = proyecto.carpeta(datos["id"]) / "clips"
    destino.mkdir(exist_ok=True)
    buenos, tiempos = 0, []
    for esc in tanda["escenas"]:
        r = escenas.get(str(esc["n"])) or {"ok": False, "error": "sin resultado"}
        e = next((x for x in datos["escenas"] if x["n"] == esc["n"]), None)
        origen = salida / (r.get("archivo") or "")
        if not (e and r.get("ok") and origen.is_file()):
            avisar(f"Clip escena {esc['n']}: fallo ({str(r.get('error', 'no llego'))[-200:]})")
            continue
        final = destino / f"escena_{esc['n']:03d}.mp4"
        shutil.copyfile(origen, final)
        e["clip"] = proyecto.relativa(datos, final)
        e["clip_s"] = round(medios.duracion(final), 2)
        buenos += 1
        if r.get("s"):
            tiempos.append(r["s"])
    datos["mp4"] = None
    proyecto.guardar(datos)
    avisar(f"Clips IA: {buenos}/{len(tanda['escenas'])} listos"
           + (f" ({res.get('gpu')}, {res.get('dtype')})" if not simulado else " (simulados)"))

    if not simulado and tiempos:
        # Lo medido de verdad sustituye a la estimacion en la cabecera.
        cfg_total = proyecto.config()
        cfg_total["video_gpu"]["medido"] = {
            "min_por_clip": round(sum(tiempos) / len(tiempos) / 60, 2),
            "min_arranque": round((res.get("s_arranque") or 0) / 60, 1),
            "gpu": res.get("gpu"), "dtype": res.get("dtype"),
            "fecha": time.strftime("%Y-%m-%d %H:%M")}
        proyecto.CONFIG.write_text(json.dumps(cfg_total, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
    if res.get("fatal"):
        avisar(f"Aviso del kernel: {res['fatal'][-300:]}")


def _una_tanda(datos, escenas, avisar, ejecutor, simulado, k, total):
    c = cfg()
    carpeta = gpu.TRABAJOS / f"clips-{datos['id']}" / "imagenes"
    tanda = preparar(datos, escenas, carpeta, c)
    ficheros = {x["imagen"]: (carpeta / x["imagen"]).read_bytes() for x in tanda["escenas"]}
    peso = sum(math.ceil(len(b) / 3) * 4 for b in ficheros.values())

    datasets, embebidas = None, None
    if peso <= LIMITE_EMBEBIDO:
        embebidas = {n: base64.b64encode(b).decode("ascii") for n, b in ficheros.items()}
        avisar(f"Tanda {k}/{total}: {len(escenas)} escenas, imagenes dentro del script "
               f"({peso // 1024} KB)")
    else:
        slug = f"vs-imagenes-{datos['id'][:15]}".lower()
        titulo = f"Video Simple imagenes {datos['id'][:15]}"
        if simulado:
            gpu.metadatos_dataset(carpeta, slug, titulo, "simulado")
            avisar(f"(simulado) {peso // 1024} KB de imagenes: irian como dataset privado {slug}")
            datasets = [f"simulado/{slug}"]
        else:
            datasets = [gpu.subir_dataset(slug, titulo, carpeta, avisar)]

    # Tope de la sesion de Kaggle: arranque + 3 veces lo estimado por clip, con
    # margen; nunca mas de las 12 h que da Kaggle.
    limite = (c["min_arranque_estimado"] * 2
              + len(escenas) * c["min_por_clip_estimado"] * 3 / gpus_de(c)) * 60
    limite = int(min(max(limite, 3600), 11.5 * 3600))
    codigo = script_kernel(tanda, embebidas, limite)
    salida = ejecutor(f"clips-{datos['id'][:22]}", codigo, avisar, limite_s=limite,
                      datasets=datasets, maquina=c.get("machine_shape") or None)
    _registrar(datos, salida, tanda, avisar, simulado)


def ejecutar(datos, avisar, solo=None, ejecutor=None):
    """Genera los clips de las escenas marcadas (o de 'solo') en la GPU de Kaggle."""
    c = cfg()
    lista = pendientes(datos, solo)
    if not lista:
        avisar("Clips IA: no hay escenas marcadas como 'Video IA' con imagen y sin clip.")
        return
    simulado = bool(datos.get("simular"))
    if not simulado and not gpu.credenciales() and ejecutor is None:
        raise RuntimeError("La GPU no esta conectada: abre el Asistente (paso 5) y conecta "
                           "tu cuenta de Kaggle.")
    ejecutor = ejecutor or (_simular_kaggle if simulado else gpu.ejecutar_script)
    paso = c["max_escenas_por_tanda"]
    tandas = [lista[i:i + paso] for i in range(0, len(lista), paso)]
    for k, escenas in enumerate(tandas, 1):
        _una_tanda(datos, escenas, avisar, ejecutor, simulado, k, len(tandas))


# ===================================================== el script de Kaggle
#
# Corre en el kernel de Kaggle (Python 3.13, torch ya instalado). Fases:
#   0. Sin GPU -> resultado.json con el error claro y fuera (no carga nada).
#   1. pip install de diffusers/transformers (versiones fijadas en config).
#   2. El codificador de texto T5 (9 GB en fp16) se carga UNA vez en la GPU 0,
#      codifica todos los prompts y se libera: asi cada trabajador solo carga el
#      transformer (2B) y el VAE, y caben dos (uno por T4).
#   3. Un trabajador por GPU (subproceso con CUDA_VISIBLE_DEVICES) genera su
#      parte de los clips y escribe su resultado; una escena que falla no para
#      las demas.
#   4. Se juntan los resultados en /kaggle/working/resultado.json.

KERNEL = r'''
import base64, json, os, subprocess, sys, time, traceback
from pathlib import Path

INICIO = time.time()
TANDA = json.loads(base64.b64decode("__TANDA__").decode("utf-8"))
IMAGENES = json.loads(base64.b64decode("__IMAGENES__").decode("utf-8"))
LIMITE_S = __LIMITE_S__
SALIDA = Path("/kaggle/working")
TMP = Path("/tmp/video_simple")
TMP.mkdir(parents=True, exist_ok=True)

resultado = {"ok": False, "tanda": TANDA["id"], "gpu": "", "dtype": "", "modelo": "",
             "s_arranque": None, "escenas": {}, "fatal": None}


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


def carpeta_imagenes():
    """Las imagenes: embebidas en este script o en el dataset montado en /kaggle/input."""
    if IMAGENES:
        d = TMP / "imagenes"
        d.mkdir(exist_ok=True)
        for nombre, b64 in IMAGENES.items():
            (d / nombre).write_bytes(base64.b64decode(b64))
        return d
    # La ruta exacta de montaje de un dataset ha cambiado alguna vez en Kaggle:
    # se busca el tanda.json de ESTA tanda en todo /kaggle/input.
    for t in Path("/kaggle/input").rglob("tanda.json"):
        try:
            if json.loads(t.read_text(encoding="utf-8")).get("id") == TANDA["id"]:
                return t.parent
        except Exception:
            pass
    raise RuntimeError("No encuentro las imagenes de la tanda en /kaggle/input "
                       "(el dataset no se ha montado o es de otra version).")


def instalar():
    log("Instalando: " + " ".join(TANDA["pip"]))
    r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", *TANDA["pip"]],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("pip install fallo: " + (r.stderr or r.stdout)[-1500:])


def codificar_textos(modelos):
    """T5 en la GPU 0, en fp16 (transformers deja en fp32 las capas que desbordan)."""
    import torch
    from transformers import T5EncoderModel, T5Tokenizer
    repo = modelos[0]["repo_base"]
    log(f"Cargando el codificador de texto de {repo}")
    tok = T5Tokenizer.from_pretrained(repo, subfolder="tokenizer")
    enc = T5EncoderModel.from_pretrained(repo, subfolder="text_encoder",
                                         torch_dtype=torch.float16).to("cuda:0")
    enc.eval()

    def uno(texto):
        t = tok(texto, padding="max_length", max_length=256, truncation=True,
                add_special_tokens=True, return_tensors="pt")
        mascara = t.attention_mask.to("cuda:0")
        with torch.no_grad():
            emb = enc(t.input_ids.to("cuda:0"), attention_mask=mascara)[0]
        return emb.float().cpu(), mascara.cpu()

    neg = uno(TANDA["negativo"])
    for esc in TANDA["escenas"]:
        p, m = uno(esc["prompt"])
        if not torch.isfinite(p).all():
            raise RuntimeError("el codificador de texto da NaN en fp16")
        torch.save({"p": p, "m": m, "np": neg[0], "nm": neg[1]}, TMP / f"emb_{esc['n']:03d}.pt")
    del enc
    torch.cuda.empty_cache()
    log("Prompts codificados.")


TRABAJADOR = r"""
import json, sys, time, traceback
from pathlib import Path
import numpy as np
import torch
from PIL import Image

trabajo = json.loads(Path(sys.argv[1]).read_text())
T = trabajo["tanda"]
TMP = Path(trabajo["tmp"])
SALIDA = Path(trabajo["salida"])
FIN = trabajo["fin"]
res = {"_dtype": "", "_modelo": "", "_cargado_s": None}
salida_res = TMP / f"resultado_{trabajo['gpu']}.json"


def guardar():
    salida_res.write_text(json.dumps(res, indent=2))


def log(t):
    print(f"[gpu{trabajo['gpu']} {time.time() - trabajo['inicio']:7.1f}s] {t}", flush=True)


def elegir_dtype():
    p = T["precision"]
    if p == "fp32":
        return torch.float32
    if p == "bf16":
        return torch.bfloat16
    if p == "fp16":
        return torch.float16
    # auto: bf16 solo si la GPU lo tiene de verdad (Ampere o mas); T4/P100 -> fp16
    return torch.bfloat16 if torch.cuda.get_device_capability(0)[0] >= 8 else torch.float16


def cargar(modelo, dtype):
    from diffusers import AutoencoderKLLTXVideo, LTXConditionPipeline, LTXVideoTransformer3DModel
    extra = {}
    if modelo.get("checkpoint"):
        log(f"Transformer de {modelo['checkpoint']}")
        extra["transformer"] = LTXVideoTransformer3DModel.from_single_file(
            modelo["checkpoint"], torch_dtype=dtype)
        try:
            extra["vae"] = AutoencoderKLLTXVideo.from_single_file(modelo["checkpoint"],
                                                                  torch_dtype=dtype)
        except Exception as err:
            log(f"VAE del checkpoint no carga ({err}); uso el del repo base")
    pipe = LTXConditionPipeline.from_pretrained(modelo["repo_base"], text_encoder=None,
                                                tokenizer=None, torch_dtype=dtype, **extra)
    pipe.to("cuda")
    pipe.vae.enable_tiling()
    pipe.set_progress_bar_config(disable=True)
    return pipe


def malo(frames):
    a = np.asarray(frames, dtype=np.float32)
    return (not np.isfinite(a).all()) or a.mean() < 0.02 or a.std() < 0.01


def escribir(frames, ruta, fps):
    import imageio.v2 as imageio
    w = imageio.get_writer(str(ruta), fps=fps, codec="libx264", quality=8,
                           pixelformat="yuv420p", macro_block_size=16)
    for f in frames:
        w.append_data((np.clip(np.nan_to_num(f), 0, 1) * 255).round().astype(np.uint8))
    w.close()


def main():
    t0 = time.time()
    dtype = elegir_dtype()
    pipe, modelo = None, None
    for m in [T["modelo"], T.get("plan_b")]:
        if not m:
            continue
        try:
            pipe, modelo = cargar(m, dtype), m
            break
        except Exception:
            log("No carga el modelo:\n" + traceback.format_exc()[-1500:])
            torch.cuda.empty_cache()
    if pipe is None:
        raise RuntimeError("no carga ningun modelo (ni el principal ni el plan B)")
    res["_modelo"] = modelo.get("checkpoint") or modelo["repo_base"]
    res["_cargado_s"] = round(time.time() - t0, 1)
    log(f"Modelo listo en {res['_cargado_s']} s ({dtype})")

    pendientes = list(trabajo["escenas"])
    while pendientes:
        esc = pendientes.pop(0)
        if time.time() > FIN:
            res[str(esc["n"])] = {"ok": False, "error": "sin tiempo en la sesion de Kaggle"}
            guardar()
            continue
        t = time.time()
        try:
            emb = torch.load(TMP / f"emb_{esc['n']:03d}.pt")
            img = Image.open(Path(trabajo["imagenes"]) / esc["imagen"]).convert("RGB")
            img = img.resize((T["ancho"], T["alto"]))
            args = dict(image=img, width=T["ancho"], height=T["alto"], num_frames=esc["frames"],
                        frame_rate=T["fps"], guidance_scale=modelo["guia"],
                        decode_timestep=0.05, decode_noise_scale=0.025,
                        image_cond_noise_scale=0.025,
                        prompt_embeds=emb["p"].to("cuda", dtype),
                        prompt_attention_mask=emb["m"].to("cuda"),
                        generator=torch.Generator("cuda").manual_seed(T["semilla"] + esc["n"]),
                        output_type="np")
            if modelo["guia"] > 1:
                args.update(negative_prompt_embeds=emb["np"].to("cuda", dtype),
                            negative_prompt_attention_mask=emb["nm"].to("cuda"))
            if modelo.get("timesteps"):
                args["timesteps"] = modelo["timesteps"]
            else:
                args["num_inference_steps"] = modelo["pasos"]
            frames = pipe(**args).frames[0]
            if malo(frames):
                if dtype == torch.float16:
                    # Plan B de precision: fp16 desborda -> todo a fp32 y se repite.
                    log(f"escena {esc['n']}: salida negra/NaN en fp16 -> paso a fp32")
                    dtype = torch.float32
                    pipe.to(dtype=torch.float32)
                    pendientes.insert(0, esc)
                    continue
                raise RuntimeError("el clip sale negro o con NaN")
            archivo = f"escena_{esc['n']:03d}.mp4"
            escribir(frames, SALIDA / archivo, T["fps"])
            res[str(esc["n"])] = {"ok": True, "archivo": archivo, "s": round(time.time() - t, 1),
                                  "frames": len(frames),
                                  "segundos_clip": round(len(frames) / T["fps"], 2),
                                  "dtype": str(dtype).replace("torch.", "")}
            log(f"escena {esc['n']}: {len(frames)} fotogramas en {time.time() - t:.0f} s")
        except Exception as err:
            log(f"escena {esc['n']} falla:\n" + traceback.format_exc()[-1500:])
            res[str(esc["n"])] = {"ok": False, "error": f"{type(err).__name__}: {err}"[-800:]}
            torch.cuda.empty_cache()
        res["_dtype"] = str(dtype).replace("torch.", "")
        guardar()


try:
    main()
except Exception:
    res["_fatal"] = traceback.format_exc()[-2000:]
    log(res["_fatal"])
guardar()
"""


def lanzar_trabajadores(n_gpus, dir_imagenes):
    escenas = TANDA["escenas"]
    n = max(1, min(n_gpus, TANDA.get("gpus_max", 1), len(escenas)))
    (TMP / "trabajador.py").write_text(TRABAJADOR)
    procesos = []
    for i in range(n):
        trabajo = {"gpu": i, "tanda": TANDA, "escenas": escenas[i::n], "tmp": str(TMP),
                   "salida": str(SALIDA), "imagenes": str(dir_imagenes),
                   "inicio": INICIO, "fin": INICIO + LIMITE_S - 900}
        ruta = TMP / f"trabajo_{i}.json"
        ruta.write_text(json.dumps(trabajo))
        entorno = {**os.environ, "CUDA_VISIBLE_DEVICES": str(i)}
        procesos.append((i, subprocess.Popen([sys.executable, str(TMP / "trabajador.py"),
                                              str(ruta)], env=entorno)))
    log(f"{n} trabajador(es) en marcha")
    cargas = []
    for i, p in procesos:
        codigo = p.wait()
        ruta = TMP / f"resultado_{i}.json"
        parcial = json.loads(ruta.read_text()) if ruta.exists() else {}
        for clave, valor in parcial.items():
            if not clave.startswith("_"):
                resultado["escenas"][clave] = valor
        resultado["dtype"] = resultado["dtype"] or parcial.get("_dtype", "")
        resultado["modelo"] = resultado["modelo"] or parcial.get("_modelo", "")
        if parcial.get("_cargado_s"):
            cargas.append(parcial["_cargado_s"])
        if parcial.get("_fatal"):
            resultado["fatal"] = (resultado["fatal"] or "") + f"\n[gpu{i}] " + parcial["_fatal"]
        for esc in escenas[i::n]:
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
    dir_imagenes = carpeta_imagenes()
    instalar()
    modelos = [m for m in (TANDA["modelo"], TANDA.get("plan_b")) if m]
    codificar_textos(modelos)
    antes = time.time() - INICIO
    cargas = lanzar_trabajadores(n_gpus, dir_imagenes)
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
