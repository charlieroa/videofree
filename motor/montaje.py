"""
Paso 4: la animacion y el montaje del MP4, todo en tu PC con ffmpeg (0 $).

Cada imagen se convierte en un plano de video con un movimiento de camara
(acercarse, alejarse, paneo a un lado o al otro) que dura exactamente lo que
dura su frase. Los movimientos se van alternando para que dos planos seguidos
nunca se muevan igual; en las escenas 'continua' (misma imagen que la
anterior) el cambio de movimiento es lo que hace que parezca otro plano.

La imagen se agranda antes de mover la ventana: zoompan trabaja en pixeles
enteros y, sin ese margen, el movimiento lento tiembla.

Las escenas con clip de video IA (clips_gpu, en la GPU de Kaggle) usan el
clip en vez de la imagen: se encuadra a 1920x1080 y se ajusta a la voz. Si el
clip es corto se ralentiza (hasta 1.4x, mas ya se nota a camara lenta) y luego
se congela su ultimo fotograma; si es largo se corta.

Despues se pega todo sin recodificar (todos los planos salen con los mismos
parametros de codificacion, sea imagen o clip), y en una ultima pasada se
queman los subtitulos y se mezcla la musica.
"""
from pathlib import Path

from . import medios, proyecto

RESPIRO = 0.25        # segundos de silencio al final de cada escena
MAX_LENTO = 1.4       # cuanto se puede ralentizar un clip de video IA

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


def _escribir_srt(datos, destino):
    lineas, t, k = [], 0.0, 1
    for e in datos["escenas"]:
        palabras = e["narracion"].split()
        trozos = [" ".join(palabras[i:i + 9]) for i in range(0, len(palabras), 9)] or [""]
        total = sum(len(x) for x in trozos) or 1
        ini = t
        for x in trozos:
            dur = e["duracion"] * len(x) / total
            lineas.append(f"{k}\n{_srt_tiempo(ini)} --> {_srt_tiempo(ini + dur)}\n{x}\n")
            ini += dur
            k += 1
        t += e["duracion"] + RESPIRO
    destino.write_text("\n".join(lineas), encoding="utf-8")


def _plano(datos, e, n_plano, destino, cfg):
    w, h, fps = cfg["ancho"], cfg["alto"], cfg["fps"]
    d = e["duracion"] + RESPIRO
    frames = max(1, round(d * fps))
    z, x, y = _movimiento(n_plano, cfg["zoom"], frames)
    vf = (f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,crop={w * 2}:{h * 2},"
          f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={w}x{h}:fps={fps},"
          f"setsar=1,format=yuv420p")
    _codificar(frames, d, destino,
               "-loop", "1", "-framerate", fps, "-i", proyecto.absoluta(datos, e["imagen"]),
               "-i", proyecto.absoluta(datos, e["audio"]),
               "-filter_complex", f"[0:v]{vf}[v];[1:a]aresample=48000,apad[a]")


def _codificar(frames, d, destino, *entradas_y_filtro):
    """Los mismos parametros en todos los planos: asi el concat no recodifica."""
    medios.ffmpeg(
        *entradas_y_filtro,
        "-map", "[v]", "-map", "[a]", "-frames:v", frames, "-t", f"{d:.2f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k", "-ac", "2", destino)


def _plano_clip(datos, e, destino, cfg):
    """El plano de una escena con clip de video IA, ajustado a lo que dura su voz."""
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
              f"setsar=1,format=yuv420p")
        _codificar(frames, d, destino,
                   "-stream_loop", "-1", "-i", ida_vuelta, "-i", proyecto.absoluta(datos, e["audio"]),
                   "-filter_complex", f"[0:v]{vf}[v];[1:a]aresample=48000,apad[a]")
        ida_vuelta.unlink(missing_ok=True)
        return
    lento = min(max(d / clip_s, 1.0), MAX_LENTO) if clip_s > 0 else 1.0
    congelar = max(0.0, d - clip_s * lento) + 0.5      # margen: luego se corta exacto
    vf = (f"setpts={lento:.4f}*(PTS-STARTPTS),fps={fps},"
          f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
          f"tpad=stop_mode=clone:stop_duration={congelar:.2f},"
          f"setsar=1,format=yuv420p")
    _codificar(frames, d, destino,
               "-i", ruta, "-i", proyecto.absoluta(datos, e["audio"]),
               "-filter_complex", f"[0:v]{vf}[v];[1:a]aresample=48000,apad[a]")


def ejecutar(datos, avisar):
    cfg = proyecto.config()["montaje"]
    faltan = [e["n"] for e in datos["escenas"] if not (e["imagen"] and e["audio"])]
    if faltan:
        raise RuntimeError(f"faltan imagen o voz en las escenas {faltan[:10]}")

    carpeta = proyecto.carpeta(datos["id"]) / "montaje"
    carpeta.mkdir(exist_ok=True)
    lista = []
    for e in datos["escenas"]:
        seg = carpeta / f"plano_{e['n']:03d}.mp4"
        clip = (e.get("clip") and e.get("video_ia", True)
                and proyecto.absoluta(datos, e["clip"]).is_file())
        avisar(f"{'Clip IA' if clip else 'Animando'} escena {e['n']}/{len(datos['escenas'])}")
        if clip:
            _plano_clip(datos, e, seg, cfg)
        else:
            _plano(datos, e, e["n"], seg, cfg)
        lista.append(f"file '{seg.name}'")
    (carpeta / "lista.txt").write_text("\n".join(lista), encoding="utf-8")
    medios.ffmpeg("-f", "concat", "-safe", "0", "-i", "lista.txt", "-c", "copy", "unido.mp4", cwd=carpeta)

    _escribir_srt(datos, carpeta / "subtitulos.srt")
    entradas = ["-i", "unido.mp4"]
    filtros, mapa_a = [], "0:a"
    if cfg.get("musica"):
        entradas += ["-stream_loop", "-1", "-i", str(proyecto.RAIZ / cfg["musica"])]
        filtros.append(f"[1:a]volume={cfg['volumen_musica']}[m];[0:a][m]amix=inputs=2:duration=first[a]")
        mapa_a = "[a]"
    if cfg.get("subtitulos"):
        filtros.append("[0:v]subtitles=subtitulos.srt:force_style='FontName=Arial,FontSize=20,"
                       "Outline=2,Shadow=0,MarginV=45'[v]")
        mapa_v, codec_v = "[v]", ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]
    else:
        mapa_v, codec_v = "0:v", ["-c:v", "copy"]

    final = "video_final.mp4"
    avisar("Uniendo todo (subtitulos y musica)...")
    args = [*entradas]
    if filtros:
        args += ["-filter_complex", ";".join(filtros)]
    args += ["-map", mapa_v, "-map", mapa_a, *codec_v, "-c:a", "aac", "-b:a", "160k",
             "-movflags", "+faststart", final]
    medios.ffmpeg(*args, cwd=carpeta)

    datos["mp4"] = proyecto.relativa(datos, carpeta / final)
    dur = medios.duracion(carpeta / final)
    avisar(f"Video listo: {dur / 60:.1f} min -> montaje/{final}")
