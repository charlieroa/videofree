"""
Paso 4: la animacion y el montaje del MP4, todo en tu PC (0 $).

Cada imagen se convierte en un plano de video con un movimiento de camara que
dura exactamente lo que dura su frase. Por defecto el movimiento es el EFECTO
3D de profundidad (motor/profundidad.py): la camara se mueve dentro de la foto
y lo cercano se desplaza mas que lo lejano. Los movimientos (acercar, barrido,
orbita, subir...) se van alternando para que dos planos seguidos nunca se
muevan igual; en las escenas 'continua' (misma imagen que la anterior) el
cambio de movimiento es lo que hace que parezca otro plano.

En Modo prueba, con "efecto_3d": false en config.json o si el modelo de
profundidad no se puede descargar, el plano es el zoom/paneo plano de ffmpeg
(zoompan): mucho mas rapido. La imagen se agranda antes de mover la ventana:
zoompan trabaja en pixeles enteros y, sin ese margen, el movimiento lento tiembla.

Las escenas que ya traen un clip de video (de versiones anteriores) usan el
clip en vez de la imagen: se encuadra a 1920x1080 y se ajusta a la voz.

Los planos se hacen varios a la vez (el efecto 3D y el codificador son calculo
de CPU) y cada uno sale ya con sus subtitulos quemados: asi el video se codifica
UNA sola vez. Luego se pegan sin recodificar (todos salen con los mismos
parametros de codificacion) y la ultima pasada solo mezcla la musica.
"""
import os
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

from . import medios, proyecto

RESPIRO = 0.25        # segundos de silencio al final de cada escena
MAX_LENTO = 1.4       # cuanto se puede ralentizar un clip de video

MOVIMIENTOS = ("acercar", "panear_derecha", "alejar", "panear_izquierda")


def _movimiento(n, zoom, frames):
    """Las expresiones de zoompan para el plano n (on = fotograma actual)."""
    t = f"(on/{max(frames - 1, 1)})"
    centro_x, centro_y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    tipo = MOVIMIENTOS[(n - 1) % len(MOVIMIENTOS)]
    if tipo == "acercar":
        return f"1+{zoom}*{t}", centro_x, centro_y
    if tipo == "alejar":
        return f"1+{zoom}-{zoom}*{t}", centro_x, centro_y
    if tipo == "panear_derecha":
        return f"1+{zoom}", f"(iw-iw/zoom)*{t}", centro_y
    return f"1+{zoom}", f"(iw-iw/zoom)*(1-{t})", centro_y


