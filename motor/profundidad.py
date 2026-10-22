"""
Efecto 3D de profundidad (parallax 2.5D): la foto se mueve como si la camara
se desplazara dentro de la escena. Corre en el PC, sin GPU.

1. Depth Anything V2 Small (ONNX, licencia Apache 2.0) saca de cada imagen un
   mapa de profundidad: 1 = cerca, 0 = lejos. Se descarga la primera vez
   (~95 MB) a modelos/ (fuera de git) y corre con onnxruntime en la CPU.
2. Cada fotograma se calcula al reves: para cada pixel de salida se busca de
   donde viene en la foto. Lo cercano se agranda y se desplaza mas que lo
   lejano, y eso es lo que da la sensacion de volumen.

Ajustes que costo encontrar y que no hay que tocar a la ligera:
- La profundidad se ENSANCHA (dilate eliptico 31) y se SUAVIZA mucho (blur
  sigma 14) a 1920x1080: asi el estiramiento cae en el fondo, que no se nota,
  y no sobre caras y manos, que sin eso se doblaban sobre si mismas.
- Zoom base 1.12 (margen para que no se vean los bordes), barridos de 0.02,
  orbita 0.018/0.008 y curva coseno: mas amplitud ya deforma.
- 2 pasadas al buscar la profundidad: la del pixel de origen, no la del destino.

Rendimiento: como la profundidad esta tan suavizada, el campo de desplazamiento
es suave y se calcula a 1/5 de resolucion (384x216) y se escala; solo el
remap final de la foto va a resolucion completa. Pasa de ~190 ms a ~25 ms por
fotograma con el mismo resultado a la vista (el desplazamiento difiere < 0.6 px).
"""
import math
import threading

import cv2
import numpy as np
import requests

from . import proyecto

MODELO_URL = ("https://huggingface.co/onnx-community/depth-anything-v2-small/"
              "resolve/main/onnx/model.onnx")
MODELO = proyecto.RAIZ / "modelos" / "depth-anything-v2-small" / "model.onnx"
LADO_RED = 518            # el modelo trabaja a 518x518

ZOOM_BASE = 1.12
REDUCCION = 5             # los mapas de desplazamiento se calculan a 1/5 de resolucion
PASADAS = 2

# (empuje hacia dentro, desplazamiento x, desplazamiento y) con t de 0 a 1.
# Rotan entre escenas, igual que los movimientos planos del montaje.
MOVIMIENTOS = (
    ("acercar", lambda t: (0.10 * t, 0.0, 0.0)),
    ("barrido derecha", lambda t: (0.03, 0.02 * (2 * t - 1), 0.0)),
    ("orbita", lambda t: (0.04, 0.018 * math.sin(2 * math.pi * t), 0.008 * math.cos(2 * math.pi * t))),
    ("subir", lambda t: (0.05 * t, 0.0, 0.018 * (1 - 2 * t))),
    ("barrido izquierda", lambda t: (0.03, 0.02 * (1 - 2 * t), 0.0)),
    ("alejar", lambda t: (0.10 * (1 - t), 0.01 * t, 0.0)),
)

_cerrojo = threading.Lock()      # una sola descarga y una inferencia a la vez (ya usa todos los nucleos)
_sesion = None


def _descargar(avisar):
    MODELO.parent.mkdir(parents=True, exist_ok=True)
    parcial = MODELO.with_suffix(".part")
    avisar("Efecto 3D: descargando el modelo de profundidad (solo la primera vez, ~95 MB)...")
    with requests.get(MODELO_URL, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length") or 0)
        hecho, ultimo = 0, -1
        with open(parcial, "wb") as f:
            for trozo in r.iter_content(1 << 20):
                f.write(trozo)
                hecho += len(trozo)
                if total:
                    pct = hecho * 100 // total
                    if pct // 10 != ultimo:
                        ultimo = pct // 10
                        avisar(f"Efecto 3D: modelo {pct}% ({hecho >> 20}/{total >> 20} MB)")
    if total and parcial.stat().st_size != total:
        parcial.unlink(missing_ok=True)
        raise RuntimeError("la descarga del modelo de profundidad quedo a medias")
    parcial.replace(MODELO)


def preparar(avisar):
    """Deja el modelo descargado y cargado. Lanza excepcion si no se puede."""
    global _sesion
    with _cerrojo:
        if _sesion is None:
            import onnxruntime as ort
            if not MODELO.is_file():
                _descargar(avisar)
            _sesion = ort.InferenceSession(str(MODELO), providers=["CPUExecutionProvider"])


def encuadrar(img, ancho, alto):
    """Recorta/escala a la proporcion del video llenando el cuadro."""
    h, w = img.shape[:2]
    s = max(ancho / w, alto / h)
    img = cv2.resize(img, (round(w * s), round(h * s)), interpolation=cv2.INTER_LANCZOS4)
    h, w = img.shape[:2]
    y, x = (h - alto) // 2, (w - ancho) // 2
    return np.ascontiguousarray(img[y:y + alto, x:x + ancho])


def profundidad(img):
    """Mapa de profundidad (float32, 1 = cerca) del mismo tamano que img, ya ensanchado y suavizado."""
    alto, ancho = img.shape[:2]
    x = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2RGB), (LADO_RED, LADO_RED), interpolation=cv2.INTER_CUBIC)
    x = ((x.astype(np.float32) / 255 - (0.485, 0.456, 0.406)) / (0.229, 0.224, 0.225)).astype(np.float32)
    with _cerrojo:
        d = _sesion.run(None, {"pixel_values": x.transpose(2, 0, 1)[None]})[0][0]
    d = cv2.resize(d, (ancho, alto), interpolation=cv2.INTER_CUBIC)
    lo, hi = np.percentile(d, 2), np.percentile(d, 98)
    d = np.clip((d - lo) / (hi - lo + 1e-6), 0, 1)
    # Los tamanos estan medidos a 1920x1080: se escalan si el video es de otro tamano.
    k = ancho / 1920
    lado = max(3, int(round(31 * k)) | 1)
    d = cv2.dilate(d, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (lado, lado)))
    d = cv2.GaussianBlur(d, (0, 0), 14 * k)
    return d.astype(np.float32)


