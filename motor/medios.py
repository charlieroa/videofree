"""ffmpeg: el que trae imageio-ffmpeg, para no depender de instalar nada en Windows."""
import re
import subprocess
import tempfile

import imageio_ffmpeg

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


class ErrorMedios(Exception):
    pass


def ffmpeg(*args, cwd=None):
    r = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *map(str, args)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=cwd)
    if r.returncode != 0:
        raise ErrorMedios(r.stderr.strip()[-800:] or "ffmpeg fallo")


def ffmpeg_cuadros(cuadros, *args, cwd=None):
    """ffmpeg leyendo fotogramas en crudo (arrays BGR) por la entrada estandar ('-i -')."""
    with tempfile.TemporaryFile() as errores:     # a fichero: un pipe lleno bloquearia a ffmpeg
        p = subprocess.Popen([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *map(str, args)],
                             stdin=subprocess.PIPE, stderr=errores, cwd=cwd)
        try:
            for c in cuadros:
                p.stdin.write(memoryview(c))
        except OSError:                           # ffmpeg murio: el motivo queda en errores
            pass
        finally:
            try:
                p.stdin.close()
            except OSError:
                pass
            p.wait()
        if p.returncode != 0:
            errores.seek(0)
            raise ErrorMedios(errores.read().decode("utf-8", "replace").strip()[-800:] or "ffmpeg fallo")


def duracion(ruta):
    """Segundos de un fichero de audio o video (sin ffprobe: se lee de ffmpeg -i)."""
    r = subprocess.run([FFMPEG, "-hide_banner", "-i", str(ruta)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr)
    if not m:
        raise ErrorMedios(f"no puedo leer la duracion de {ruta}")
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


def ultimo_fotograma(video, destino):
    ffmpeg("-sseof", "-0.2", "-i", video, "-frames:v", "1", "-update", "1", destino)
    return destino