def _srt_tiempo(s):
    ms = int(round(s * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    seg, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{seg:02d},{ms:03d}"


def _trozos(e):
    """Los subtitulos de una escena: (inicio, fin, texto) en segundos desde que empieza."""
    palabras = e["narracion"].split()
    trozos = [" ".join(palabras[i:i + 9]) for i in range(0, len(palabras), 9)] or [""]
    total = sum(len(x) for x in trozos) or 1
    ini = 0.0
    for x in trozos:
        dur = e["duracion"] * len(x) / total
        yield ini, ini + dur, x
        ini += dur


def _srt(lineas, destino):
    destino.write_text("\n".join(f"{k}\n{_srt_tiempo(a)} --> {_srt_tiempo(b)}\n{x}\n"
                                 for k, (a, b, x) in enumerate(lineas, 1)), encoding="utf-8")


def _escribir_srt(datos, destino):
    """El .srt de todo el video (para subirlo aparte a YouTube, si se quiere)."""
    lineas, t = [], 0.0
    for e in datos["escenas"]:
        lineas += [(t + a, t + b, x) for a, b, x in _trozos(e)]
        t += e["duracion"] + RESPIRO
    _srt(lineas, destino)


def _subtitulos(e, destino, cfg):
    """El filtro que quema los subtitulos de la escena en su plano ('' si van apagados)."""
    if not cfg.get("subtitulos"):
        return ""
    srt = Path(destino).with_suffix(".srt")
    _srt(list(_trozos(e)), srt)
    # ffmpeg corre con cwd en la carpeta del montaje: el nombre suelto evita escapar rutas de Windows.
    return (f",subtitles={srt.name}:force_style='FontName=Arial,FontSize=20,"
            f"Outline=2,Shadow=0,MarginV=45'")


def _plano(datos, e, n_plano, destino, cfg):
    w, h, fps = cfg["ancho"], cfg["alto"], cfg["fps"]
    d = e["duracion"] + RESPIRO
    frames = max(1, round(d * fps))
    z, x, y = _movimiento(n_plano, cfg["zoom"], frames)
    vf = (f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,crop={w * 2}:{h * 2},"
          f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={w}x{h}:fps={fps},"
          f"setsar=1,format=yuv420p{_subtitulos(e, destino, cfg)}")
    _codificar(frames, d, destino, cfg,
               "-loop", "1", "-framerate", fps, "-i", proyecto.absoluta(datos, e["imagen"]),
               "-i", proyecto.absoluta(datos, e["audio"]),
               "-filter_complex", f"[0:v]{vf}[v];[1:a]aresample=48000,apad[a]")


def _salida(frames, d, destino):
    """Los mismos parametros en todos los planos: asi el concat no recodifica."""
    return ("-map", "[v]", "-map", "[a]", "-frames:v", frames, "-t", f"{d:.2f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "160k", "-ac", "2", Path(destino).name)


def _codificar(frames, d, destino, cfg, *entradas_y_filtro):
    medios.ffmpeg(*entradas_y_filtro, *_salida(frames, d, destino), cwd=Path(destino).parent)


class _Imagenes3D:
    """La foto encuadrada y su profundidad, calculadas una vez por imagen (las escenas
    'continua' la comparten) y soltadas cuando ya no la usa ninguna escena."""

    def __init__(self, datos, escenas, cfg):
        self.datos, self.cfg = datos, cfg
        self.usos = {}
        for e in escenas:
            self.usos[e["imagen"]] = self.usos.get(e["imagen"], 0) + 1
        self.hechas, self.cerrojos, self.cerrojo = {}, {}, threading.Lock()

    def tomar(self, rel):
        import cv2
        from . import profundidad
        with self.cerrojo:
            propio = self.cerrojos.setdefault(rel, threading.Lock())
        with propio:
            if rel not in self.hechas:
                img = cv2.imread(str(proyecto.absoluta(self.datos, rel)))
                if img is None:
                    raise RuntimeError(f"no puedo leer la imagen {rel}")
                img = profundidad.encuadrar(img, self.cfg["ancho"], self.cfg["alto"])
                self.hechas[rel] = profundidad.Escena(img, profundidad.profundidad(img))
            return self.hechas[rel]

    def soltar(self, rel):
        with self.cerrojo:
            self.usos[rel] -= 1
            if self.usos[rel] <= 0:
                self.hechas.pop(rel, None)


def _plano_3d(datos, e, n_plano, destino, cfg, imagenes3d):
    """El plano con el efecto 3D: los fotogramas se calculan aqui y van a ffmpeg por un pipe."""
    w, h, fps = cfg["ancho"], cfg["alto"], cfg["fps"]
    d = e["duracion"] + RESPIRO
    frames = max(1, round(d * fps))
    try:
        escena = imagenes3d.tomar(e["imagen"])
        medios.ffmpeg_cuadros(
            escena.cuadros(n_plano, frames),
            "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-framerate", fps, "-i", "-",
            "-i", proyecto.absoluta(datos, e["audio"]),
            "-filter_complex", f"[0:v]setsar=1,format=yuv420p{_subtitulos(e, destino, cfg)}[v];"
                               "[1:a]aresample=48000,apad[a]",
            *_salida(frames, d, destino), cwd=Path(destino).parent)
    finally:
        imagenes3d.soltar(e["imagen"])


def _plano_clip(datos, e, destino, cfg):
    """El plano de una escena que trae clip de video, ajustado a lo que dura su voz."""
    w, h, fps = cfg["ancho"], cfg["alto"], cfg["fps"]
    d = e["duracion"] + RESPIRO
    frames = max(1, round(d * fps))
    ruta = proyecto.absoluta(datos, e["clip"])
    clip_s = e.get("clip_s") or medios.duracion(ruta)
    if datos.get("movimiento") and clip_s > 0:
        # Ida y vuelta (el clip y luego al reves) repetido hasta cubrir la voz: el
        # movimiento leve no se corta ni se congela, y no se nota el salto del bucle.
        ida_vuelta = Path(destino).with_name(Path(destino).stem + "_idavuelta.mp4")
        medios.ffmpeg("-i", ruta, "-filter_complex",
                      "[0:v]setpts=1.1*(PTS-STARTPTS),split[ida][b];[b]reverse[vuelta];"
                      "[ida][vuelta]concat=n=2:v=1:a=0[v]", "-map", "[v]", "-an",
                      "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", ida_vuelta)
        vf = (f"fps={fps},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
              f"setsar=1,format=yuv420p{_subtitulos(e, destino, cfg)}")
        _codificar(frames, d, destino, cfg,
                   "-stream_loop", "-1", "-i", ida_vuelta, "-i", proyecto.absoluta(datos, e["audio"]),
                   "-filter_complex", f"[0:v]{vf}[v];[1:a]aresample=48000,apad[a]")
        ida_vuelta.unlink(missing_ok=True)
        return
    lento = min(max(d / clip_s, 1.0), MAX_LENTO) if clip_s > 0 else 1.0
    congelar = max(0.0, d - clip_s * lento) + 0.5      # margen: luego se corta exacto
    vf = (f"setpts={lento:.4f}*(PTS-STARTPTS),fps={fps},"
          f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
          f"tpad=stop_mode=clone:stop_duration={congelar:.2f},"
          f"setsar=1,format=yuv420p{_subtitulos(e, destino, cfg)}")
    _codificar(frames, d, destino, cfg,
               "-i", ruta, "-i", proyecto.absoluta(datos, e["audio"]),
               "-filter_complex", f"[0:v]{vf}[v];[1:a]aresample=48000,apad[a]")


def _usar_3d(datos, cfg, escenas, avisar):
    if datos.get("simular") or not cfg.get("efecto_3d", True) or not escenas:
        return False
    try:
        from . import profundidad
        profundidad.preparar(avisar)
        return True
    except Exception as err:          # sin internet la primera vez, o faltan librerias
        avisar(f"Efecto 3D no disponible ({str(err)[:160]}): se usa el zoom plano.")
        return False


def ejecutar(datos, avisar):
    cfg = proyecto.config()["montaje"]
    faltan = [e["n"] for e in datos["escenas"] if not (e["imagen"] and e["audio"])]
    if faltan:
        raise RuntimeError(f"faltan imagen o voz en las escenas {faltan[:10]}")

    carpeta = proyecto.carpeta(datos["id"]) / "montaje"
    carpeta.mkdir(exist_ok=True)

    def tiene_clip(e):
        return bool(e.get("clip") and e.get("video_ia", True)
                    and proyecto.absoluta(datos, e["clip"]).is_file())

    con_imagen = [e for e in datos["escenas"] if not tiene_clip(e)]
    en_3d = _usar_3d(datos, cfg, con_imagen, avisar)
    imagenes3d = _Imagenes3D(datos, con_imagen, cfg) if en_3d else None

    def hacer(e):
        seg = carpeta / f"plano_{e['n']:03d}.mp4"
        if tiene_clip(e):
            _plano_clip(datos, e, seg, cfg)
        elif en_3d:
            _plano_3d(datos, e, e["n"], seg, cfg, imagenes3d)
        else:
            _plano(datos, e, e["n"], seg, cfg)

    # Varios planos a la vez. Los avisos salen de este hilo: el registro no es de varios hilos.
    total = len(datos["escenas"])
    hilos = int(cfg.get("planos_a_la_vez") or max(2, min(4, (os.cpu_count() or 2) * 3 // 8)))  # 8 hilos -> 3, lo medido
    avisar(f"Animando {total} escenas ({'efecto 3D' if en_3d else 'zoom plano'}, {hilos} a la vez)...")
    hechos = 0
    with ThreadPoolExecutor(hilos) as pool:
        pendientes = {pool.submit(hacer, e) for e in datos["escenas"]}
        while pendientes:
            listos, pendientes = wait(pendientes, return_when=FIRST_COMPLETED)
            for f in listos:
                if f.exception():
                    for p in pendientes:
                        p.cancel()
                    raise f.exception()
                hechos += 1
                if hechos == total or hechos % max(1, total // 10) == 0:
                    avisar(f"Animadas {hechos}/{total} escenas")
    lista = [f"file 'plano_{e['n']:03d}.mp4'" for e in datos["escenas"]]
    (carpeta / "lista.txt").write_text("\n".join(lista), encoding="utf-8")
    medios.ffmpeg("-f", "concat", "-safe", "0", "-i", "lista.txt", "-c", "copy", "unido.mp4", cwd=carpeta)

    _escribir_srt(datos, carpeta / "subtitulos.srt")
    final = "video_final.mp4"
    if cfg.get("musica"):
        avisar("Uniendo todo (musica)...")
        medios.ffmpeg("-i", "unido.mp4", "-stream_loop", "-1", "-i", str(proyecto.RAIZ / cfg["musica"]),
                      "-filter_complex",
                      f"[1:a]volume={cfg['volumen_musica']}[m];[0:a][m]amix=inputs=2:duration=first[a]",
                      "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                      "-movflags", "+faststart", final, cwd=carpeta)
    else:
        medios.ffmpeg("-i", "unido.mp4", "-c", "copy", "-movflags", "+faststart", final, cwd=carpeta)

    datos["mp4"] = proyecto.relativa(datos, carpeta / final)
    dur = medios.duracion(carpeta / final)
    avisar(f"Video listo: {dur / 60:.1f} min -> montaje/{final}")