def _suave(t):
    return 0.5 - 0.5 * math.cos(math.pi * t)


def _reduccion(ancho, alto):
    """Cuanto se reduce la rejilla de los mapas: un divisor exacto de ancho y alto."""
    for k in (REDUCCION, 4, 6, 8, 3, 2):
        if ancho % k == 0 and alto % k == 0:
            return k
    return 1


class Escena:
    """Una imagen con su profundidad, lista para sacar fotogramas.

    Los mapas se calculan en una rejilla k veces mas pequena (con una celda de mas
    por cada lado, para que el escalado no aplaste los bordes) y se agrandan con
    interpolacion bilineal, que reproduce exacto la parte lineal (el zoom). Medido
    contra el calculo a resolucion completa: el desplazamiento difiere < 0.6 px.
    """

    def __init__(self, img, prof):
        self.img = img
        self.alto, self.ancho = img.shape[:2]
        self.k = k = _reduccion(self.ancho, self.alto)
        ws, hs = self.ancho // k, self.alto // k
        self.d = cv2.resize(prof, (ws, hs), interpolation=cv2.INTER_AREA)
        # La rejilla con borde: la celda j tiene su centro en el pixel (j - 1 + 0.5) * k - 0.5.
        self.d_borde = cv2.copyMakeBorder(self.d, 1, 1, 1, 1, cv2.BORDER_REPLICATE)
        self.cx, self.cy = self.ancho / 2, self.alto / 2
        jx = ((np.arange(-1, ws + 1) + 0.5) * k - 0.5 - self.cx).astype(np.float32)
        iy = ((np.arange(-1, hs + 1) + 0.5) * k - 0.5 - self.cy).astype(np.float32)
        self.rx, self.ry = np.meshgrid(jx, iy)       # posicion relativa al centro

    def cuadro(self, empuje, dx, dy, buf=None):
        """Un fotograma. buf: arrays de trabajo de un solo hilo (los da cuadros())."""
        inv, mx, my, u, v = buf or [np.empty_like(self.rx) for _ in range(5)]
        k, W, H = self.k, self.ancho, self.alto
        dd = self.d_borde
        for paso in range(PASADAS):
            # z = base * (1 + empuje * (0.4 + dd));  mx = cx + rx / z - dx * W * (dd - 0.5)
            np.multiply(dd, ZOOM_BASE * empuje, out=inv)
            np.add(inv, ZOOM_BASE * (1 + 0.4 * empuje), out=inv)
            np.reciprocal(inv, out=inv)
            np.multiply(self.rx, inv, out=mx)
            np.add(mx, self.cx + 0.5 * dx * W, out=mx)
            np.multiply(self.ry, inv, out=my)
            np.add(my, self.cy + 0.5 * dy * H, out=my)
            if dx:
                np.subtract(mx, dd * (dx * W), out=mx)
            if dy:
                np.subtract(my, dd * (dy * H), out=my)
            if paso == PASADAS - 1:
                break
            # La profundidad del pixel de ORIGEN (en coordenadas de la rejilla pequena).
            np.multiply(mx, 1 / k, out=u)
            np.add(u, 0.5 / k - 0.5, out=u)
            np.multiply(my, 1 / k, out=v)
            np.add(v, 0.5 / k - 0.5, out=v)
            dd = cv2.remap(self.d, u, v, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        mapa = cv2.resize(cv2.merge((mx, my)), (W + 2 * k, H + 2 * k), interpolation=cv2.INTER_LINEAR)
        return cv2.remap(self.img, mapa[k:k + H, k:k + W], None, cv2.INTER_LINEAR,
                         borderMode=cv2.BORDER_REFLECT)

    def cuadros(self, n_movimiento, frames):
        """Los fotogramas del plano: el movimiento n (rota entre los 6) con curva suave."""
        _, mov = MOVIMIENTOS[(n_movimiento - 1) % len(MOVIMIENTOS)]
        buf = [np.empty_like(self.rx) for _ in range(5)]
        for f in range(frames):
            yield self.cuadro(*mov(_suave(f / max(1, frames - 1))), buf)


def nombre_movimiento(n):
    return MOVIMIENTOS[(n - 1) % len(MOVIMIENTOS)][0]
